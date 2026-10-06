from __future__ import annotations

import asyncio
import json
import shutil
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


async def _player(runtime, adapter: str, user: str) -> None:
    result = await runtime.adapters.dispatch(adapter, _context(adapter, user, f"create-{user}"), "开始修仙")
    assert result.ok


def test_cross_realm_purchase_order_settlement_and_replay_on_qq_and_onebot() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 25, 12, tzinfo=timezone.utc))
        for adapter in ("qq.official", "onebot.v11"):
            with TemporaryDirectory() as data_dir:
                runtime = create_runtime(data_dir=Path(data_dir), clock=clock)
                buyer = f"purchase-buyer-{adapter}"
                seller = f"purchase-seller-{adapter}"
                await _player(runtime, adapter, buyer)
                await _player(runtime, adapter, seller)
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE players SET location_key='demon.abyss_market', faction_reputation_json=?, spirit_stones=1000 WHERE platform=? AND platform_user_id=?",
                        (json.dumps({"demon": 200}), adapter, buyer),
                    )
                    connection.execute(
                        "UPDATE players SET location_key='beast.ten_thousand_hills', faction_reputation_json=?, inventory_json=? WHERE platform=? AND platform_user_id=?",
                        (json.dumps({"beast": 200}), json.dumps({"item.beast_blood": 3}), adapter, seller),
                    )

                created = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, buyer, "create-order", f"{adapter}-create-order"),
                    "发布求购 item.beast_blood 2 100",
                )
                assert created.code == "PURCHASE_ORDER_CREATED"
                assert created.data["purchase_fee"] == 16
                assert created.data["escrow_amount"] == 216
                order_id = created.data["order_id"]
                replay = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, buyer, "replay-order", f"{adapter}-create-order"),
                    "发布跨界求购 item.beast_blood 2 100",
                )
                assert replay.data["idempotent_replay"] is True

                matched = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, seller, "match-order", f"{adapter}-match-order"),
                    f"匹配求购 {order_id}",
                )
                assert matched.code == "PURCHASE_ORDER_MATCHED"
                assert matched.data["buyer_faction"] == "demon"
                assert matched.data["seller_faction"] == "beast"
                assert matched.data["item_region"] == "beast"
                matched_replay = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, seller, "match-replay", f"{adapter}-match-order"),
                    f"接取求购 {order_id}",
                )
                assert matched_replay.data["idempotent_replay"] is True

                settled = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, seller, "deliver-order", f"{adapter}-deliver-order"),
                    f"交付求购 {order_id}",
                )
                assert settled.code == "PURCHASE_ORDER_SETTLED"
                settled_replay = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, seller, "deliver-replay", f"{adapter}-deliver-order"),
                    f"完成求购 {order_id}",
                )
                assert settled_replay.data["idempotent_replay"] is True
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    rows = connection.execute(
                        "SELECT platform_user_id, spirit_stones, inventory_json FROM players WHERE platform=? ORDER BY platform_user_id",
                        (adapter,),
                    ).fetchall()
                buyer_row = next(row for row in rows if row[0] == buyer)
                seller_row = next(row for row in rows if row[0] == seller)
                assert buyer_row[1] == 784
                assert json.loads(buyer_row[2]) == {"item.beast_blood": 2}
                assert seller_row[1] == 200
                assert json.loads(seller_row[2]) == {"item.beast_blood": 1}
                await runtime.close()

    asyncio.run(run())


def test_purchase_order_create_replays_after_item_rename_on_qq_and_onebot() -> None:
    async def run() -> None:
        source_data = Path(__file__).resolve().parents[1] / "data"
        clock = MutableClock(datetime(2026, 9, 25, 12, tzinfo=timezone.utc))
        for adapter in ("qq.official", "onebot.v11"):
            with TemporaryDirectory() as temp_dir:
                data_dir = Path(temp_dir) / "data"
                shutil.copytree(source_data, data_dir)
                runtime = create_runtime(data_dir=data_dir, clock=clock)
                buyer = f"rename-buyer-{adapter}"
                seller = f"rename-seller-{adapter}"
                await _player(runtime, adapter, buyer)
                await _player(runtime, adapter, seller)
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE players SET location_key='demon.abyss_market', faction_reputation_json=?, spirit_stones=1000 WHERE platform=? AND platform_user_id=?",
                        (json.dumps({"demon": 200}), adapter, buyer),
                    )
                    connection.execute(
                        "UPDATE players SET location_key='beast.ten_thousand_hills', faction_reputation_json=?, inventory_json=? WHERE platform=? AND platform_user_id=?",
                        (json.dumps({"beast": 200}), json.dumps({"item.beast_blood": 3}), adapter, seller),
                    )

                created = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, buyer, "create-before-rename", "rename-create-order"),
                    "发布求购 兽血 2 100",
                )
                assert created.code == "PURCHASE_ORDER_CREATED"
                order_id = created.data["order_id"]
                assert created.data["item_label"] == "兽血"
                await runtime.close()

                item_path = data_dir / "道具" / "材料.json"
                document = json.loads(item_path.read_text(encoding="utf-8"))
                item = next(row for row in document["records"] if row["key"] == "item.beast_blood")
                item["name"] = "新名兽血"
                item_path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

                runtime = create_runtime(data_dir=data_dir, clock=clock)
                replay = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, buyer, "replay-after-rename", "rename-create-order"),
                    "发布求购 兽血 2 100",
                )
                assert replay.code == "PURCHASE_ORDER_CREATED"
                assert replay.data["idempotent_replay"] is True
                assert replay.data["order_id"] == order_id
                assert replay.data["item_label"] == "兽血"
                assert "兽血 ×2" in replay.message

                matched = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, seller, "match-after-rename", "rename-match-order"),
                    f"匹配求购 {order_id}",
                )
                assert matched.code == "PURCHASE_ORDER_MATCHED"
                assert matched.data["item_label"] == "兽血"
                delivered = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, seller, "deliver-after-rename", "rename-deliver-order"),
                    f"交付求购 {order_id}",
                )
                assert delivered.code == "PURCHASE_ORDER_SETTLED"
                assert "兽血 ×2" in delivered.message

                changed = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, buyer, "conflicting-replay", "rename-create-order"),
                    "发布求购 兽血 3 100",
                )
                assert changed.code == "LEDGER_CONFLICT"
                rejected = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, buyer, "new-old-name", "new-order-after-rename"),
                    "发布求购 兽血 2 100",
                )
                assert rejected.code == "PURCHASE_ITEM_FORBIDDEN"

                with sqlite3.connect(runtime.settings.database_path) as connection:
                    assert connection.execute(
                        "SELECT COUNT(*) FROM purchase_orders WHERE buyer_player_id=(SELECT id FROM players WHERE platform=? AND platform_user_id=?)",
                        (adapter, buyer),
                    ).fetchone()[0] == 1
                    buyer_assets = connection.execute(
                        "SELECT spirit_stones, inventory_json FROM players WHERE platform=? AND platform_user_id=?",
                        (adapter, buyer),
                    ).fetchone()
                    assert buyer_assets[0] == 784
                    assert json.loads(buyer_assets[1]) == {"item.beast_blood": 2}
                    seller_assets = connection.execute(
                        "SELECT spirit_stones, inventory_json FROM players WHERE platform=? AND platform_user_id=?",
                        (adapter, seller),
                    ).fetchone()
                    assert seller_assets[0] == 200
                    assert json.loads(seller_assets[1]) == {"item.beast_blood": 1}
                    assert connection.execute(
                        "SELECT COUNT(*) FROM operations WHERE operation_id='rename-create-order'"
                    ).fetchone()[0] == 1
                await runtime.close()

    asyncio.run(run())


def test_purchase_delivery_timeout_releases_item_and_order_expiry_refunds_escrow() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 25, 12, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=Path(data_dir), clock=clock)
            adapter = "qq.official"
            await _player(runtime, adapter, "buyer")
            await _player(runtime, adapter, "seller")
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute("UPDATE players SET spirit_stones=500 WHERE platform=? AND platform_user_id='buyer'", (adapter,))
                connection.execute("UPDATE players SET inventory_json=? WHERE platform=? AND platform_user_id='seller'", (json.dumps({"item.demon_core": 2}), adapter))
            created = await runtime.adapters.dispatch(adapter, _context(adapter, "buyer", "create", "create"), "发布求购 item.demon_core 1 100")
            order_id = created.data["order_id"]
            await runtime.adapters.dispatch(adapter, _context(adapter, "seller", "match", "match"), f"匹配求购 {order_id}")
            clock.advance(minutes=11)
            timed_out = await runtime.adapters.dispatch(adapter, _context(adapter, "seller", "timeout", "timeout"), f"交付求购 {order_id}")
            assert timed_out.code == "PURCHASE_DELIVERY_EXPIRED"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute("SELECT status FROM purchase_orders WHERE order_id=?", (order_id,)).fetchone()[0] == "listed"
                assert connection.execute("SELECT COUNT(*) FROM purchase_item_locks WHERE order_id=?", (order_id,)).fetchone()[0] == 0
                assert connection.execute("SELECT spirit_stones FROM players WHERE platform=? AND platform_user_id='buyer'", (adapter,)).fetchone()[0] == 392
            clock.advance(hours=12)
            expired = await runtime.adapters.dispatch(adapter, _context(adapter, "buyer", "expire", "expire"), f"清理求购 {order_id}")
            assert expired.code == "PURCHASE_ORDER_EXPIRED"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute("SELECT status FROM purchase_orders WHERE order_id=?", (order_id,)).fetchone()[0] == "expired"
                assert connection.execute("SELECT spirit_stones FROM players WHERE platform=? AND platform_user_id='buyer'", (adapter,)).fetchone()[0] == 500
                assert connection.execute("SELECT COUNT(*) FROM purchase_order_funds WHERE order_id=?", (order_id,)).fetchone()[0] == 0
            await runtime.close()

    asyncio.run(run())


def test_purchase_order_competing_sellers_only_one_match() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=Path(data_dir))
            adapter = "onebot.v11"
            for user in ("buyer", "seller-a", "seller-b"):
                await _player(runtime, adapter, user)
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute("UPDATE players SET spirit_stones=500 WHERE platform=? AND platform_user_id='buyer'", (adapter,))
                for user in ("seller-a", "seller-b"):
                    connection.execute("UPDATE players SET inventory_json=? WHERE platform=? AND platform_user_id=?", (json.dumps({"item.demon_core": 1}), adapter, user))
            created = await runtime.adapters.dispatch(adapter, _context(adapter, "buyer", "create", "create"), "发布求购 item.demon_core 1 100")
            order_id = created.data["order_id"]
            results = await asyncio.gather(
                runtime.adapters.dispatch(adapter, _context(adapter, "seller-a", "match-a", "match-a"), f"匹配求购 {order_id}"),
                runtime.adapters.dispatch(adapter, _context(adapter, "seller-b", "match-b", "match-b"), f"匹配求购 {order_id}"),
            )
            assert sorted(result.ok for result in results) == [False, True]
            assert {result.code for result in results} == {"PURCHASE_ORDER_MATCHED", "PURCHASE_ORDER_STATE_CONFLICT"}
            await runtime.close()

    asyncio.run(run())
