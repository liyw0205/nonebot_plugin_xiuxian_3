"""Contract for the two exploration modes at the inert open locations.

`xuantian.array_hall` and `xuantian.war_front` shipped with a place codex entry
and a realm gate but no activity at all. These two modes give each location a
real, reachable exploration run with a combat-ready enemy, a distinct weighted
pool and a challenge codex entry, reusing the generic exploration engine.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from combat_fixtures import BALANCED_QUALIFICATION

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.combat.rules import enemy_definition
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle
from nonebot_plugin_xiuxian_3.xiuxian.exploration.rules import (
    EXPLORATION_REWARD_POOLS,
    battle_roll_bp,
    exploration_definition,
    resolve_exploration_mode,
)
from nonebot_plugin_xiuxian_3.xiuxian.rewards.rules import reward_pool_outcomes

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

MODES = (
    {
        "key": "explore.array_hall_drill",
        "command": "阵堂值守",
        "location": "xuantian.array_hall",
        "realm": "qi_gathering",
        "stamina": 6,
        "duration": 120,
        "limit": 5,
        "chance": 2500,
        "pool": "reward_pool.exploration.array_hall_drill",
        "encounter": "encounter.array_hall_drill",
        "enemy": "enemy.array_hall_sentry",
        "codex": "codex.escort.array_hall_drill",
    },
    {
        "key": "explore.war_front_patrol",
        "command": "战线巡防",
        "location": "xuantian.war_front",
        "realm": "nascent_soul",
        "stamina": 12,
        "duration": 300,
        "limit": 3,
        "chance": 3000,
        "pool": "reward_pool.exploration.war_front_patrol",
        "encounter": "encounter.war_front_patrol",
        "enemy": "enemy.war_front_vanguard",
        "codex": "codex.escort.war_front_patrol",
    },
)


def _bundle() -> ContentBundle:
    return ContentBundle.load(DATA)


def _context(user: str, name: str, operation_id: str = "") -> CommandContext:
    return CommandContext(
        adapter="web", user_id=user, request_id=name, operation_id=operation_id
    )


def _clock():
    value = datetime(2026, 9, 30, 12, tzinfo=timezone.utc)
    box = [value]

    def clock() -> datetime:
        return box[0]

    return clock, box


def _calm_operation(prefix: str, chance: int) -> str:
    return next(
        f"{prefix}-{index}"
        for index in range(10_000)
        if battle_roll_bp(f"{prefix}-{index}:battle") >= chance
    )


def _hit_operation(prefix: str, chance: int) -> str:
    return next(
        f"{prefix}-{index}"
        for index in range(10_000)
        if battle_roll_bp(f"{prefix}-{index}:battle") < chance
    )


def _prepare(
    runtime, user: str, *, location: str, realm: str, stamina: int = 200
) -> None:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE players SET stage='cultivator', realm_key=?, realm_layer=1, "
            "location_key=?, stamina=?, stamina_max=?, qualification_json=?, "
            "max_hp=9000, initiative=9000 WHERE platform_user_id=?",
            (
                realm,
                location,
                stamina,
                max(stamina, 200),
                json.dumps(BALANCED_QUALIFICATION),
                user,
            ),
        )


async def _create(runtime, user: str) -> None:
    assert (await runtime.dispatch(_context(user, "create"), "开始修仙")).ok
    assert (await runtime.dispatch(_context(user, "seek"), "寻仙问道")).ok


def test_modes_close_the_two_inert_locations_end_to_end() -> None:
    bundle = _bundle()
    for spec in MODES:
        definition = exploration_definition(spec["key"], bundle)
        assert definition.location_key == spec["location"]
        assert definition.required_realm == spec["realm"]
        assert definition.required_layer == 1
        assert definition.daily_limit == spec["limit"]
        assert definition.stamina_cost == spec["stamina"]
        assert definition.duration_seconds == spec["duration"]
        assert definition.battle_chance_bp == spec["chance"]
        assert EXPLORATION_REWARD_POOLS[spec["key"]] == spec["pool"]

        # The pool must be a real weighted pool with at least three distinct
        # outcomes; a single-outcome pool would be quota padding.
        outcomes = reward_pool_outcomes(spec["pool"], bundle)
        distinct = {tuple(sorted(rewards.items())) for _, rewards in outcomes}
        assert len(distinct) >= 3, spec["key"]
        assert all(rewards for _, rewards in outcomes), spec["key"]

        pool = bundle.get("encounter_pool", spec["encounter"], include_locked=False)
        assert pool and pool["candidates"], spec["key"]
        enemy_keys = {candidate["enemy_key"] for candidate in pool["candidates"]}
        assert enemy_keys == {spec["enemy"]}, spec["key"]
        enemy = enemy_definition(spec["enemy"], content=bundle)
        assert enemy.location_key == spec["location"], spec["enemy"]

        assert bundle.get("codex_entry", spec["codex"], include_locked=False)

        # The location must actually advertise the mode, so the player can find
        # it: the action string is the discoverability pointer for the seed.
        location = bundle.require("location", spec["location"])
        assert spec["key"] in location["actions"], spec["location"]

    for spec in MODES:
        assert resolve_exploration_mode(spec["command"], bundle) == spec["key"]


def test_new_enemies_are_combat_ready() -> None:
    bundle = _bundle()
    for spec in MODES:
        record = bundle.require("enemy", spec["enemy"])
        assert isinstance(record.get("combat_profile"), dict), spec["enemy"]
        for field in ("hp", "attack", "initiative", "agility"):
            value = record["stats"].get(field)
            assert isinstance(value, int) and value > 0, (spec["enemy"], field)
        assert record["combat_profile"]["drop_pool_key"], spec["enemy"]
        assert bundle.has(
            "reward", record["combat_profile"]["drop_pool_key"], include_locked=False
        ), spec["enemy"]
        assert record.get("codex_entry_key"), spec["enemy"]


def test_modes_reject_foreign_location_realm_and_quota(tmp_path: Path) -> None:
    async def run() -> None:
        clock, box = _clock()
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            try:
                for spec in MODES:
                    # Foreign location: the mode must refuse.
                    user = f"inert-wrong-{spec['key']}"
                    await _create(runtime, user)
                    _prepare(
                        runtime,
                        user,
                        location="xuantian.new_town",
                        realm=spec["realm"],
                    )
                    wrong = await runtime.dispatch(
                        _context(user, "wrong", f"{user}-wrong"),
                        f"开始探索 {spec['command']}",
                    )
                    assert wrong.code in {
                        "EXPLORATION_REQUIREMENT_MISSING",
                        "EXPLORATION_LOCATION_FORBIDDEN",
                    }, (spec["key"], wrong)

                    # Too low a realm at the right location must also refuse.
                    low = f"inert-low-{spec['key']}"
                    await _create(runtime, low)
                    _prepare(
                        runtime,
                        low,
                        location=spec["location"],
                        realm="mortal",
                    )
                    refused = await runtime.dispatch(
                        _context(low, "low", f"{low}-low"),
                        f"开始探索 {spec['command']}",
                    )
                    assert refused.code in {
                        "EXPLORATION_REQUIREMENT_MISSING",
                        "EXPLORATION_LOCATION_FORBIDDEN",
                    }, (spec["key"], refused)

                    # At most one run per day beyond the configured limit.
                    ok = f"inert-quota-{spec['key']}"
                    await _create(runtime, ok)
                    _prepare(
                        runtime,
                        ok,
                        location=spec["location"],
                        realm=spec["realm"],
                        stamina=200,
                    )
                    for index in range(spec["limit"]):
                        op = _calm_operation(f"{ok}-run-{index}", spec["chance"])
                        started = await runtime.dispatch(
                            _context(ok, f"s{index}", op),
                            f"开始探索 {spec['command']}",
                        )
                        assert started.code == "EXPLORATION_STARTED", (index, started)
                        box[0] = box[0] + timedelta(seconds=spec["duration"] + 5)
                        settled = await runtime.dispatch(
                            _context(ok, f"t{index}"), "结算探索"
                        )
                        assert settled.code == "EXPLORATION_SETTLED", (index, settled)
                    exhausted = await runtime.dispatch(
                        _context(ok, "extra", f"{ok}-run-extra"),
                        f"开始探索 {spec['command']}",
                    )
                    assert exhausted.code == "EXPLORATION_QUOTA_EXHAUSTED", exhausted
            finally:
                await runtime.close()

    asyncio.run(run())


def test_new_mode_settles_calm_and_pays_its_own_pool() -> None:
    async def run() -> None:
        clock, box = _clock()
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            try:
                for spec in MODES:
                    user = f"inert-calm-{spec['key']}"
                    await _create(runtime, user)
                    _prepare(
                        runtime,
                        user,
                        location=spec["location"],
                        realm=spec["realm"],
                    )
                    op = _calm_operation(f"{user}-calm", spec["chance"])
                    started = await runtime.dispatch(
                        _context(user, "start", op), f"开始探索 {spec['command']}"
                    )
                    assert started.code == "EXPLORATION_STARTED", (spec["key"], started)
                    box[0] = box[0] + timedelta(seconds=spec["duration"] + 5)
                    settled = await runtime.dispatch(_context(user, "settle"), "结算探索")
                    assert settled.code == "EXPLORATION_SETTLED", (spec["key"], settled)
                    assert settled.data["mode_key"] == spec["key"]
                    result = settled.data["result"]
                    assert result, (spec["key"], result)
                    assert all(q > 0 for q in result.values()), (spec["key"], result)
            finally:
                await runtime.close()

    asyncio.run(run())


def test_new_mode_battle_path_records_a_real_fight_and_replay_is_idempotent() -> None:
    async def run() -> None:
        clock, box = _clock()
        spec = MODES[0]
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            try:
                user = "inert-battle"
                await _create(runtime, user)
                _prepare(
                    runtime, user, location=spec["location"], realm=spec["realm"]
                )
                op = _hit_operation(f"{user}-hit", spec["chance"])
                started = await runtime.dispatch(
                    _context(user, "start", op), f"开始探索 {spec['command']}"
                )
                assert started.code == "EXPLORATION_STARTED", started
                box[0] = box[0] + timedelta(seconds=spec["duration"] + 5)
                settled = await runtime.dispatch(_context(user, "settle"), "结算探索")
                assert settled.code == "EXPLORATION_SETTLED", settled
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    rows = connection.execute(
                        "SELECT enemy_key, battle_type FROM battle_sessions "
                        "WHERE player_id=(SELECT id FROM players WHERE platform_user_id=?)",
                        (user,),
                    ).fetchall()
                assert len(rows) == 1, rows
                assert rows[0][0] == spec["enemy"], rows
                assert rows[0][1] == "pve.exploration", rows

                # Replaying the exact same start request must not start a second
                # run or open a second battle.
                replay = await runtime.dispatch(
                    _context(user, "start", op), f"开始探索 {spec['command']}"
                )
                assert replay.code in {
                    "EXPLORATION_STARTED",
                    "EXPLORATION_BUSY",
                    "EXPLORATION_QUOTA_EXHAUSTED",
                }, replay
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    after = connection.execute(
                        "SELECT COUNT(*) FROM battle_sessions WHERE player_id="
                        "(SELECT id FROM players WHERE platform_user_id=?)",
                        (user,),
                    ).fetchone()[0]
                assert after == 1, after
            finally:
                await runtime.close()

    asyncio.run(run())
