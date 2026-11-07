"""Behavioural + content contract for the two foundation exploration modes.

The foundation realm only had explore.cloud_mine. These two modes add coverage
at existing open locations (cloud city / spirit field) with real combat-ready
enemies, distinct weighted pools, daily limits and codex entries, reusing the
existing exploration contract without new commands or settlement semantics.
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
)
from nonebot_plugin_xiuxian_3.xiuxian.rewards.rules import reward_pool_outcomes

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

MODES = (
    {
        "key": "explore.cloud_city_escort",
        "command": "云城护送",
        "location": "xuantian.cloud_city",
        "pool": "reward_pool.exploration.cloud_city_escort",
        "encounter": "encounter.cloud_city_escort",
        "codex": "codex.escort.cloud_city_escort",
        "chance": 2500,
        "enemy": "enemy.bandit_apprentice",
    },
    {
        "key": "explore.spirit_field_tending",
        "command": "灵田巡护",
        "location": "xuantian.spirit_field",
        "pool": "reward_pool.exploration.spirit_field_tending",
        "encounter": "encounter.spirit_field_tending",
        "codex": "codex.escort.spirit_field_tending",
        "chance": 2000,
        "enemy": "enemy.spring_wisp",
    },
)


def _bundle() -> ContentBundle:
    return ContentBundle.load(DATA)


def _context(user: str, name: str, operation_id: str = "") -> CommandContext:
    return CommandContext(
        adapter="web", user_id=user, request_id=name, operation_id=operation_id
    )


def _prepare(
    runtime, user: str, *, location: str, realm: str = "foundation",
    layer: int = 1, stamina: int = 200,
) -> None:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE players SET stage='cultivator', realm_key=?, realm_layer=?, "
            "location_key=?, stamina=?, stamina_max=?, qualification_json=?, "
            "max_hp=8000, initiative=8000 WHERE platform_user_id=?",
            (realm, layer, location, stamina, max(stamina, 200),
             json.dumps(BALANCED_QUALIFICATION), user),
        )


async def _create(runtime, user: str) -> None:
    assert (await runtime.dispatch(_context(user, "create"), "开始修仙")).ok
    assert (await runtime.dispatch(_context(user, "seek"), "寻仙问道")).ok


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


def test_foundation_modes_resolve_content_end_to_end() -> None:
    bundle = _bundle()
    for spec in MODES:
        definition = exploration_definition(spec["key"], bundle)
        assert definition.location_key == spec["location"]
        assert definition.required_realm == "foundation"
        assert definition.required_layer == 1
        assert definition.daily_limit == 5
        assert definition.battle_chance_bp == spec["chance"]
        assert EXPLORATION_REWARD_POOLS[spec["key"]] == spec["pool"]

        outcomes = reward_pool_outcomes(spec["pool"], bundle)
        distinct = {tuple(sorted(rewards.items())) for _, rewards in outcomes}
        assert len(distinct) >= 2, spec["key"]

        pool = bundle.get("encounter_pool", spec["encounter"], include_locked=False)
        assert pool and pool["candidates"], spec["key"]
        for candidate in pool["candidates"]:
            enemy = enemy_definition(candidate["enemy_key"], content=bundle)
            assert enemy.location_key == spec["location"], candidate["enemy_key"]

        assert bundle.get("codex_entry", spec["codex"], include_locked=False)

    # The two new commands must resolve unambiguously through the shipped alias
    # table (the loader raises on any alias mapped to two different mode keys).
    from nonebot_plugin_xiuxian_3.xiuxian.exploration.rules import (
        resolve_exploration_mode,
    )

    for spec in MODES:
        assert resolve_exploration_mode(spec["command"], bundle) == spec["key"]


def test_foundation_modes_settle_calm_runs_and_pay_pool_rewards() -> None:
    async def run() -> None:
        clock, box = _clock()
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            try:
                for spec in MODES:
                    user = f"foundation-calm-{spec['key']}"
                    await _create(runtime, user)
                    _prepare(runtime, user, location=spec["location"])
                    op = _calm_operation(f"{user}-calm", spec["chance"])
                    started = await runtime.dispatch(
                        _context(user, "start", op), f"开始探索 {spec['command']}"
                    )
                    assert started.code == "EXPLORATION_STARTED", (spec["key"], started)
                    box[0] = box[0] + timedelta(seconds=400)
                    settled = await runtime.dispatch(_context(user, "settle"), "结算探索")
                    assert settled.code == "EXPLORATION_SETTLED", (spec["key"], settled)
                    assert settled.data["mode_key"] == spec["key"]
                    result = settled.data["result"]
                    assert result, (spec["key"], result)
                    assert all(q > 0 for q in result.values()), (spec["key"], result)
            finally:
                await runtime.close()

    asyncio.run(run())


def test_foundation_modes_enforce_location_and_daily_limit() -> None:
    async def run() -> None:
        clock, box = _clock()
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            try:
                for spec in MODES:
                    user = f"foundation-limits-{spec['key']}"
                    await _create(runtime, user)
                    _prepare(runtime, user, location="xuantian.new_town")
                    wrong = await runtime.dispatch(
                        _context(user, "wrong", f"{user}-wrong"),
                        f"开始探索 {spec['command']}",
                    )
                    assert wrong.code in {
                        "EXPLORATION_REQUIREMENT_MISSING",
                        "EXPLORATION_LOCATION_FORBIDDEN",
                    }, (spec["key"], wrong)

                    _prepare(runtime, user, location=spec["location"])
                    for index in range(5):
                        op = _calm_operation(f"{user}-run-{index}", spec["chance"])
                        started = await runtime.dispatch(
                            _context(user, f"s{index}", op),
                            f"开始探索 {spec['command']}",
                        )
                        assert started.code == "EXPLORATION_STARTED", (index, started)
                        box[0] = box[0] + timedelta(seconds=400)
                        settled = await runtime.dispatch(
                            _context(user, f"t{index}"), "结算探索"
                        )
                        assert settled.code == "EXPLORATION_SETTLED", (index, settled)
                    exhausted = await runtime.dispatch(
                        _context(user, "sixth", f"{user}-run-5"),
                        f"开始探索 {spec['command']}",
                    )
                    assert exhausted.code == "EXPLORATION_QUOTA_EXHAUSTED", exhausted
            finally:
                await runtime.close()

    asyncio.run(run())


def test_foundation_escort_hit_seed_creates_one_battle() -> None:
    """A forced-battle settle persists exactly one battle with the pool enemy."""
    async def run() -> None:
        clock, box = _clock()
        spec = MODES[0]
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            try:
                user = "foundation-battle-escort"
                await _create(runtime, user)
                _prepare(runtime, user, location=spec["location"])
                op = _hit_operation(f"{user}-hit", spec["chance"])
                started = await runtime.dispatch(
                    _context(user, "start", op), f"开始探索 {spec['command']}"
                )
                assert started.code == "EXPLORATION_STARTED", started
                box[0] = box[0] + timedelta(seconds=400)
                settled = await runtime.dispatch(_context(user, "settle"), "结算探索")
                assert settled.code == "EXPLORATION_SETTLED", settled
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    rows = connection.execute(
                        "SELECT enemy_key, battle_type FROM battle_sessions "
                        "WHERE player_id=(SELECT id FROM players WHERE platform_user_id=?)",
                        (user,),
                    ).fetchall()
                assert len(rows) == 1, rows
                assert rows[0][0] == spec["enemy"]
                assert rows[0][1] == "pve.exploration"
            finally:
                await runtime.close()

    asyncio.run(run())
