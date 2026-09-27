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


def _context(adapter: str, user_id: str, operation_id: str = "") -> CommandContext:
    return CommandContext(adapter=adapter, user_id=user_id, operation_id=operation_id)


async def _mortal(runtime, adapter: str, user_id: str, prefix: str) -> None:
    assert (await runtime.dispatch(_context(adapter, user_id, f"{prefix}-create"), "开始修仙")).ok
    assert (await runtime.dispatch(_context(adapter, user_id, f"{prefix}-seek"), "寻仙问道")).ok


def test_idle_qq_and_onebot_time_window_and_replay() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 27, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            await _mortal(runtime, "qq.official", "qq-idle", "qq")
            await _mortal(runtime, "onebot.v11", "ob-idle", "ob")
            started = await runtime.dispatch(
                _context("qq.official", "qq-idle", "qq-start"), "开始挂机 idle.town_errand"
            )
            assert started.code == "IDLE_STARTED"
            early = await runtime.dispatch(
                _context("qq.official", "qq-idle", "qq-early"), "领取挂机"
            )
            assert early.code == "IDLE_CLAIM_TOO_EARLY"
            clock.advance(hours=2)
            claimed = await runtime.dispatch(
                _context("qq.official", "qq-idle", "qq-claim"), "领取挂机"
            )
            assert claimed.code == "IDLE_CLAIMED"
            replay = await runtime.dispatch(
                _context("qq.official", "qq-idle", "qq-claim"), "领取挂机"
            )
            assert replay.data["idempotent_replay"] is True
            assert replay.data["reward"] == claimed.data["reward"]
            other = await runtime.dispatch(
                _context("qq.official", "qq-idle", "qq-claim-again"), "领取挂机"
            )
            assert other.code == "IDLE_NOT_FOUND"
            ob = await runtime.dispatch(
                _context("onebot.v11", "ob-idle", "ob-start"), "开始挂机 idle.town_errand"
            )
            assert ob.code == "IDLE_STARTED"
            await runtime.close()

    asyncio.run(run())


def test_idle_cancel_refunds_cost_and_late_claim_is_floor() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 27, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            await _mortal(runtime, "qq.official", "idle-cost", "cost")
            with sqlite3.connect(runtime.settings.database_path) as connection:
                player_id = connection.execute(
                    "SELECT id FROM players WHERE platform = 'qq.official' AND platform_user_id = 'idle-cost'"
                ).fetchone()[0]
                now = clock().isoformat()
                connection.execute(
                    "INSERT INTO residences(residence_id, player_id, operation_id, residence_key, status, starts_at, ends_at, rent_cost, created_at, updated_at) VALUES (?, ?, ?, ?, 'active', ?, ?, 0, ?, ?)",
                    ("res-idle", player_id, "res-op", "residence.town_room", now, (clock.value + timedelta(days=1)).isoformat(), now, now),
                )
            start = await runtime.dispatch(
                _context("qq.official", "idle-cost", "herb-start"), "开始挂机 idle.herb_watch"
            )
            assert start.code == "IDLE_STARTED"
            clock.advance(seconds=30)
            cancelled = await runtime.dispatch(
                _context("qq.official", "idle-cost", "herb-cancel"), "取消挂机"
            )
            assert cancelled.code == "IDLE_CANCELLED"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                energy = connection.execute(
                    "SELECT energy FROM players WHERE platform_user_id = 'idle-cost'"
                ).fetchone()[0]
                assert energy == 30

            late = await runtime.dispatch(
                _context("qq.official", "idle-cost", "town-start"), "开始挂机 idle.town_errand"
            )
            assert late.code == "IDLE_STARTED"
            clock.advance(hours=26, seconds=1)
            floor = await runtime.dispatch(
                _context("qq.official", "idle-cost", "town-claim"), "领取挂机"
            )
            assert floor.code == "IDLE_CLAIMED"
            assert floor.data["fallback"] is True
            assert floor.data["reward"] == {"spirit_stones": 8}
            await runtime.close()

    asyncio.run(run())


def test_idle_workshop_tool_snapshot_and_no_forbidden_rewards() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 27, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            await _mortal(runtime, "onebot.v11", "idle-tool", "tool")
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE players SET inventory_json = ?, durability_json = ? WHERE platform = 'onebot.v11' AND platform_user_id = 'idle-tool'",
                    (json.dumps({"item.tool.basic_hammer": 1}), json.dumps({"item.tool.basic_hammer": 10000})),
                )
            started = await runtime.dispatch(
                _context("onebot.v11", "idle-tool", "tool-start"), "开始挂机 idle.workshop_care item.tool.basic_hammer"
            )
            assert started.code == "IDLE_STARTED"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                held = connection.execute(
                    "SELECT inventory_json FROM players WHERE platform_user_id = 'idle-tool'"
                ).fetchone()[0]
                assert "item.tool.basic_hammer" not in json.loads(held)
                snapshot = connection.execute(
                    "SELECT snapshot_json FROM idle_assignments WHERE assignment_id = ?",
                    (started.data["assignment_id"],),
                ).fetchone()[0]
                assert json.loads(snapshot)["random_seed"] != "tool-start"
            clock.advance(hours=3)
            claimed = await runtime.dispatch(
                _context("onebot.v11", "idle-tool", "tool-claim"), "领取挂机"
            )
            assert claimed.code == "IDLE_CLAIMED"
            assert claimed.data["tool_durability_after"] == 9950
            with sqlite3.connect(runtime.settings.database_path) as connection:
                inventory = connection.execute(
                    "SELECT inventory_json FROM players WHERE platform_user_id = 'idle-tool'"
                ).fetchone()[0]
                assert json.loads(inventory)["item.tool.basic_hammer"] == 1
            assert not any(key in claimed.data["reward"] for key in ("cultivation", "total_cultivation"))
            await runtime.close()

    asyncio.run(run())


def test_idle_rejects_unlisted_tool_and_fallback_preserves_durability() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 27, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            await _mortal(runtime, "onebot.v11", "idle-fallback", "fallback")
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE players SET inventory_json = ?, durability_json = ? WHERE platform = 'onebot.v11' AND platform_user_id = 'idle-fallback'",
                    (json.dumps({"item.tool.unlisted": 1}), json.dumps({"item.tool.unlisted": 10000})),
                )
            rejected = await runtime.dispatch(
                _context("onebot.v11", "idle-fallback", "bad-tool"),
                "开始挂机 idle.workshop_care item.tool.unlisted",
            )
            assert rejected.code == "IDLE_REQUIREMENT_MISSING"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                inventory = connection.execute(
                    "SELECT inventory_json FROM players WHERE platform_user_id = 'idle-fallback'"
                ).fetchone()[0]
                assert json.loads(inventory)["item.tool.unlisted"] == 1
                connection.execute(
                    "UPDATE players SET inventory_json = ?, durability_json = ? WHERE platform = 'onebot.v11' AND platform_user_id = 'idle-fallback'",
                    (json.dumps({"item.tool.basic_hammer": 1}), json.dumps({"item.tool.basic_hammer": 10000})),
                )
            started = await runtime.dispatch(
                _context("onebot.v11", "idle-fallback", "valid-tool"),
                "开始挂机 idle.workshop_care item.tool.basic_hammer",
            )
            assert started.code == "IDLE_STARTED"
            cancelled = await runtime.dispatch(
                _context("onebot.v11", "idle-fallback", "cancel-tool"), "取消挂机"
            )
            assert cancelled.code == "IDLE_CANCELLED"
            assert cancelled.data["returned_tool_key"] == "item.tool.basic_hammer"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                inventory = connection.execute(
                    "SELECT inventory_json FROM players WHERE platform_user_id = 'idle-fallback'"
                ).fetchone()[0]
                assert json.loads(inventory)["item.tool.basic_hammer"] == 1
            started = await runtime.dispatch(
                _context("onebot.v11", "idle-fallback", "fallback-tool"),
                "开始挂机 idle.workshop_care item.tool.basic_hammer",
            )
            assert started.code == "IDLE_STARTED"
            clock.advance(hours=28)
            claimed = await runtime.dispatch(
                _context("onebot.v11", "idle-fallback", "fallback-claim"), "领取挂机"
            )
            assert claimed.code == "IDLE_CLAIMED"
            assert claimed.data["fallback"] is True
            assert claimed.data["tool_durability_before"] == claimed.data["tool_durability_after"] == 10000
            with sqlite3.connect(runtime.settings.database_path) as connection:
                durability = connection.execute(
                    "SELECT durability_json FROM players WHERE platform_user_id = 'idle-fallback'"
                ).fetchone()[0]
                inventory = connection.execute(
                    "SELECT inventory_json FROM players WHERE platform_user_id = 'idle-fallback'"
                ).fetchone()[0]
                assert json.loads(durability)["item.tool.basic_hammer"] == 10000
                assert json.loads(inventory)["item.tool.basic_hammer"] == 1
            await runtime.close()

    asyncio.run(run())


def test_idle_facility_lock_excludes_production_reservation() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 27, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            await _mortal(runtime, "qq.official", "idle-facility", "facility")
            with sqlite3.connect(runtime.settings.database_path) as connection:
                player_id = connection.execute(
                    "SELECT id FROM players WHERE platform_user_id = 'idle-facility'"
                ).fetchone()[0]
                now = clock().isoformat()
                connection.execute(
                    "UPDATE players SET location_key = 'cave.mist_grotto_2' WHERE id = ?", (player_id,)
                )
                connection.execute(
                    "UPDATE production_facility_slots SET owner_type = 'personal', owner_id = ?, status = 'active', updated_at = ? WHERE slot_key = 'facility.artifice_table.1'",
                    (str(player_id), now),
                )
            started = await runtime.dispatch(
                _context("qq.official", "idle-facility", "facility-start"), "开始挂机 idle.workshop_care facility.artifice_table.1"
            )
            assert started.code == "IDLE_STARTED"
            assert started.data["facility_slot_key"] == "facility.artifice_table.1"
            with runtime.repository._connect() as connection:
                player = connection.execute(
                    "SELECT * FROM players WHERE platform_user_id = 'idle-facility'"
                ).fetchone()
                from nonebot_plugin_xiuxian_3.xiuxian.production.rules import recipe_definition
                from nonebot_plugin_xiuxian_3.xiuxian.persistence.errors import FacilitySlotOccupiedError

                try:
                    runtime.repository._facility_reserve_for_recipe(
                    connection, player, recipe_definition("recipe.weapon.cloud_sword")
                )
                except FacilitySlotOccupiedError:
                    pass
                else:
                    raise AssertionError("idle did not reserve its facility slot")
            await runtime.close()

    asyncio.run(run())
