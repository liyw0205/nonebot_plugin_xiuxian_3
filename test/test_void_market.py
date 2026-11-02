from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from nonebot_plugin_xiuxian_3.adapters.message.markdown import (
    markdown_to_text,
    send_markdown_message,
)
from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime

MARKET_LOCATION = "void.void_market"
CRYSTAL = "offer.void_market.void_crystal"
ANCHOR = "offer.void_market.void_anchor"
TIME_TRACE = "offer.void_market.time_trace"


class MutableClock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value

    def advance(self, **kwargs: int) -> None:
        self.value += timedelta(**kwargs)


class FakeBot:
    def __init__(self) -> None:
        self.sent: list[object] = []

    async def send(self, *, event: object, message: object, **kwargs: object) -> dict[str, str]:
        self.sent.append(message)
        return {"message_id": "reply-1"}


def _context(user: str, operation: str = "") -> CommandContext:
    return CommandContext(adapter="onebot.v11", user_id=user, operation_id=operation)


async def _send(runtime, user: str, text: str, operation: str = ""):
    return await runtime.adapters.dispatch("onebot.v11", _context(user, operation), text)


async def _create_player(runtime, user: str, **fields) -> None:
    assert (await _send(runtime, user, "开始修仙")).ok
    assert (await _send(runtime, user, "寻仙问道")).ok
    values = {
        "stage": "cultivator",
        "realm_key": "void_refining",
        "realm_layer": 1,
        "location_key": MARKET_LOCATION,
        "spirit_stones": 60000,
        "void_merit": 1200,
        **fields,
    }
    assignments = ", ".join(f"{key}=?" for key in values)
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            f"UPDATE players SET {assignments} WHERE platform='onebot.v11' AND platform_user_id=?",
            (*values.values(), user),
        )


def _player(runtime, user: str):
    with sqlite3.connect(runtime.settings.database_path) as connection:
        return connection.execute(
            "SELECT spirit_stones, inventory_json, location_key, void_merit "
            "FROM players WHERE platform='onebot.v11' AND platform_user_id=?",
            (user,),
        ).fetchone()


def _stock(runtime, offer_key: str, week_id: str) -> int:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        row = connection.execute(
            "SELECT COALESCE(SUM(quantity), 0) FROM void_market_purchases "
            "WHERE offer_key=? AND week_id=?",
            (offer_key, week_id),
        ).fetchone()
    return int(row[0])


def _count(runtime, table: str) -> int:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def test_market_preview_and_purchase_settle_real_assets() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 11, 3, 4, 0, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            try:
                await _create_player(runtime, "buyer")
                operations_before = _count(runtime, "operations")
                preview = await _send(runtime, "buyer", "虚空集市")
                assert preview.code == "VOID_MARKET_PREVIEW", preview
                assert preview.data["at_market"] is True
                assert preview.data["qualified"] is True
                assert preview.data["week_id"] == "2026-11-02"
                assert preview.data["stock_remaining"] == 20
                assert preview.data["daily_used"] == 0
                assert "购买虚空物资 虚空晶体" in markdown_to_text(preview.message)
                assert "command:" in preview.message
                assert "offer.void_market" not in preview.message
                assert not preview.actions

                # Preview is read-only: no new operations and no stock movement.
                assert _count(runtime, "operations") == operations_before
                assert _stock(runtime, CRYSTAL, "2026-11-02") == 0

                before = _player(runtime, "buyer")
                bought = await _send(runtime, "buyer", "购买虚空物资 虚晶", "buy-crystal")
                assert bought.code == "VOID_MARKET_PURCHASED", bought
                assert bought.data["quantity"] == 1
                assert bought.data["total_cost"] == 12000
                assert bought.data["remaining"] == 3
                assert bought.data["daily_used"] == 1
                assert bought.data["idempotent_replay"] is False
                assert "虚空晶体 ×1" in bought.message
                assert "灵石 ×12000" in bought.message
                assert "item.void_crystal" not in bought.message
                assert bought.actions and bought.actions[0].command == "虚空集市"

                after = _player(runtime, "buyer")
                assert after[0] == before[0] - 12000
                inventory = json.loads(after[1])
                assert inventory["item.void_crystal"] == 1
                assert _stock(runtime, CRYSTAL, "2026-11-02") == 1
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    binding = connection.execute(
                        "SELECT item_key, quantity, bound_until FROM void_market_item_bindings"
                    ).fetchone()
                    ledger = connection.execute(
                        "SELECT asset_kind, direction, amount FROM economy_ledger_entries "
                        "WHERE operation_id='buy-crystal' ORDER BY id"
                    ).fetchall()
                assert binding[0] == "item.void_crystal"
                assert binding[1] == 1
                assert binding[2] == "2026-11-04T04:00:00+00:00"
                assert ("currency", "debit", 12000) in ledger
                assert ("item", "credit", 1) in ledger

                replay = await _send(runtime, "buyer", "购买虚空物资 虚晶", "buy-crystal")
                assert replay.code == "VOID_MARKET_PURCHASED"
                assert replay.data["idempotent_replay"] is True
                assert replay.data["remaining"] == 3
                assert _player(runtime, "buyer")[0] == after[0]
                assert _stock(runtime, CRYSTAL, "2026-11-02") == 1

                conflict = await _send(runtime, "buyer", "购买虚空物资 虚空锚", "buy-crystal")
                assert conflict.code == "LEDGER_CONFLICT"
                assert _player(runtime, "buyer")[0] == after[0]

                single = await _send(runtime, "buyer", "虚空集市 时痕草")
                assert single.code == "VOID_MARKET_PREVIEW"
                assert single.data["selected"] == TIME_TRACE
                assert single.actions and single.actions[0].command == "购买虚空物资 时痕草"
                assert "3000" in single.message
                missing = await _send(runtime, "buyer", "虚空集市 不存在之物")
                assert missing.code == "VOID_MARKET_OFFER_NOT_FOUND"
                too_many = await _send(runtime, "buyer", "虚空集市 时痕草 虚空锚")
                assert too_many.code == "INVALID_VOID_MARKET_COMMAND"
            finally:
                await runtime.close()

    asyncio.run(run())


def test_daily_cap_weekly_stock_and_refresh_boundaries() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 11, 3, 4, 0, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            try:
                await _create_player(runtime, "capped", spirit_stones=200000)
                first = await _send(runtime, "capped", "购买虚空物资 虚晶", "cap-1")
                second = await _send(runtime, "capped", "购买虚空物资 虚晶", "cap-2")
                third = await _send(runtime, "capped", "购买虚空物资 虚空锚", "cap-3")
                assert first.ok and second.ok and third.ok
                blocked = await _send(runtime, "capped", "购买虚空物资 时痕草", "cap-4")
                assert blocked.code == "VOID_DAILY_PURCHASE_CAP"
                assert "未扣除任何资源" in blocked.message
                stones = _player(runtime, "capped")[0]
                assert stones == 200000 - 12000 - 12000 - 5000
                assert _stock(runtime, CRYSTAL, "2026-11-02") == 2

                # The daily cap is a UTC business-date boundary, not a rolling window.
                clock.advance(days=1)
                next_day = await _send(runtime, "capped", "虚空集市")
                assert next_day.data["daily_used"] == 0
                resumed = await _send(runtime, "capped", "购买虚空物资 虚晶", "cap-5")
                assert resumed.ok, resumed
                assert resumed.data["daily_used"] == 1
                assert resumed.data["remaining"] == 1

                # Weekly stock is shared: the fourth crystal exhausts the pool.
                clock.advance(days=1)
                last = await _send(runtime, "capped", "购买虚空物资 虚晶", "cap-6")
                assert last.ok and last.data["remaining"] == 0
                sold_out = await _send(runtime, "capped", "购买虚空物资 晶体", "cap-7")
                assert sold_out.code == "VOID_STOCK_SOLD_OUT"
                assert "未扣除任何资源" in sold_out.message
                stones_before = _player(runtime, "capped")[0]
                assert _stock(runtime, CRYSTAL, "2026-11-02") == 4
                assert stones_before == 200000 - 12000 * 3 - 12000 - 5000

                # Weekly refresh restores every slot and resets the daily counter.
                clock.value = datetime(2026, 11, 9, 0, 0, tzinfo=timezone.utc)
                refreshed = await _send(runtime, "capped", "虚空集市")
                assert refreshed.data["week_id"] == "2026-11-09"
                assert refreshed.data["stock_remaining"] == 20
                assert refreshed.data["daily_used"] == 0
                restocked = next(
                    offer for offer in refreshed.data["offers"] if offer["key"] == CRYSTAL
                )
                assert restocked["remaining"] == 4
                assert (await _send(runtime, "capped", "购买虚空物资 虚晶", "cap-8")).ok
            finally:
                await runtime.close()

    asyncio.run(run())


def test_gate_and_failures_never_write() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 11, 3, 4, 0, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            try:
                await _create_player(runtime, "away", location_key="void.first_route")
                away_preview = await _send(runtime, "away", "虚空集市")
                assert away_preview.data["at_market"] is False
                assert "虚空集市" in away_preview.message
                assert "进入虚空航道" in away_preview.message
                away = await _send(runtime, "away", "购买虚空物资 虚晶", "gate-away")
                assert away.code == "VOID_MARKET_REQUIREMENT_MISSING"
                assert "未扣除任何资源" in away.message

                await _create_player(
                    runtime,
                    "weak",
                    realm_key="nascent_soul",
                    realm_layer=9,
                    void_merit=499,
                )
                weak_preview = await _send(runtime, "weak", "虚空集市")
                assert weak_preview.data["qualified"] is False
                assert weak_preview.data["missing"]
                weak = await _send(runtime, "weak", "购买虚空物资 虚晶", "gate-weak")
                assert weak.code == "VOID_MARKET_REQUIREMENT_MISSING"
                assert "虚空功勋 500" in weak.message

                # The merit branch alone satisfies the gate.
                await _create_player(
                    runtime,
                    "merited",
                    realm_key="nascent_soul",
                    realm_layer=9,
                    void_merit=500,
                )
                merited = await _send(runtime, "merited", "购买虚空物资 时花", "gate-merit")
                assert merited.ok, merited
                assert merited.data["item_key"] == "item.herb.time_trace"

                await _create_player(runtime, "broke", spirit_stones=100)
                broke = await _send(runtime, "broke", "购买虚空物资 虚晶", "gate-broke")
                assert broke.code == "BALANCE_INSUFFICIENT"
                assert "需要 12000 灵石" in broke.message
                assert _stock(runtime, CRYSTAL, "2026-11-02") == 0
                assert _player(runtime, "broke")[0] == 100

                for command, code in (
                    ("购买虚空物资", "INVALID_VOID_MARKET_COMMAND"),
                    ("购买虚空物资 不存在", "VOID_MARKET_OFFER_NOT_FOUND"),
                    ("购买虚空物资 虚晶 0", "INVALID_VOID_MARKET_COMMAND"),
                    ("购买虚空物资 虚晶 四", "INVALID_VOID_MARKET_COMMAND"),
                    ("购买虚空物资 虚晶 4", "INVALID_VOID_MARKET_COMMAND"),
                ):
                    rejected = await _send(runtime, "merited", command, f"reject-{command}")
                    assert rejected.code == code, (command, rejected)
                assert _stock(runtime, CRYSTAL, "2026-11-02") == 0
                assert _stock(runtime, TIME_TRACE, "2026-11-02") == 1

                stranger = await _send(runtime, "no-such-player", "虚空集市")
                assert stranger.code == "PLAYER_NOT_FOUND"
            finally:
                await runtime.close()

    asyncio.run(run())


def test_market_state_survives_restart_and_replays_after_reopen() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 11, 3, 4, 0, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            try:
                await _create_player(runtime, "restart")
                first = await _send(runtime, "restart", "购买虚空物资 虚空锚", "restart-buy")
                assert first.ok, first
                stones = _player(runtime, "restart")[0]
            finally:
                await runtime.close()

            reopened = create_runtime(data_dir=data_dir, clock=clock)
            try:
                preview = await _send(reopened, "restart", "虚空集市")
                assert preview.data["daily_used"] == 1
                assert preview.data["stock_remaining"] == 19
                assert next(
                    offer for offer in preview.data["offers"] if offer["key"] == ANCHOR
                )["remaining"] == 7
                replay = await _send(reopened, "restart", "购买虚空物资 虚空锚", "restart-buy")
                assert replay.code == "VOID_MARKET_PURCHASED"
                assert replay.data["idempotent_replay"] is True
                assert _player(reopened, "restart")[0] == stones
                assert _stock(reopened, ANCHOR, "2026-11-02") == 1
            finally:
                await reopened.close()

    asyncio.run(run())


def test_adapter_rendering_keeps_blue_links_and_onebot_fallback() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 11, 3, 4, 0, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            try:
                await _create_player(runtime, "render")
                preview = await _send(runtime, "render", "虚空集市")
                single = await _send(runtime, "render", "虚空集市 虚晶")
                assert preview.actions == ()
                assert single.actions and single.actions[0].label == "购买此物资"

                from urllib.parse import unquote

                links = [
                    unquote(match.group(1))
                    for match in __import__("re").finditer(r"command:([^)]+)", preview.message)
                ]
                assert links and all(link.startswith("购买虚空物资 ") for link in links)
                text = markdown_to_text(preview.message)
                assert "购买虚空物资 虚空晶体" in text
                assert "command:" not in text

                bot = FakeBot()
                fallback = await send_markdown_message(
                    bot,
                    SimpleNamespace(),
                    single.message,
                    capabilities=("text",),
                    actions=single.actions,
                )
                assert fallback.sent_format == "text" and fallback.degraded is True
                assert str(bot.sent[0]).endswith("可发送：购买虚空物资 虚空晶体")
                assert "command:" not in str(bot.sent[0])

                class FakeQQBot(FakeBot):
                    __module__ = "nonebot.adapters.qq.bot"

                class FakeQQEvent:
                    __module__ = "nonebot.adapters.qq.event"

                qq_bot = FakeQQBot()
                native = await send_markdown_message(
                    qq_bot,
                    FakeQQEvent(),
                    single.message,
                    capabilities=("markdown", "keyboard"),
                    actions=single.actions,
                )
                assert native.sent_format == "markdown+keyboard", native
                assert native.degraded is False
                assert "keyboard" in str(qq_bot.sent[0])

                help_page = await _send(runtime, "render", "修仙帮助 生活")
                assert help_page.code == "HELP_CATEGORY"
                assert "虚空集市" in help_page.message
                assert "购买虚空物资 虚空晶体" in markdown_to_text(help_page.message)
                assert not help_page.actions
            finally:
                await runtime.close()

    asyncio.run(run())
