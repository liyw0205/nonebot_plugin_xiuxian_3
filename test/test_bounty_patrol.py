from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from datetime import timedelta

import pytest

from nonebot_plugin_xiuxian_3.xiuxian.adventures.rules import (
    bounty_definitions, bounty_refresh_seed, refresh_bounty_candidates, reward_map,
)
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentError, bundled_content
from nonebot_plugin_xiuxian_3.xiuxian.exploration.rules import battle_roll_bp
from test_companion_old_trail_mainline import _database_state, _inventory
from test_field_journeys import FieldJourney
from test_mainline_vertical_slice import _copy_content
from test_patrol_events import ROUTES
from test_wilderness_idle import change_content, starter
from combat_fixtures import BALANCED_QUALIFICATION


def available_day(j, key):
    repo = j.runtime.repository
    with repo._connect() as db:
        row = db.execute("SELECT * FROM players WHERE platform_user_id='gatherer'").fetchone()
        candidates = [d for d in bounty_definitions(repo.content) if d.runtime_status == "open"
                      and repo._bounty_player_eligible(db, row, d, j.clock(), {})]
    for day in range(60):
        now = j.clock() + timedelta(days=day)
        keys = {d.key for d in refresh_bounty_candidates(candidates, seed=bounty_refresh_seed(row["id"], now.date().isoformat()))[:3]}
        if key in keys:
            j.clock.value = now
            return
    raise AssertionError("patrol contract never appears on eligible daily board")


@pytest.mark.parametrize("damage", ["missing", "closed", "realm", "quota", "duration", "amount", "access"])
def test_patrol_bounty_requires_reachable_new_explorations(damage):
    def mutate(records):
        bounty = records["bounty", "bounty.patrol.outskirts"]
        if damage == "missing": bounty["target_key"] = "explore.missing"
        elif damage == "closed": records["exploration_mode", bounty["target_key"]]["status"] = "locked"
        elif damage == "realm": bounty["required_layer"] = 1
        elif damage == "quota": bounty["target_amount"] = 5
        elif damage == "duration": bounty["duration_seconds"] = 90
        elif damage == "amount": bounty["target_amount"] = True
        else: bounty["access_any"] = [{"type": "intro_flag", "value": "skip"}]
    with pytest.raises(ContentError):
        bounty_definitions(change_content(mutate))


def test_patrol_contracts_have_multiple_tiers_and_real_random_rewards():
    content = bundled_content()
    definitions = [d for d in bounty_definitions(content) if d.target_kind == "exploration_completions"]
    assert len(definitions) == 6
    assert {d.target_amount for d in definitions} == {1, 2}
    for definition in definitions:
        rewards = [reward_map(definition, content, seed=f"patrol-reward-{i}", realm_key=definition.required_realm, realm_layer=definition.required_layer) for i in range(30)]
        assert len({json.dumps(r, sort_keys=True) for r in rewards}) == 2
        assert all(r.get("spirit_stones", 0) > 0 and any(k.startswith("item.") for k in r) for r in rewards)


@pytest.mark.parametrize("adapter", ["qq.official", "onebot.v11"])
@pytest.mark.parametrize("slug,name,location,realm,layer", ROUTES)
def test_patrol_bounty_public_loop_frozen_claim_and_owned_new_evidence(tmp_path, adapter, slug, name, location, realm, layer):
    async def run():
        j = FieldJourney(_copy_content(tmp_path), adapter)
        try:
            await starter(j.runtime, adapter=adapter)
            with j.runtime.repository._connect() as db:
                db.execute("UPDATE players SET location_key=?, realm_key=?, realm_layer=?, stamina=100, energy=100", (location, realm, layer))
            key = "bounty.patrol." + slug + "_pair"
            available_day(j, key)
            before = _database_state(j.runtime)
            board = await j.send("悬赏榜", writable=False)
            assert board.ok, board.message
            offer = next(o for o in board.data["offers"] if o["bounty_key"] == key)
            assert offer["status"] == "available" and len(offer["next_actions"]) == 2
            await j.render(board, "接取悬赏 " + offer["label"])
            assert _database_state(j.runtime) == before
            op = next(f"old-{i}" for i in range(100) if battle_roll_bp(f"old-{i}:battle") >= 6500)
            assert (await j.send("开始探索 " + name, op)).ok
            assert not (await j.send("接取悬赏 " + offer["label"], writable=False)).ok
            j.fail("accept")
            before = _database_state(j.runtime)
            assert (await j.send("接取悬赏 " + offer["label"], "accept")).code == "PERSISTENCE_ERROR"
            assert _database_state(j.runtime) == before
            j.repair()
            accepted = await j.send("接取悬赏 " + offer["label"], "accept")
            assert accepted.ok, accepted.message
            await j.render(accepted, "巡查预览 " + name)
            assert (await j.send("接取悬赏 " + offer["label"], "accept")).data["idempotent_replay"]
            assert (await j.send("接取悬赏 镇外路况札", "accept", user="foreign")).code == "OPERATION_CONFLICT"
            j.clock.advance(minutes=5)
            assert (await j.send("结算探索", "old-claim")).ok
            assert (await j.send("领取悬赏", "claim")).code == "BOUNTY_NOT_COMPLETE"
            assert (await j.send("开始探索 " + name, "cancel-new")).ok
            assert (await j.send("取消探索", "cancel")).ok
            for i in range(2):
                op = next(f"new-{i}-{n}" for n in range(100) if battle_roll_bp(f"new-{i}-{n}:battle") >= 6500)
                assert (await j.send("开始探索 " + name + " 稳行", op)).ok
                j.clock.advance(minutes=5)
                assert (await j.send("结算探索", f"new-claim-{i}")).ok
            with j.runtime.repository._connect() as db:
                saved = db.execute("SELECT result_json FROM exploration_sessions WHERE operation_id=?", (op,)).fetchone()[0]
                broken = json.loads(saved)
                broken["result"][next(iter(broken["result"]))] = True
                db.execute("UPDATE exploration_sessions SET result_json=? WHERE operation_id=?", (json.dumps(broken), op))
            before = _database_state(j.runtime)
            assert (await j.send("领取悬赏", "claim")).code == "PERSISTENCE_ERROR"
            assert _database_state(j.runtime) == before
            with j.runtime.repository._connect() as db:
                db.execute("UPDATE exploration_sessions SET result_json=? WHERE operation_id=?", (saved, op))
                snapshot = json.loads(db.execute("SELECT snapshot_json FROM bounty_offers WHERE operation_id='accept'").fetchone()[0])
            j.fail("claim")
            before = _database_state(j.runtime)
            assert (await j.send("领取悬赏", "claim")).code == "PERSISTENCE_ERROR"
            assert _database_state(j.runtime) == before
            j.repair()
            await j.restart()
            content = j.runtime.repository.content
            records = dict(content._records)
            for kind, record_key in [("bounty", key), ("reward", snapshot["reward_pool_key"]), ("exploration_mode", "explore.patrol_" + slug)]:
                records[kind, record_key] = {**records[kind, record_key], "status": "locked"}
            j.runtime.repository.content = replace(content, _records=records)
            inventory = _inventory(j.runtime)
            results = await asyncio.gather(j.send("领取悬赏", "claim"), j.send("领取悬赏", "claim"))
            assert all(r.ok for r in results), [r.message for r in results]
            assert sum(r.data["idempotent_replay"] for r in results) == 1
            assert results[0].data["rewards"] == snapshot["reward"]
            for k, n in snapshot["reward"].items():
                if k.startswith("item."):
                    assert _inventory(j.runtime).get(k, 0) - inventory.get(k, 0) == n
            assert (await j.send("领取悬赏", "again")).code == "BOUNTY_REWARD_ALREADY_CLAIMED"
            before = _database_state(j.runtime)
            assert (await j.send("领取悬赏", "claim", user="foreign")).code == "OPERATION_CONFLICT"
            assert _database_state(j.runtime) == before
        finally:
            await j.runtime.close()
    asyncio.run(run())


def test_patrol_bounty_lost_battle_and_expired_exploration_do_not_count(tmp_path):
    async def run():
        j = FieldJourney(_copy_content(tmp_path), "onebot.v11")
        try:
            await starter(j.runtime)
            with j.runtime.repository._connect() as db:
                db.execute("UPDATE players SET realm_layer=2, stamina=100, energy=100")
            assert (await j.send("接取悬赏 镇外路况札", "accept")).ok
            original = j.runtime.repository.content
            records = dict(original._records)
            for candidate in original.require("encounter_pool", "encounter.xuantian.outskirts")["candidates"]:
                key = ("enemy", candidate["enemy_key"])
                records[key] = {**records[key], "stats": {"hp": 10000, "attack": 10000, "initiative": 100, "agility": 100}}
            j.runtime.repository.content = replace(original, _records=records)
            op = next(f"loss-{n}" for n in range(100) if battle_roll_bp(f"loss-{n}:battle") < 6500)
            assert (await j.send("开始探索 近郊巡路 追迹", op)).ok
            j.clock.advance(minutes=5)
            result = await j.send("结算探索", "lost")
            assert result.ok and result.data["battle_outcome"] == "lost", result.message
            assert (await j.send("领取悬赏", "claim")).code == "BOUNTY_NOT_COMPLETE"
            j.runtime.repository.content = original
            with j.runtime.repository._connect() as db:
                db.execute("UPDATE players SET max_hp=999, initiative=99, qualification_json=?", (json.dumps(BALANCED_QUALIFICATION),))
            op = next(f"win-{n}" for n in range(100) if battle_roll_bp(f"win-{n}:battle") < 6500)
            assert (await j.send("开始探索 近郊巡路 追迹", op)).ok
            j.clock.advance(minutes=5)
            won = await j.send("结算探索", "win-claim")
            assert won.ok and won.data["battle_outcome"] == "won", won.message
            board = await j.send("悬赏榜")
            assert next(o for o in board.data["offers"] if o["bounty_key"] == "bounty.patrol.outskirts")["progress"] == 1
            assert (await j.send("开始探索 近郊巡路", "late")).ok
            j.clock.advance(hours=25)
            assert (await j.send("结算探索", "late-claim")).code == "EXPLORATION_EXPIRED"
            inventory = _inventory(j.runtime)
            assert (await j.send("领取悬赏", "claim")).code == "BOUNTY_EXPIRED"
            assert _inventory(j.runtime) == inventory
        finally:
            await j.runtime.close()
    asyncio.run(run())


def test_patrol_bounty_realm_quota_and_malformed_baseline(tmp_path):
    async def run():
        j = FieldJourney(_copy_content(tmp_path), "onebot.v11")
        try:
            await starter(j.runtime)
            before = _database_state(j.runtime)
            assert (await j.send("接取悬赏 林桥巡护札", "gate")).code == "BOUNTY_REQUIREMENT_MISSING"
            assert _database_state(j.runtime) == before
            with j.runtime.repository._connect() as db:
                db.execute("UPDATE players SET realm_layer=2, stamina=100, energy=100")
            assert (await j.send("接取悬赏 镇外路况札", "accept")).ok
            with j.runtime.repository._connect() as db:
                saved = db.execute("SELECT snapshot_json FROM bounty_offers").fetchone()[0]
                broken = json.loads(saved)
                broken["baseline_operation_rowid"] = True
                db.execute("UPDATE bounty_offers SET snapshot_json=?", (json.dumps(broken),))
            before = _database_state(j.runtime)
            assert (await j.send("领取悬赏", "claim")).code == "PERSISTENCE_ERROR"
            assert _database_state(j.runtime) == before
            with j.runtime.repository._connect() as db:
                broken["baseline_operation_rowid"] = 0
                db.execute("UPDATE bounty_offers SET snapshot_json=?", (json.dumps(broken),))
            before = _database_state(j.runtime)
            assert (await j.send("领取悬赏", "claim")).code == "PERSISTENCE_ERROR"
            assert _database_state(j.runtime) == before
            with j.runtime.repository._connect() as db:
                db.execute("UPDATE bounty_offers SET snapshot_json=?", (saved,))
            for n in range(4):
                assert (await j.send("开始探索 近郊巡路", f"quota-{n}")).ok
                assert (await j.send("取消探索", f"cancel-{n}")).ok
            repo = j.runtime.repository
            with repo._connect() as db:
                row = db.execute("SELECT * FROM players").fetchone()
                definitions = [d for d in bounty_definitions(repo.content) if d.target_kind == "exploration_completions" and d.target_key == "explore.patrol_outskirts"]
                assert all(not repo._bounty_player_eligible(db, row, d, j.clock(), {}) for d in definitions)
            await j.next_day()
            with repo._connect() as db:
                row = db.execute("SELECT * FROM players").fetchone()
                assert all(repo._bounty_player_eligible(db, row, d, j.clock(), {}) for d in definitions)
        finally:
            await j.runtime.close()
    asyncio.run(run())
