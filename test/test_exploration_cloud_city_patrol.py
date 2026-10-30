"""Behavioural contract for the cloud-city night patrol exploration mode."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timezone
from tempfile import TemporaryDirectory

from combat_fixtures import BALANCED_QUALIFICATION

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime

MODE = "explore.cloud_city_patrol"
LOCATION = "xuantian.cloud_city"


def _context(user: str, name: str, operation_id: str = "") -> CommandContext:
    return CommandContext(adapter="web", user_id=user, request_id=name, operation_id=operation_id)


def _prepare(runtime, user: str, *, location: str = LOCATION, realm: str = "golden_core",
             layer: int = 1, stamina: int = 200) -> None:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE players SET stage='cultivator', realm_key=?, realm_layer=?, location_key=?, "
            "stamina=?, stamina_max=?, qualification_json=?, max_hp=8000, initiative=8000 "
            "WHERE platform_user_id=?",
            (realm, layer, location, stamina, max(stamina, 200),
             json.dumps(BALANCED_QUALIFICATION), user),
        )


async def _create(runtime, user: str) -> None:
    assert (await runtime.dispatch(_context(user, "create"), "开始修仙")).ok
    assert (await runtime.dispatch(_context(user, "seek"), "寻仙问道")).ok


def _clock_at(hour: int = 21):
    value = datetime(2026, 9, 30, hour, tzinfo=timezone.utc)
    box = [value]

    def clock() -> datetime:
        return box[0]

    return clock, box


def test_cloud_city_patrol_settles_and_pays_pool_rewards() -> None:
    async def run() -> None:
        clock, box = _clock_at()
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            user = "patrol-settle"
            try:
                await _create(runtime, user)
                _prepare(runtime, user)
                started = await runtime.dispatch(
                    _context(user, "start", f"{user}-start"), "开始探索 云城巡夜"
                )
                assert started.code == "EXPLORATION_STARTED", started
                box[0] = box[0].replace(second=0) + __import__("datetime").timedelta(seconds=200)
                settled = await runtime.dispatch(_context(user, "settle"), "结算探索")
                assert settled.code == "EXPLORATION_SETTLED", settled
                assert settled.data["mode_key"] == MODE
                result = settled.data["result"]
                assert result["spirit_stones"] > 0, result
                assert result.get("cultivation", 0) > 0, result
            finally:
                await runtime.close()

    asyncio.run(run())


def test_cloud_city_patrol_requires_location_and_enforces_daily_limit() -> None:
    async def run() -> None:
        clock, box = _clock_at()
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            user = "patrol-limits"
            try:
                await _create(runtime, user)
                _prepare(runtime, user, location="xuantian.new_town")
                wrong_place = await runtime.dispatch(
                    _context(user, "wrong", f"{user}-start"), "开始探索 云城巡夜"
                )
                assert wrong_place.code in {
                    "EXPLORATION_REQUIREMENT_MISSING",
                    "EXPLORATION_LOCATION_FORBIDDEN",
                }, wrong_place

                _prepare(runtime, user, location=LOCATION)
                for index in range(4):
                    started = await runtime.dispatch(
                        _context(user, f"s{index}", f"{user}-run-{index}"), "开始探索 云城巡夜"
                    )
                    assert started.code == "EXPLORATION_STARTED", (index, started)
                    box[0] = box[0] + __import__("datetime").timedelta(seconds=200)
                    settled = await runtime.dispatch(_context(user, f"t{index}"), "结算探索")
                    assert settled.code == "EXPLORATION_SETTLED", (index, settled)

                fifth = await runtime.dispatch(
                    _context(user, "s4", f"{user}-run-4"), "开始探索 云城巡夜"
                )
                assert fifth.code == "EXPLORATION_QUOTA_EXHAUSTED", fifth
            finally:
                await runtime.close()

    asyncio.run(run())
