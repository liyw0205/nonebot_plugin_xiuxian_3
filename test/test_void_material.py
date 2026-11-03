from __future__ import annotations

import asyncio
import json
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from urllib.parse import unquote

from nonebot_plugin_xiuxian_3.adapters.message.markdown import (
    markdown_to_text,
    send_markdown_message,
)
from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime

ITEM = "item.void_crystal"
ITEM_LABEL = "虚空晶体"


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


async def _create(
    runtime,
    user: str,
    *,
    realm: str = "void_refining",
    layer: int = 1,
    stones: int = 5000,
    items: dict[str, int] | None = None,
    merit: int = 0,
) -> int:
    assert (await _send(runtime, user, "开始修仙")).ok
    assert (await _send(runtime, user, "寻仙问道")).ok
    values = {
        "realm_key": realm,
        "realm_layer": layer,
        "spirit_stones": stones,
        "void_merit": merit,
        "inventory_json": json.dumps(items if items is not None else {ITEM: 5}),
    }
    assignments = ", ".join(f"{key}=?" for key in values)
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            f"UPDATE players SET {assignments} WHERE platform='onebot.v11' AND platform_user_id=?",
            (*values.values(), user),
        )
        return int(
            connection.execute(
                "SELECT id FROM players WHERE platform='onebot.v11' AND platform_user_id=?", (user,)
            ).fetchone()[0]
        )


def _player(runtime, player_id: int):
    with sqlite3.connect(runtime.settings.database_path) as connection:
        row = connection.execute(
            "SELECT spirit_stones, inventory_json FROM players WHERE id = ?", (player_id,)
        ).fetchone()
    return row[0], json.loads(row[1])


def _statuses(runtime) -> list[str]:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        return [
            row[0]
            for row in connection.execute(
                "SELECT status FROM void_material_listings ORDER BY created_at, listing_id"
            ).fetchall()
        ]


def test_admission_and_whitelist_rejections_write_nothing() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 11, 3, 5, 0, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            try:
                low_id = await _create(runtime, "low", realm="qi_sensing", layer=3, merit=499)
                board = await _send(runtime, "low", "虚空寄售")
                assert board.ok and board.code == "VOID_MATERIAL_BOARD"
                assert board.data["qualified"] is False
                assert len(board.data["missing"]) == 2
                assert board.actions == ()

                blocked = await _send(runtime, "low", f"寄售物资 {ITEM_LABEL} 1 100", "l-1")
                assert not blocked.ok and blocked.code == "VOID_MARKET_ADMISSION"
                assert _statuses(runtime) == []
                assert _player(runtime, low_id) == (5000, {ITEM: 5})

                # Merit alone is enough even at a low realm.
                await _create(runtime, "merited", realm="qi_sensing", layer=3, merit=500)
                allowed = await _send(runtime, "merited", f"寄售物资 {ITEM_LABEL} 1 100", "l-2")
                assert allowed.ok and allowed.code == "VOID_MATERIAL_LISTED"

                # An item outside the whitelist never reaches the listing table.
                forbidden = await _send(runtime, "merited", "寄售物资 木材 1 100", "l-3")
                assert not forbidden.ok and forbidden.code == "VOID_MARKET_ITEM_FORBIDDEN"
                assert len(_statuses(runtime)) == 1
            finally:
                await runtime.close()

    asyncio.run(run())


def test_listing_locks_items_and_respects_the_cap() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 11, 3, 5, 0, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            try:
                player_id = await _create(runtime, "seller", items={ITEM: 12})

                listed = await _send(runtime, "seller", f"寄售物资 {ITEM_LABEL} 2 100", "l-1")
                assert listed.ok and listed.code == "VOID_MATERIAL_LISTED"
                assert listed.data["quantity"] == 2
                # The listed copies leave the inventory: they are locked, not copied.
                assert _player(runtime, player_id) == (5000, {ITEM: 10})

                too_many = await _send(runtime, "seller", f"寄售物资 {ITEM_LABEL} 99 100", "l-2")
                assert not too_many.ok and too_many.code == "VOID_MARKET_NOT_ENOUGH_ITEMS"
                assert _player(runtime, player_id) == (5000, {ITEM: 10})

                for index in range(3, 7):
                    ok = await _send(runtime, "seller", f"寄售物资 {ITEM_LABEL} 1 10", f"l-{index}")
                    assert ok.ok, ok
                capped = await _send(runtime, "seller", f"寄售物资 {ITEM_LABEL} 1 10", "l-7")
                assert not capped.ok and capped.code == "VOID_MARKET_LIMIT"
                assert len(_statuses(runtime)) == 5
            finally:
                await runtime.close()

    asyncio.run(run())


def test_purchase_moves_items_and_splits_the_fee() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 11, 3, 5, 0, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            try:
                seller_id = await _create(runtime, "seller", items={ITEM: 4}, stones=5000)
                buyer_id = await _create(runtime, "buyer", items={}, stones=1000)
                assert (await _send(runtime, "seller", f"寄售物资 {ITEM_LABEL} 2 100", "l-1")).ok

                own = await _send(runtime, "seller", "购入寄售 1", "b-own")
                assert not own.ok and own.code == "VOID_MARKET_OWN_LISTING"

                bought = await _send(runtime, "buyer", "购入寄售 1", "b-1")
                assert bought.ok and bought.code == "VOID_MATERIAL_BOUGHT"
                assert bought.data["gross"] == 200
                assert bought.data["fee"] == 16
                assert bought.data["net"] == 184
                # The fee leaves the economy: buyer -200, seller +184.
                assert _player(runtime, buyer_id) == (800, {ITEM: 2})
                assert _player(runtime, seller_id) == (5184, {ITEM: 2})

                gone = await _send(runtime, "buyer", "购入寄售 1", "b-2")
                assert not gone.ok and gone.code == "VOID_MARKET_NOT_FOUND"
            finally:
                await runtime.close()

    asyncio.run(run())


def test_insufficient_funds_leaves_the_listing_open() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 11, 3, 5, 0, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            try:
                await _create(runtime, "seller", items={ITEM: 2})
                poor_id = await _create(runtime, "poor", items={}, stones=10)
                assert (await _send(runtime, "seller", f"寄售物资 {ITEM_LABEL} 2 100", "l-1")).ok

                refused = await _send(runtime, "poor", "购入寄售 1", "b-1")
                assert not refused.ok and refused.code == "VOID_MARKET_INSUFFICIENT"
                assert _statuses(runtime) == ["listed"]
                assert _player(runtime, poor_id) == (10, {})
            finally:
                await runtime.close()

    asyncio.run(run())


def test_cancel_and_expiry_return_the_items() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 11, 3, 5, 0, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            try:
                seller_id = await _create(runtime, "seller", items={ITEM: 4})

                assert (await _send(runtime, "seller", f"寄售物资 {ITEM_LABEL} 1 50", "l-1")).ok
                assert _player(runtime, seller_id) == (5000, {ITEM: 3})
                cancelled = await _send(runtime, "seller", "撤下寄售 1", "c-1")
                assert cancelled.ok and cancelled.code == "VOID_MATERIAL_CANCELLED"
                assert _player(runtime, seller_id) == (5000, {ITEM: 4})
                again = await _send(runtime, "seller", "撤下寄售 1", "c-2")
                assert not again.ok and again.code == "VOID_MARKET_NOT_FOUND"

                # Expiry is lazy: the browse path closes the listing and refunds.
                assert (await _send(runtime, "seller", f"寄售物资 {ITEM_LABEL} 2 50", "l-2")).ok
                assert _player(runtime, seller_id) == (5000, {ITEM: 2})
                clock.advance(hours=7)
                board = await _send(runtime, "seller", "虚空寄售")
                assert board.ok and board.data["listings"] == []
                assert _player(runtime, seller_id) == (5000, {ITEM: 4})
                assert sorted(_statuses(runtime)) == ["cancelled", "expired"]
            finally:
                await runtime.close()

    asyncio.run(run())


def test_replay_is_idempotent_and_survives_restart() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 11, 3, 5, 0, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            try:
                seller_id = await _create(runtime, "seller", items={ITEM: 4})
                first = await _send(runtime, "seller", f"寄售物资 {ITEM_LABEL} 1 100", "l-1")
                assert first.ok
                replay = await _send(runtime, "seller", f"寄售物资 {ITEM_LABEL} 1 100", "l-1")
                assert replay.ok and replay.data["listing_id"] == first.data["listing_id"]
                assert _player(runtime, seller_id) == (5000, {ITEM: 3})
                assert len(_statuses(runtime)) == 1
            finally:
                await runtime.close()

            reopened = create_runtime(data_dir=data_dir, clock=clock)
            try:
                board = await _send(reopened, "seller", "虚空寄售")
                assert board.ok
                assert len(board.data["listings"]) == 1
                assert board.data["listings"][0]["item_key"] == ITEM
            finally:
                await reopened.close()

    asyncio.run(run())


def test_rendering_and_help() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 11, 3, 5, 0, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            try:
                await _create(runtime, "seller", items={ITEM: 3})
                empty_before = await _send(runtime, "seller", "虚空寄售")
                assert empty_before.actions == ()

                assert (await _send(runtime, "seller", f"寄售物资 {ITEM_LABEL} 1 100", "l-1")).ok
                page = await _send(runtime, "seller", "虚空寄售")
                assert page.ok
                assert [action.label for action in page.actions] == ["购入第一单"]
                links = [
                    unquote(match.group(1))
                    for match in re.finditer(r"command:([^)]+)", page.message)
                ]
                assert "购入寄售 1" in links
                text = markdown_to_text(page.message)
                assert "command:" not in text
                assert "item.void_crystal" not in page.message

                bot = FakeBot()
                fallback = await send_markdown_message(
                    bot,
                    SimpleNamespace(),
                    page.message,
                    capabilities=("text",),
                    actions=page.actions,
                )
                assert fallback.sent_format == "text" and fallback.degraded is True
                assert str(bot.sent[0]).endswith("可发送：购入寄售 1")

                class FakeQQBot(FakeBot):
                    __module__ = "nonebot.adapters.qq.bot"

                class FakeQQEvent:
                    __module__ = "nonebot.adapters.qq.event"

                qq_bot = FakeQQBot()
                native = await send_markdown_message(
                    qq_bot,
                    FakeQQEvent(),
                    page.message,
                    capabilities=("markdown", "keyboard"),
                    actions=page.actions,
                )
                assert native.sent_format == "markdown+keyboard", native
                assert "keyboard" in str(qq_bot.sent[0])

                help_page = await _send(runtime, "seller", "修仙帮助 生活")
                assert help_page.code == "HELP_CATEGORY"
                assert "虚空寄售" in help_page.message
                assert not help_page.actions
            finally:
                await runtime.close()

    asyncio.run(run())