from __future__ import annotations

import asyncio
import json
import sqlite3
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime


def _context(adapter: str, user: str, request: str, operation: str = "") -> CommandContext:
    return CommandContext(adapter=adapter, user_id=user, request_id=request, operation_id=operation)


async def _high_realm_player(runtime, adapter: str, user: str, realm: str = "nascent_soul") -> None:
    created = await runtime.dispatch(_context(adapter, user, f"create-{user}"), "开始修仙")
    assert created.ok, created
    with sqlite3.connect(runtime.settings.database_path) as db:
        db.execute(
            """
            UPDATE players
            SET stage = 'cultivator', realm_key = ?, realm_layer = 10,
                cultivation = 100000, total_cultivation = 848960,
                max_hp = 1200, initiative = 80,
                qualification_json = ?, stamina = 100, stamina_max = 100,
                inventory_json = ?, faction_reputation_json = ?
            WHERE platform = ? AND platform_user_id = ?
            """,
            (
                realm,
                json.dumps({"body": 40, "agility": 30, "spirit": 30, "root": 30, "insight": 30, "fortune": 10}),
                json.dumps(
                    {
                        "item.soul_seed": 1,
                        "item.domain_core": 1,
                        "item.ancient_fruit": 3,
                        "item.soul_crystal": 3,
                    }
                ),
                json.dumps({"xuantian": 2500}),
                adapter,
                user,
            ),
        )


def test_soul_transformation_permit_is_player_reachable_and_idempotent() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            user = "quest-soul"
            await _high_realm_player(runtime, "qq.official", user)
            for index in range(3):
                result = await runtime.dispatch(
                    _context("qq.official", user, f"commission-{index}", f"commission-{index}"),
                    "完成领域委托",
                )
                assert result.code == "QUEST_ACTION_RECORDED"
            replay = await runtime.dispatch(
                _context("qq.official", user, "commission-replay", "commission-2"), "完成领域委托"
            )
            assert replay.code == "QUEST_ACTION_RECORDED"
            assert replay.data["idempotent_replay"] is True
            for index in range(3):
                result = await runtime.dispatch(
                    _context("qq.official", user, f"line-{index}", f"line-{index}"), "完成远古洞天任务"
                )
                assert result.code == "QUEST_ACTION_RECORDED"
            battle = await runtime.dispatch(
                _context("qq.official", user, "cross", "cross-battle"), "开始跨界战"
            )
            assert battle.code == "CROSS_REALM_BATTLE_SETTLED"
            assert battle.data["outcome"] == "won"
            permit = await runtime.dispatch(
                _context("qq.official", user, "permit", "soul-permit"), "领取化神许可"
            )
            assert permit.code == "QUEST_PERMIT_GRANTED"
            with sqlite3.connect(runtime.settings.database_path) as db:
                intro = json.loads(db.execute("SELECT intro_json FROM players WHERE platform_user_id = ?", (user,)).fetchone()[0])
                inventory = json.loads(db.execute("SELECT inventory_json FROM players WHERE platform_user_id = ?", (user,)).fetchone()[0])
                assert "quest.soul_transformation" in intro["flags"]
                assert inventory.get("item.ancient_fruit") == 4
                assert "item.soul_crystal" not in inventory
                assert db.execute("SELECT COUNT(*) FROM quest_events WHERE player_id = (SELECT id FROM players WHERE platform_user_id = ?)", (user,)).fetchone()[0] == 7
            replay_permit = await runtime.dispatch(
                _context("qq.official", user, "permit-replay", "soul-permit"), "领取化神许可"
            )
            assert replay_permit.code == "QUEST_PERMIT_GRANTED"
            assert replay_permit.data["idempotent_replay"] is True
            await runtime.close()

    asyncio.run(run())


def test_void_permit_counts_failed_trials_and_requires_archive_delivery() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            user = "quest-void"
            await _high_realm_player(runtime, "onebot.v11", user, realm="soul_transformation")
            for index in range(3):
                result = await runtime.dispatch(
                    _context("onebot.v11", user, f"trial-{index}", f"trial-{index}"), "开始界壁试炼"
                )
                assert result.code == "VOID_WALL_TRIAL_RECORDED"
                assert result.data["progress"]["void_wall_trial"] == index + 1
            archive = await runtime.dispatch(
                _context("onebot.v11", user, "archive", "archive-source"), "探索档案遗迹"
            )
            assert archive.code == "QUEST_ACTION_RECORDED"
            delivered = await runtime.dispatch(
                _context("onebot.v11", user, "deliver", "archive-delivery"), "交付虚空档案"
            )
            assert delivered.code == "QUEST_ACTION_RECORDED"
            permit = await runtime.dispatch(
                _context("onebot.v11", user, "permit", "void-permit"), "领取炼虚许可"
            )
            assert permit.code == "QUEST_PERMIT_GRANTED"
            status = await runtime.dispatch(_context("onebot.v11", user, "status"), "高阶任务")
            assert status.code == "QUEST_STATUS"
            assert status.data["quests"]["quest.break_void"]["status"] == "completed"
            await runtime.close()

    asyncio.run(run())


def test_quest_commands_reject_forged_progress_arguments() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            user = "quest-forge"
            await _high_realm_player(runtime, "qq.official", user)
            forged = await runtime.dispatch(
                _context("qq.official", user, "forge"), "完成领域委托 999"
            )
            assert forged.code == "INVALID_QUEST_COMMAND"
            status = await runtime.dispatch(_context("qq.official", user, "status"), "高阶任务")
            assert status.data["quests"]["quest.domain_material_commission"]["progress"] == {}
            await runtime.close()

    asyncio.run(run())
