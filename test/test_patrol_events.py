from __future__ import annotations

import asyncio
import json
from dataclasses import replace

import pytest

from combat_fixtures import BALANCED_QUALIFICATION
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentError, bundled_content
from nonebot_plugin_xiuxian_3.xiuxian.exploration.patrol_rules import freeze_patrol, patrol_definition
from nonebot_plugin_xiuxian_3.xiuxian.exploration.rules import battle_roll_bp, exploration_definition
from test_field_journeys import FieldJourney
from test_mainline_vertical_slice import _copy_content
from test_companion_old_trail_mainline import _database_state, _inventory
from test_wilderness_idle import change_content, starter


ROUTES = [
    ("outskirts", "近郊巡路", "xuantian.outskirts", "qi_sensing", 2),
    ("ironwood", "铁木巡林", "xuantian.ironwood_grove", "qi_sensing", 4),
    ("basalt", "岩径巡标", "xuantian.basalt_pass", "qi_gathering", 3),
]


@pytest.mark.parametrize("damage", ["shape", "scene", "weight", "duplicate", "pool", "consumer", "default", "cost", "risk", "enemy", "few"])
def test_patrol_content_rejects_invalid_events_and_consumers(damage):
    def mutate(records):
        p = records["exploration_mode", "explore.patrol_outskirts"]["patrol"]
        if damage == "shape": p["extra"] = 1
        elif damage == "scene": p["scene"] = "短"
        elif damage == "weight": p["events"][0]["weight"] = True
        elif damage == "duplicate": p["events"][1]["key"] = p["events"][0]["key"]
        elif damage == "pool": p["events"][0]["pools"].pop("pursuit")
        elif damage == "consumer": p["recipe_keys"] = ["recipe.array.gathering_basic"]
        elif damage == "default": p["approaches"][0]["duration_seconds"] += 1
        elif damage == "cost": p["approaches"][1]["stamina_cost"] = -1
        elif damage == "risk": p["approaches"][1]["battle_chance_bp"] = 10001
        elif damage == "enemy": records["exploration_mode", "explore.patrol_outskirts"].pop("enemy_pool_key")
        else: p["events"].pop()
    with pytest.raises(ContentError):
        exploration_definition("explore.patrol_outskirts", change_content(mutate))


def test_patrol_event_distribution_and_all_approach_consumers():
    content = bundled_content()
    for slug, *_ in ROUTES:
        row = content.require("exploration_mode", "explore.patrol_" + slug)
        p = patrol_definition(row, content)
        for approach in p["approaches"]:
            rolls = [freeze_patrol(row, content, approach["key"], f"event-{i}") for i in range(40)]
            assert {r["event"]["key"] for r in rolls} == {e["key"] for e in p["events"]}
            assert all(r["reward"] and r["uses"] for r in rolls)


@pytest.mark.parametrize("adapter", ["qq.official", "onebot.v11"])
@pytest.mark.parametrize("slug,name,location,realm,layer", ROUTES)
def test_patrol_public_events_frozen_rewards_recovery_and_rendering(tmp_path, adapter, slug, name, location, realm, layer):
    async def run():
        j = FieldJourney(_copy_content(tmp_path), adapter)
        try:
            await starter(j.runtime, adapter=adapter)
            with j.runtime.repository._connect() as db:
                db.execute("UPDATE players SET location_key=?, realm_key=?, realm_layer=?, stamina=100, energy=100", (location, realm, layer))
            before = _database_state(j.runtime)
            preview = await j.send("巡查预览 " + name, writable=False)
            assert preview.ok and len(preview.data["routes"]) == 1
            await j.render(preview, f"开始探索 {name} 稳行")
            assert _database_state(j.runtime) == before
            assert not (await j.send(f"开始探索 {name} 稳行", writable=False)).ok
            assert (await j.send(f"开始探索 {name} 乱走")).code == "INVALID_PATROL_APPROACH"
            assert _database_state(j.runtime) == before
            for approach in ("稳行", "追迹"):
                op = next(f"patrol-{approach}-{n}" for n in range(100) if battle_roll_bp(f"patrol-{approach}-{n}:battle") >= 6500)
                j.fail(op)
                before = _database_state(j.runtime)
                assert (await j.send(f"开始探索 {name} {approach}", op)).code == "PERSISTENCE_ERROR"
                assert _database_state(j.runtime) == before
                j.repair()
                result = await j.send(f"开始探索 {name} {approach}", op)
                assert result.ok, result.message
                p = result.data["patrol"]
                await j.render(result, "结算探索", keyboard=True)
                assert (await j.send(f"开始探索 {name} {approach}", op)).data["idempotent_replay"]
                assert (await j.send(f"开始探索 {name} " + ("追迹" if approach == "稳行" else "稳行"), op)).code == "OPERATION_CONFLICT"
                assert (await j.send("结算探索")).code == "EXPLORATION_NOT_READY"
                j.clock.advance(minutes=5)
                await j.restart()
                content = j.runtime.repository.content
                records = dict(content._records)
                records["exploration_mode", "explore.patrol_" + slug] = {**records["exploration_mode", "explore.patrol_" + slug], "status": "locked"}
                j.runtime.repository.content = replace(content, _records=records)
                assert (await j.send(f"开始探索 {name} {approach}", op)).data["idempotent_replay"]
                with j.runtime.repository._connect() as db:
                    saved = db.execute("SELECT snapshot_json FROM exploration_sessions WHERE operation_id=?", (op,)).fetchone()[0]
                    broken = json.loads(saved)
                    broken["patrol"]["reward"][next(iter(p["reward"]))] = True
                    db.execute("UPDATE exploration_sessions SET snapshot_json=? WHERE operation_id=?", (json.dumps(broken), op))
                before = _database_state(j.runtime)
                assert (await j.send("结算探索", "claim-" + op)).code == "PERSISTENCE_ERROR"
                assert _database_state(j.runtime) == before
                with j.runtime.repository._connect() as db:
                    broken = json.loads(saved)
                    broken.pop("patrol")
                    db.execute("UPDATE exploration_sessions SET snapshot_json=? WHERE operation_id=?", (json.dumps(broken), op))
                before = _database_state(j.runtime)
                assert (await j.send("结算探索", "claim-" + op)).code == "PERSISTENCE_ERROR"
                assert _database_state(j.runtime) == before
                with j.runtime.repository._connect() as db:
                    db.execute("UPDATE exploration_sessions SET snapshot_json=? WHERE operation_id=?", (saved, op))
                j.fail("claim-" + op)
                before = _database_state(j.runtime)
                assert (await j.send("结算探索", "claim-" + op)).code == "PERSISTENCE_ERROR"
                assert _database_state(j.runtime) == before
                j.repair()
                inventory = _inventory(j.runtime)
                claimed = await j.send("结算探索", "claim-" + op)
                assert claimed.ok and claimed.data["result"] == p["reward"], claimed.message
                assert all(_inventory(j.runtime).get(k, 0) - inventory.get(k, 0) == n for k, n in p["reward"].items())
                assert p["event"]["complete_text"] in claimed.message
                await j.render(claimed, p["uses"][0]["command"])
                before = _database_state(j.runtime)
                assert (await j.send("结算探索", "claim-" + op)).data["idempotent_replay"]
                assert _database_state(j.runtime) == before
                j.runtime.repository.content = content
            cancelled = await j.send(f"开始探索 {name} 追迹", "cancel-start")
            assert cancelled.ok
            cancel = await j.send("取消探索", "cancel")
            assert cancel.ok and cancel.data["stamina_refund"] == cancelled.data["stamina_cost"]
            assert (await j.send("开始探索 " + name, "late")).ok
            j.clock.advance(hours=25)
            expired = await j.send("结算探索", "expired")
            assert expired.code == "EXPLORATION_EXPIRED" and "本次无奖励" in expired.message
        finally:
            await j.runtime.close()
    asyncio.run(run())


@pytest.mark.parametrize("win", [True, False])
def test_patrol_real_battle_and_retry_after_reward_rollback(tmp_path, win):
    async def run():
        j = FieldJourney(_copy_content(tmp_path), "onebot.v11")
        try:
            await starter(j.runtime)
            if not win:
                content = j.runtime.repository.content
                records = dict(content._records)
                for candidate in content.require("encounter_pool", "encounter.xuantian.outskirts")["candidates"]:
                    key = ("enemy", candidate["enemy_key"])
                    records[key] = {**records[key], "stats": {"hp": 10000, "attack": 10000, "initiative": 100, "agility": 100}}
                j.runtime.repository.content = replace(content, _records=records)
            with j.runtime.repository._connect() as db:
                db.execute("UPDATE players SET realm_layer=2, stamina=100, max_hp=?, initiative=?, qualification_json=?", (999 if win else 0, 99 if win else 0, json.dumps(BALANCED_QUALIFICATION)))
            op = next(f"battle-{n}" for n in range(100) if battle_roll_bp(f"battle-{n}:battle") < 6500)
            start = await j.send("开始探索 近郊巡路 追迹", op)
            assert start.ok, start.message
            j.clock.advance(minutes=5)
            j.fail("battle-claim:combat")
            inventory = _inventory(j.runtime)
            assert (await j.send("结算探索", "battle-claim")).code == "PERSISTENCE_ERROR"
            assert _inventory(j.runtime) == inventory
            j.repair()
            await j.restart()
            claim = await j.send("结算探索", "battle-claim")
            assert claim.ok, claim.message
            assert (claim.data["battle_outcome"] == "won") == win
            assert claim.data["result"] == (start.data["patrol"]["reward"] if win else {})
            assert start.data["patrol"]["event"]["complete_text" if win else "defeat_text"] in claim.message
            before = _database_state(j.runtime)
            assert (await j.send("结算探索", "battle-claim")).data["idempotent_replay"]
            assert _database_state(j.runtime) == before
        finally:
            await j.runtime.close()
    asyncio.run(run())


def test_patrol_boundaries_quota_and_concurrent_start(tmp_path):
    async def run():
        j = FieldJourney(_copy_content(tmp_path), "onebot.v11")
        try:
            await starter(j.runtime)
            for values, expected in [
                ({"realm_layer": 1}, "EXPLORATION_LOCATION_FORBIDDEN"),
                ({"realm_layer": 2, "location_key": "xuantian.new_town"}, "EXPLORATION_LOCATION_FORBIDDEN"),
                ({"location_key": "xuantian.outskirts", "stamina": 0}, "RESOURCE_INSUFFICIENT"),
                ({"stamina": 30, "energy": 0}, "ENERGY_INSUFFICIENT"),
            ]:
                with j.runtime.repository._connect() as db:
                    db.execute("UPDATE players SET " + ", ".join(f"{k}=?" for k in values), tuple(values.values()))
                before = _database_state(j.runtime)
                assert (await j.send("开始探索 近郊巡路", "boundary")).code == expected
                assert _database_state(j.runtime) == before
            with j.runtime.repository._connect() as db:
                db.execute("UPDATE players SET energy=30")
            results = await asyncio.gather(j.send("开始探索 近郊巡路", "once"), j.send("开始探索 近郊巡路", "once"))
            assert all(r.ok for r in results) and sum(r.data["idempotent_replay"] for r in results) == 1
            before = _database_state(j.runtime)
            assert (await j.send("开始探索 近郊巡路", "once", user="foreign")).code == "OPERATION_CONFLICT"
            assert _database_state(j.runtime) == before
            assert (await j.send("取消探索", "undo")).ok
            for i in range(3):
                assert (await j.send("开始探索 近郊巡路", f"quota-{i}")).ok
                assert (await j.send("取消探索", f"undo-{i}")).ok
            before = _database_state(j.runtime)
            assert (await j.send("开始探索 近郊巡路", "over")).code == "EXPLORATION_QUOTA_EXHAUSTED"
            assert _database_state(j.runtime) == before
            await j.next_day()
            assert (await j.send("开始探索 近郊巡路", "tomorrow")).ok
        finally:
            await j.runtime.close()
    asyncio.run(run())
