from __future__ import annotations

import asyncio
import json
import shutil
import sqlite3
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

import pytest
from combat_fixtures import equip_damage_weapon
from test_team_arena import MutableClock, _ctx, _player, _ready_party

from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.combat.spectator_rules import simulate_spectator_match
from nonebot_plugin_xiuxian_3.xiuxian.persistence.errors import OperationConflictError, OperationResultMalformedError
from nonebot_plugin_xiuxian_3.xiuxian.stats.rules import COMBAT_STAT_KEYS


async def _prepare(runtime, team: bool):
    identities = (("qq.official", "left"), ("onebot.v11", "right"))
    for adapter, user in identities:
        await _player(runtime, adapter, user, user + "-create")
        if team:
            await _player(runtime, adapter, user + "-member", user + "-member-create")
            await _ready_party(runtime, adapter, user, user + "-member", user + "-party")
    return identities


async def _publish(runtime, identities, team: bool):
    command = "发布组队竞技场快照" if team else "发布竞技场快照"
    snapshots = []
    for adapter, user in identities:
        result = await runtime.adapters.dispatch(adapter, _ctx(adapter, user, user + "-publish"), command)
        assert result.ok, result
        snapshots.append(result.data["snapshot_id"])
    return snapshots


def _database(runtime):
    with sqlite3.connect(runtime.settings.database_path) as connection:
        return tuple(connection.iterdump())


@pytest.mark.parametrize("team", (False, True), ids=("solo", "team"))
def test_arena_build_is_shared_frozen_and_recovered(tmp_path, monkeypatch, team):
    async def run():
        data_dir = tmp_path / "data"
        shutil.copytree(Path(__file__).parents[1] / "data", data_dir)
        clock = MutableClock(datetime(2026, 10, 7, tzinfo=timezone.utc))
        runtime = create_runtime(data_dir=data_dir, clock=clock)
        identities = await _prepare(runtime, team)
        now = clock().isoformat()
        constitution = runtime.repository.content.require("constitution", "constitution.iron_bone")
        for adapter, user in identities:
            equip_damage_weapon(runtime, adapter, user, 15)
            with sqlite3.connect(runtime.settings.database_path) as connection:
                player_id = connection.execute(
                    "SELECT id FROM players WHERE platform=? AND platform_user_id=?", (adapter, user)
                ).fetchone()[0]
                connection.execute("UPDATE equipment_instances SET temper_level=2 WHERE player_id=?", (player_id,))
                connection.execute("UPDATE players SET inventory_json=? WHERE id=?", (json.dumps({"item.manual.basic_qi": 1}), player_id))
                connection.execute(
                    "INSERT INTO constitution_profiles(profile_id, player_id, operation_id, constitution_key, "
                    "status, selected_at, snapshot_json, created_at, updated_at) VALUES (?, ?, ?, ?, 'selected', ?, ?, ?, ?)",
                    (user + "-constitution", player_id, user + "-constitution", constitution["key"], now,
                     json.dumps({"effect": constitution["effect"]}), now, now),
                )
        previews = {
            user: await runtime.repository.preview_stats(platform=adapter, platform_user_id=user)
            for adapter, user in identities
        }
        snapshots = await _publish(runtime, identities, team)
        table = "arena_team_snapshots" if team else "arena_snapshots"
        with sqlite3.connect(runtime.settings.database_path) as connection:
            frozen = json.loads(connection.execute(
                f"SELECT snapshot_json FROM {table} WHERE snapshot_id=?", (snapshots[1],)
            ).fetchone()[0])
            frozen_player = frozen["members"][0] if team else frozen
            preview = previews["right"]
            assert frozen_player["stats"] == preview["combat_stats"]
            assert frozen_player["derived_stats"] == preview["derived_stats"]
            assert frozen_player["equipment"] == preview["equipment"]
            assert frozen_player["constitution_effect"] == preview["constitution_effect"]
            assert frozen_player["manual_effects"] == preview["manual_effects"]
            assert frozen_player["source_refs"] == preview["source_refs"]
            assert frozen_player["formula_fingerprint"] == preview["formula_fingerprint"]
            assert frozen_player["equipment"][0]["temper_level"] == 2
            assert frozen_player["manual_effects"]["combat_stat_bonus_bp"]["attack"] > 0
            assert connection.execute("SELECT COUNT(*) FROM stat_snapshots").fetchone()[0] == 0
            connection.execute("UPDATE equipment_instances SET durability_bp=0")
            connection.execute("UPDATE players SET max_hp=100, initiative=10, inventory_json='{}'")
        await runtime.close()
        rules_path = data_dir / "养成" / "规则.json"
        document = json.loads(rules_path.read_text(encoding="utf-8"))
        formula = next(record for record in document["records"] if record["key"] == "stats.formula")
        formula["formulas"]["max_hp_body"] += 2
        rules_path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
        runtime = create_runtime(data_dir=data_dir, clock=clock)
        current = await runtime.repository.preview_stats(platform=identities[1][0], platform_user_id="right")
        assert current["combat_stats"] != frozen_player["stats"]
        assert current["formula_fingerprint"] != frozen_player["formula_fingerprint"]
        clock.advance(minutes=31)
        challenge_command = "挑战组队竞技场" if team else "挑战竞技场"
        challenge = await runtime.adapters.dispatch(
            "qq.official", _ctx("qq.official", "left", "challenge"), f"{challenge_command} {snapshots[1]}"
        )
        assert challenge.ok, challenge
        match_id = challenge.data["match_id"]
        await runtime.close()
        runtime = create_runtime(data_dir=data_dir, clock=clock)
        await runtime.initialize()

        def no_live_build(*args, **kwargs):
            raise AssertionError("replay must use the settled match and frozen snapshots")

        monkeypatch.setattr(runtime.repository, "_build_player_stat_snapshot", no_live_build)
        before = _database(runtime)
        replay_command = "组队竞技场回放" if team else "竞技场回放"
        for adapter, user in identities:
            replay = await runtime.adapters.dispatch(adapter, _ctx(adapter, user, user + "-replay"), f"{replay_command} {match_id}")
            assert replay.ok, replay
            assert replay.data["snapshot"]["defender"] == frozen
        duplicate = await runtime.adapters.dispatch(
            "qq.official", _ctx("qq.official", "left", "challenge"), f"{challenge_command} {snapshots[1]}"
        )
        assert duplicate.data["idempotent_replay"] is True
        assert duplicate.data["match_id"] == match_id
        challenge_method = runtime.repository.challenge_team_arena if team else runtime.repository.challenge_arena
        with pytest.raises(OperationConflictError):
            await challenge_method(platform="qq.official", platform_user_id="left", snapshot_id=None, operation_id="challenge")
        assert _database(runtime) == before
        with sqlite3.connect(runtime.settings.database_path) as connection:
            match_table = "arena_team_matches" if team else "arena_matches"
            assert connection.execute(f"SELECT COUNT(*) FROM {match_table}").fetchone()[0] == 1
            assert connection.execute("SELECT COUNT(*) FROM arena_projection_events").fetchone()[0] == (4 if team else 2)
            assert connection.execute("SELECT COUNT(*) FROM stat_snapshots").fetchone()[0] == 0
        await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("team", (False, True), ids=("solo", "team"))
def test_malformed_arena_build_and_operation_roll_back(tmp_path, team):
    async def run():
        clock = MutableClock(datetime(2026, 10, 7, tzinfo=timezone.utc))
        runtime = create_runtime(data_dir=tmp_path, clock=clock)
        identities = await _prepare(runtime, team)
        snapshots = await _publish(runtime, identities, team)
        clock.advance(minutes=31)
        table = "arena_team_snapshots" if team else "arena_snapshots"
        with sqlite3.connect(runtime.settings.database_path) as connection:
            original = connection.execute(f"SELECT snapshot_json FROM {table} WHERE snapshot_id=?", (snapshots[1],)).fetchone()[0]
        corruptions = ["{", original.replace('"stats": {', '"stats": {"attack": 1, ', 1)]
        for field, value in (("max_hp", None), ("attack", True), ("initiative", -1)):
            snapshot = deepcopy(json.loads(original))
            stats = snapshot["members"][0]["stats"] if team else snapshot["stats"]
            if value is None:
                del stats[field]
            else:
                stats[field] = value
            corruptions.append(json.dumps(snapshot))
        challenge = runtime.repository.challenge_team_arena if team else runtime.repository.challenge_arena
        for corrupt in corruptions:
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(f"UPDATE {table} SET snapshot_json=? WHERE snapshot_id=?", (corrupt, snapshots[1]))
            before = _database(runtime)
            with pytest.raises(ValueError):
                await challenge(platform="qq.official", platform_user_id="left", snapshot_id=snapshots[1], operation_id="bad-build")
            assert _database(runtime) == before
        with sqlite3.connect(runtime.settings.database_path) as connection:
            connection.execute(f"UPDATE {table} SET snapshot_json=? WHERE snapshot_id=?", (original, snapshots[1]))
        settled = await challenge(platform="qq.official", platform_user_id="left", snapshot_id=snapshots[1], operation_id="bad-build")
        assert settled.match_id
        with sqlite3.connect(runtime.settings.database_path) as connection:
            connection.execute("UPDATE operations SET result_json=? WHERE operation_id=?", ('{"match_id":"a","match_id":"b"}', "bad-build"))
        before = _database(runtime)
        with pytest.raises(OperationResultMalformedError):
            await challenge(platform="qq.official", platform_user_id="left", snapshot_id=snapshots[1], operation_id="bad-build")
        assert _database(runtime) == before
        await runtime.close()

    asyncio.run(run())


def test_spectator_uses_explicit_low_stats_without_recalculating():
    left = {key: 0 for key in COMBAT_STAT_KEYS}
    left.update(max_hp=20, attack=2, initiative=1)
    right = {**left, "max_hp": 30, "attack": 3, "initiative": 2}
    outcome, rounds, actions = simulate_spectator_match(
        {"stats": left}, {"stats": right}, seed="low-stats", max_rounds=1
    )
    assert outcome == "draw"
    assert rounds == 1
    assert actions[0]["actor_key"] == "defender"
    assert all(action["state"]["challenger_hp"] <= 20 and action["state"]["defender_hp"] <= 30 for action in actions)
    assert all(action["damage"] <= 5 for action in actions)
