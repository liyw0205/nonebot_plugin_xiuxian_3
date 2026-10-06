from __future__ import annotations

import asyncio
import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.content import bundled_content
from nonebot_plugin_xiuxian_3.xiuxian.persistence.errors import OperationConflictError, OperationResultMalformedError
from nonebot_plugin_xiuxian_3.xiuxian.stats.models import StatSnapshotError
from nonebot_plugin_xiuxian_3.xiuxian.stats.presentation import STAT_LABELS
from nonebot_plugin_xiuxian_3.xiuxian.stats.rules import stats_formula
from nonebot_plugin_xiuxian_3.xiuxian.utils.equipment import create_equipment_instances
from nonebot_plugin_xiuxian_3.xiuxian.utils.player import grant_player_state


ADAPTERS = ("qq.official", "onebot.v11")


async def _send(runtime, adapter, command, operation=None):
    return await runtime.adapters.dispatch(
        adapter,
        CommandContext(adapter=adapter, user_id="stat-reader", operation_id=f"{adapter}:{operation or command}"),
        command,
    )


async def _enter(runtime, adapter):
    for command in (
        "开始修仙", "寻仙问道", "完成引导 阅读", "前往近郊",
        "完成引导 采集", "完成引导 炼丹", "选择道途 体修", "返回新手城", "选择体质 铁骨",
    ):
        result = await _send(runtime, adapter, command)
        assert result.ok, (command, result.code, result.message)


def _build_fixture(runtime, adapter):
    # Only the accumulated growth and equipment are fixtures; entry and constitution use commands.
    with runtime.repository._connect() as connection:
        player = connection.execute("SELECT * FROM players WHERE platform=?", (adapter,)).fetchone()
        now = datetime.now(timezone.utc).isoformat()
        grant_player_state(
            connection, player, updated_at=now,
            rewards={"item.manual.purple_mansion": 1},
            value_delta={"max_hp": 120, "max_mp": 90, "initiative": 7},
        )
        assert create_equipment_instances(
            connection, player_id=player["id"], item_key="item.weapon.wood_sword",
            quantity=1, now_text=now, content=runtime.content, durability_bp=5000,
        )
        connection.execute(
            "UPDATE equipment_instances SET temper_level=2, affixes_json=? WHERE player_id=? AND equipped=1",
            (json.dumps({"hp": 20, "damage": 8, "max_mana": 10}), player["id"]),
        )


def _dump(runtime):
    with runtime.repository._connect() as connection:
        return tuple(connection.iterdump())


def _freeze(runtime, adapter, operation="freeze", purpose="battle"):
    return runtime.repository.freeze_stats(
        platform=adapter, platform_user_id="stat-reader", operation_id=operation, purpose=purpose,
    )


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_profile_preview_explanation_and_spectator_share_one_complete_build(tmp_path, adapter):
    async def run():
        runtime = create_runtime(data_dir=tmp_path)
        try:
            assert (await _send(runtime, adapter, "开始修仙")).ok
            new_profile = await _send(runtime, adapter, "我的状态")
            assert new_profile.ok and new_profile.data["stats"] == {}
            await _enter(runtime, adapter)
            _build_fixture(runtime, adapter)
            before = _dump(runtime)
            preview = await _send(runtime, adapter, "我的属性")
            profile = await _send(runtime, adapter, "我的状态")
            assert preview.ok and profile.ok
            assert profile.data["stats"] == preview.data
            for label in STAT_LABELS.values():
                assert label in preview.message
            assert "攻势" in profile.message and "派生" not in profile.message
            explained = await _send(runtime, adapter, "属性说明 气血上限")
            assert explained.ok
            assert all(text in explained.message for text in ("历练所得", "随身法器", "所修功法", "天生体质"))
            assert "formula_fingerprint" not in explained.message
            assert "max_hp" not in explained.message
            rate = await _send(runtime, adapter, "属性说明 反震")
            assert rate.ok and "%" in rate.message

            with runtime.repository._connect() as connection:
                player = connection.execute("SELECT * FROM players WHERE platform=?", (adapter,)).fetchone()
                spectator, _ = runtime.repository._spectator_player_snapshot(connection, player)
                assert spectator["stats"] == preview.data["combat_stats"]
                assert spectator["stat_snapshot"] == preview.data
                formula = stats_formula(runtime.content).values
                base = preview.data["base_stats"]
                realm = (runtime.content or bundled_content()).require("realm", player["realm_key"])
                hp = (formula["max_hp_base"] + formula["realm_growth_per_index"] * realm["rank"]
                      + formula["realm_growth_per_layer"] * max(player["realm_layer"] - 1, 0)
                      + formula["max_hp_body"] * base["body"] + formula["max_hp_root"] * base["root"])
                hp += player["max_hp"] + 10
                bonus = (preview.data["manual_effects"]["combat_stat_bonus_bp"]["max_hp"]
                         + preview.data["constitution_effect"]["value"])
                assert preview.data["derived_stats"]["max_hp"] == hp + hp * bonus // 10000
                mana = (formula["max_mp_base"] + formula["max_mp_per_index"] * realm["rank"]
                        + formula["max_mp_per_layer"] * max(player["realm_layer"] - 1, 0)
                        + formula["max_mp_spirit"] * base["spirit"] + formula["max_mp_insight"] * base["insight"])
                assert preview.data["combat_stats"]["max_mana"] == mana + player["max_mp"] + 5
            training = await _send(runtime, adapter, "开始训练战")
            assert training.code == "TRAINING_SPECTATOR"
            assert _dump(runtime) == before
        finally:
            await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_stat_snapshot_replays_after_content_change_and_rejects_damaged_ledger(tmp_path, adapter):
    shutil.copytree(Path("data"), tmp_path / "content")
    data_dir = tmp_path / "content"

    async def run():
        runtime = create_runtime(data_dir=data_dir)
        try:
            await _enter(runtime, adapter)
            _build_fixture(runtime, adapter)
            original = await _freeze(runtime, adapter)
        finally:
            await runtime.close()
        rules_path = data_dir / "养成" / "规则.json"
        document = json.loads(rules_path.read_text(encoding="utf-8"))
        formula = next(row for row in document["records"] if row["key"] == "stats.formula")
        formula["formulas"]["max_hp_base"] += 700
        formula["formulas"]["weapon_temper_attack"] += 9
        rules_path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
        runtime = create_runtime(data_dir=data_dir)
        try:
            replay = await _freeze(runtime, adapter)
            assert replay.already_completed and replay.payload() == original.payload()
            with pytest.raises(OperationConflictError):
                await _freeze(runtime, adapter, purpose="exploration")
            current = await _send(runtime, adapter, "我的属性")
            assert current.data["derived_stats"]["max_hp"] > original.derived_stats["max_hp"]
            assert current.data["derived_stats"]["attack"] > original.derived_stats["attack"]
            with runtime.repository._connect() as connection:
                stored = connection.execute("SELECT result_json FROM operations WHERE operation_id='freeze'").fetchone()[0]
            missing = json.loads(stored)
            del missing["derived_stats"]["max_mp"]
            corruptions = (json.dumps(missing), stored[:-1] + ', "player_id": 0}', '{"snapshot_id":')
            for corruption in corruptions:
                with runtime.repository._connect() as connection:
                    connection.execute("UPDATE operations SET result_json=? WHERE operation_id='freeze'", (corruption,))
                before = _dump(runtime)
                with pytest.raises((OperationResultMalformedError, StatSnapshotError)):
                    await _freeze(runtime, adapter)
                assert _dump(runtime) == before
            with runtime.repository._connect() as connection:
                connection.execute("UPDATE operations SET result_json=? WHERE operation_id='freeze'", (stored,))
            assert (await _freeze(runtime, adapter)).payload() == original.payload()
        finally:
            await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_bad_stat_inputs_refuse_all_views_and_freeze_without_partial_writes(tmp_path, adapter):
    async def run():
        runtime = create_runtime(data_dir=tmp_path)
        try:
            await _enter(runtime, adapter)
            _build_fixture(runtime, adapter)
            cases = (
                ("players", "qualification_json", '{"body":10,"body":10}'),
                ("players", "qualification_json", '[]'),
                ("players", "inventory_json", '{"item.manual.basic_qi":1,"item.manual.basic_qi":0}'),
                ("players", "inventory_json", '{"item.manual.basic_qi":1.9}'),
                ("players", "inventory_json", '{"item.manual.basic_qi":"1"}'),
                ("players", "inventory_json", '{"item.manual.basic_qi":true}'),
                ("equipment_instances", "affixes_json", '{"hp":10,"hp":20}'),
                ("equipment_instances", "affixes_json", '{"damage":true}'),
                ("constitution_profiles", "snapshot_json", '{"effect":{"type":"max_hp_bp","value":300,"value":900}}'),
                ("constitution_profiles", "snapshot_json", '{"effect":{"type":"max_hp_bp","value":-1}}'),
            )
            for table, field, broken in cases:
                with runtime.repository._connect() as connection:
                    original = connection.execute(f"SELECT {field} FROM {table}").fetchone()[0]
                    connection.execute(f"UPDATE {table} SET {field}=?", (broken,))
                before = _dump(runtime)
                for command in ("我的状态", "我的属性", "属性说明 攻势"):
                    result = await _send(runtime, adapter, command)
                    assert not result.ok, (table, field, command)
                with pytest.raises(ValueError):
                    await _freeze(runtime, adapter)
                assert _dump(runtime) == before
                with runtime.repository._connect() as connection:
                    connection.execute(f"UPDATE {table} SET {field}=?", (original,))
            assert (await _send(runtime, adapter, "我的状态")).ok
            assert (await _freeze(runtime, adapter)).snapshot_id
        finally:
            await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_stat_freeze_ledger_failure_rolls_back_and_concurrent_retry_writes_once(tmp_path, adapter):
    async def run():
        runtime = create_runtime(data_dir=tmp_path)
        second = None
        try:
            await _enter(runtime, adapter)
            with runtime.repository._connect() as connection:
                connection.execute(
                    "CREATE TRIGGER reject_stat_operation BEFORE INSERT ON operations "
                    "WHEN NEW.operation_name='stats.freeze' BEGIN SELECT RAISE(ABORT, 'ledger fault'); END"
                )
            before = _dump(runtime)
            with pytest.raises(sqlite3.IntegrityError, match="ledger fault"):
                await _freeze(runtime, adapter)
            assert _dump(runtime) == before
            with runtime.repository._connect() as connection:
                connection.execute("DROP TRIGGER reject_stat_operation")
            second = create_runtime(data_dir=tmp_path)
            await second.initialize()
            results = await asyncio.gather(_freeze(runtime, adapter), _freeze(second, adapter))
            assert results[0].payload() == results[1].payload()
            assert sorted(result.already_completed for result in results) == [False, True]
            with runtime.repository._connect() as connection:
                assert connection.execute("SELECT COUNT(*) FROM stat_snapshots").fetchone()[0] == 1
                assert connection.execute("SELECT COUNT(*) FROM operations WHERE operation_id='freeze'").fetchone()[0] == 1
        finally:
            if second is not None:
                await second.close()
            await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("adapter", ADAPTERS)
@pytest.mark.parametrize("party", (False, True))
def test_combat_rejects_incomplete_or_duplicate_frozen_stats_before_writing(tmp_path, adapter, party):
    async def run():
        runtime = create_runtime(data_dir=tmp_path)
        try:
            await _enter(runtime, adapter)
            _build_fixture(runtime, adapter)
            assert (await _send(runtime, adapter, "前往近郊", "battle-location")).ok
            if party:
                helper = next(value for value in ADAPTERS if value != adapter)
                await _enter(runtime, helper)
                assert (await _send(runtime, helper, "前往近郊", "battle-location")).ok
                created = await _send(runtime, adapter, "创建双人队伍")
                assert created.ok
                party_id = created.data["party_id"]
                assert (await _send(runtime, adapter, f"邀请入队 {helper}:stat-reader")).ok
                assert (await _send(runtime, helper, f"接受入队 {party_id}")).ok
                for member in (adapter, helper):
                    assert (await _send(runtime, member, f"确认入队 {party_id}")).ok
                started = await runtime.repository.start_party_battle(
                    platform=adapter, platform_user_id="stat-reader", party_id=party_id, operation_id="battle",
                )
                table = "party_battle_sessions"
                turn = runtime.repository.run_party_battle_turn
            else:
                started = await runtime.repository.start_quest_battle(
                    platform=adapter, platform_user_id="stat-reader", enemy_key="enemy.wood_rat",
                    battle_type="pve.quest", operation_id="battle",
                )
                table = "battle_sessions"
                turn = runtime.repository.run_battle_turn
            with runtime.repository._connect() as connection:
                original = connection.execute(f"SELECT snapshot_json FROM {table}").fetchone()[0]
            missing = json.loads(original)
            player = missing["members"][0] if party else missing["player"]
            del player["stats"]["max_mana"]
            for corrupted in (json.dumps(missing), original[:-1] + ', "enemy": {}}'):
                with runtime.repository._connect() as connection:
                    connection.execute(f"UPDATE {table} SET snapshot_json=?", (corrupted,))
                before = _dump(runtime)
                with pytest.raises(ValueError):
                    await turn(battle_id=started.battle_id, expected_round=1)
                assert _dump(runtime) == before
            with runtime.repository._connect() as connection:
                connection.execute(f"UPDATE {table} SET snapshot_json=?", (original,))
            result = await turn(battle_id=started.battle_id, expected_round=1)
            assert (result["round_no"] if party else result.round_no) == 1
            before = _dump(runtime)
            await turn(battle_id=started.battle_id, expected_round=1)
            assert _dump(runtime) == before
            for round_no in range(2, 31):
                status = result["status"] if party else result.status
                if status not in {"created", "running"}:
                    break
                result = await turn(battle_id=started.battle_id, expected_round=round_no)
            assert (result["status"] if party else result.status) == "won"

            async def resolve():
                if party:
                    return await runtime.repository.resolve_party_battle(
                        platform=adapter, platform_user_id="stat-reader", battle_id=started.battle_id,
                        operation_id="resolve",
                    )
                return await runtime.repository.resolve_battle(battle_id=started.battle_id)

            for field, broken in (
                ("snapshot_json", "{"), ("snapshot_json", json.dumps(missing)),
                ("result_json", '{"outcome":"won","outcome":"lost"}'),
                *(([("state_json", '{}')]) if party else []),
            ):
                with runtime.repository._connect() as connection:
                    saved = connection.execute(f"SELECT {field} FROM {table}").fetchone()[0]
                    connection.execute(f"UPDATE {table} SET {field}=?", (broken,))
                before = _dump(runtime)
                with pytest.raises((ValueError, KeyError)):
                    await resolve()
                assert _dump(runtime) == before
                with runtime.repository._connect() as connection:
                    connection.execute(f"UPDATE {table} SET {field}=?", (saved,))
            settled = await resolve()
            assert settled.outcome == "won"
            with runtime.repository._connect() as connection:
                if party:
                    assert connection.execute("SELECT COUNT(*) FROM party_battle_rewards").fetchone()[0] == 2
                else:
                    assert connection.execute("SELECT durability_bp FROM equipment_instances").fetchone()[0] == 4950
            before = _dump(runtime)
            assert (await resolve()).already_completed
            assert _dump(runtime) == before
        finally:
            await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_profile_recovery_and_attribute_read_share_one_transaction(tmp_path, adapter):
    async def run():
        runtime = create_runtime(data_dir=tmp_path)
        try:
            await _enter(runtime, adapter)
            with runtime.repository._connect() as connection:
                qualification = connection.execute("SELECT qualification_json FROM players").fetchone()[0]
                connection.execute(
                    "UPDATE players SET realm_key='soul_transformation', realm_layer=1, domain_charge=0, "
                    "domain_charge_max=150, domain_charge_reset_date='2000-01-01', "
                    "domain_crack_until='2000-01-01T00:00:00+00:00', qualification_json='{}'"
                )
            before = _dump(runtime)
            assert not (await _send(runtime, adapter, "我的状态")).ok
            assert _dump(runtime) == before
            with runtime.repository._connect() as connection:
                connection.execute("UPDATE players SET qualification_json=?", (qualification,))
            profile = await _send(runtime, adapter, "我的状态")
            assert profile.ok
            with runtime.repository._connect() as connection:
                row = connection.execute("SELECT domain_charge, domain_crack_until FROM players").fetchone()
                assert tuple(row) == (150, None)
            preview = await _send(runtime, adapter, "我的属性")
            assert profile.data["stats"] == preview.data
        finally:
            await runtime.close()

    asyncio.run(run())
