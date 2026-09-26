from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory

import pytest

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime


def _context(adapter: str, user: str, request: str, operation: str = "") -> CommandContext:
    return CommandContext(adapter=adapter, user_id=user, request_id=request, operation_id=operation)


async def _high_realm_player(
    runtime,
    adapter: str,
    user: str,
    realm: str = "nascent_soul",
    location_key: str = "xuantian.new_town",
) -> None:
    created = await runtime.dispatch(_context(adapter, user, f"create-{user}"), "开始修仙")
    assert created.ok, created
    with sqlite3.connect(runtime.settings.database_path) as db:
        db.execute(
            """
            UPDATE players
            SET stage = 'cultivator', realm_key = ?, realm_layer = 10, location_key = ?,
                cultivation = 100000, total_cultivation = 848960,
                max_hp = 100000, initiative = 100000,
                qualification_json = ?, stamina = 100, stamina_max = 100,
                soul_power = 100, soul_power_max = 300,
                intro_json = ?, inventory_json = ?, faction_reputation_json = ?
            WHERE platform = ? AND platform_user_id = ?
            """,
            (
                realm,
                location_key,
                json.dumps({"body": 2000, "agility": 2000, "spirit": 30, "root": 30, "insight": 30, "fortune": 10}),
                json.dumps({"flags": ["story.mainline.three_realms"]}),
                json.dumps(
                    {
                        "item.domain_core": 1,
                        "item.ancient_fruit": 3,
                        "item.soul_crystal": 3,
                        "item.void_anchor": 8,
                    }
                ),
                json.dumps({"xuantian": 2500}),
                adapter,
                user,
            ),
        )


def _expire_void_route(runtime) -> None:
    with sqlite3.connect(runtime.settings.database_path) as db:
        db.execute(
            "UPDATE void_route_sessions SET ends_at = ? WHERE status = 'running'",
            ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),),
        )


@pytest.mark.parametrize(
    ("quest_adapter", "leader_adapter"),
    (("qq.official", "onebot.v11"), ("onebot.v11", "qq.official")),
)
def test_soul_transformation_permit_is_player_reachable_and_idempotent(
    quest_adapter: str, leader_adapter: str
) -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            user = "quest-soul"
            await _high_realm_player(runtime, quest_adapter, user)
            leader = "quest-soul-leader"
            await _high_realm_player(runtime, leader_adapter, leader)
            with sqlite3.connect(runtime.settings.database_path) as db:
                inventory = json.loads(
                    db.execute(
                        "SELECT inventory_json FROM players WHERE platform=? AND platform_user_id=?",
                        (quest_adapter, user),
                    ).fetchone()[0]
                )
                inventory.pop("item.ancient_fruit", None)
                inventory.pop("item.soul_crystal", None)
                inventory.pop("item.demon_core", None)
                db.execute(
                    "UPDATE players SET inventory_json=? WHERE platform=? AND platform_user_id=?",
                    (json.dumps(inventory), quest_adapter, user),
                )
            missing_material = await runtime.dispatch(
                _context(quest_adapter, user, "commission-missing", "commission-missing"),
                "完成领域委托",
            )
            assert missing_material.code == "QUEST_RESOURCE_INSUFFICIENT"
            with sqlite3.connect(runtime.settings.database_path) as db:
                unchanged_inventory = json.loads(
                    db.execute(
                        "SELECT inventory_json FROM players WHERE platform=? AND platform_user_id=?",
                        (quest_adapter, user),
                    ).fetchone()[0]
                )
                assert "item.ancient_fruit" not in unchanged_inventory
                assert "item.demon_core" not in unchanged_inventory
                assert db.execute(
                    "SELECT COUNT(*) FROM quest_events WHERE player_id = "
                    "(SELECT id FROM players WHERE platform=? AND platform_user_id=?)",
                    (quest_adapter, user),
                ).fetchone()[0] == 0
                unchanged_inventory["item.demon_core"] = 3
                db.execute(
                    "UPDATE players SET inventory_json=? WHERE platform=? AND platform_user_id=?",
                    (json.dumps(unchanged_inventory), quest_adapter, user),
                )
            for index in range(3):
                result = await runtime.dispatch(
                    _context(quest_adapter, user, f"commission-{index}", f"commission-{index}"),
                    "完成领域委托",
                )
                assert result.code == "QUEST_ACTION_RECORDED"
                assert result.data["reward"] == {"item.ancient_fruit": 1}
            replay = await runtime.dispatch(
                _context(quest_adapter, user, "commission-replay", "commission-2"), "完成领域委托"
            )
            assert replay.code == "QUEST_ACTION_RECORDED"
            assert replay.data["idempotent_replay"] is True
            forged_line = await runtime.dispatch(
                _context(quest_adapter, user, "line-forged", "line-forged"),
                "完成远古洞天任务 made-up-battle",
            )
            assert forged_line.code == "QUEST_REQUIREMENT_MISSING"
            wrong_location = await runtime.dispatch(
                _context(quest_adapter, user, "cross-wrong-location", "cross-wrong-location"), "开始跨界战"
            )
            assert wrong_location.code == "BATTLE_REQUIREMENT_MISSING"
            with sqlite3.connect(runtime.settings.database_path) as db:
                assert db.execute(
                    "SELECT COUNT(*) FROM battle_sessions WHERE player_id = "
                    "(SELECT id FROM players WHERE platform = ? AND platform_user_id = ?)",
                    (quest_adapter, user),
                ).fetchone()[0] == 0
                db.execute(
                    "UPDATE players SET location_key = 'cave.boundary_realm' WHERE platform = ? AND platform_user_id = ?",
                    (quest_adapter, user),
                )
                db.execute(
                    "UPDATE players SET location_key = 'cave.boundary_realm' WHERE platform = ? AND platform_user_id = ?",
                    (leader_adapter, leader),
                )
                leader_inventory = json.loads(
                    db.execute(
                        "SELECT inventory_json FROM players WHERE platform=? AND platform_user_id=?",
                        (leader_adapter, leader),
                    ).fetchone()[0]
                )
                leader_inventory["item.soul_crystal"] = 1
                db.execute(
                    "UPDATE players SET stamina=100, inventory_json=? WHERE platform=? AND platform_user_id=?",
                    (json.dumps(leader_inventory), leader_adapter, leader),
                )
                db.execute(
                    "UPDATE players SET stamina=100 WHERE platform=? AND platform_user_id=?",
                    (quest_adapter, user),
                )
            battle = await runtime.dispatch(
                _context(quest_adapter, user, "cross", "cross-battle"), "开始跨界战"
            )
            assert battle.code == "CROSS_REALM_BATTLE_SETTLED"
            assert battle.data["outcome"] == "won"

            created = await runtime.adapters.dispatch(
                leader_adapter, _context(leader_adapter, leader, "party-create"), "创建界隙队伍"
            )
            assert created.code == "PARTY_CREATED"
            party_id = str(created.data["party_id"])
            invited = await runtime.adapters.dispatch(
                leader_adapter,
                _context(leader_adapter, leader, "party-invite"),
                f"邀请入队 {quest_adapter}:{user}",
            )
            assert invited.code == "PARTY_INVITED"
            accepted = await runtime.adapters.dispatch(
                quest_adapter, _context(quest_adapter, user, "party-accept"), f"接受入队 {party_id}"
            )
            assert accepted.code == "PARTY_JOINED"
            for adapter, member in ((leader_adapter, leader), (quest_adapter, user)):
                confirmed = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, member, f"party-confirm-{adapter}"),
                    f"确认入队 {party_id}",
                )
                assert confirmed.ok

            for index in range(3):
                started = await runtime.repository.start_party_battle(
                    platform=leader_adapter,
                    platform_user_id=leader,
                    party_id=party_id,
                    operation_id=f"boundary-start-{index}",
                )
                resolved = await runtime.repository.settle_party_battle(
                    platform=quest_adapter,
                    platform_user_id=user,
                    battle_id=started.battle_id,
                    operation_id=f"boundary-settle-{index}",
                )
                assert resolved.outcome == "won"
                line = await runtime.adapters.dispatch(
                    quest_adapter,
                    _context(quest_adapter, user, f"line-{index}", f"line-{index}"),
                    f"完成远古洞天任务 {started.battle_id}",
                )
                assert line.code == "QUEST_ACTION_RECORDED"
                assert line.data["progress"]["success"] == index + 1

            repeated_line = await runtime.adapters.dispatch(
                quest_adapter,
                _context(quest_adapter, user, "line-reused", "line-reused"),
                f"完成远古洞天任务 {started.battle_id}",
            )
            assert repeated_line.code == "QUEST_ALREADY_COMPLETED"
            permit = await runtime.dispatch(
                _context(quest_adapter, user, "permit", "soul-permit"), "领取化神许可"
            )
            assert permit.code == "QUEST_PERMIT_GRANTED"
            with sqlite3.connect(runtime.settings.database_path) as db:
                intro = json.loads(db.execute("SELECT intro_json FROM players WHERE platform_user_id = ?", (user,)).fetchone()[0])
                inventory = json.loads(db.execute("SELECT inventory_json FROM players WHERE platform_user_id = ?", (user,)).fetchone()[0])
                assert "quest.soul_transformation" in intro["flags"]
                assert inventory.get("item.ancient_fruit") == 3
                assert inventory.get("item.soul_seed") == 1
                assert inventory.get("item.domain_core") == 2
                assert inventory.get("item.demon_core", 0) == 0
                assert "item.soul_crystal" not in inventory
                assert db.execute("SELECT COUNT(*) FROM quest_events WHERE player_id = (SELECT id FROM players WHERE platform_user_id = ?)", (user,)).fetchone()[0] == 7
            replay_permit = await runtime.dispatch(
                _context(quest_adapter, user, "permit-replay", "soul-permit"), "领取化神许可"
            )
            assert replay_permit.code == "QUEST_PERMIT_GRANTED"
            assert replay_permit.data["idempotent_replay"] is True
            await runtime.close()

    asyncio.run(run())


def test_void_permit_counts_failed_trials_and_requires_archive_delivery() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            for adapter in ("qq.official", "onebot.v11"):
                user = f"quest-void-{adapter}"
                await _high_realm_player(
                    runtime, adapter, user, realm="soul_transformation", location_key="void.portal"
                )
                with sqlite3.connect(runtime.settings.database_path) as db:
                    before = db.execute(
                        "SELECT stamina, inventory_json FROM players WHERE platform = ? AND platform_user_id = ?",
                        (adapter, user),
                    ).fetchone()
                blocked_route = await runtime.dispatch(
                    _context(adapter, user, f"archive-route-blocked-{adapter}"), "进入虚空航道 档案遗迹"
                )
                assert blocked_route.code == "VOID_ROUTE_LOCKED"
                with sqlite3.connect(runtime.settings.database_path) as db:
                    after = db.execute(
                        "SELECT stamina, inventory_json FROM players WHERE platform = ? AND platform_user_id = ?",
                        (adapter, user),
                    ).fetchone()
                assert after == before
                legacy_blocked = await runtime.dispatch(
                    _context(adapter, user, f"archive-without-route-{adapter}"), "探索档案遗迹"
                )
                assert legacy_blocked.code == "ARCHIVE_ROUTE_REQUIRED"
                for index in range(3):
                    result = await runtime.dispatch(
                        _context(adapter, user, f"trial-{adapter}-{index}", f"trial-{adapter}-{index}"),
                        "开始界壁试炼",
                    )
                    assert result.code == "VOID_WALL_TRIAL_RECORDED"
                    assert result.data["progress"]["void_wall_trial"] == index + 1
                started = await runtime.dispatch(
                    _context(adapter, user, f"archive-route-{adapter}"), "进入虚空航道 档案遗迹"
                )
                assert started.code == "VOID_ROUTE_STARTED"
                _expire_void_route(runtime)
                settled = await runtime.dispatch(
                    _context(adapter, user, f"archive-settle-{adapter}"), "结算虚空航道"
                )
                assert settled.code == "VOID_ROUTE_SETTLED"
                assert settled.data["route_key"] == "void.archive_ruins"
                archive = await runtime.dispatch(
                    _context(adapter, user, f"archive-{adapter}"), "探索档案遗迹"
                )
                assert archive.code == "ARCHIVE_RUN_SETTLED"
                assert archive.data["outcome"] == "won"
                delivered = await runtime.dispatch(
                    _context(adapter, user, f"deliver-{adapter}"), "交付虚空档案"
                )
                assert delivered.code == "QUEST_ACTION_RECORDED"
                permit = await runtime.dispatch(
                    _context(adapter, user, f"permit-{adapter}"), "领取炼虚许可"
                )
                assert permit.code == "QUEST_PERMIT_GRANTED"
                status = await runtime.dispatch(_context(adapter, user, f"status-{adapter}"), "高阶任务")
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
