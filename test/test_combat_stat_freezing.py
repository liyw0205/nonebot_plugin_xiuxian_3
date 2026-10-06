from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from combat_fixtures import equip_damage_weapon

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.exploration.rules import battle_roll_bp


@pytest.mark.parametrize("adapter", ("qq.official", "onebot.v11"))
def test_exploration_freezes_complete_build_before_restart(tmp_path, monkeypatch, adapter):
    async def run():
        user = "frozen-explorer"
        runtime = create_runtime(data_dir=tmp_path)

        async def dispatch(operation, command):
            return await runtime.adapters.dispatch(
                adapter, CommandContext(adapter=adapter, user_id=user, operation_id=operation), command
            )

        assert (await dispatch("create", "开始修仙")).ok
        assert (await dispatch("seek", "寻仙问道")).ok
        with sqlite3.connect(runtime.settings.database_path) as connection:
            connection.execute(
                "UPDATE players SET stage='cultivator', realm_key='qi_sensing', realm_layer=2, "
                "location_key='xuantian.outskirts', path_key='body', stamina=100, max_hp=1000, "
                "initiative=100, inventory_json=? WHERE platform=? AND platform_user_id=?",
                (json.dumps({"item.manual.basic_qi": 1}), adapter, user),
            )
        operation = next(
            f"freeze-explore:{index}" for index in range(1000)
            if battle_roll_bp(f"freeze-explore:{index}:battle") < 1000
        )
        started = await dispatch(operation, "开始探索 短历练")
        assert started.code == "EXPLORATION_STARTED"
        exploration_id = started.data["exploration_id"]
        with sqlite3.connect(runtime.settings.database_path) as connection:
            frozen = json.loads(connection.execute(
                "SELECT snapshot_json FROM exploration_sessions WHERE exploration_id=?", (exploration_id,)
            ).fetchone()[0])
            assert frozen["stat_snapshot"]["combat_stats"]["max_hp"] > 1000
            assert frozen["stat_snapshot"]["manual_effects"]["combat_stat_bonus_bp"]["attack"] > 0
            connection.execute(
                "UPDATE players SET max_hp=0, initiative=0, path_key='sword', inventory_json='{}' "
                "WHERE platform=? AND platform_user_id=?", (adapter, user)
            )
            connection.execute(
                "UPDATE exploration_sessions SET ends_at=? WHERE exploration_id=?",
                ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(), exploration_id),
            )
        await runtime.close()
        runtime = create_runtime(data_dir=tmp_path)

        def no_live_build(*args, **kwargs):
            raise AssertionError("an exploration encounter must consume its entry build")

        monkeypatch.setattr(runtime.repository, "_build_player_stat_snapshot", no_live_build)
        monkeypatch.setattr(runtime.repository, "_battle_skill_snapshot", no_live_build)
        monkeypatch.setattr(runtime.repository, "_battle_equipment_snapshot", no_live_build)
        settled = await dispatch("settle", "结算探索")
        assert settled.code == "EXPLORATION_SETTLED"
        assert settled.data["battle_outcome"] == "won"
        replay = await runtime.repository.replay_battle(
            platform=adapter, platform_user_id=user, battle_id=settled.data["battle_id"]
        )
        player = replay.snapshot["player"]
        assert player["stat_snapshot"] == frozen["stat_snapshot"]
        assert player["stats"] == frozen["stat_snapshot"]["combat_stats"]
        assert player["path_key"] == frozen["path_key"]
        assert player["skills"] == frozen["skills"]
        again = await dispatch("settle", "结算探索")
        assert again.code == "EXPLORATION_SETTLED"
        assert again.data["idempotent_replay"] is True
        with sqlite3.connect(runtime.settings.database_path) as connection:
            assert connection.execute("SELECT COUNT(*) FROM battle_sessions").fetchone()[0] == 1
            assert connection.execute("SELECT COUNT(*) FROM stat_snapshots").fetchone()[0] == 0
            assert connection.execute(
                "SELECT stamina FROM players WHERE platform=? AND platform_user_id=?", (adapter, user)
            ).fetchone()[0] == 100 - started.data["stamina_cost"]
        await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize(
    "name,table,realm,location,permission,nodes,member_count",
    (
        ("远古洞天", "ancient_domain_runs", "soul_transformation", "cave.ancient_domain", None,
         ("洞天入口", "裂痕回廊 内", "封印古藏", "太初灵园", "洞天灵泉", "远古洞天之主"), 3),
        ("虚空遗迹", "void_ruins_runs", "void_refining", "void.archive_ruins", None,
         ("遗迹入口", "破碎信标", "虚空回廊", "裂隙哨卫"), 2),
        ("时序堡垒", "time_fort_runs", "void_refining", "void.archive_ruins", "access.void.time_fort",
         ("堡垒门庭", "星时回廊", "时间风暴", "残破沙漏", "守时者"), 2),
    ),
)
def test_secret_realm_party_uses_complete_entry_build(
    tmp_path, monkeypatch, name, table, realm, location, permission, nodes, member_count
):
    async def run():
        runtime = create_runtime(data_dir=tmp_path)
        identities = [("qq.official" if index % 2 else "onebot.v11", f"member-{index}")
                      for index in range(member_count)]

        async def dispatch(identity, operation, command):
            adapter, user = identity
            return await runtime.adapters.dispatch(
                adapter, CommandContext(adapter=adapter, user_id=user, operation_id=operation), command
            )

        for index, identity in enumerate(identities):
            assert (await dispatch(identity, f"create:{index}", "开始修仙")).ok
            assert (await dispatch(identity, f"seek:{index}", "寻仙问道")).ok
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE players SET stage='cultivator', realm_key=?, realm_layer=1, location_key=?, "
                    "stamina=100, stamina_max=100, max_hp=10000, initiative=100, inventory_json=?, "
                    "intro_json=? WHERE platform=? AND platform_user_id=?",
                    (realm, location, json.dumps({"item.manual.basic_qi": 1, "item.void_anchor": 1}),
                     json.dumps({"flags": [permission] if permission else []}), *identity),
                )
            equip_damage_weapon(runtime, *identity, 100)
        leader = identities[0]
        created = await dispatch(leader, "party", f"创建{name}秘境队伍")
        assert created.ok, created
        party_id = created.data["party_id"]
        for index, identity in enumerate(identities[1:]):
            assert (await dispatch(leader, f"invite:{index}", f"邀请入队 {identity[0]}:{identity[1]}")).ok
            assert (await dispatch(identity, f"accept:{index}", f"接受入队 {party_id}")).ok
        for index, identity in enumerate(identities):
            assert (await dispatch(identity, f"confirm:{index}", f"确认入队 {party_id}")).ok
        entered = await dispatch(leader, "enter", f"进入秘境 {name}")
        assert entered.ok, entered
        with sqlite3.connect(runtime.settings.database_path) as connection:
            entry = json.loads(connection.execute(
                f"SELECT snapshot_json FROM {table} WHERE run_id=?", (entered.data["run_id"],)
            ).fetchone()[0])
            by_id = {member["player_id"]: member for member in entry["member_combat_snapshots"]}
            assert all(member["stat_snapshot"]["manual_effects"]["combat_stat_bonus_bp"]["attack"] == 150
                       for member in by_id.values())
            connection.execute("UPDATE players SET max_hp=0, initiative=0, inventory_json='{}', path_key='sword'")
            connection.execute("UPDATE equipment_instances SET affixes_json='{}', durability_bp=0")
        await runtime.close()
        runtime = create_runtime(data_dir=tmp_path)

        def no_live_build(*args, **kwargs):
            raise AssertionError("secret realm combat must consume its entry build")

        monkeypatch.setattr(runtime.repository, "_build_player_stat_snapshot", no_live_build)
        monkeypatch.setattr(runtime.repository, "_battle_equipment_snapshot", no_live_build)
        monkeypatch.setattr(runtime.repository, "_battle_skill_snapshot", no_live_build)
        for index, node in enumerate(nodes):
            selected = await dispatch(leader, f"node:{index}", f"选择秘境节点 {node}")
            assert selected.ok, selected
        battle_id = selected.data["battle_id"]
        with sqlite3.connect(runtime.settings.database_path) as connection:
            snapshot = json.loads(connection.execute(
                "SELECT snapshot_json FROM party_battle_sessions WHERE battle_id=?", (battle_id,)
            ).fetchone()[0])
            for member in snapshot["members"]:
                frozen = by_id[member["player_id"]]
                assert member["stat_snapshot"] == frozen["stat_snapshot"]
                assert member["stats"] == frozen["stat_snapshot"]["combat_stats"]
                assert member["path_key"] == frozen["path_key"]
                assert member["skills"] == frozen["skills"]
            assert connection.execute("SELECT COUNT(*) FROM stat_snapshots").fetchone()[0] == 0
        await runtime.close()

    asyncio.run(run())
