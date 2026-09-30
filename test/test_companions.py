from __future__ import annotations

import asyncio
import json
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime


def _context(adapter: str, user: str, operation: str, message: str) -> CommandContext:
    return CommandContext(
        adapter=adapter,
        user_id=user,
        scene_id="private",
        message_id=message,
        operation_id=operation,
    )


async def _prepare(runtime, *, adapter: str, user: str) -> None:
    created = await runtime.dispatch(_context(adapter, user, f"{adapter}:create", "create"), "开始修仙")
    assert created.ok
    await runtime.repository.initialize()
    with runtime.repository._connect() as connection:
        connection.execute(
            "UPDATE players SET location_key = ?, inventory_json = ? WHERE platform = ? AND platform_user_id = ?",
            (
                "xuantian.outskirts",
                json.dumps({"item.food.coarse_spirit_rice": 2, "beast.gear.sack_small": 1}),
                adapter,
                user,
            ),
        )


def test_companion_flow_is_shared_by_qq_and_onebot_and_survives_restart() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            await _prepare(runtime, adapter="qq.official", user="qq-user")
            await _prepare(runtime, adapter="onebot.v11", user="ob-user")

            qq_bond = await runtime.dispatch(
                _context("qq.official", "qq-user", "qq:bond", "bond"),
                "结缘灵兽 beast.wood_rat",
            )
            ob_bond = await runtime.dispatch(
                _context("onebot.v11", "ob-user", "ob:bond", "bond"),
                "结缘灵兽 beast.wood_rat",
            )
            assert qq_bond.code == "COMPANION_BONDED"
            assert ob_bond.code == "COMPANION_BONDED"

            qq_feed_context = _context("qq.official", "qq-user", "qq:feed", "feed")
            first = await runtime.dispatch(qq_feed_context, f"喂养灵兽 {qq_bond.data['instance_id']}")
            replay = await runtime.dispatch(
                _context("qq.official", "qq-user", "qq:feed", "feed-retry"),
                f"喂养灵兽 {qq_bond.data['instance_id']}",
            )
            assert first.code == "COMPANION_FED"
            assert first.data["experience"] == 10
            assert replay.data["experience"] == 10
            assert replay.data["idempotent_replay"] is True

            gear = await runtime.dispatch(
                _context("onebot.v11", "ob-user", "ob:gear", "gear"),
                f"装备灵具 {ob_bond.data['instance_id']} beast.gear.sack_small",
            )
            assert gear.code == "COMPANION_GEAR_EQUIPPED"

            await runtime.close()
            runtime = create_runtime(data_dir=data_dir)
            restored = await runtime.dispatch(
                _context("onebot.v11", "ob-user", "ob:status", "status"), "灵兽状态"
            )
            assert restored.code == "COMPANION_STATUS"
            assert restored.data["companions"][0]["companion_key"] == "beast.wood_rat"
            assert restored.data["companions"][0]["gear"][0]["gear_key"] == "beast.gear.sack_small"
            await runtime.close()

    asyncio.run(run())


def test_companion_battle_snapshot_is_detached_and_read_only() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            await _prepare(runtime, adapter="onebot.v11", user="u")
            bonded = await runtime.dispatch(
                _context("onebot.v11", "u", "bond", "bond"), "结缘灵兽 beast.wood_rat"
            )
            await runtime.repository.initialize()
            with runtime.repository._connect() as connection:
                player = connection.execute(
                    "SELECT id FROM players WHERE platform = ? AND platform_user_id = ?",
                    ("onebot.v11", "u"),
                ).fetchone()
                snapshot = runtime.repository.companion_battle_snapshot(connection, player["id"])
                snapshot.companions[0]["effect"]["value"] = 9999
            status = await runtime.dispatch(
                _context("onebot.v11", "u", "status", "status"), "灵兽状态"
            )
            assert status.data["companions"][0]["level"] == 1
            assert bonded.data["instance_id"] == status.data["companions"][0]["instance_id"]
            await runtime.close()

    asyncio.run(run())
