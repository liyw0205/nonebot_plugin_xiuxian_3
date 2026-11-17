from __future__ import annotations

import asyncio
import json
from dataclasses import replace

import pytest

from nonebot_plugin_xiuxian_3.xiuxian.content import ContentError, bundled_content
from nonebot_plugin_xiuxian_3.xiuxian.content_integrity import validate_source_content
from nonebot_plugin_xiuxian_3.xiuxian.production.rules import recipe_definitions, random_quality_bp
from nonebot_plugin_xiuxian_3.xiuxian.specials.idle_rules import idle_route_definitions, select_wilderness_choice
from nonebot_plugin_xiuxian_3.xiuxian.persistence.errors import IdleRequirementError
from test_companion_old_trail_mainline import _database_state, _inventory
from test_field_journeys import FieldJourney
from test_mainline_vertical_slice import _copy_content
from test_wilderness_idle import change_content, starter


CAMPS = [
    ("outskirts", "近郊篝火营", "xuantian.outskirts", "qi_sensing", 2, 4, "分饭搬材", "备药守草"),
    ("ironwood", "铁木桥畔营", "xuantian.ironwood_grove", "qi_sensing", 4, 6, "分饭固桥", "备药巡林"),
    ("basalt", "岩径避风营", "xuantian.basalt_pass", "qi_gathering", 3, 8, "分饭筛砂", "备药立标"),
]


def raw_supplies(j):
    with j.runtime.repository._connect() as db:
        row = db.execute("SELECT inventory_json FROM players WHERE platform_user_id='gatherer'").fetchone()
        inventory = json.loads(row[0])
        for key in ("item.food.spirit_rice", "item.pill.healing_low"):
            inventory.pop(key, None)
        inventory.update({"item.food.coarse_spirit_rice": 12, "item.herb.blood_grass": 12, "item.tool.basic_furnace": 1})
        db.execute("UPDATE players SET inventory_json=?, realm_layer=4, stamina=100, energy=100, spirit_stones=1000", (json.dumps(inventory),))


async def prepare(j, variant):
    with j.runtime.repository._connect() as db:
        db.execute("UPDATE players SET subprofession_key=?, selected_service=?, realm_key='qi_sensing', realm_layer=4, energy=100",
                   ("cooking" if variant == "meal" else "alchemy", "cooking" if variant == "meal" else "alchemy"))
    name = "灵米饭" if variant == "meal" else "低阶疗伤丹"
    op = next(f"supply-{variant}-{j.sequence}-{n}" for n in range(100) if random_quality_bp(f"supply-{variant}-{j.sequence}-{n}") == 1000)
    started = await j.send("开始生产 " + name, op)
    assert started.ok, started.message
    j.clock.advance(minutes=1)
    made = await j.send("领取生产", "claim-" + op)
    assert made.ok and made.data["success"], made.message
    return "item.food.spirit_rice" if variant == "meal" else "item.pill.healing_low"


@pytest.mark.parametrize("damage", ["bool", "zero", "empty", "unknown", "unproduced", "partial", "consumer", "fallback"])
def test_supplied_camps_strict_costs_producers_and_consumers(damage):
    def mutate(records):
        row = records["livelihood", "idle.camp.outskirts"]
        choice = row["wilderness_event"]["choices"][0]
        if damage == "bool": choice["supplies"]["item.food.spirit_rice"] = True
        elif damage == "zero": choice["supplies"]["item.food.spirit_rice"] = 0
        elif damage == "empty": choice["supplies"] = {}
        elif damage == "unknown": choice["supplies"] = {"item.missing": 1}
        elif damage == "unproduced": choice["supplies"] = {"item.mat.wood": 1}
        elif damage == "partial": row["wilderness_event"]["choices"][1].pop("supplies")
        elif damage == "consumer": choice["recipe_keys"] = ["recipe.array.gathering_basic"]
        else: records["reward", row["fallback_reward_pool_key"]]["outcomes"][0]["rewards"]["codex.story.camp.outskirts"] = 1
    with pytest.raises((ContentError, KeyError)):
        idle_route_definitions(change_content(mutate))


def test_supplied_camp_content_has_real_production_and_economic_consumers():
    content = bundled_content()
    validate_source_content(content)
    recipes = recipe_definitions(content)
    assert recipes["recipe.armor.patrol_vest"].outputs == {"item.armor.patrol_vest": 1}
    for slug, *_ in CAMPS:
        route = idle_route_definitions(content)["idle.camp." + slug]
        assert route.required_location and route.duration_seconds in {14400, 21600, 28800}
        with pytest.raises(IdleRequirementError):
            select_wilderness_choice(route, None)
        choices = [select_wilderness_choice(route, c["key"]) for c in route.wilderness_event["choices"]]
        assert choices[0].supply_cost != choices[1].supply_cost
        assert choices[0].pool_key != choices[1].pool_key


@pytest.mark.parametrize("adapter", ["qq.official", "onebot.v11"])
@pytest.mark.parametrize("slug,name,location,realm,layer,hours,meal,pill", CAMPS)
def test_supplied_camp_public_choices_cost_refund_freeze_and_recovery(tmp_path, adapter, slug, name, location, realm, layer, hours, meal, pill):
    async def run():
        j = FieldJourney(_copy_content(tmp_path), adapter)
        try:
            await starter(j.runtime, adapter=adapter)
            raw_supplies(j)
            with j.runtime.repository._connect() as db:
                db.execute("UPDATE players SET location_key=?, realm_key=?, realm_layer=?", (location, realm, layer))
            before = _database_state(j.runtime)
            preview = await j.send("挂机预览 " + name, writable=False)
            assert preview.ok and "补给不足" in preview.message
            await j.render(preview, "开始挂机 " + name + " " + meal)
            assert not preview.actions and _database_state(j.runtime) == before
            assert (await j.send("开始挂机 " + name)).code == "IDLE_REQUIREMENT_MISSING"
            for index, (variant, choice) in enumerate((("meal", meal), ("pill", pill))):
                if index:
                    await j.next_day()
                supply = await prepare(j, variant)
                with j.runtime.repository._connect() as db:
                    db.execute("UPDATE players SET location_key=?, realm_key=?, realm_layer=?, stamina=100, energy=100", (location, realm, layer))
                assert not (await j.send(f"开始挂机 {name} {choice}", writable=False)).ok
                inventory = _inventory(j.runtime)
                assert (await j.send(f"开始挂机 {name} {choice}", "undo-" + variant)).ok
                assert _inventory(j.runtime).get(supply, 0) == inventory[supply] - 1
                j.fail("cancel-" + variant)
                before = _database_state(j.runtime)
                assert (await j.send("取消挂机", "cancel-" + variant)).code == "PERSISTENCE_ERROR"
                assert _database_state(j.runtime) == before
                j.repair()
                cancelled = await j.send("取消挂机", "cancel-" + variant)
                assert cancelled.ok and cancelled.data["refunded"][supply] == 1
                assert _inventory(j.runtime) == inventory
                assert (await j.send("取消挂机", "cancel-" + variant)).data["idempotent_replay"]
                op = "start-" + variant
                j.fail(op)
                before = _database_state(j.runtime)
                assert (await j.send(f"开始挂机 {name} {choice}", op)).code == "PERSISTENCE_ERROR"
                assert _database_state(j.runtime) == before
                j.repair()
                started = await j.send(f"开始挂机 {name} {choice}", op)
                assert started.ok and started.data["cost"][supply] == 1, started.message
                await j.render(started, "取消挂机", keyboard=True)
                assert (await j.send(f"开始挂机 {name} {choice}", op)).data["idempotent_replay"]
                assert (await j.send(f"开始挂机 {name} " + (pill if variant == "meal" else meal), op)).code == "OPERATION_CONFLICT"
                assert (await j.send(f"开始挂机 {name} {choice}", op, user="foreign")).code == "OPERATION_CONFLICT"
                assert (await j.send("领取挂机", "claim-" + variant)).code == "IDLE_CLAIM_TOO_EARLY"
                j.clock.advance(seconds=61)
                assert (await j.send("取消挂机", "late-cancel")).code == "IDLE_CANCEL_WINDOW_EXPIRED"
                j.clock.advance(hours=hours)
                await j.restart()
                with j.runtime.repository._connect() as db:
                    saved = db.execute("SELECT snapshot_json FROM idle_assignments WHERE operation_id=?", (op,)).fetchone()[0]
                    snapshot = json.loads(saved)
                    bad = json.loads(saved)
                    bad["cost"][supply] = 100
                    db.execute("UPDATE idle_assignments SET snapshot_json=? WHERE operation_id=?", (json.dumps(bad), op))
                before = _database_state(j.runtime)
                with pytest.raises(ValueError, match="supply evidence"):
                    await j.send("领取挂机", "claim-" + variant)
                assert _database_state(j.runtime) == before
                with j.runtime.repository._connect() as db:
                    db.execute("UPDATE idle_assignments SET snapshot_json=? WHERE operation_id=?", (saved, op))
                original = j.runtime.repository.content
                records = dict(original._records)
                for kind, key in [("livelihood", "idle.camp." + slug), ("reward", snapshot["pool_key"]), ("recipe", "recipe.armor.patrol_vest")]:
                    records[kind, key] = {**records[kind, key], "status": "locked"}
                j.runtime.repository.content = replace(original, _records=records)
                j.fail("claim-" + variant)
                before = _database_state(j.runtime)
                assert (await j.send("领取挂机", "claim-" + variant)).code == "PERSISTENCE_ERROR"
                assert _database_state(j.runtime) == before
                j.repair()
                inventory = _inventory(j.runtime)
                claims = await asyncio.gather(j.send("领取挂机", "claim-" + variant), j.send("领取挂机", "claim-" + variant))
                assert all(r.ok for r in claims), [r.message for r in claims]
                assert sum(r.data["idempotent_replay"] for r in claims) == 1
                assert claims[0].data["reward"] == snapshot["full_reward"] and not claims[0].data["fallback"]
                assert _inventory(j.runtime).get(supply, 0) == inventory.get(supply, 0)
                await j.render(claims[0], "生产预览 巡山护甲")
                assert snapshot["gathering_journal"]["complete_text"] in claims[0].message
                j.runtime.repository.content = original
                before = _database_state(j.runtime)
                assert (await j.send(f"开始挂机 {name} {choice}", "quota")).code == "IDLE_DAILY_LIMIT"
                assert _database_state(j.runtime) == before
        finally:
            await j.runtime.close()
    asyncio.run(run())
