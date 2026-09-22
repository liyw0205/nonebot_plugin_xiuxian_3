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


def _set_resources(runtime, user_id: str, *, insights: int, stones: int) -> None:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE players SET skill_insights = ?, spirit_stones = ? WHERE platform = ? AND platform_user_id = ?",
            (insights, stones, "web", user_id),
        )


def test_skill_progression_costs_snapshots_and_operation_replay() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            assert (await runtime.dispatch(_context("missing", "preview"), "神通预览")).ok
            assert (await runtime.dispatch(_context("missing", "profile"), "我的神通")).code == "PLAYER_NOT_FOUND"
            user = "skill-progress"
            await _enter_cultivator(runtime, user)
            _set_resources(runtime, user, insights=4, stones=500)

            first = await runtime.dispatch(
                _context(user, "train-1", operation_id="skill-1"), "参悟神通 基础攻击"
            )
            assert first.code == "SKILL_TRAINED"
            assert first.data["level"] == 1
            assert first.data["effective_effect"]["value"] == 10300
            replay = await runtime.dispatch(
                _context(user, "train-1-replay", operation_id="skill-1"), "参悟神通 基础攻击"
            )
            assert replay.data["idempotent_replay"] is True
            conflict = await runtime.dispatch(
                _context(user, "train-1-conflict", operation_id="skill-1"), "参悟神通 重击"
            )
            assert conflict.code == "OPERATION_CONFLICT"

            second = await runtime.dispatch(
                _context(user, "train-2", operation_id="skill-2"), "参悟神通 基础攻击"
            )
            third = await runtime.dispatch(
                _context(user, "train-3", operation_id="skill-3"), "参悟神通 基础攻击"
            )
            assert second.data["level"] == 2
            assert third.data["level"] == 3
            assert third.data["effective_effect"]["value"] == 10900
            maxed = await runtime.dispatch(_context(user, "train-4"), "参悟神通 基础攻击")
            assert maxed.code == "SKILL_MAXED"

            profile = await runtime.dispatch(_context(user, "profile"), "我的神通")
            assert profile.code == "SKILL_PROFILE"
            assert profile.data["skill_insights"] == 0
            assert profile.data["skills"][0]["level"] == 3
            with sqlite3.connect(runtime.settings.database_path) as connection:
                player = connection.execute(
                    "SELECT skill_insights, spirit_stones FROM players WHERE platform_user_id = ?", (user,)
                ).fetchone()
                mastery = connection.execute(
                    "SELECT level, snapshot_json FROM skill_masteries WHERE player_id = (SELECT id FROM players WHERE platform_user_id = ?)",
                    (user,),
                ).fetchone()
                events = connection.execute(
                    "SELECT COUNT(*) FROM skill_insight_events WHERE player_id = (SELECT id FROM players WHERE platform_user_id = ?)",
                    (user,),
                ).fetchone()[0]
            assert player == (0, 360)
            assert mastery[0] == 3
            assert json.loads(mastery[1])["realm_key"] == "qi_sensing"
            assert events == 3
            await runtime.close()

    asyncio.run(run())


def test_skill_path_resource_and_long_action_gates() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            user = "skill-gates"
            await _enter_cultivator(runtime, user)
            _set_resources(runtime, user, insights=1, stones=20)
            wrong_path = await runtime.dispatch(_context(user, "wrong"), "参悟神通 水箭")
            assert wrong_path.code == "SKILL_NOT_AVAILABLE"
            insufficient = await runtime.dispatch(_context(user, "insufficient"), "参悟神通 基础攻击")
            assert insufficient.ok
            no_resources = await runtime.dispatch(_context(user, "no-resources"), "参悟神通 基础攻击")
            assert no_resources.code == "SKILL_RESOURCE_INSUFFICIENT"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute(
                    "SELECT skill_insights, spirit_stones FROM players WHERE platform_user_id = ?", (user,)
                ).fetchone() == (0, 0)

            other = "skill-busy"
            await _enter_cultivator(runtime, other)
            _set_resources(runtime, other, insights=2, stones=100)
            started = await runtime.dispatch(_context(other, "retreat"), "开始闭关")
            assert started.ok
            blocked = await runtime.dispatch(_context(other, "blocked"), "参悟神通 基础攻击")
            assert blocked.code == "SKILL_BUSY"
            await runtime.close()

    asyncio.run(run())


def test_skill_concurrent_training_consumes_one_available_level() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            user = "skill-concurrent"
            await _enter_cultivator(runtime, user)
            _set_resources(runtime, user, insights=1, stones=20)
            results = await asyncio.gather(
                *(
                    runtime.dispatch(
                        _context(user, f"concurrent-{index}", operation_id=f"skill-concurrent-{index}"),
                        "参悟神通 基础攻击",
                    )
                    for index in range(10)
                )
            )
            assert sum(result.ok for result in results) == 1
            assert {result.code for result in results} == {"SKILL_TRAINED", "SKILL_RESOURCE_INSUFFICIENT"}
            await runtime.close()

    asyncio.run(run())
