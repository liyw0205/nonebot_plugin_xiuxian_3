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


async def _enter_cultivator(runtime, user_id: str) -> None:
    commands = (
        "开始修仙",
        "寻仙问道",
        "完成引导 阅读",
        "前往近郊",
        "完成引导 采集",
        "完成引导 炼丹",
        "选择道途 体修",
    )
    for index, command in enumerate(commands):
        result = await runtime.dispatch(_context(user_id, f"setup-{index}"), command)
        assert result.ok, (command, result.code, result.message)


def _finish_retreat(runtime, session_id: str, *, clock: MutableClock, hours_ago: int = 0) -> None:
    now = clock.value - timedelta(hours=hours_ago, seconds=1)
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE retreat_sessions SET ends_at = ? WHERE session_id = ?",
            (now.isoformat(), session_id),
        )


def _set_player(runtime, user_id: str, *, spirit_stones: int | None = None, energy: int | None = None) -> None:
    updates: list[str] = []
    values: list[object] = []
    if spirit_stones is not None:
        updates.append("spirit_stones = ?")
        values.append(spirit_stones)
    if energy is not None:
        updates.append("energy = ?")
        values.append(energy)
    if not updates:
        return
    values.append(user_id)
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            f"UPDATE players SET {', '.join(updates)} WHERE platform_user_id = ?",
            values,
        )


def test_basic_retreat_locks_cultivation_and_replays_settlement() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            user = "retreat-basic"
            await _enter_cultivator(runtime, user)

            started = await runtime.dispatch(
                _context(user, "start", operation_id="retreat-start"), "开始闭关 基础"
            )
            assert started.code == "RETREAT_STARTED"
            assert started.data["energy_cost"] == 4
            assert started.data["item_cost"] == {"item.food.coarse_spirit_rice": 1}

            busy = await runtime.dispatch(_context(user, "cultivation"), "开始修炼")
            assert busy.code == "CULTIVATION_BUSY"

            _finish_retreat(runtime, started.data["session_id"], clock=clock)
            settled = await runtime.dispatch(
                _context(user, "settle", operation_id="retreat-settle"), "结算闭关"
            )
            assert settled.code == "RETREAT_SETTLED"
            assert settled.data["result"]["cultivation"] in {80, 100, 120}
            replay = await runtime.dispatch(
                _context(user, "replay", operation_id="retreat-settle"), "结算闭关"
            )
            assert replay.code == "RETREAT_SETTLED"
            assert replay.data["idempotent_replay"] is True
            assert replay.data["result"] == settled.data["result"]
            await runtime.close()

    asyncio.run(run())


def test_basic_retreat_daily_limit_and_expired_recovery() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            user = "retreat-limits"
            await _enter_cultivator(runtime, user)

            for index in range(3):
                started = await runtime.dispatch(
                    _context(user, f"start-{index}", operation_id=f"retreat-{index}"), "开始闭关"
                )
                assert started.code == "RETREAT_STARTED"
                _finish_retreat(runtime, started.data["session_id"], clock=clock)
                settled = await runtime.dispatch(
                    _context(user, f"settle-{index}", operation_id=f"settle-{index}"), "结算闭关"
                )
                assert settled.ok
            limited = await runtime.dispatch(_context(user, "limited"), "开始闭关")
            assert limited.code == "RETREAT_DAILY_LIMIT"
            await runtime.close()

        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            user = "retreat-expired"
            await _enter_cultivator(runtime, user)
            started = await runtime.dispatch(
                _context(user, "start-expired", operation_id="retreat-expired-start"), "开始闭关"
            )
            assert started.ok
            clock.advance(hours=27)
            expired = await runtime.dispatch(_context(user, "expired"), "结算闭关")
            assert expired.code == "RETREAT_EXPIRED"
            recovered = await runtime.dispatch(
                _context(user, "recover", operation_id="retreat-recover"), "恢复闭关"
            )
            assert recovered.code == "RETREAT_RECOVERED"
            assert recovered.data["expired"] is True
            replay = await runtime.dispatch(
                _context(user, "recover-replay", operation_id="retreat-recover"), "恢复闭关"
            )
            assert replay.data["idempotent_replay"] is True
            await runtime.close()

    asyncio.run(run())


def test_residence_rent_and_restful_retreat() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            user = "retreat-restful"
            await runtime.dispatch(_context(user, "create"), "开始修仙")
            await runtime.dispatch(_context(user, "seek"), "寻仙问道")
            leased = await runtime.dispatch(
                _context(user, "lease", operation_id="lease-1"), "租住居所"
            )
            assert leased.code == "RESIDENCE_LEASED"
            assert leased.data["rent_cost"] == 20
            duplicate = await runtime.dispatch(_context(user, "duplicate"), "租住居所")
            assert duplicate.code == "RESIDENCE_ALREADY_ACTIVE"

            started = await runtime.dispatch(
                _context(user, "rest-start", operation_id="rest-start"), "开始闭关 静养"
            )
            assert started.code == "RETREAT_STARTED"
            assert started.data["energy_cost"] == 2
            profile = await runtime.dispatch(_context(user, "profile"), "我的居所")
            assert profile.code == "RESIDENCE_PROFILE"
            clock.advance(hours=4)
            settled = await runtime.dispatch(
                _context(user, "rest-settle", operation_id="rest-settle"), "结算闭关"
            )
            assert settled.code == "RETREAT_SETTLED"
            assert settled.data["result"] == {"energy": 8}
            assert "cultivation" not in settled.data["result"]

            clock.advance(days=4)
            _set_player(runtime, user, spirit_stones=0)
            poor = await runtime.dispatch(_context(user, "lease-poor"), "租住居所")
            assert poor.code == "CURRENCY_INSUFFICIENT"
            await runtime.close()

    asyncio.run(run())


def test_retreat_snapshot_keeps_item_cost_structured() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            user = "retreat-snapshot"
            await _enter_cultivator(runtime, user)
            started = await runtime.dispatch(_context(user, "start"), "开始闭关")
            assert started.ok
            with sqlite3.connect(runtime.settings.database_path) as connection:
                snapshot = connection.execute(
                    "SELECT snapshot_json FROM retreat_sessions WHERE session_id = ?",
                    (started.data["session_id"],),
                ).fetchone()[0]
            payload = json.loads(snapshot)
            assert payload["content_version"] == "content-0.1"
            assert payload["rule_version"] == "advancement-0.1.0"
            assert payload["item_cost"] == {"item.food.coarse_spirit_rice": 1}
            await runtime.close()

    asyncio.run(run())


def test_basic_retreat_requires_the_frozen_manual() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            user = "retreat-manual"
            await _enter_cultivator(runtime, user)
            with sqlite3.connect(runtime.settings.database_path) as connection:
                row = connection.execute(
                    "SELECT inventory_json FROM players WHERE platform_user_id = ?", (user,)
                ).fetchone()
                inventory = json.loads(row[0])
                inventory.pop("item.manual.basic_qi", None)
                connection.execute(
                    "UPDATE players SET inventory_json = ? WHERE platform_user_id = ?",
                    (json.dumps(inventory, ensure_ascii=False, sort_keys=True), user),
                )
            result = await runtime.dispatch(_context(user, "start"), "开始闭关")
            assert result.code == "RESOURCE_INSUFFICIENT"
            await runtime.close()

    asyncio.run(run())
