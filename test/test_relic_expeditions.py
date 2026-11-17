from __future__ import annotations

import asyncio
import json
from dataclasses import replace

import pytest

from nonebot_plugin_xiuxian_3.xiuxian.content import ContentError, bundled_content
from nonebot_plugin_xiuxian_3.xiuxian.content_integrity import validate_exploration_content, validate_source_content
from nonebot_plugin_xiuxian_3.xiuxian.exploration.relic_rules import relic_definition
from combat_fixtures import BALANCED_QUALIFICATION
from test_companion_old_trail_mainline import _database_state, _inventory
from test_field_journeys import FieldJourney
from test_mainline_vertical_slice import _copy_content
from test_wilderness_idle import change_content, starter
from nonebot_plugin_xiuxian_3.xiuxian.exploration.rules import battle_roll_bp, resolve_exploration_mode


MODES = ("explore.relic.creek", "explore.relic.ironwood", "explore.relic.basalt")


def configure_player(j, **values):
    with j.runtime.repository._connect() as db:
        db.execute("UPDATE players SET " + ", ".join(f"{key}=?" for key in values), tuple(values.values()))


def player_resources(j):
    with j.runtime.repository._connect() as db:
        row = db.execute("SELECT stamina, energy FROM players").fetchone()
        return int(row["stamina"]), int(row["energy"])


def strengthen_outskirts_encounters(j):
    original = j.runtime.repository.content
    records = dict(original._records)
    for key in ("enemy.wood_rat", "enemy.iron_boar"):
        enemy = dict(records["enemy", key])
        stats = dict(enemy["stats"])
        stats.update(hp=1_000_000, attack=100_000, initiative=10_000)
        enemy["stats"] = stats
        records["enemy", key] = enemy
    j.runtime.repository.content = replace(original, _records=records)
    return original


async def complete_site(j, key, prefix):
    started = await j.send("勘察地貌 " + key, prefix + "-start")
    assert started.ok, started.message
    for index, node in enumerate(started.data["site"]["nodes"]):
        result = await j.send(f"勘察抉择 {key} {node['choices'][0]['key']}", f"{prefix}-{index}")
        assert result.ok and result.data["success"] and result.data["state"]["step"] == index + 1
        j.clock.advance(seconds=60)
    return result


@pytest.mark.parametrize("damage", ["extra", "chance", "survey", "cost", "window", "supply", "restore", "delivery", "consumer", "encounter"])
def test_relic_content_requires_real_gates_producers_and_consumers(damage):
    def mutate(records):
        mode = records["exploration_mode", MODES[0]]
        if damage == "extra":
            mode["relic"]["unknown"] = True
        elif damage == "chance":
            mode["battle_chance_bp"] = 9999
        elif damage == "survey":
            mode["relic"]["survey_key"] = "survey.missing"
        elif damage == "cost":
            mode["relic"]["costs"]["item.relic.excavation_kit"] = True
        elif damage == "window":
            mode["relic"]["cancel_seconds"] = mode["duration_seconds"]
        elif damage == "supply":
            mode["relic"]["supply_recipe_key"] = "recipe.missing"
        elif damage == "restore":
            mode["relic"]["recipe_key"] = "recipe.missing"
        elif damage == "delivery":
            mode["relic"]["commission_key"] = "town_commission.missing"
        elif damage == "encounter":
            records["exploration_mode", MODES[1]]["enemy_pool_key"] = "encounter.xuantian.ironwood"
        else:
            records["recipe", "recipe.relic.field_compass"]["inputs"].pop("item.relic.clay_disc")

    with pytest.raises(ContentError):
        bundle = change_content(mutate)
        target = MODES[1] if damage == "encounter" else MODES[0]
        relic_definition(bundle.require("exploration_mode", target), bundle)


def test_relic_content_is_bound_to_sources_and_usable_consumers():
    bundle = bundled_content()
    assert validate_exploration_content(bundle) == 33
    assert validate_source_content(bundle) == 34
    for key, alias in zip(MODES, ("溪崖寻遗", "匠棚寻遗", "岩径寻遗"), strict=True):
        row = bundle.require("exploration_mode", key)
        assert row["aliases"] == [alias]
        assert resolve_exploration_mode(alias, bundle) == key
        definition = relic_definition(row, bundle)
        assert definition["survey_key"] in {"survey.creek_cliff", "survey.iron_roots", "survey.basalt_channel"}
        assert definition["costs"] == {"item.relic.excavation_kit": 1}
        pool = bundle.require("encounter_pool", row["enemy_pool_key"])
        assert all(
            bundle.require("enemy", candidate["enemy_key"])["location_key"] == row["location_key"]
            for candidate in pool["candidates"]
        )


@pytest.mark.parametrize("adapter", ["qq.official", "onebot.v11"])
def test_relic_full_public_battle_restore_commission_and_equipment_projection(tmp_path, adapter):
    async def run():
        j = FieldJourney(_copy_content(tmp_path), adapter)
        try:
            await starter(j.runtime, adapter=adapter)
            configure_player(j, realm_key="qi_gathering", realm_layer=3, stamina=100, stamina_max=100,
                             energy=100, energy_max=100, spirit_stones=1000, max_hp=999, initiative=99)
            before = _database_state(j.runtime)
            preview = await j.send("寻遗预览", writable=False)
            assert preview.ok and len(preview.data["entries"]) == 3
            assert all(not entry["unlocked"] for entry in preview.data["entries"])
            await j.render(preview, "开始探索 溪崖旧窑")
            assert _database_state(j.runtime) == before
            assert (await j.send("开始探索 溪崖旧窑", "ungated")).code == "RELIC_REQUIREMENT_MISSING"

            await complete_site(j, "survey.creek_cliff", "relic-creek")
            before_supplies = _database_state(j.runtime)
            missing_supplies = await j.send("开始探索 溪崖寻遗", "relic-no-supplies")
            assert missing_supplies.code == "RELIC_REQUIREMENT_MISSING"
            assert _database_state(j.runtime) == before_supplies
            await j.move("铁木林")
            await complete_site(j, "survey.iron_roots", "relic-iron")
            await j.move("近郊")
            await j.move("玄武岩径")
            await complete_site(j, "survey.basalt_channel", "relic-basalt")
            await j.move("近郊")
            await j.move("青石镇")

            for index in range(2):
                made = await j.send("开始生产 勘掘行囊", f"kit-{index}")
                assert made.ok, made.message
                j.clock.advance(seconds=30)
                collected = await j.send("领取生产", f"kit-claim-{index}")
                assert collected.ok and collected.data["outputs"] == {"item.relic.excavation_kit": 2}
            await j.move("近郊")

            # The short preparation cancellation restores the kit; replay is read-only.
            kit_before = _inventory(j.runtime)["item.relic.excavation_kit"]
            resources_before = player_resources(j)
            for field, code in (("stamina", "RESOURCE_INSUFFICIENT"), ("energy", "ENERGY_INSUFFICIENT")):
                configure_player(j, **{field: 0})
                before_insufficient = _database_state(j.runtime)
                insufficient = await j.send("开始探索 溪崖寻遗", "relic-low-" + field)
                assert insufficient.code == code
                assert _database_state(j.runtime) == before_insufficient
                configure_player(j, stamina=resources_before[0], energy=resources_before[1])
            state_before_rollback = _database_state(j.runtime)
            j.fail("relic-start-rollback")
            trigger_state = _database_state(j.runtime)
            rollback = await j.send("开始探索 溪崖旧窑", "relic-start-rollback")
            assert rollback.code == "PERSISTENCE_ERROR"
            assert _database_state(j.runtime) == trigger_state
            assert _inventory(j.runtime)["item.relic.excavation_kit"] == kit_before
            j.repair()
            assert _database_state(j.runtime) == state_before_rollback

            raced = await asyncio.gather(
                j.send("开始探索 溪崖旧窑", "relic-creek-start-cancel"),
                j.send("开始探索 溪崖旧窑", "relic-creek-start-race"),
            )
            successful = [result for result in raced if result.ok]
            rejected = [result for result in raced if not result.ok]
            assert len(successful) == len(rejected) == 1
            first = successful[0]
            first_operation = first.operation_id
            assert first.data["relic"]["definition"]["cancel_seconds"] == 60
            assert rejected[0].code == "EXPLORATION_BUSY"
            assert _inventory(j.runtime)["item.relic.excavation_kit"] == kit_before - 1
            assert player_resources(j) == (resources_before[0] - 5, resources_before[1] - 2)

            with j.runtime.repository._connect() as db:
                row = db.execute("SELECT snapshot_json FROM exploration_sessions WHERE operation_id=?",
                                 (first_operation,)).fetchone()
                original_snapshot = row["snapshot_json"]
                tampered = json.loads(original_snapshot)
                tampered["relic"]["reward"] = {"item.relic.clay_disc": 999}
                db.execute("UPDATE exploration_sessions SET snapshot_json=? WHERE operation_id=?",
                           (json.dumps(tampered, ensure_ascii=False), first_operation))
            tampered_state = _database_state(j.runtime)
            refused_cancel = await j.send("取消探索", "relic-corrupt-cancel")
            assert refused_cancel.code == "PERSISTENCE_ERROR"
            assert _database_state(j.runtime) == tampered_state
            with j.runtime.repository._connect() as db:
                db.execute("UPDATE exploration_sessions SET snapshot_json=? WHERE operation_id=?",
                           (original_snapshot, first_operation))

            assert (await j.send("开始探索 溪崖旧窑", first_operation)).data["idempotent_replay"]
            conflict_before = _database_state(j.runtime)
            assert (await j.send("开始探索 铁木旧匠棚", first_operation)).code == "OPERATION_CONFLICT"
            assert _database_state(j.runtime) == conflict_before
            j.clock.advance(seconds=10)
            cancelled = await j.send("取消探索", "relic-creek-cancel")
            assert cancelled.ok and cancelled.data["item_refund"] == {"item.relic.excavation_kit": 1}
            assert _inventory(j.runtime)["item.relic.excavation_kit"] == kit_before
            assert player_resources(j) == resources_before
            assert (await j.send("取消探索", "relic-creek-cancel")).data["idempotent_replay"]
            await j.restart()
            before_restart_replay = _database_state(j.runtime)
            assert (await j.send("取消探索", "relic-creek-cancel")).data["idempotent_replay"]
            assert _database_state(j.runtime) == before_restart_replay

            # The second same-day outing wins and preserves the first relic.
            second = await j.send("开始探索 溪崖旧窑", "relic-creek-win")
            assert second.ok and second.data["relic"]
            with j.runtime.repository._connect() as db:
                frozen = json.loads(db.execute("SELECT snapshot_json FROM exploration_sessions WHERE operation_id='relic-creek-win'").fetchone()[0])
                assert frozen["battle_chance_bp"] == frozen["base_battle_chance_bp"] == 10000
                assert frozen["relic"]["discovery_operation_id"]
            j.clock.advance(seconds=180)
            creek_win = await j.send("结算探索", "relic-creek-win-settle")
            assert creek_win.ok and creek_win.data["battle_outcome"] == "won"
            assert creek_win.data["result"]["item.relic.clay_disc"] >= 2
            before_quota = _database_state(j.runtime)
            limited = await j.send("开始探索 溪崖寻遗", "relic-creek-quota")
            assert limited.code == "EXPLORATION_QUOTA_EXHAUSTED"
            assert _database_state(j.runtime) == before_quota
            before_loss = _inventory(j.runtime).get("item.relic.clay_disc", 0)
            kit_before_loss = _inventory(j.runtime)["item.relic.excavation_kit"]

            # A next-day outing passes the cancel window and loses to real combat.
            await j.next_day()
            configure_player(j, max_hp=0, initiative=0)
            original_content = strengthen_outskirts_encounters(j)
            lost_start = await j.send("开始探索 溪崖旧窑", "relic-creek-loss")
            assert lost_start.ok
            j.clock.advance(seconds=60)
            before_closed_cancel = _database_state(j.runtime)
            assert (await j.send("取消探索", "relic-late-cancel")).code == "RELIC_CANCEL_WINDOW_CLOSED"
            assert _database_state(j.runtime) == before_closed_cancel
            j.clock.advance(seconds=120)
            lost = await j.send("结算探索", "relic-creek-loss-settle")
            assert lost.ok and lost.data["battle_outcome"] == "lost" and lost.data["result"] == {}
            with j.runtime.repository._connect() as db:
                battle = db.execute(
                    "SELECT snapshot_json FROM battle_sessions WHERE battle_id=?",
                    (lost.data["battle_id"],),
                ).fetchone()
                enemy_snapshot = json.loads(battle["snapshot_json"])["enemy"]
                assert enemy_snapshot["max_hp"] == 1_000_000
            assert enemy_snapshot["attack"] == 100_000
            assert _inventory(j.runtime).get("item.relic.clay_disc", 0) == before_loss
            assert _inventory(j.runtime)["item.relic.excavation_kit"] == kit_before_loss - 1
            before = _database_state(j.runtime)
            replay = await j.send("结算探索", "relic-creek-loss-settle")
            assert replay.data["idempotent_replay"] and _database_state(j.runtime) == before
            j.clock.advance(minutes=15)
            j.runtime.repository.content = original_content
            configure_player(j, max_hp=999, initiative=99)

            recovered = dict(creek_win.data["result"])
            for location, mode, op, duration in (
                ("铁木林", "铁木旧匠棚", "relic-iron-run", 240),
                ("玄武岩径", "岩径水工坊", "relic-basalt-run", 300),
            ):
                if location == "铁木林":
                    await j.move("铁木林")
                else:
                    await j.next_day()
                    await j.move("近郊")
                    await j.move("玄武岩径")
                started = await j.send("开始探索 " + mode, op)
                assert started.ok, started.message
                assert (await j.send("开始探索 " + mode, op)).data["idempotent_replay"]
                await j.restart()
                if mode == "岩径水工坊":
                    original = j.runtime.repository.content
                    records = dict(original._records)
                    records["exploration_mode", "explore.relic.basalt"] = {
                        **records["exploration_mode", "explore.relic.basalt"], "status": "locked"
                    }
                    j.runtime.repository.content = replace(original, _records=records)
                j.clock.advance(seconds=duration)
                settled = await j.send("结算探索", op + "-settle")
                assert settled.ok and settled.data["battle_outcome"] == "won", settled.message
                assert settled.data["result"] and settled.data["relic"]
                recovered.update(settled.data["result"])
                if mode == "岩径水工坊":
                    assert "复原山河罗盘" in settled.message
                    j.runtime.repository.content = original

            for key in ("item.relic.clay_disc", "item.relic.bronze_needle", "item.relic.water_ring"):
                assert recovered[key] >= 2
            await j.move("近郊")
            await j.move("青石镇")
            compass = await j.send("开始生产 山河罗盘", "compass")
            assert compass.ok, compass.message
            j.clock.advance(seconds=90)
            compass_result = await j.send("领取生产", "compass-claim")
            assert compass_result.ok and compass_result.data["success"]
            assert compass_result.data["outputs"] == {"item.accessory.field_compass": 1}
            assert (await j.send("接取委托 古器收录", "relic-delivery-accept")).ok
            delivery_before = _inventory(j.runtime)
            delivered = await j.send("交付委托 古器收录", "relic-delivery")
            assert delivered.ok, delivered.message
            for key in ("item.relic.clay_disc", "item.relic.bronze_needle", "item.relic.water_ring"):
                assert _inventory(j.runtime).get(key, 0) == delivery_before.get(key, 0) - 1
            assert (await j.send("交付委托 古器收录", "relic-delivery")).data["idempotent_replay"]

            assert (await j.send("卸下装备 山河罗盘", "unequip-compass")).ok
            with j.runtime.repository._connect() as db:
                player = db.execute("SELECT * FROM players").fetchone()
                before_stats = j.runtime.repository._build_player_stat_snapshot(db, player)
            assert (await j.send("穿戴装备 山河罗盘", "equip-compass")).ok
            with j.runtime.repository._connect() as db:
                player = db.execute("SELECT * FROM players").fetchone()
                after_stats = j.runtime.repository._build_player_stat_snapshot(db, player)
            compass_instance = next(item for item in after_stats["equipment"]
                                    if item["item_key"] == "item.accessory.field_compass")
            durability = compass_instance["durability_bp"]
            assert after_stats["derived_stats"]["max_hp"] - before_stats["derived_stats"]["max_hp"] == 28 * durability // 10000
            assert after_stats["derived_stats"]["accuracy_bp"] - before_stats["derived_stats"]["accuracy_bp"] == 180 * durability // 10000
            await j.move("近郊")
            fight_op = next(f"compass-fight-{n}" for n in range(1000)
                            if battle_roll_bp(f"compass-fight-{n}:battle") < 6500)
            assert (await j.send("开始探索 近郊巡路 追迹", fight_op)).ok
            j.clock.advance(minutes=5)
            fought = await j.send("结算探索", "compass-fight-settle")
            assert fought.ok
            with j.runtime.repository._connect() as db:
                snapshot = json.loads(db.execute("SELECT snapshot_json FROM exploration_sessions WHERE operation_id=?", (fight_op,)).fetchone()[0])
                assert any(item["item_key"] == "item.accessory.field_compass" for item in snapshot["equipment"])
                assert any(item["item_key"] == "item.accessory.field_compass" for item in snapshot["stat_snapshot"]["equipment"])
                assert snapshot["stat_snapshot"]["combat_stats"] == after_stats["combat_stats"]
        finally:
            await j.runtime.close()
    asyncio.run(run())


def test_relic_expiration_keeps_spent_resources_and_skips_combat(tmp_path):
    async def run():
        j = FieldJourney(_copy_content(tmp_path), "onebot.v11")
        try:
            await starter(j.runtime, adapter="onebot.v11")
            configure_player(j, realm_key="qi_gathering", realm_layer=3, stamina=100, stamina_max=100,
                             energy=100, energy_max=100, spirit_stones=1000, max_hp=999, initiative=99)
            await complete_site(j, "survey.creek_cliff", "relic-expiry-survey")
            await j.move("铁木林")
            await complete_site(j, "survey.iron_roots", "relic-expiry-iron-survey")
            await j.move("近郊")
            await j.move("青石镇")
            made = await j.send("开始生产 勘掘行囊", "relic-expiry-kit")
            assert made.ok, made.message
            j.clock.advance(seconds=30)
            assert (await j.send("领取生产", "relic-expiry-kit-claim")).data["outputs"] == {
                "item.relic.excavation_kit": 2
            }
            await j.move("近郊")
            kit_before = _inventory(j.runtime)["item.relic.excavation_kit"]
            resources_before = player_resources(j)
            started = await j.send("开始探索 溪崖旧窑", "relic-expiry-start")
            assert started.ok
            j.clock.advance(seconds=180 + 24 * 60 * 60 + 1)
            expired = await j.send("结算探索", "relic-expiry-settle")
            assert not expired.ok and expired.code == "EXPLORATION_EXPIRED"
            assert _inventory(j.runtime)["item.relic.excavation_kit"] == kit_before - 1
            assert _inventory(j.runtime).get("item.relic.clay_disc", 0) == 0
            assert player_resources(j) == (resources_before[0] - 5, resources_before[1] - 2)
            with j.runtime.repository._connect() as db:
                session = db.execute(
                    "SELECT status, result_json FROM exploration_sessions WHERE operation_id='relic-expiry-start'"
                ).fetchone()
                assert session["status"] == "expired"
                assert json.loads(session["result_json"])["result"] == {}
                assert db.execute("SELECT COUNT(*) FROM battle_sessions").fetchone()[0] == 0
            before_replay = _database_state(j.runtime)
            replay = await j.send("结算探索", "relic-expiry-settle")
            assert replay.data["idempotent_replay"] and _database_state(j.runtime) == before_replay
        finally:
            await j.runtime.close()
    asyncio.run(run())
