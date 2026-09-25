from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
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


def _context(adapter: str, user: str, request: str, operation: str = "") -> CommandContext:
    return CommandContext(
        adapter=adapter,
        user_id=user,
        request_id=request,
        operation_id=operation,
        can_write_assets=True,
    )


def test_weekly_auction_outbid_settlement_and_expiry_on_qq_and_onebot() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 21, 12, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=Path(data_dir), clock=clock)
            for adapter in ("qq.official", "onebot.v11"):
                seller = f"auction-seller-{adapter}"
                bidder_one = f"auction-bidder-one-{adapter}"
                bidder_two = f"auction-bidder-two-{adapter}"
                for user in (seller, bidder_one, bidder_two):
                    await runtime.adapters.dispatch(adapter, _context(adapter, user, f"create-{user}"), "开始修仙")
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE players SET inventory_json=?, spirit_stones=? WHERE platform=? AND platform_user_id=?",
                        (json.dumps({"item.material.cloud_iron": 1}), 0, adapter, seller),
                    )
                    connection.execute(
                        "UPDATE players SET inventory_json=?, spirit_stones=? WHERE platform=? AND platform_user_id=?",
                        ("{}", 200, adapter, bidder_one),
                    )
                    connection.execute(
                        "UPDATE players SET inventory_json=?, spirit_stones=? WHERE platform=? AND platform_user_id=?",
                        ("{}", 300, adapter, bidder_two),
                    )

                created = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, seller, "auction-create", f"{adapter}-auction-create"),
                    "发布拍卖 云铁 1 100",
                )
                assert created.code == "AUCTION_CREATED"
                listed = await runtime.adapters.dispatch(
                    adapter, _context(adapter, bidder_one, "auction-list"), "拍卖列表"
                )
                assert listed.code == "AUCTION_LISTED"
                auction_id = created.data["auction_id"]

                first_bid = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, bidder_one, "auction-bid-one", f"{adapter}-auction-bid-one"),
                    f"竞价 {auction_id} 100",
                )
                assert first_bid.code == "AUCTION_BID_PLACED"
                too_low = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, bidder_two, "auction-bid-low", f"{adapter}-auction-bid-low"),
                    f"竞价 {auction_id} 104",
                )
                assert too_low.code == "AUCTION_BID_TOO_LOW"
                second_bid = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, bidder_two, "auction-bid-two", f"{adapter}-auction-bid-two"),
                    f"竞价 {auction_id} 105",
                )
                assert second_bid.code == "AUCTION_BID_PLACED"

                with sqlite3.connect(runtime.settings.database_path) as connection:
                    balances = connection.execute(
                        "SELECT platform_user_id, spirit_stones FROM players WHERE platform=? AND platform_user_id IN (?, ?) ORDER BY platform_user_id",
                        (adapter, bidder_one, bidder_two),
                    ).fetchall()
                assert balances == [(bidder_one, 200), (bidder_two, 195)]

                clock.advance(hours=12, minutes=1)
                settled = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, seller, "auction-settle", f"{adapter}-auction-settle"),
                    f"结算拍卖 {auction_id}",
                )
                assert settled.code == "AUCTION_SETTLED"
                replay = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, seller, "auction-settle-replay", f"{adapter}-auction-settle"),
                    f"结算拍卖 {auction_id}",
                )
                assert replay.data["idempotent_replay"] is True
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    seller_state = connection.execute(
                        "SELECT spirit_stones, inventory_json FROM players WHERE platform=? AND platform_user_id=?",
                        (adapter, seller),
                    ).fetchone()
                    winner_state = connection.execute(
                        "SELECT spirit_stones, inventory_json FROM players WHERE platform=? AND platform_user_id=?",
                        (adapter, bidder_two),
                    ).fetchone()
                assert seller_state[0] == 105
                assert json.loads(seller_state[1]) == {}
                assert winner_state[0] == 195
                assert json.loads(winner_state[1]) == {"item.material.cloud_iron": 1}

                expired = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, seller, "auction-expired-create", f"{adapter}-auction-expired-create"),
                    "发布拍卖 云铁 0 100",
                )
                assert expired.code == "AUCTION_INPUT_INVALID"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE players SET inventory_json=? WHERE platform=? AND platform_user_id=?",
                        (json.dumps({"item.material.cloud_iron": 1}), adapter, seller),
                    )
                expired = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, seller, "auction-expired-create-2", f"{adapter}-auction-expired-create-2"),
                    "发布拍卖 云铁 1 100",
                )
                assert expired.code == "AUCTION_CREATED"
                clock.advance(hours=12, minutes=11)
                expired_settlement = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, bidder_one, "auction-expired-settle", f"{adapter}-auction-expired-settle"),
                    f"结算拍卖 {expired.data['auction_id']}",
                )
                assert expired_settlement.code == "AUCTION_SETTLEMENT_EXPIRED"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    row = connection.execute(
                        "SELECT status FROM auction_lots WHERE auction_id=?", (expired.data["auction_id"],)
                    ).fetchone()
                assert row[0] == "expired"
            await runtime.close()

    asyncio.run(run())


def test_weekly_auction_slot_limit_is_atomic_on_both_adapters() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            clock = MutableClock(datetime(2026, 9, 21, 12, tzinfo=timezone.utc))
            runtime = create_runtime(data_dir=Path(data_dir), clock=clock)
            for adapter in ("qq.official", "onebot.v11"):
                user = f"auction-slots-{adapter}"
                await runtime.adapters.dispatch(adapter, _context(adapter, user, "create"), "开始修仙")
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE players SET inventory_json=? WHERE platform=? AND platform_user_id=?",
                        (json.dumps({"item.material.cloud_iron": 21}), adapter, user),
                    )
                for index in range(20):
                    created = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, user, f"slot-{index}", f"{adapter}-slot-{index}"),
                        "发布拍卖 云铁 1 1",
                    )
                    assert created.code == "AUCTION_CREATED"
                full = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "slot-full", f"{adapter}-slot-full"),
                    "发布拍卖 云铁 1 1",
                )
                assert full.code == "AUCTION_SLOT_FULL"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    state = connection.execute(
                        "SELECT inventory_json FROM players WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    ).fetchone()[0]
                    assert json.loads(state) == {"item.material.cloud_iron": 21}
                    assert connection.execute(
                        "SELECT COALESCE(SUM(quantity), 0) FROM auction_item_locks WHERE seller_player_id=(SELECT id FROM players WHERE platform=? AND platform_user_id=?)",
                        (adapter, user),
                    ).fetchone()[0] == 20
                clock.advance(days=7)
            await runtime.close()

    asyncio.run(run())
