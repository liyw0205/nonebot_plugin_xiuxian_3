from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime


class MutableClock:
    def __init__(self, value: datetime):
        self.value = value

    def __call__(self) -> datetime:
        return self.value


def _context(adapter: str, user_id: str, operation_id: str) -> CommandContext:
    return CommandContext(adapter=adapter, user_id=user_id, operation_id=operation_id, request_id=operation_id, can_write_assets=True)


def test_qq_onebot_void_beacon_discount_and_alliance_contract() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 25, 12, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            for adapter, user_id in (("qq.official", "leader-a"), ("onebot.v11", "leader-b"), ("onebot.v11", "member-a")):
                assert (await runtime.dispatch(_context(adapter, user_id, f"create-{user_id}"), "开始修仙")).code == "PLAYER_CREATED"
            now_text = clock.value.isoformat()
            with sqlite3.connect(runtime.settings.database_path) as connection:
                players = dict(connection.execute("SELECT platform_user_id,id FROM players").fetchall())
                for sect_id, name, leader, warehouse in (
                    ("sect-a", "甲宗", players["leader-a"], {"item.void_anchor": 35, "item.mat.array_sand": 40}),
                    ("sect-b", "乙宗", players["leader-b"], {"item.void_anchor": 20, "item.mat.array_sand": 30}),
                ):
                    connection.execute(
                        "INSERT INTO sects(sect_id,name,name_key,leader_id,status,level,max_members,warehouse_capacity,construction,spirit_stones,sect_merit,warehouse_json,created_at,updated_at,content_version,rule_version) VALUES (?,?,?,?, 'active',5,120,100,0,20000,0,?,?,?,'content-0.5','social-0.5.0')",
                        (sect_id, name, name.casefold(), leader, json.dumps(warehouse), now_text, now_text),
                    )
                connection.execute("UPDATE players SET stage='cultivator', realm_key='void_refining', realm_layer=1, stamina=100, stamina_max=100, inventory_json=?", (json.dumps({"item.void_anchor": 20}),))
                for sect_id, user_id, role in (("sect-a", "leader-a", "leader"), ("sect-a", "member-a", "member"), ("sect-b", "leader-b", "leader")):
                    connection.execute(
                        "INSERT INTO sect_members(sect_id,player_id,role,status,contribution,joined_at,last_action_at,created_at,updated_at) VALUES (?,?,?,'active',0,?,?,?,?)",
                        (sect_id, players[user_id], role, now_text, now_text, now_text, now_text),
                    )
                connection.execute(
                    "INSERT INTO sect_void_fortresses(sect_id,status,anchor_balance,build_operation_id,build_ends_at,maintenance_due_at,snapshot_json,content_version,rule_version,created_at,updated_at) VALUES ('sect-a','active',20,'fortress-a',NULL,?,?, 'content-0.5','social-0.5.0',?,?)",
                        ((clock.value + timedelta(days=6)).isoformat(), json.dumps({}), now_text, now_text),
                )

            qq = _context("qq.official", "leader-a", "beacon-build")
            onebot_member = _context("onebot.v11", "member-a", "member-beacon-build")
            assert (await runtime.dispatch(qq, "建造虚空信标")).code == "VOID_BEACON_BUILDING"
            assert (await runtime.dispatch(onebot_member, "建造虚空信标")).code == "SECT_PERMISSION_DENIED"
            clock.value += timedelta(hours=25)
            beacon = await runtime.dispatch(_context("onebot.v11", "member-a", "beacon-status"), "虚空信标")
            assert beacon.code == "VOID_BEACON_STATUS"
            assert beacon.data["status"] == "active"
            route = await runtime.repository.start_void_route(platform="qq.official", platform_user_id="leader-a", route_key="void.sect_fortress", operation_id="beacon-route")
            assert route.anchor_cost == 1
            with sqlite3.connect(runtime.settings.database_path) as connection:
                snapshot = json.loads(connection.execute("SELECT snapshot_json FROM void_route_sessions WHERE operation_id='beacon-route'").fetchone()[0])
                assert snapshot["beacon_discount"] == 1

            proposal = await runtime.dispatch(_context("qq.official", "leader-a", "alliance-propose"), "发起生产联盟 sect-b")
            assert proposal.code == "ALLIANCE_PROPOSED"
            alliance_id = proposal.data["alliance_id"]
            confirmed = await runtime.dispatch(_context("onebot.v11", "leader-b", "alliance-confirm"), f"确认生产联盟 {alliance_id}")
            assert confirmed.code == "ALLIANCE_CONFIRMED"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute("INSERT INTO sect_recipe_unlocks(sect_id,recipe_key,source_operation_id,unlocked_at) VALUES ('sect-a','recipe.one','seed-one',?)", (clock.value.isoformat(),))
                connection.execute("INSERT INTO sect_recipe_unlocks(sect_id,recipe_key,source_operation_id,unlocked_at) VALUES ('sect-a','recipe.two','seed-two',?)", (clock.value.isoformat(),))
                connection.execute("INSERT INTO sect_recipe_unlocks(sect_id,recipe_key,source_operation_id,unlocked_at) VALUES ('sect-a','recipe.three','seed-three',?)", (clock.value.isoformat(),))
                connection.execute("INSERT INTO sect_recipe_unlocks(sect_id,recipe_key,source_operation_id,unlocked_at) VALUES ('sect-a','recipe.four','seed-four',?)", (clock.value.isoformat(),))
            for index, recipe in enumerate(("recipe.one", "recipe.two", "recipe.three"), start=1):
                result = await runtime.dispatch(_context("qq.official", "leader-a", f"sync-{index}"), f"同步联盟配方 {alliance_id} {recipe}")
                assert result.code == "ALLIANCE_RESEARCH_SYNCED"
            capped = await runtime.dispatch(_context("qq.official", "leader-a", "sync-four"), f"同步联盟配方 {alliance_id} recipe.four")
            assert capped.code == "ALLIANCE_RESEARCH_WEEKLY_CAP"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute("SELECT COUNT(*) FROM sect_recipe_unlocks WHERE sect_id='sect-b'").fetchone()[0] == 3
                assert connection.execute("SELECT spirit_stones FROM sects WHERE sect_id='sect-a'").fetchone()[0] == 20000

            first_end = await runtime.dispatch(_context("qq.official", "leader-a", "alliance-end-request"), f"解除生产联盟 {alliance_id}")
            assert first_end.code == "ALLIANCE_END_REQUESTED"
            second_end = await runtime.dispatch(_context("onebot.v11", "leader-b", "alliance-end"), f"解除生产联盟 {alliance_id}")
            assert second_end.code == "ALLIANCE_END_REQUESTED"
            assert second_end.data["status"] == "ended"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute("SELECT spirit_stones FROM sects WHERE sect_id='sect-a'").fetchone()[0] == 10000
                assert connection.execute("SELECT COUNT(*) FROM sect_alliance_cooldowns").fetchone()[0] == 2
            await runtime.close()

    asyncio.run(run())


def test_alliance_confirmation_expires_and_is_idempotent() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 25, 12, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            for user_id in ("expire-a", "expire-b"):
                assert (await runtime.dispatch(_context("qq.official", user_id, f"create-{user_id}"), "开始修仙")).code == "PLAYER_CREATED"
            now_text = clock.value.isoformat()
            with sqlite3.connect(runtime.settings.database_path) as connection:
                players = dict(connection.execute("SELECT platform_user_id,id FROM players").fetchall())
                for sect_id, name, leader in (("expire-a-sect", "甲过期", players["expire-a"]), ("expire-b-sect", "乙过期", players["expire-b"])):
                    connection.execute("INSERT INTO sects(sect_id,name,name_key,leader_id,status,level,max_members,warehouse_capacity,construction,spirit_stones,sect_merit,warehouse_json,created_at,updated_at,content_version,rule_version) VALUES (?,?,?,?, 'active',5,120,100,0,20000,0, '{}',?,?, 'content-0.5','social-0.5.0')", (sect_id, name, name.casefold(), leader, now_text, now_text))
                    connection.execute("INSERT INTO sect_members(sect_id,player_id,role,status,contribution,joined_at,last_action_at,created_at,updated_at) VALUES (?,?, 'leader','active',0,?,?,?,?)", (sect_id, leader, now_text, now_text, now_text, now_text))
            proposal = await runtime.dispatch(_context("qq.official", "expire-a", "expire-propose"), "发起生产联盟 expire-b-sect")
            assert proposal.code == "ALLIANCE_PROPOSED"
            replay = await runtime.dispatch(_context("qq.official", "expire-a", "expire-propose"), "发起生产联盟 expire-b-sect")
            assert replay.data["idempotent_replay"] is True
            clock.value += timedelta(hours=25)
            expired = await runtime.dispatch(_context("qq.official", "expire-b", "expire-confirm"), f"确认生产联盟 {proposal.data['alliance_id']}")
            assert expired.code == "ALLIANCE_CONFIRMATION_EXPIRED"
            await runtime.close()

    asyncio.run(run())
