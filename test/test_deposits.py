from __future__ import annotations

import asyncio
import json
from dataclasses import replace

import pytest

from nonebot_plugin_xiuxian_3.xiuxian.content import ContentError
from nonebot_plugin_xiuxian_3.xiuxian.exploration.deposit_rules import deposit_definitions
from test_companion_old_trail_mainline import _database_state, _inventory
from test_field_journeys import FieldJourney
from test_mainline_vertical_slice import _copy_content
from test_surveys import SITES, complete_site, configure
from test_wilderness_idle import change_content, starter


DEPOSITS = ["deposit.creek_roots", "deposit.ironwood_layer", "deposit.basalt_sand"]


@pytest.mark.parametrize("damage", ["extra", "capacity", "regen", "stock", "delay", "cost", "duplicate",
                                    "survey", "consumer", "upkeep", "source", "renewable"])
def test_deposit_strict_sources_consumers_and_stock_rules(damage):
    def mutate(records):
        value = records["deposit", DEPOSITS[0]]
        plan = value["plans"][0]
        if damage == "extra": value["refresh_on_preview"] = True
        elif damage == "capacity": value["capacity"] = True
        elif damage == "regen": value["regen_units"] = 7
        elif damage == "stock": plan["stock_cost"] = 7
        elif damage == "delay": plan["recovery_delay"] = -1
        elif damage == "cost": plan["costs"]["energy"] = True
        elif damage == "duplicate": value["plans"][1]["name"] = plan["name"]
        elif damage == "survey": value["survey_key"] = "survey.missing"
        elif damage == "consumer": value["recipe_keys"] = ["recipe.array.gathering_basic"]
        elif damage == "upkeep": value["maintenance"]["restore_units"] = 7
        elif damage == "source": value["maintenance"]["recipe_key"] = "recipe.armor.patrol_vest"
        else:
            for p in value["plans"]:
                p["rewards"].pop("item.herb.blood_grass")
    with pytest.raises(ContentError):
        deposit_definitions(change_content(mutate))


@pytest.mark.parametrize("adapter", ["onebot.v11", "qq.official"])
def test_deposit_public_survey_harvest_supply_production_upkeep_and_restart(tmp_path, adapter):
    async def run():
        j = FieldJourney(_copy_content(tmp_path), adapter)
        try:
            await starter(j.runtime, adapter=adapter)
            configure(j, realm_key="qi_gathering", realm_layer=3, stamina=100, energy=100, spirit_stones=1000)
            before = _database_state(j.runtime)
            preview = await j.send("资源脉预览 溪崖药根", writable=False)
            assert preview.ok and not preview.data["entries"][0]["unlocked"]
            await j.render(preview, "山野手札 survey.creek_cliff")
            assert (await j.send("取用资源脉 溪崖药根 留根采叶")).code == "DEPOSIT_REQUIREMENT_MISSING"
            assert _database_state(j.runtime) == before
            for index, (survey, deposit) in enumerate(zip(SITES, DEPOSITS)):
                if index == 1:
                    await j.move("铁木林")
                elif index == 2:
                    await j.move("近郊")
                    await j.move("玄武岩径")
                await complete_site(j, survey, "survey-" + str(index))
                before = _database_state(j.runtime)
                preview = await j.send("资源脉预览 " + deposit, writable=False)
                assert preview.ok and preview.data["entries"][0]["unlocked"]
                await j.render(preview, f"取用资源脉 {deposit} gentle")
                assert _database_state(j.runtime) == before
                assert not (await j.send(f"取用资源脉 {deposit} gentle", writable=False)).ok
                j.fail("harvest-" + str(index))
                before = _database_state(j.runtime)
                assert (await j.send(f"取用资源脉 {deposit} gentle", "harvest-" + str(index))).code == "PERSISTENCE_ERROR"
                assert _database_state(j.runtime) == before
                j.repair()
                inventory = _inventory(j.runtime)
                harvested = await j.send(f"取用资源脉 {deposit} gentle", "harvest-" + str(index))
                assert harvested.ok and harvested.data["state"]["stock"] == 5, harvested.message
                for key, quantity in harvested.data["reward"].items():
                    assert _inventory(j.runtime).get(key, 0) == inventory.get(key, 0) + quantity
                await j.render(harvested, "资源脉预览 " + deposit, keyboard=True)
                before = _database_state(j.runtime)
                assert (await j.send(f"取用资源脉 {deposit} gentle", "harvest-" + str(index))).data["idempotent_replay"]
                assert (await j.send(f"取用资源脉 {deposit} intensive", "harvest-" + str(index))).code == "OPERATION_CONFLICT"
                assert (await j.send(f"取用资源脉 {deposit} gentle")).code == "DEPOSIT_REQUIREMENT_MISSING"
                assert _database_state(j.runtime) == before
            await j.move("近郊")
            await j.move("青石镇")
            inventory = _inventory(j.runtime)
            assert (await j.send("开始生产 护脉木楔", "wedge")).ok
            j.clock.advance(seconds=30)
            made = await j.send("领取生产", "wedge-claim")
            assert made.ok and made.data["success"] and made.data["outputs"] == {"item.mat.root_wedge": 2}, made.message
            for k in ("item.mat.wood", "item.herb.blood_grass"):
                assert _inventory(j.runtime).get(k, 0) == inventory[k] - 1
            await j.move("近郊")
            j.fail("upkeep")
            before = _database_state(j.runtime)
            assert (await j.send("养护资源脉 溪崖药根", "upkeep")).code == "PERSISTENCE_ERROR"
            assert _database_state(j.runtime) == before
            j.repair()
            maintained = await j.send("养护资源脉 溪崖药根", "upkeep")
            assert maintained.ok and maintained.data["state"]["stock"] == 6
            assert maintained.data["state"]["maintenance_used"] == 1
            assert _inventory(j.runtime)["item.mat.root_wedge"] == 1
            assert (await j.send("养护资源脉 溪崖药根", "upkeep")).data["idempotent_replay"]
            await j.restart()
            before = _database_state(j.runtime)
            preview = await j.send("资源脉预览 溪崖药根", writable=False)
            assert preview.data["entries"][0]["state"]["stock"] == 6
            assert preview.data["entries"][0]["state"]["maintenance_used"] == 1
            j.clock.advance(days=3)
            preview = await j.send("资源脉预览 溪崖药根", writable=False)
            assert preview.data["entries"][0]["state"]["stock"] == 6
            assert preview.data["entries"][0]["state"]["maintenance_used"] == 0
            assert _database_state(j.runtime) == before
        finally:
            await j.runtime.close()
    asyncio.run(run())


def test_deposit_depletion_elapsed_regeneration_quota_evidence_and_closure(tmp_path):
    async def run():
        j = FieldJourney(_copy_content(tmp_path), "onebot.v11")
        try:
            await starter(j.runtime)
            configure(j, realm_key="qi_gathering", realm_layer=3, stamina=100, energy=100, spirit_stones=1000)
            await complete_site(j, SITES[0], "survey")
            configure(j, energy=0)
            before = _database_state(j.runtime)
            assert (await j.send("取用资源脉 溪崖药根 留根采叶")).code == "DEPOSIT_REQUIREMENT_MISSING"
            assert (await j.send("取用资源脉 溪崖药根 随意")).code == "DEPOSIT_REQUIREMENT_MISSING"
            assert _database_state(j.runtime) == before
            configure(j, energy=100)
            results = await asyncio.gather(*(j.send("取用资源脉 溪崖药根 急取药丛", op) for op in ("race-a", "race-b")))
            assert sum(r.ok for r in results) == 1
            assert next(r for r in results if r.ok).data["state"]["stock"] == 3
            j.clock.advance(minutes=30)
            depleted = await j.send("取用资源脉 溪崖药根 急取药丛", "deplete")
            assert depleted.ok and depleted.data["state"]["stock"] == 0
            j.clock.advance(minutes=30)
            before = _database_state(j.runtime)
            assert (await j.send("取用资源脉 溪崖药根 留根采叶")).code == "DEPOSIT_REQUIREMENT_MISSING"
            assert (await j.send("养护资源脉 溪崖药根")).code == "DEPOSIT_REQUIREMENT_MISSING"
            assert _database_state(j.runtime) == before
            await j.restart()
            j.clock.advance(hours=2, minutes=30)
            before = _database_state(j.runtime)
            preview = await j.send("资源脉预览 溪崖药根", writable=False)
            assert preview.data["entries"][0]["state"]["stock"] == 1
            assert _database_state(j.runtime) == before
            assert (await j.send("取用资源脉 溪崖药根 留根采叶", "after-regen")).data["state"]["stock"] == 0
            await j.move("青石镇")
            assert (await j.send("开始生产 护脉木楔", "wedge-1")).ok
            j.clock.advance(seconds=30)
            assert (await j.send("领取生产", "claim-wedge-1")).ok
            assert (await j.send("开始生产 护脉木楔", "wedge-2")).ok
            j.clock.advance(seconds=30)
            assert (await j.send("领取生产", "claim-wedge-2")).ok
            await j.move("近郊")
            j.clock.advance(minutes=5)
            for i in range(2):
                assert (await j.send("养护资源脉 溪崖药根", f"upkeep-{i}")).ok
                j.clock.advance(minutes=15)
            before = _database_state(j.runtime)
            assert (await j.send("养护资源脉 溪崖药根")).code == "DEPOSIT_REQUIREMENT_MISSING"
            assert _database_state(j.runtime) == before
            for damage in ("snapshot", "state", "receipt", "reward", "missing"):
                with j.runtime.repository._connect() as db:
                    row = dict(db.execute("SELECT * FROM field_deposits").fetchone())
                    receipt = db.execute("SELECT result_json FROM operations WHERE operation_id=?", (row["last_operation_id"],)).fetchone()[0]
                    if damage == "snapshot":
                        frozen = json.loads(row["snapshot_json"])
                        frozen["definition"]["capacity"] = 100
                        db.execute("UPDATE field_deposits SET snapshot_json=?", (json.dumps(frozen),))
                    elif damage == "state": db.execute("UPDATE field_deposits SET stock=6")
                    elif damage in {"receipt", "reward"}:
                        payload = json.loads(receipt)
                        if damage == "receipt": payload["costs"]["item.mat.root_wedge"] = True
                        else: payload["reward"] = {"item.mat.wood": 99}
                        db.execute("UPDATE operations SET result_json=? WHERE operation_id=?", (json.dumps(payload), row["last_operation_id"]))
                    else:
                        db.execute("PRAGMA foreign_keys=OFF")
                        db.execute("UPDATE field_deposits SET last_operation_id='missing'")
                        db.execute("PRAGMA foreign_keys=ON")
                before = _database_state(j.runtime)
                assert (await j.send("资源脉预览")).code == "PERSISTENCE_ERROR"
                assert (await j.send("取用资源脉 溪崖药根 留根采叶")).code == "PERSISTENCE_ERROR"
                assert _database_state(j.runtime) == before
                with j.runtime.repository._connect() as db:
                    db.execute("UPDATE field_deposits SET snapshot_json=?, stock=?, last_operation_id=?",
                               (row["snapshot_json"], row["stock"], row["last_operation_id"]))
                    db.execute("UPDATE operations SET result_json=? WHERE operation_id=?", (receipt, row["last_operation_id"]))
            content = j.runtime.repository.content
            records = dict(content._records)
            for key in DEPOSITS:
                records["deposit", key] = {**records["deposit", key], "status": "locked"}
            j.runtime.repository.content = replace(content, _records=records)
            before = _database_state(j.runtime)
            assert (await j.send("取用资源脉 溪崖药根 急取药丛", "deplete")).data["idempotent_replay"]
            assert (await j.send("取用资源脉 溪崖药根 留根采叶")).code == "DEPOSIT_REQUIREMENT_MISSING"
            assert (await j.send("资源脉预览 溪崖药根")).ok
            assert _database_state(j.runtime) == before
            await starter(j.runtime, user="other")
            before = _database_state(j.runtime)
            assert (await j.send("取用资源脉 溪崖药根 急取药丛", "deplete", user="other")).code == "OPERATION_CONFLICT"
            assert _database_state(j.runtime) == before
        finally:
            await j.runtime.close()
    asyncio.run(run())
