from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime


class MutableClock:
    def __init__(self, value: datetime):
        self.value = value

    def __call__(self) -> datetime:
        return self.value

    def advance(self, **kwargs: int) -> None:
        self.value += timedelta(**kwargs)


def _context(user_id: str, request_id: str, *, operation_id: str = "") -> CommandContext:
    return CommandContext(adapter="web", user_id=user_id, request_id=request_id, operation_id=operation_id)


async def _enter_mortal(runtime, user_id: str) -> None:
    assert (await runtime.dispatch(_context(user_id, "create"), "开始修仙")).ok
    assert (await runtime.dispatch(_context(user_id, "seek"), "寻仙问道")).ok


def _set_resources(runtime, user_id: str, *, stones: int = 100, energy: int = 10) -> None:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE players SET spirit_stones = ?, energy = ?, energy_max = 30 WHERE platform_user_id = ?",
            (stones, energy, user_id),
        )


def test_daily_checkin_is_idempotent_and_unique_across_operations() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            user = "routine-checkin"
            await _enter_mortal(runtime, user)
            _set_resources(runtime, user, stones=0, energy=0)

            results = await asyncio.gather(
                runtime.dispatch(_context(user, "a", operation_id="checkin-a"), "道历问安"),
                runtime.dispatch(_context(user, "b", operation_id="checkin-b"), "道历问安"),
            )
            assert sorted(result.ok for result in results) == [False, True]
            assert {result.code for result in results} == {"DAILY_CHECKIN_CLAIMED", "CHECKIN_ALREADY_CLAIMED"}
            success = next(result for result in results if result.ok)
            assert success.data["reward"] == {"spirit_stones": 20, "energy": 3}
            replay = await runtime.dispatch(
                _context(user, "replay", operation_id=success.operation_id or ""), "道历问安"
            )
            assert replay.ok and replay.data["idempotent_replay"] is True
            conflict = await runtime.dispatch(
                _context(user, "conflict", operation_id=success.operation_id or ""), "浇灌灵木"
            )
            assert conflict.code == "OPERATION_CONFLICT"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                row = connection.execute(
                    "SELECT spirit_stones, energy, COUNT(*) FROM players JOIN routine_checkins ON routine_checkins.player_id = players.id WHERE platform_user_id = ?",
                    (user,),
                ).fetchone()
            assert row == (20, 3, 1)
            await runtime.close()

    asyncio.run(run())


def test_seven_direct_checkins_award_fate_ticket_but_makeup_does_not_extend_streak() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            user = "routine-streak"
            await _enter_mortal(runtime, user)
            _set_resources(runtime, user, stones=500, energy=0)
            first = await runtime.dispatch(
                _context(user, "daily-0", operation_id="daily-0"), "道历问安"
            )
            assert first.ok
            clock.advance(days=2)
            makeup = await runtime.dispatch(
                _context(user, "makeup", operation_id="makeup-streak"), "补录道历 2026-09-23"
            )
            assert makeup.ok
            # Makeup fills the missed date but does not extend the direct streak.
            for day in range(1, 8):
                result = await runtime.dispatch(
                    _context(user, f"daily-{day}", operation_id=f"daily-{day}"), "道历问安"
                )
                assert result.ok
                if day < 7:
                    clock.advance(days=1)
            assert result.data["consecutive_days"] == 7
            with sqlite3.connect(runtime.settings.database_path) as connection:
                inventory = json.loads(
                    connection.execute(
                        "SELECT inventory_json FROM players WHERE platform_user_id = ?", (user,)
                    ).fetchone()[0]
                )
            assert inventory["item.ticket.fate_basic"] == 1

            await runtime.close()

    asyncio.run(run())


def test_makeup_window_monthly_limit_and_failed_cost_are_atomic() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            user = "routine-makeup"
            await _enter_mortal(runtime, user)
            _set_resources(runtime, user, stones=60, energy=0)
            first = await runtime.dispatch(
                _context(user, "first", operation_id="makeup-1"), "补录道历 2026-09-21"
            )
            second = await runtime.dispatch(
                _context(user, "second", operation_id="makeup-2"), "补录道历 2026-09-20"
            )
            assert first.ok and second.ok
            third = await runtime.dispatch(
                _context(user, "third", operation_id="makeup-3"), "补录道历 2026-09-19"
            )
            assert third.code == "MAKEUP_LIMIT_REACHED"
            invalid = await runtime.dispatch(
                _context(user, "invalid", operation_id="makeup-4"), "补录道历 2026-09-18"
            )
            assert invalid.code == "INVALID_MAKEUP_DATE"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                row = connection.execute(
                    "SELECT spirit_stones, COUNT(*) FROM players JOIN routine_checkins ON routine_checkins.player_id = players.id WHERE platform_user_id = ?",
                    (user,),
                ).fetchone()
            assert row == (32, 2)

            poor = "routine-makeup-poor"
            await _enter_mortal(runtime, poor)
            _set_resources(runtime, poor, stones=29, energy=0)
            refused = await runtime.dispatch(
                _context(poor, "poor", operation_id="makeup-poor"), "补录道历 2026-09-21"
            )
            assert refused.code == "RESOURCE_INSUFFICIENT"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                balance = connection.execute(
                    "SELECT spirit_stones FROM players WHERE platform_user_id = ?", (poor,)
                ).fetchone()[0]
            assert balance == 29
            await runtime.close()

    asyncio.run(run())


def test_spirit_tree_requires_seven_days_persists_harvest_roll_and_cools_down() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 1, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            user = "routine-tree"
            await _enter_mortal(runtime, user)
            _set_resources(runtime, user, stones=0, energy=20)
            for index in range(7):
                watered = await runtime.dispatch(
                    _context(user, f"water-{index}", operation_id=f"water-{index}"), "浇灌灵木"
                )
                assert watered.ok
                if index == 0:
                    duplicate = await runtime.dispatch(
                        _context(user, "water-duplicate", operation_id="water-duplicate"), "浇灌灵木"
                    )
                    assert duplicate.code == "SPIRIT_TREE_ALREADY_WATERED"
                if index < 6:
                    clock.advance(days=1)
            assert watered.data["status"] == "ready"
            harvested = await runtime.dispatch(
                _context(user, "harvest", operation_id="harvest-1"), "收获灵木"
            )
            assert harvested.ok
            replay = await runtime.dispatch(
                _context(user, "harvest-replay", operation_id="harvest-1"), "收获灵木"
            )
            assert replay.data["idempotent_replay"] is True
            assert replay.data["reward"] == harvested.data["reward"]
            blocked = await runtime.dispatch(
                _context(user, "harvest-again", operation_id="harvest-2"), "收获灵木"
            )
            assert blocked.code == "SPIRIT_TREE_COOLDOWN"
            clock.advance(hours=24)
            watered_again = await runtime.dispatch(
                _context(user, "water-next", operation_id="water-next"), "浇灌灵木"
            )
            assert watered_again.ok and watered_again.data["water_count"] == 1
            with sqlite3.connect(runtime.settings.database_path) as connection:
                count = connection.execute(
                    "SELECT COUNT(*) FROM spirit_tree_harvests WHERE player_id = (SELECT id FROM players WHERE platform_user_id = ?)",
                    (user,),
                ).fetchone()[0]
            assert count == 1
            await runtime.close()

    asyncio.run(run())


def test_routine_schema_is_safe_to_initialize_twice() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            first = create_runtime(data_dir=data_dir)
            await first.initialize()
            second = create_runtime(data_dir=data_dir)
            await second.initialize()
            with sqlite3.connect(second.settings.database_path) as connection:
                tables = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }
                migration = connection.execute(
                    "SELECT migration_key FROM schema_migrations WHERE migration_key = 'routine.v0.1'"
                ).fetchone()
            assert {"routine_checkins", "spirit_trees", "spirit_tree_waterings", "spirit_tree_harvests"} <= tables
            assert migration == ("routine.v0.1",)
            await first.close()
            await second.close()

    asyncio.run(run())
