from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import replace

import pytest

from nonebot_plugin_xiuxian_3.xiuxian.content import ContentError
from nonebot_plugin_xiuxian_3.xiuxian.exploration.survey_rules import survey_definitions
from test_companion_old_trail_mainline import _database_state, _inventory
from test_field_journeys import FieldJourney
from test_mainline_vertical_slice import _copy_content
from test_wilderness_idle import change_content, starter


SITES = ["survey.creek_cliff", "survey.iron_roots", "survey.basalt_channel"]


@pytest.mark.parametrize("damage", ["extra", "body", "cost", "chance", "reliable", "duplicate", "consumer",
                                    "cycle", "location", "recipe", "layer", "item"])
def test_survey_strict_content_references_choices_and_consumers(damage):
    def mutate(records):
        site = records["survey", SITES[0]]
        choice = site["nodes"][0]["choices"][0]
        if damage == "extra": site["client_complete"] = True
        elif damage == "body": site["nodes"][0]["body"] = "短"
        elif damage == "cost": choice["costs"]["energy"] = True
        elif damage == "chance": choice["success_bp"] = 10001
        elif damage == "reliable": choice["success_bp"] = 9999
        elif damage == "duplicate": site["nodes"][1]["choices"][0]["key"] = choice["key"]
        elif damage == "consumer": site["recipe_keys"] = ["recipe.array.gathering_basic"]
        elif damage == "cycle": site["prerequisite"] = SITES[2]
        elif damage == "location": site["location_key"] = "missing"
        elif damage == "recipe": site["recipe_keys"] = ["missing"]
        elif damage == "layer": site["required_layer"] = True
        else: choice["costs"]["item.missing"] = 1
    with pytest.raises(ContentError):
        survey_definitions(change_content(mutate))


def configure(j, **values):
    with j.runtime.repository._connect() as db:
        db.execute("UPDATE players SET " + ", ".join(f"{k}=?" for k in values), tuple(values.values()))


async def complete_site(j, key, prefix):
    started = await j.send("勘察地貌 " + key, prefix + "-start")
    assert started.ok, started.message
    for index, node in enumerate(started.data["site"]["nodes"]):
        result = await j.send(f"勘察抉择 {key} {node['choices'][0]['key']}", f"{prefix}-{index}")
        assert result.ok and result.data["success"] and result.data["state"]["step"] == index + 1, result.message
        j.clock.advance(seconds=60)
    return result


@pytest.mark.parametrize("adapter", ["onebot.v11", "qq.official"])
def test_survey_public_discoveries_travel_production_restart_and_rendering(tmp_path, adapter):
    async def run():
        j = FieldJourney(_copy_content(tmp_path), adapter)
        try:
            await starter(j.runtime, adapter=adapter)
            before = _database_state(j.runtime)
            preview = await j.send("山野手札 溪崖石层", writable=False)
            assert preview.ok and len(preview.data["entries"]) == 1
            await j.render(preview, "勘察地貌 survey.creek_cliff")
            assert _database_state(j.runtime) == before
            assert not (await j.send("勘察地貌 溪崖石层", writable=False)).ok
            assert (await j.send("勘察地貌 溪崖石层", "start")).code == "SURVEY_REQUIREMENT_MISSING"
            configure(j, realm_key="qi_gathering", realm_layer=3, stamina=100, energy=100, spirit_stones=1000)
            with j.runtime.repository._connect() as db:
                inventory = _inventory(j.runtime)
                for k in ("item.mat.wood", "item.ore.ironstone", "item.mat.array_sand"):
                    inventory.pop(k, None)
                db.execute("UPDATE players SET inventory_json=?", (json.dumps(inventory),))
            j.fail("start")
            before = _database_state(j.runtime)
            assert (await j.send("勘察地貌 溪崖石层", "start")).code == "PERSISTENCE_ERROR"
            assert _database_state(j.runtime) == before
            j.repair()
            started = await j.send("勘察地貌 溪崖石层", "start")
            assert started.ok
            assert (await j.send("勘察地貌 溪崖石层", "start")).data["idempotent_replay"]
            assert (await j.send("勘察地貌 铁木根脉", "start")).code == "OPERATION_CONFLICT"
            await j.render(started, "勘察抉择 survey.creek_cliff measure_water")
            assert (await j.send("勘察抉择 溪崖石层 无此做法")).code == "SURVEY_REQUIREMENT_MISSING"
            j.fail("first")
            before = _database_state(j.runtime)
            assert (await j.send("勘察抉择 溪崖石层 量痕探水", "first")).code == "PERSISTENCE_ERROR"
            assert _database_state(j.runtime) == before
            j.repair()
            first = await j.send("勘察抉择 溪崖石层 量痕探水", "first")
            assert first.ok and first.data["costs"] == {"stamina": 3, "energy": 2}
            assert (await j.send("勘察抉择 溪崖石层 量痕探水", "first")).data["idempotent_replay"]
            assert (await j.send("勘察抉择 溪崖石层 循根辨土", "first")).code == "OPERATION_CONFLICT"
            before = _database_state(j.runtime)
            assert (await j.send("勘察抉择 溪崖石层 循根辨土")).code == "SURVEY_REQUIREMENT_MISSING"
            assert _database_state(j.runtime) == before
            rested = await j.send("暂离勘察 溪崖石层", "rest")
            assert rested.ok and rested.data["state"]["step"] == 1
            await j.render(rested, "勘察地貌 survey.creek_cliff", keyboard=True)
            await j.move("青石镇")
            assert (await j.send("勘察地貌 溪崖石层")).code == "SURVEY_REQUIREMENT_MISSING"
            await j.restart()
            await j.move("近郊")
            assert (await j.send("勘察地貌 溪崖石层", "resume")).ok
            assert (await j.send("勘察抉择 溪崖石层 循根辨土", "second")).ok
            j.clock.advance(minutes=1)
            j.fail("finish")
            before = _database_state(j.runtime)
            assert (await j.send("勘察抉择 溪崖石层 牵线定标", "finish")).code == "PERSISTENCE_ERROR"
            assert _database_state(j.runtime) == before
            j.repair()
            inventory = _inventory(j.runtime)
            done = await j.send("勘察抉择 溪崖石层 牵线定标", "finish")
            assert done.ok and done.data["state"]["status"] == "completed"
            assert _inventory(j.runtime)["item.mat.wood"] == inventory.get("item.mat.wood", 0) + 2
            await j.render(done, done.actions[0].command, keyboard=True)
            before = _database_state(j.runtime)
            assert (await j.send("勘察抉择 溪崖石层 牵线定标", "finish")).data["idempotent_replay"]
            assert (await j.send("勘察地貌 溪崖石层")).code == "SURVEY_REQUIREMENT_MISSING"
            assert _database_state(j.runtime) == before
            await j.move("铁木林")
            assert (await complete_site(j, SITES[1], "iron")).data["reward"]["item.ore.ironstone"] == 2
            await j.move("近郊")
            await j.move("玄武岩径")
            assert (await complete_site(j, SITES[2], "sand")).data["reward"]["item.mat.array_sand"] == 3
            journal = await j.send("山野手札", writable=False)
            assert all(e["state"]["status"] == "completed" for e in journal.data["entries"])
            await j.move("近郊")
            await j.move("青石镇")
            inventory = _inventory(j.runtime)
            assert (await j.send("开始生产 巡山护甲", "vest")).ok
            j.clock.advance(minutes=1)
            made = await j.send("领取生产", "vest-claim")
            assert made.ok and made.data["success"], made.message
            for key, amount in {"item.mat.wood": 2, "item.ore.ironstone": 2, "item.mat.array_sand": 1}.items():
                assert _inventory(j.runtime).get(key, 0) == inventory[key] - amount
            with j.runtime.repository._connect() as db:
                p = db.execute("SELECT * FROM players").fetchone()
                stats = j.runtime.repository._build_player_stat_snapshot(db, p)
                assert any(e["item_key"] == "item.armor.patrol_vest" for e in stats["equipment"])
        finally:
            await j.runtime.close()
    asyncio.run(run())


def test_survey_failure_gates_concurrency_and_corrupt_evidence(tmp_path):
    async def run():
        j = FieldJourney(_copy_content(tmp_path), "onebot.v11")
        try:
            await starter(j.runtime)
            configure(j, realm_key="qi_gathering", realm_layer=3, stamina=100, energy=100,
                      location_key="xuantian.ironwood_grove")
            before = _database_state(j.runtime)
            assert (await j.send("勘察地貌 铁木根脉")).code == "SURVEY_REQUIREMENT_MISSING"
            assert _database_state(j.runtime) == before
            configure(j, location_key="xuantian.outskirts")
            started = await j.send("勘察地貌 溪崖石层", "start")
            assert started.ok
            configure(j, stamina=0)
            before = _database_state(j.runtime)
            assert (await j.send("勘察抉择 溪崖石层 量痕探水")).code == "SURVEY_REQUIREMENT_MISSING"
            assert _database_state(j.runtime) == before
            configure(j, stamina=100)
            with j.runtime.repository._connect() as db:
                saved = db.execute("SELECT snapshot_json FROM field_surveys").fetchone()[0]
                frozen = json.loads(saved)
                seed = next(str(i) for i in range(100) if int.from_bytes(hashlib.sha256(f"{i}:0".encode()).digest()[:8], "big") % 10000 >= 5500)
                frozen["seed"] = seed
                initial = json.loads(db.execute("SELECT result_json FROM operations WHERE operation_id='start'").fetchone()[0])
                initial["snapshot"] = frozen
                db.execute("UPDATE field_surveys SET snapshot_json=?", (json.dumps(frozen),))
                db.execute("UPDATE operations SET result_json=? WHERE operation_id='start'", (json.dumps(initial),))
            failed = await j.send("勘察抉择 溪崖石层 跃石试路", "risk")
            assert failed.ok and failed.data["success"] is False and failed.data["state"]["step"] == 0
            assert failed.data["costs"] == {"stamina": 2}
            before = _database_state(j.runtime)
            assert (await j.send("勘察抉择 溪崖石层 跃石试路", "risk")).data["idempotent_replay"]
            assert _database_state(j.runtime) == before
            j.clock.advance(seconds=15)
            results = await asyncio.gather(*(j.send("勘察抉择 溪崖石层 量痕探水", op) for op in ("race-a", "race-b")))
            assert sum(r.ok for r in results) == 1
            with j.runtime.repository._connect() as db:
                assert db.execute("SELECT step, attempts FROM field_surveys").fetchone()[:] == (1, 2)
            await j.restart()
            for damage in ("snapshot", "progress", "receipt", "missing"):
                with j.runtime.repository._connect() as db:
                    saved_row = dict(db.execute("SELECT * FROM field_surveys").fetchone())
                    last = db.execute("SELECT result_json FROM operations WHERE operation_id=?", (saved_row["last_operation_id"],)).fetchone()[0]
                    if damage == "snapshot":
                        value = json.loads(saved_row["snapshot_json"])
                        value["site"]["rewards"]["item.mat.wood"] = True
                        db.execute("UPDATE field_surveys SET snapshot_json=?", (json.dumps(value),))
                    elif damage == "progress": db.execute("UPDATE field_surveys SET step=2")
                    elif damage == "receipt":
                        db.execute("UPDATE operations SET result_json='[]' WHERE operation_id=?", (saved_row["last_operation_id"],))
                    else:
                        db.execute("PRAGMA foreign_keys=OFF")
                        db.execute("UPDATE field_surveys SET last_operation_id='missing'")
                        db.execute("PRAGMA foreign_keys=ON")
                before = _database_state(j.runtime)
                assert (await j.send("山野手札")).code == "PERSISTENCE_ERROR"
                assert (await j.send("暂离勘察 溪崖石层")).code == "PERSISTENCE_ERROR"
                assert _database_state(j.runtime) == before
                with j.runtime.repository._connect() as db:
                    db.execute("UPDATE field_surveys SET snapshot_json=?, step=?, last_operation_id=?",
                               (saved_row["snapshot_json"], saved_row["step"], saved_row["last_operation_id"]))
                    db.execute("UPDATE operations SET result_json=? WHERE operation_id=?", (last, saved_row["last_operation_id"]))
            j.clock.advance(minutes=1)
            content = j.runtime.repository.content
            records = dict(content._records)
            for key in SITES:
                records["survey", key] = {**records["survey", key], "status": "locked"}
            j.runtime.repository.content = replace(content, _records=records)
            assert (await j.send("山野手札")).ok
            assert (await j.send("勘察地貌 溪崖石层", "start")).data["idempotent_replay"]
            assert (await j.send("勘察抉择 溪崖石层 循根辨土", "closed-2")).ok
            j.clock.advance(minutes=1)
            inventory = _inventory(j.runtime)
            results = await asyncio.gather(*(j.send("勘察抉择 溪崖石层 牵线定标", op) for op in ("closed-3", "closed-race")))
            assert sum(r.ok for r in results) == 1
            assert next(r for r in results if r.ok).data["state"]["status"] == "completed"
            assert _inventory(j.runtime)["item.mat.wood"] == inventory.get("item.mat.wood", 0) + 2
            configure(j, location_key="xuantian.ironwood_grove")
            assert (await j.send("勘察地貌 铁木根脉")).code == "SURVEY_REQUIREMENT_MISSING"
            await starter(j.runtime, user="other")
            before = _database_state(j.runtime)
            assert (await j.send("勘察地貌 溪崖石层", "start", user="other")).code == "OPERATION_CONFLICT"
            assert _database_state(j.runtime) == before
        finally:
            await j.runtime.close()
    asyncio.run(run())
