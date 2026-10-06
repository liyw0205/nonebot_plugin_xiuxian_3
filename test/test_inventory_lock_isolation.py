from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime


def _context(adapter: str, user: str, request: str, operation: str = "") -> CommandContext:
    return CommandContext(
        adapter=adapter,
        user_id=user,
        request_id=request,
        operation_id=operation,
        can_write_assets=True,
    )


async def _player(runtime, adapter: str, user: str) -> None:
    result = await runtime.adapters.dispatch(
        adapter, _context(adapter, user, f"create-{user}"), "开始修仙"
    )
    assert result.ok


def test_trade_locks_are_exclusive_across_market_purchase_auction_and_item_use() -> None:
    async def run() -> None:
        for adapter in ("qq.official", "onebot.v11"):
            with TemporaryDirectory() as data_dir:
                runtime = create_runtime(
                    data_dir=Path(data_dir),
                    clock=lambda: datetime(2026, 10, 6, 12, tzinfo=timezone.utc),
                )
                users = (
                    "market-seller",
                    "market-buyer",
                    "market-free-stock",
                    "purchase-seller",
                    "purchase-buyer",
                    "auction-seller",
                    "auction-buyer",
                )
                for user in users:
                    await _player(runtime, adapter, f"{user}-{adapter}")

                with sqlite3.connect(runtime.settings.database_path) as connection:
                    for user, inventory, location in (
                        ("market-seller", {"item.food.cloud_tea": 1}, "beast.ten_thousand_hills"),
                        ("market-free-stock", {"item.food.cloud_tea": 2}, "beast.ten_thousand_hills"),
                        ("purchase-seller", {"item.spirit_water": 1}, "beast.ten_thousand_hills"),
                        ("auction-seller", {"item.spirit_water": 1}, "beast.ten_thousand_hills"),
                    ):
                        connection.execute(
                            "UPDATE players SET inventory_json=?, location_key=?, faction_reputation_json=?, spirit_stones=1000 WHERE platform=? AND platform_user_id=?",
                            (json.dumps(inventory), location, json.dumps({"beast": 200}), adapter, f"{user}-{adapter}"),
                        )
                    for user in ("market-buyer", "purchase-buyer", "auction-buyer"):
                        connection.execute(
                            "UPDATE players SET location_key='demon.abyss_market', faction_reputation_json=?, spirit_stones=1000 WHERE platform=? AND platform_user_id=?",
                            (json.dumps({"demon": 200}), adapter, f"{user}-{adapter}"),
                        )

                market_seller = f"market-seller-{adapter}"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    stones_before = connection.execute(
                        "SELECT spirit_stones FROM players WHERE platform=? AND platform_user_id=?",
                        (adapter, market_seller),
                    ).fetchone()[0]
                    connection.execute(
                        f"CREATE TRIGGER reject_market_operation BEFORE INSERT ON operations WHEN NEW.operation_id='{adapter}-market-create' BEGIN SELECT RAISE(ABORT, 'injected market operation failure'); END"
                    )
                failed_market_create = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, market_seller, "market-create-failure", f"{adapter}-market-create"),
                    "发布摆摊 item.food.cloud_tea 1 100",
                )
                assert not failed_market_create.ok
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    assert connection.execute("SELECT COUNT(*) FROM market_orders").fetchone()[0] == 0
                    assert connection.execute("SELECT COUNT(*) FROM market_item_locks").fetchone()[0] == 0
                    assert connection.execute(
                        "SELECT spirit_stones FROM players WHERE platform=? AND platform_user_id=?",
                        (adapter, market_seller),
                    ).fetchone()[0] == stones_before
                    assert connection.execute(
                        "SELECT COUNT(*) FROM operations WHERE operation_id=?",
                        (f"{adapter}-market-create",),
                    ).fetchone()[0] == 0
                    connection.execute("DROP TRIGGER reject_market_operation")
                market_created = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, market_seller, "market-create", f"{adapter}-market-create"),
                    "发布摆摊 item.food.cloud_tea 1 100",
                )
                assert market_created.code == "MARKET_ORDER_CREATED"
                await runtime.close()
                runtime = create_runtime(
                    data_dir=Path(data_dir),
                    clock=lambda: datetime(2026, 10, 6, 12, tzinfo=timezone.utc),
                )
                market_replay = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, market_seller, "market-replay", f"{adapter}-market-create"),
                    "发布摆摊 item.food.cloud_tea 1 100",
                )
                assert market_replay.data["idempotent_replay"] is True
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    assert connection.execute("SELECT COUNT(*) FROM market_orders").fetchone()[0] == 1
                    assert connection.execute("SELECT COUNT(*) FROM market_item_locks").fetchone()[0] == 1
                    assert connection.execute(
                        "SELECT spirit_stones FROM players WHERE platform=? AND platform_user_id=?",
                        (adapter, market_seller),
                    ).fetchone()[0] == stones_before - 1

                blocked_use = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, market_seller, "use-reserved", f"{adapter}-use-reserved"),
                    "使用 item.food.cloud_tea",
                )
                assert blocked_use.code == "ITEM_RESERVED"
                blocked_auction = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, market_seller, "auction-reserved", f"{adapter}-auction-market-lock"),
                    "发布拍卖 item.food.cloud_tea 1 100",
                )
                assert blocked_auction.code == "AUCTION_ITEM_LOCKED"

                buyer = f"market-buyer-{adapter}"
                market_offer = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, buyer, "market-offer", f"{adapter}-market-offer"),
                    "发布求购 item.food.cloud_tea 1 100",
                )
                assert market_offer.code == "PURCHASE_ORDER_CREATED"
                blocked_match = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, market_seller, "match-market-lock", f"{adapter}-match-market-lock"),
                    f"匹配求购 {market_offer.data['order_id']}",
                )
                assert blocked_match.code == "PURCHASE_ITEM_LOCKED"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    assert connection.execute(
                        "SELECT COUNT(*) FROM operations WHERE operation_id IN (?, ?, ?)",
                        (
                            f"{adapter}-use-reserved",
                            f"{adapter}-auction-market-lock",
                            f"{adapter}-match-market-lock",
                        ),
                    ).fetchone()[0] == 0

                cancelled = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, market_seller, "market-cancel", f"{adapter}-market-cancel"),
                    f"取消摆摊 {market_created.data['order_id']}",
                )
                assert cancelled.code == "MARKET_ORDER_CANCELLED"
                released_use = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, market_seller, "use-after-release", f"{adapter}-use-reserved"),
                    "使用 item.food.cloud_tea",
                )
                assert released_use.code == "ITEM_USED"
                assert released_use.data["idempotent_replay"] is False

                free_stock = f"market-free-stock-{adapter}"
                free_listing = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, free_stock, "free-market-create", f"{adapter}-free-market-create"),
                    "发布摆摊 item.food.cloud_tea 1 100",
                )
                assert free_listing.code == "MARKET_ORDER_CREATED"
                free_use = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, free_stock, "free-stock-use", f"{adapter}-free-stock-use"),
                    "使用 item.food.cloud_tea",
                )
                assert free_use.code == "ITEM_USED"

                purchase_seller = f"purchase-seller-{adapter}"
                purchase_buyer = f"purchase-buyer-{adapter}"
                purchase = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, purchase_buyer, "purchase-create", f"{adapter}-purchase-create"),
                    "发布求购 item.spirit_water 1 100",
                )
                assert purchase.code == "PURCHASE_ORDER_CREATED"
                matched = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, purchase_seller, "purchase-match", f"{adapter}-purchase-match"),
                    f"匹配求购 {purchase.data['order_id']}",
                )
                assert matched.code == "PURCHASE_ORDER_MATCHED"
                await runtime.close()
                runtime = create_runtime(
                    data_dir=Path(data_dir),
                    clock=lambda: datetime(2026, 10, 6, 12, tzinfo=timezone.utc),
                )
                matched_replay = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, purchase_seller, "purchase-match-replay", f"{adapter}-purchase-match"),
                    f"匹配求购 {purchase.data['order_id']}",
                )
                assert matched_replay.data["idempotent_replay"] is True
                assert (
                    await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, purchase_seller, "purchase-lock-market", f"{adapter}-purchase-lock-market"),
                        "发布摆摊 item.spirit_water 1 100",
                    )
                ).code == "MARKET_ITEM_LOCKED"
                assert (
                    await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, purchase_seller, "purchase-lock-auction", f"{adapter}-purchase-lock-auction"),
                        "发布拍卖 item.spirit_water 1 100",
                    )
                ).code == "AUCTION_ITEM_LOCKED"

                auction_seller = f"auction-seller-{adapter}"
                auction_buyer = f"auction-buyer-{adapter}"
                auction = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, auction_seller, "auction-create", f"{adapter}-auction-create"),
                    "发布拍卖 item.spirit_water 1 100",
                )
                assert auction.code == "AUCTION_CREATED"
                auction_replay = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, auction_seller, "auction-replay", f"{adapter}-auction-create"),
                    "发布拍卖 item.spirit_water 1 100",
                )
                assert auction_replay.data["idempotent_replay"] is True
                auction_offer = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, auction_buyer, "auction-offer", f"{adapter}-auction-offer"),
                    "发布求购 item.spirit_water 1 100",
                )
                assert auction_offer.code == "PURCHASE_ORDER_CREATED"
                assert (
                    await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, auction_seller, "auction-lock-match", f"{adapter}-auction-lock-match"),
                        f"匹配求购 {auction_offer.data['order_id']}",
                    )
                ).code == "PURCHASE_ITEM_LOCKED"
                assert (
                    await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, auction_seller, "auction-lock-market", f"{adapter}-auction-lock-market"),
                        "发布摆摊 item.spirit_water 1 100",
                    )
                ).code == "MARKET_ITEM_LOCKED"

                rejected_operations = (
                    f"{adapter}-auction-market-lock",
                    f"{adapter}-match-market-lock",
                    f"{adapter}-purchase-lock-market",
                    f"{adapter}-purchase-lock-auction",
                    f"{adapter}-auction-lock-match",
                    f"{adapter}-auction-lock-market",
                )
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    recorded = connection.execute(
                        f"SELECT COUNT(*) FROM operations WHERE operation_id IN ({','.join('?' for _ in rejected_operations)})",
                        rejected_operations,
                    ).fetchone()[0]
                    assert recorded == 0
                    inventory_rows = connection.execute(
                        "SELECT platform_user_id, inventory_json FROM players WHERE platform=?",
                        (adapter,),
                    ).fetchall()
                    inventories = {user: json.loads(raw) for user, raw in inventory_rows}
                    assert inventories[market_seller] == {}
                    assert inventories[free_stock] == {"item.food.cloud_tea": 1}
                    assert inventories[purchase_seller] == {"item.spirit_water": 1}
                    assert inventories[auction_seller] == {"item.spirit_water": 1}
                    assert connection.execute(
                        "SELECT COUNT(*) FROM purchase_item_locks WHERE seller_player_id=(SELECT id FROM players WHERE platform=? AND platform_user_id=?)",
                        (adapter, purchase_seller),
                    ).fetchone()[0] == 1
                    assert connection.execute(
                        "SELECT COUNT(*) FROM auction_item_locks WHERE seller_player_id=(SELECT id FROM players WHERE platform=? AND platform_user_id=?)",
                        (adapter, auction_seller),
                    ).fetchone()[0] == 1
                await runtime.close()

    asyncio.run(run())
