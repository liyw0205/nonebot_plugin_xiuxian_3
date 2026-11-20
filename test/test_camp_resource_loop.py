from __future__ import annotations

import asyncio
import json

import pytest

from combat_fixtures import BALANCED_QUALIFICATION
from nonebot_plugin_xiuxian_3.xiuxian.exploration.rules import battle_roll_bp
from test_companion_old_trail_mainline import _database_state, _inventory
from test_field_journeys import FieldJourney
from test_mainline_vertical_slice import _copy_content
from test_supplied_camps import CAMPS, prepare, raw_supplies
from test_wilderness_idle import starter


@pytest.mark.parametrize("adapter", ["qq.official", "onebot.v11"])
def test_camps_real_supply_production_travel_equipment_combat_and_delivery(tmp_path, adapter):
    async def run():
        j = FieldJourney(_copy_content(tmp_path), adapter)
        try:
            await starter(j.runtime, adapter=adapter)
            raw_supplies(j)
            with j.runtime.repository._connect() as db:
                inventory = _inventory(j.runtime)
                for key in ("item.mat.wood", "item.ore.ironstone", "item.mat.array_sand"):
                    inventory.pop(key, None)
                db.execute("UPDATE players SET inventory_json=?", (json.dumps(inventory),))
            await prepare(j, "meal")
            await prepare(j, "meal")
            with j.runtime.repository._connect() as db:
                db.execute("UPDATE players SET realm_key='qi_gathering', realm_layer=3, stamina=100, energy=100, qualification_json=?", (json.dumps(BALANCED_QUALIFICATION),))
            for slug, name, _, _, _, hours, meal, _ in CAMPS:
                if slug == "ironwood":
                    await j.move("铁木林")
                elif slug == "basalt":
                    await j.move("近郊")
                    await j.move("玄武岩径")
                supply_before = _inventory(j.runtime)["item.food.spirit_rice"]
                assert (await j.send(f"开始挂机 {name} {meal}", "camp-" + slug)).ok
                assert _inventory(j.runtime).get("item.food.spirit_rice", 0) == supply_before - 1
                j.clock.advance(hours=hours)
                result = await j.send("领取挂机", "collect-" + slug)
                assert result.ok and not result.data["fallback"], result.message
                await j.render(result, "生产预览 巡山护甲")
            await j.move("近郊")
            await j.move("青石镇")
            inventory = _inventory(j.runtime)
            assert inventory["item.mat.wood"] >= 3 and inventory["item.ore.ironstone"] >= 3 and inventory["item.mat.array_sand"] >= 2
            assert (await j.send("开始生产 巡山护甲", "vest")).ok
            j.clock.advance(minutes=1)
            j.fail("vest-claim")
            before = _database_state(j.runtime)
            assert (await j.send("领取生产", "vest-claim")).code == "PERSISTENCE_ERROR"
            assert _database_state(j.runtime) == before
            j.repair()
            made = await j.send("领取生产", "vest-claim")
            assert made.ok and made.data["success"] and made.data["outputs"] == {"item.armor.patrol_vest": 1}, made.message
            assert _inventory(j.runtime)["item.mat.wood"] == inventory["item.mat.wood"] - 2
            assert _inventory(j.runtime)["item.ore.ironstone"] == inventory["item.ore.ironstone"] - 2
            assert _inventory(j.runtime)["item.mat.array_sand"] == inventory["item.mat.array_sand"] - 1
            assert (await j.send("卸下装备 巡山护甲", "unequip")).ok
            with j.runtime.repository._connect() as db:
                player = db.execute("SELECT * FROM players").fetchone()
                before_stats = j.runtime.repository._build_player_stat_snapshot(db, player)
            equipped = await j.send("穿戴装备 巡山护甲", "equip")
            assert equipped.ok, equipped.message
            with j.runtime.repository._connect() as db:
                player = db.execute("SELECT * FROM players").fetchone()
                after_stats = j.runtime.repository._build_player_stat_snapshot(db, player)
            vest = next(item for item in after_stats["equipment"] if item["item_key"] == "item.armor.patrol_vest")
            assert vest["effects"] == [{"type": "flat_stat", "stat": "max_hp", "value": 35}]
            assert vest["durability_bp"] == 8000 + made.data["quality_bp"] // 5
            assert after_stats["derived_stats"]["max_hp"] - before_stats["derived_stats"]["max_hp"] == 35 * vest["durability_bp"] // 10000
            assert (await j.send("接取委托 巡营备材", "delivery-accept")).ok
            inventory = _inventory(j.runtime)
            j.fail("delivery")
            before = _database_state(j.runtime)
            assert (await j.send("交付委托 巡营备材", "delivery")).code == "PERSISTENCE_ERROR"
            assert _database_state(j.runtime) == before
            j.repair()
            delivered = await j.send("交付委托 巡营备材", "delivery")
            assert delivered.ok, delivered.message
            for key in ("item.mat.wood", "item.ore.ironstone", "item.mat.array_sand"):
                assert _inventory(j.runtime).get(key, 0) == inventory[key] - 1
            assert (await j.send("交付委托 巡营备材", "delivery")).data["idempotent_replay"]
            await j.move("近郊")
            op = next(f"armored-{i}" for i in range(100) if battle_roll_bp(f"armored-{i}:battle") < 6500)
            assert (await j.send("开始探索 近郊巡路 追迹", op)).ok
            j.clock.advance(minutes=5)
            fought = await j.send("结算探索", "armored-fight")
            assert fought.ok and fought.data["battle_outcome"] in {"won", "lost"}, fought.message
            with j.runtime.repository._connect() as db:
                snapshot = json.loads(db.execute("SELECT snapshot_json FROM exploration_sessions WHERE operation_id=?", (op,)).fetchone()[0])
                assert "item.armor.patrol_vest" in json.dumps(snapshot["equipment"])
                assert snapshot["stat_snapshot"]["combat_stats"]["max_hp"] == after_stats["combat_stats"]["max_hp"]
                assert db.execute("SELECT COUNT(*) FROM battle_sessions WHERE battle_type='pve.exploration' AND status='settled'").fetchone()[0] == 1
        finally:
            await j.runtime.close()
    asyncio.run(run())


def test_camp_supply_gates_cancellation_evidence_and_expired_fallback(tmp_path):
    async def run():
        j = FieldJourney(_copy_content(tmp_path), "onebot.v11")
        try:
            await starter(j.runtime)
            raw_supplies(j)
            await prepare(j, "meal")
            for values in ({"realm_layer": 1}, {"realm_layer": 2, "location_key": "xuantian.new_town"},
                           {"location_key": "xuantian.outskirts", "energy": 0}, {"energy": 100, "stamina": 0}):
                with j.runtime.repository._connect() as db:
                    db.execute("UPDATE players SET " + ", ".join(f"{k}=?" for k in values), tuple(values.values()))
                before = _database_state(j.runtime)
                assert (await j.send("开始挂机 近郊篝火营 分饭搬材", "gate")).code == "IDLE_REQUIREMENT_MISSING"
                assert _database_state(j.runtime) == before
            with j.runtime.repository._connect() as db:
                db.execute("UPDATE players SET stamina=100")
            before = _database_state(j.runtime)
            omitted = await j.send("开始挂机 近郊篝火营", "omitted")
            assert omitted.code == "IDLE_REQUIREMENT_MISSING" and "选择补给方案" in omitted.message
            assert _database_state(j.runtime) == before
            results = await asyncio.gather(j.send("开始挂机 近郊篝火营 分饭搬材", "start"), j.send("开始挂机 近郊篝火营 分饭搬材", "start"))
            assert all(r.ok for r in results) and sum(r.data["idempotent_replay"] for r in results) == 1
            with j.runtime.repository._connect() as db:
                saved = db.execute("SELECT cost_json FROM idle_assignments").fetchone()[0]
                cost = json.loads(saved)
                cost["item.food.spirit_rice"] = 99
                db.execute("UPDATE idle_assignments SET cost_json=?", (json.dumps(cost),))
            before = _database_state(j.runtime)
            with pytest.raises(ValueError, match="supply evidence"):
                await j.send("取消挂机", "refund")
            assert _database_state(j.runtime) == before
            with j.runtime.repository._connect() as db:
                db.execute("UPDATE idle_assignments SET cost_json=?", (saved,))
                snapshot = json.loads(db.execute("SELECT snapshot_json FROM idle_assignments").fetchone()[0])
            for bad_cost, bad_snapshot in (
                (saved.replace('"stamina":', '"stamina": 99, "stamina":', 1), json.dumps(snapshot)),
                (saved, json.dumps({**snapshot, "cost": {**snapshot["cost"], "item.food.spirit_rice": True}})),
                (saved, json.dumps(snapshot).replace('"pool_key":', '"pool_key": null, "pool_key":', 1)),
            ):
                with j.runtime.repository._connect() as db:
                    db.execute("UPDATE idle_assignments SET cost_json=?, snapshot_json=?", (bad_cost, bad_snapshot))
                before = _database_state(j.runtime)
                with pytest.raises(ValueError, match="supply evidence|duplicate JSON"):
                    await j.send("取消挂机", "refund")
                assert _database_state(j.runtime) == before
            with j.runtime.repository._connect() as db:
                db.execute("UPDATE idle_assignments SET cost_json=?, snapshot_json=?", (saved, json.dumps(snapshot)))
            before_inventory = _inventory(j.runtime)
            j.clock.advance(hours=29)
            await j.restart()
            late = await j.send("领取挂机", "late")
            assert late.ok and late.data["fallback"] and late.data["reward"] == snapshot["fallback_reward"]
            assert _inventory(j.runtime).get("item.food.spirit_rice", 0) == before_inventory.get("item.food.spirit_rice", 0)
            assert not any(k.startswith("codex.") for k in late.data["reward"])
            before = _database_state(j.runtime)
            assert (await j.send("领取挂机", "late")).data["idempotent_replay"]
            assert _database_state(j.runtime) == before
        finally:
            await j.runtime.close()
    asyncio.run(run())
