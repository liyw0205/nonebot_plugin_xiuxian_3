from __future__ import annotations

import asyncio
import json
import sqlite3
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime


def _context(user_id: str, request_id: str, *, operation_id: str = "") -> CommandContext:
    return CommandContext(adapter="web", user_id=user_id, request_id=request_id, operation_id=operation_id)


async def _enter_cultivator(runtime, user_id: str) -> None:
    commands = (
        "开始修仙",
        "寻仙问道",
        "完成引导 阅读",
        "前往近郊",
        "完成引导 采集",
        "完成引导 炼丹",
        "选择道途 体修",
    )
    for index, command in enumerate(commands):
        result = await runtime.dispatch(_context(user_id, f"setup-{index}"), command)
        assert result.ok, (command, result.code, result.message)


def _set_talent_points(runtime, user_id: str, points: int) -> None:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE players SET talent_points = ? WHERE platform = ? AND platform_user_id = ?",
            (points, "web", user_id),
        )


def test_talent_preview_profile_and_linear_unlocks_are_idempotent() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            user = "talent-linear"
            preview = await runtime.dispatch(_context(user, "preview"), "道脉预览")
            assert preview.ok
            assert "体修道脉" in preview.message
            assert "1/2/3/5" in preview.message

            missing = await runtime.dispatch(_context(user, "missing"), "我的道脉")
            assert missing.code == "PLAYER_NOT_FOUND"
            await _enter_cultivator(runtime, user)

            profile = await runtime.dispatch(_context(user, "profile"), "我的道脉")
            assert profile.code == "TALENT_PROFILE"
            assert profile.data["points_available"] == 0
            assert profile.data["nodes"] == []

            first = await runtime.dispatch(
                _context(user, "first", operation_id="talent-first"), "解锁天赋 1"
            )
            assert first.code == "TALENT_UNLOCKED"
            assert first.data["cost_points"] == 0
            replay = await runtime.dispatch(
                _context(user, "first-replay", operation_id="talent-first"), "解锁天赋 1"
            )
            assert replay.data["idempotent_replay"] is True
            assert replay.data["node_key"] == first.data["node_key"]
            conflict = await runtime.dispatch(
                _context(user, "first-conflict", operation_id="talent-first"), "解锁天赋 2"
            )
            assert conflict.code == "OPERATION_CONFLICT"

            blocked = await runtime.dispatch(_context(user, "blocked"), "解锁天赋 2")
            assert blocked.code == "TALENT_POINT_INSUFFICIENT"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute(
                    "SELECT COUNT(*) FROM talent_node_states WHERE player_id = (SELECT id FROM players WHERE platform_user_id = ?)",
                    (user,),
                ).fetchone()[0] == 1
            _set_talent_points(runtime, user, 11)
            for tier, cost in ((2, 1), (3, 2), (4, 3), (5, 5)):
                result = await runtime.dispatch(
                    _context(user, f"tier-{tier}", operation_id=f"talent-tier-{tier}"),
                    f"解锁天赋 {tier}",
                )
                assert result.code == "TALENT_UNLOCKED"
                assert result.data["cost_points"] == cost

            profile = await runtime.dispatch(_context(user, "profile-final"), "我的天赋")
            assert profile.code == "TALENT_PROFILE"
            assert profile.data["points_available"] == 0
            assert [node["tier"] for node in profile.data["nodes"]] == [1, 2, 3, 4, 5]
            with sqlite3.connect(runtime.settings.database_path) as connection:
                points_events = connection.execute(
                    "SELECT COUNT(*) FROM talent_point_events WHERE player_id = (SELECT id FROM players WHERE platform_user_id = ?)",
                    (user,),
                ).fetchone()[0]
                node_snapshot = connection.execute(
                    "SELECT snapshot_json FROM talent_node_states WHERE player_id = (SELECT id FROM players WHERE platform_user_id = ?) AND tier = 5",
                    (user,),
                ).fetchone()[0]
            assert points_events == 4
            snapshot = json.loads(node_snapshot)
            assert snapshot["path_key"] == "body"
            assert snapshot["content_version"] == "content-0.1"
            await runtime.close()

    asyncio.run(run())


def test_talent_rejects_wrong_tree_and_requires_prerequisite() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            user = "talent-gates"
            await _enter_cultivator(runtime, user)
            wrong_tree = await runtime.dispatch(
                _context(user, "wrong-tree"), "解锁天赋 talent.tree.spell.tier1"
            )
            assert wrong_tree.code == "TALENT_PATH_MISMATCH"
            _set_talent_points(runtime, user, 10)
            out_of_order = await runtime.dispatch(_context(user, "out-of-order"), "解锁天赋 3")
            assert out_of_order.code == "TALENT_PREREQUISITE"
            await runtime.close()

    asyncio.run(run())


def test_talent_unlock_is_unique_under_concurrency() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            user = "talent-concurrent"
            await _enter_cultivator(runtime, user)
            results = await asyncio.gather(
                *(
                    runtime.dispatch(
                        _context(user, f"unlock-{index}", operation_id=f"talent-concurrent-{index}"),
                        "解锁天赋 1",
                    )
                    for index in range(12)
                )
            )
            assert sum(result.ok for result in results) == 1
            assert {result.code for result in results} == {"TALENT_UNLOCKED", "TALENT_ALREADY_LEARNED"}
            with sqlite3.connect(runtime.settings.database_path) as connection:
                count = connection.execute(
                    "SELECT COUNT(*) FROM talent_node_states WHERE player_id = (SELECT id FROM players WHERE platform_user_id = ?)",
                    (user,),
                ).fetchone()[0]
            assert count == 1
            await runtime.close()

    asyncio.run(run())


def test_talent_unlock_respects_long_action_lock() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            user = "talent-busy"
            await _enter_cultivator(runtime, user)
            started = await runtime.dispatch(_context(user, "retreat"), "开始闭关")
            assert started.ok
            blocked = await runtime.dispatch(_context(user, "unlock"), "解锁天赋 1")
            assert blocked.code == "TALENT_BUSY"
            await runtime.close()

    asyncio.run(run())
