from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.config import XiuxianSettings
from nonebot_plugin_xiuxian_3.xiuxian.routine.rules import redemption_code_definition


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


async def _enter_alchemy(runtime, user_id: str) -> None:
    commands = (
        "开始修仙",
        "寻仙问道",
        "完成引导 阅读",
        "前往近郊",
        "完成引导 采集",
        "完成引导 炼丹",
        "选择道途 辅修 炼丹",
    )
    for index, command in enumerate(commands):
        result = await runtime.dispatch(_context(user_id, f"alchemy-{index}"), command)
        assert result.ok, (command, result.code, result.message)


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
                redemption_migration = connection.execute(
                    "SELECT migration_key FROM schema_migrations WHERE migration_key = 'routine.redemption.v0.1'"
                ).fetchone()
            assert {"routine_checkins", "spirit_trees", "spirit_tree_waterings", "spirit_tree_harvests"} <= tables
            assert migration == ("routine.v0.1",)
            assert redemption_migration == ("routine.redemption.v0.1",)
            await first.close()
            await second.close()

    asyncio.run(run())


def test_seven_day_campaign_uses_first_seeking_clock_and_claims_one_goal_once() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 1, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            user = "routine-seven-day"
            await _enter_mortal(runtime, user)

            status = await runtime.dispatch(_context(user, "status"), "七日入道")
            assert status.code == "SEVEN_DAY_STATUS"
            assert status.data["start_date"] == "2026-09-01"
            assert status.data["current_day"] == 1
            assert status.data["goals"][1]["state"] == "locked"

            not_done = await runtime.dispatch(
                _context(user, "claim-before", operation_id="seven-before"), "领取七日目标 1"
            )
            assert not_done.code == "SEVEN_DAY_GOAL_NOT_COMPLETED"

            checked = await runtime.dispatch(
                _context(user, "checkin", operation_id="seven-checkin"), "道历问安"
            )
            assert checked.ok
            claimed = await runtime.dispatch(
                _context(user, "claim", operation_id="seven-claim-1"), "领取七日目标 1"
            )
            assert claimed.code == "SEVEN_DAY_GOAL_CLAIMED"
            replay = await runtime.dispatch(
                _context(user, "claim-replay", operation_id="seven-claim-1"), "领取七日目标 1"
            )
            assert replay.ok and replay.data["idempotent_replay"] is True
            conflict = await runtime.dispatch(
                _context(user, "claim-conflict", operation_id="seven-claim-1"), "领取七日目标 2"
            )
            assert conflict.code == "OPERATION_CONFLICT"
            duplicate = await runtime.dispatch(
                _context(user, "claim-duplicate", operation_id="seven-claim-1b"), "领取七日目标 1"
            )
            assert duplicate.code == "SEVEN_DAY_ALREADY_CLAIMED"

            clock.advance(days=1)
            future = await runtime.dispatch(
                _context(user, "future", operation_id="seven-future"), "领取七日目标 3"
            )
            assert future.code == "SEVEN_DAY_GOAL_NOT_OPEN"

            clock.advance(days=4)
            closed = await runtime.dispatch(_context(user, "closed"), "七日入道")
            assert closed.data["current_day"] == 6
            assert closed.data["goals"][4]["state"] == "content_closed"
            assert closed.data["goals"][5]["state"] == "content_closed"
            blocked = await runtime.dispatch(
                _context(user, "tower", operation_id="seven-tower"), "领取七日目标 5"
            )
            assert blocked.code == "SEVEN_DAY_GOAL_NOT_COMPLETED"
            await runtime.close()

    asyncio.run(run())


def test_seven_day_production_preview_is_audited_as_day_three_activity() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 1, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            user = "routine-seven-production"
            await _enter_alchemy(runtime, user)
            clock.advance(days=2)
            preview = await runtime.dispatch(
                _context(user, "preview", operation_id="preview-seven-day"), "生产预览 疗伤丹"
            )
            assert preview.code == "RECIPE_PREVIEW"
            claimed = await runtime.dispatch(
                _context(user, "claim", operation_id="claim-seven-day-3"), "领取七日目标 3"
            )
            assert claimed.code == "SEVEN_DAY_GOAL_CLAIMED"
            assert claimed.data["reward"] == {"spirit_stones": 30}
            with sqlite3.connect(runtime.settings.database_path) as connection:
                event = connection.execute(
                    "SELECT event_key, source_operation_id FROM activity_events WHERE player_id = (SELECT id FROM players WHERE platform_user_id = ?)",
                    (user,),
                ).fetchone()
            assert event == ("production.preview", "preview-seven-day")
            await runtime.close()

    asyncio.run(run())


def test_honor_titles_and_achievements_are_audited_and_idempotent() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            user = "routine-honor"
            await _enter_mortal(runtime, user)

            initial = await runtime.dispatch(_context(user, "honor-status"), "功业录")
            assert initial.code == "HONOR_STATUS"
            assert initial.data["titles"][0]["acquired"] is True
            assert initial.data["achievements"][0]["state"] == "pending"

            equipped = await runtime.dispatch(
                _context(user, "equip-first", operation_id="equip-first"), "佩戴称号 1"
            )
            assert equipped.code == "TITLE_EQUIPPED"
            blocked_read_only = await runtime.dispatch(
                CommandContext(
                    adapter="web",
                    user_id=user,
                    can_write_assets=False,
                ),
                "佩戴称号 1",
            )
            assert blocked_read_only.code == "INVALID_CONTEXT"

            checkin = await runtime.dispatch(
                _context(user, "honor-checkin", operation_id="honor-checkin"), "道历问安"
            )
            assert checkin.ok
            claim = await runtime.dispatch(
                _context(user, "honor-claim", operation_id="honor-claim"), "领取功业 1"
            )
            assert claim.code == "ACHIEVEMENT_CLAIMED"
            assert claim.data["reward"] == {"local_reputation": 3}
            replay = await runtime.dispatch(
                _context(user, "honor-replay", operation_id="honor-claim"), "领取功业 1"
            )
            assert replay.data["idempotent_replay"] is True
            duplicate = await runtime.dispatch(
                _context(user, "honor-duplicate", operation_id="honor-claim-2"), "领取功业 1"
            )
            assert duplicate.code == "ACHIEVEMENT_ALREADY_CLAIMED"

            clock.advance(days=1)
            assert (await runtime.dispatch(_context(user, "daily-2"), "道历问安")).ok
            clock.advance(days=1)
            assert (await runtime.dispatch(_context(user, "daily-3"), "道历问安")).ok
            status = await runtime.dispatch(_context(user, "honor-status-2"), "功业录")
            assert status.data["titles"][1]["acquired"] is True

            closed = await runtime.dispatch(
                _context(user, "closed-achievement", operation_id="closed-achievement"),
                "领取功业 3",
            )
            assert closed.code == "CONTENT_CLOSED"
            await runtime.close()

    asyncio.run(run())


def test_first_craft_achievement_uses_production_operation_source() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            user = "routine-craft-honor"
            await _enter_alchemy(runtime, user)
            started = await runtime.dispatch(
                _context(user, "craft-start", operation_id="craft-start"),
                "开始生产 疗伤丹",
            )
            assert started.code == "PRODUCTION_STARTED"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                old = (datetime.now(timezone.utc) - timedelta(seconds=2)).isoformat()
                connection.execute(
                    "UPDATE production_orders SET starts_at = ?, ends_at = ? WHERE order_id = ?",
                    (old, old, started.data["order_id"]),
                )
            completed = await runtime.dispatch(
                _context(user, "craft-complete", operation_id="craft-complete"),
                "领取生产",
            )
            assert completed.code == "PRODUCTION_COMPLETED"
            claim = await runtime.dispatch(
                _context(user, "craft-claim", operation_id="craft-achievement"),
                "领取功业 2",
            )
            assert claim.code == "ACHIEVEMENT_CLAIMED"
            assert claim.data["reward"] == {"service_reputation": 2}
            await runtime.close()

    asyncio.run(run())


def test_redemption_code_is_hashed_idempotent_and_player_unique() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            code = redemption_code_definition(
                "code.onboarding.v0.1",
                "WELCOME-01",
                {"item.herb.blood_grass": 2},
            )
            settings = XiuxianSettings(data_dir=Path(data_dir), redemption_codes=(code,))
            runtime = create_runtime(settings=settings)
            user = "routine-code"
            await _enter_mortal(runtime, user)

            claimed = await runtime.dispatch(
                _context(user, "code-first", operation_id="code-op"),
                "兑换密令 welcome-01",
            )
            assert claimed.code == "REDEMPTION_CODE_CLAIMED"
            assert claimed.data["reward"] == {"item.herb.blood_grass": 2}
            replay = await runtime.dispatch(
                _context(user, "code-replay", operation_id="code-op"),
                "兑换密令 WELCOME-01",
            )
            assert replay.ok and replay.data["idempotent_replay"] is True
            duplicate = await runtime.dispatch(
                _context(user, "code-duplicate", operation_id="code-op-2"),
                "兑换密令 WELCOME-01",
            )
            assert duplicate.code == "REDEMPTION_CODE_ALREADY_CLAIMED"

            with sqlite3.connect(runtime.settings.database_path) as connection:
                stored = connection.execute(
                    "SELECT code_hash, claimed_count FROM redemption_codes WHERE code_key = ?",
                    (code.code_key,),
                ).fetchone()
                claim = connection.execute(
                    "SELECT code_key, operation_id FROM redemption_claims WHERE player_id = (SELECT id FROM players WHERE platform_user_id = ?)",
                    (user,),
                ).fetchone()
                dump = " ".join(str(row) for row in connection.iterdump())
            assert stored == (code.code_hash, 1)
            assert claim == (code.code_key, "code-op")
            assert "WELCOME-01" not in dump
            await runtime.close()

    asyncio.run(run())


def test_redemption_code_window_revoke_capacity_and_reward_validation() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            limited = redemption_code_definition(
                "code.repair.v0.1",
                "LIMIT-01",
                {"item.mat.array_sand": 1},
                max_claims=1,
            )
            expired = redemption_code_definition(
                "code.expired.v0.1",
                "EXPIRED-01",
                {"item.herb.blood_grass": 1},
                ends_on="2026-09-21",
            )
            revoked = redemption_code_definition(
                "code.revoked.v0.1",
                "REVOKED-01",
                {"item.herb.blood_grass": 1},
                revoked=True,
            )
            settings = XiuxianSettings(
                data_dir=Path(data_dir),
                redemption_codes=(limited, expired, revoked),
            )
            runtime = create_runtime(settings=settings, clock=clock)
            users = ("routine-code-a", "routine-code-b")
            await asyncio.gather(*(_enter_mortal(runtime, user) for user in users))
            results = await asyncio.gather(
                *(
                    runtime.dispatch(
                        _context(user, f"limited-{index}", operation_id=f"limited-{index}"),
                        "兑换密令 LIMIT-01",
                    )
                    for index, user in enumerate(users)
                )
            )
            assert {result.code for result in results} == {
                "REDEMPTION_CODE_CLAIMED",
                "REDEMPTION_CODE_EXHAUSTED",
            }
            expired_result = await runtime.dispatch(
                _context(users[0], "expired", operation_id="expired-op"),
                "兑换密令 EXPIRED-01",
            )
            revoked_result = await runtime.dispatch(
                _context(users[0], "revoked", operation_id="revoked-op"),
                "兑换密令 REVOKED-01",
            )
            assert expired_result.code == "REDEMPTION_CODE_EXPIRED"
            assert revoked_result.code == "REDEMPTION_CODE_REVOKED"
            await runtime.close()

        with pytest.raises(ValueError):
            redemption_code_definition(
                "code.invalid.v0.1",
                "INVALID-01",
                {"cultivation": 1},
            )

    asyncio.run(run())
