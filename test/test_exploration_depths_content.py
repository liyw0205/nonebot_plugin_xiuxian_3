"""Content contract for the two terminal exploration depths."""

from __future__ import annotations

import asyncio
import copy
import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle, ContentError
from nonebot_plugin_xiuxian_3.xiuxian.exploration.rules import (
    exploration_definition,
    resolve_exploration_mode,
)

DATA = Path(__file__).parents[1] / "data"
MODES = ("explore.ancient_domain", "explore.abyss_depths")


class MutableClock:
    def __init__(self, value: datetime):
        self.value = value

    def __call__(self) -> datetime:
        return self.value

    def advance(self, **kwargs: int) -> None:
        self.value += timedelta(**kwargs)


def _context(user_id: str, request_id: str, *, operation_id: str = "") -> CommandContext:
    return CommandContext(
        adapter="web", user_id=user_id, request_id=request_id, operation_id=operation_id
    )


def _with_record(bundle, kind, key, **changes):
    records = dict(bundle._records)
    row = copy.deepcopy(records[(kind, key)])
    row.update(changes)
    records[(kind, key)] = row
    return replace(bundle, _records=records)


def test_depths_modes_close_their_location_pool_and_encounter_references() -> None:
    bundle = ContentBundle.load(DATA)
    for key in MODES:
        row = bundle.get("exploration_mode", key, include_locked=False)
        assert row is not None and row["status"] == "open"
        location = bundle.get("location", row["location_key"], include_locked=False)
        assert location is not None and location["status"] == "open"
        assert row["key"] in location["actions"]
        pool = bundle.get("reward", row["reward_pool_key"], include_locked=False)
        assert pool is not None and pool["outcomes"]
        encounter = bundle.get("encounter_pool", row["enemy_pool_key"], include_locked=False)
        assert encounter is not None and encounter["candidates"]
        for candidate in encounter["candidates"]:
            enemy = bundle.get("enemy", candidate["enemy_key"], include_locked=False)
            assert enemy is not None and enemy["status"] == "active"
            assert enemy["location_key"] == row["location_key"]
        definition = exploration_definition(key, bundle)
        assert definition.location_key == row["location_key"]
        assert definition.daily_limit == 2
        assert resolve_exploration_mode(row["name"], bundle) == key

    assert exploration_definition("explore.ancient_domain", bundle).stamina_cost == 18
    assert exploration_definition("explore.abyss_depths", bundle).energy_cost == 3
    assert bundle.get("location", "cave.ancient_domain")["requirements"] == [
        {"type": "realm", "realm_key": "soul_transformation", "min_layer": 1},
        {"type": "item", "item_key": "item.domain_core", "quantity": 1},
    ]


@pytest.mark.parametrize(
    "key,changes,message",
    [
        ("explore.ancient_domain", {"enemy_pool_key": "encounter.missing"}, "empty encounter pool"),
        ("explore.ancient_domain", {"reward_pool_key": "reward_pool.missing"}, "unavailable reward"),
        ("explore.ancient_domain", {"location_key": "cave.missing"}, "unavailable location"),
        ("explore.ancient_domain", {"daily_limit": 0}, "invalid daily_limit"),
        ("explore.abyss_depths", {"battle_chance_bp": 20000}, "invalid battle_chance_bp"),
        ("explore.abyss_depths", {"required_realm": "realm.missing"}, "unavailable realm"),
    ],
)
def test_depths_modes_reject_broken_records(key: str, changes: dict, message: str) -> None:
    content = _with_record(ContentBundle.load(DATA), "exploration_mode", key, **changes)
    with pytest.raises(ContentError, match=message):
        exploration_definition(key, content)


def test_abyss_depths_settles_and_replays_once() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            user = "depths-explorer"
            await runtime.dispatch(_context(user, "create"), "开始修仙")
            await runtime.dispatch(_context(user, "seek"), "寻仙问道")
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE players SET realm_key='soul_transformation', realm_layer=1, "
                    "location_key='demon.abyss_depths', stamina=80, stamina_max=80, "
                    "energy=20, energy_max=20 "
                    "WHERE platform_user_id = ?",
                    (user,),
                )
            started = await runtime.dispatch(
                _context(user, "start", operation_id="abyss-start"), "开始探索 魔渊深层探索"
            )
            assert started.code == "EXPLORATION_STARTED", started
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE exploration_sessions SET ends_at = ?",
                    ((clock.value - timedelta(seconds=1)).isoformat(),),
                )
            settled = await runtime.dispatch(
                _context(user, "settle", operation_id="abyss-settle"), "结算探索"
            )
            assert settled.code == "EXPLORATION_SETTLED", settled
            replay = await runtime.dispatch(
                _context(user, "settle", operation_id="abyss-settle"), "结算探索"
            )
            assert replay.data["idempotent_replay"] is True
            await runtime.close()

    asyncio.run(run())
