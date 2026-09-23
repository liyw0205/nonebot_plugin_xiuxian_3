"""SQLite transactions for wallets and fixed-price market orders."""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from typing import Any
from uuid import uuid4

from ...contracts import serialize_datetime
from ..persistence.errors import (
    BalanceInsufficientError,
    MarketBuyerCapacityInsufficientError,
    MarketItemForbiddenError,
    MarketItemLockedError,
    MarketOrderAlreadySettledError,
    MarketOrderExpiredError,
    MarketOrderLimitError,
    MarketOrderNotFoundError,
    MarketOrderNotListedError,
    MarketPriceInvalidError,
    MarketSelfTradeError,
    OperationConflictError,
    PlayerNotFoundError,
    PlayerSuspendedError,
)
from .models import MarketOrderRecord
from .rules import (
    ECONOMY_RULE_VERSION,
    MARKET_MAX_LISTINGS,
    MARKET_ORDER_TTL_SECONDS,
    listing_fee,
    resolve_market_item,
    trade_fee,
    validate_market_listing,
)


class EconomyRepositoryMixin:
    """Own market locks, wallet movement, and economic asset ledger writes."""

    async def create_market_order(
        self,
        *,
        platform: str,
        platform_user_id: str,
        item_key: str,
        quantity: int,
        unit_price: int,
        operation_id: str,
    ) -> MarketOrderRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._market_create_once,
                platform,
                platform_user_id,
                item_key,
                quantity,
                unit_price,
                operation_id,
            )

    async def buy_market_order(
        self,
        *,
        platform: str,
        platform_user_id: str,
        order_id: str,
        quantity: int | None,
        operation_id: str,
    ) -> MarketOrderRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._market_buy_once,
                platform,
                platform_user_id,
                order_id,
                quantity,
                operation_id,
            )

    async def cancel_market_order(
        self,
        *,
        platform: str,
        platform_user_id: str,
        order_id: str,
        operation_id: str,
    ) -> MarketOrderRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._market_cancel_once,
                platform,
                platform_user_id,
                order_id,
                operation_id,
            )

    async def expire_market_order(
        self,
        *,
        platform: str,
        platform_user_id: str,
        order_id: str,
        operation_id: str,
    ) -> MarketOrderRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._market_expire_once,
                platform,
                platform_user_id,
                order_id,
                operation_id,
            )

    async def list_market_orders(self, *, platform: str, platform_user_id: str) -> tuple[MarketOrderRecord, ...]:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._market_list_once, platform, platform_user_id)

    def _market_create_once(
        self,
        platform: str,
        platform_user_id: str,
        item_key: str,
        quantity: int,
        unit_price: int,
        operation_id: str,
    ) -> MarketOrderRecord:
        operation_name = "economy.create_market_order"
        request_hash = self._request_hash(
            operation_name,
            {
                "platform": platform,
                "platform_user_id": platform_user_id,
                "item_key": item_key,
                "quantity": quantity,
                "unit_price": unit_price,
            },
        )
        now = self._now()
        now_text = serialize_datetime(now)
        try:
            item = resolve_market_item(item_key)
            validate_market_listing(int(quantity), int(unit_price))
        except (ValueError, TypeError) as exc:
            if "item" in str(exc):
                raise MarketItemForbiddenError(str(exc)) from exc
            raise MarketPriceInvalidError(str(exc)) from exc
        fee = listing_fee(int(quantity))
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._market_operation(connection, operation_id, operation_name, request_hash)
            if existing is not None:
                return self._market_record_from_payload(existing, replay=True)
            player = self._require_player(connection, platform, platform_user_id)
            self._market_expire_due(connection, now, operation_id, now_text)
            active_count = connection.execute(
                "SELECT COUNT(*) FROM market_orders WHERE seller_player_id = ? AND status = 'listed'",
                (player["id"],),
            ).fetchone()[0]
            if int(active_count) >= MARKET_MAX_LISTINGS:
                raise MarketOrderLimitError("listing limit reached")
            inventory = self._json_object(player["inventory_json"], {})
            available = int(inventory.get(item.key, 0)) - self._market_locked_quantity(
                connection, int(player["id"]), item.key
            )
            if available < quantity:
                raise MarketItemLockedError("not enough unlocked inventory")
            if int(player["spirit_stones"]) < fee:
                raise BalanceInsufficientError("listing fee is not affordable")
            order_id = f"market-{uuid4().hex}"
            expires_at = now + timedelta(seconds=MARKET_ORDER_TTL_SECONDS)
            connection.execute(
                """
                INSERT INTO market_orders(
                    order_id, seller_player_id, buyer_player_id, item_key, quantity,
                    remaining_quantity, unit_price, listing_fee, status, expires_at,
                    created_at, updated_at
                ) VALUES (?, ?, NULL, ?, ?, ?, ?, ?, 'listed', ?, ?, ?)
                """,
                (
                    order_id,
                    player["id"],
                    item.key,
                    quantity,
                    quantity,
                    unit_price,
                    fee,
                    serialize_datetime(expires_at),
                    now_text,
                    now_text,
                ),
            )
            connection.execute(
                """
                INSERT INTO market_item_locks(order_id, seller_player_id, item_key, quantity, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (order_id, player["id"], item.key, quantity, now_text, now_text),
            )
            connection.execute(
                "UPDATE players SET spirit_stones = spirit_stones - ?, updated_at = ? WHERE id = ?",
                (fee, now_text, player["id"]),
            )
            self._market_ledger(
                connection, operation_id, int(player["id"]), "currency", "currency.spirit_stone",
                "market.listing_fee", "debit", fee, int(player["spirit_stones"]), int(player["spirit_stones"]) - fee,
                order_id, now_text,
            )
            self._market_ledger(
                connection, operation_id, int(player["id"]), "item", item.key,
                "market.item_lock", "lock", quantity, available, available - quantity, order_id, now_text,
            )
            payload = self._market_payload(connection, order_id)
            self._market_record_operation(connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text)
            return self._market_record_from_payload(payload)

    def _market_buy_once(
        self,
        platform: str,
        platform_user_id: str,
        order_id: str,
        quantity: int | None,
        operation_id: str,
    ) -> MarketOrderRecord:
        operation_name = "economy.buy_market_order"
        request_hash = self._request_hash(
            operation_name,
            {"platform": platform, "platform_user_id": platform_user_id, "order_id": order_id, "quantity": quantity},
        )
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._market_operation(connection, operation_id, operation_name, request_hash)
            if existing is not None:
                return self._market_record_from_payload(existing, replay=True)
            buyer = self._require_player(connection, platform, platform_user_id)
            self._market_expire_due(connection, now, operation_id, now_text)
            order = connection.execute("SELECT * FROM market_orders WHERE order_id = ?", (order_id,)).fetchone()
            if order is None:
                raise MarketOrderNotFoundError("market order does not exist")
            if int(order["seller_player_id"]) == int(buyer["id"]):
                raise MarketSelfTradeError("seller cannot buy own order")
            if str(order["status"]) == "expired":
                raise MarketOrderExpiredError("market order expired")
            if str(order["status"]) != "listed":
                if str(order["status"]) in {"settled", "cancelled", "matched"}:
                    raise MarketOrderAlreadySettledError("market order is no longer listed")
                raise MarketOrderNotListedError("market order is not listed")
            expires_at = str(order["expires_at"])
            if expires_at <= now_text:
                self._market_expire_row(connection, order, operation_id, now_text)
                raise MarketOrderExpiredError("market order expired")
            remaining = int(order["remaining_quantity"])
            if quantity is None:
                quantity = remaining
            try:
                quantity = int(quantity)
            except (TypeError, ValueError) as exc:
                raise MarketPriceInvalidError("quantity is invalid") from exc
            if quantity < 1 or quantity > remaining:
                raise MarketPriceInvalidError("quantity out of range")
            lock = connection.execute(
                "SELECT quantity FROM market_item_locks WHERE order_id = ?", (order_id,)
            ).fetchone()
            if lock is None or int(lock["quantity"]) < quantity:
                raise MarketItemLockedError("seller item lock is missing")
            seller = connection.execute("SELECT * FROM players WHERE id = ?", (order["seller_player_id"],)).fetchone()
            if seller is None:
                raise PlayerNotFoundError("seller does not exist")
            seller_inventory = self._json_object(seller["inventory_json"], {})
            buyer_inventory = self._json_object(buyer["inventory_json"], {})
            if int(seller_inventory.get(order["item_key"], 0)) < quantity:
                raise MarketItemLockedError("seller inventory no longer contains locked item")
            capacity = int(buyer["carry_capacity"] or 0)
            if capacity > 0 and sum(int(value) for value in buyer_inventory.values()) + quantity > capacity:
                raise MarketBuyerCapacityInsufficientError("buyer inventory capacity is insufficient")
            total = quantity * int(order["unit_price"])
            fee = trade_fee(total)
            if int(buyer["spirit_stones"]) < total:
                raise BalanceInsufficientError("buyer balance is insufficient")
            seller_before = int(seller["spirit_stones"])
            buyer_before = int(buyer["spirit_stones"])
            seller_inventory[order["item_key"]] = int(seller_inventory[order["item_key"]]) - quantity
            if seller_inventory[order["item_key"]] <= 0:
                seller_inventory.pop(order["item_key"], None)
            buyer_inventory[order["item_key"]] = int(buyer_inventory.get(order["item_key"], 0)) + quantity
            new_remaining = remaining - quantity
            new_status = "settled" if new_remaining == 0 else "listed"
            connection.execute(
                "UPDATE players SET inventory_json = ?, spirit_stones = spirit_stones - ?, updated_at = ? WHERE id = ?",
                (json.dumps(buyer_inventory, ensure_ascii=False, sort_keys=True), total, now_text, buyer["id"]),
            )
            connection.execute(
                "UPDATE players SET inventory_json = ?, spirit_stones = spirit_stones + ?, updated_at = ? WHERE id = ?",
                (json.dumps(seller_inventory, ensure_ascii=False, sort_keys=True), total - fee, now_text, seller["id"]),
            )
            if new_remaining:
                connection.execute(
                    "UPDATE market_item_locks SET quantity = ?, updated_at = ? WHERE order_id = ?",
                    (new_remaining, now_text, order_id),
                )
            else:
                connection.execute("DELETE FROM market_item_locks WHERE order_id = ?", (order_id,))
            connection.execute(
                "UPDATE market_orders SET buyer_player_id = ?, remaining_quantity = ?, status = ?, updated_at = ? WHERE order_id = ?",
                (buyer["id"], new_remaining, new_status, now_text, order_id),
            )
            self._market_ledger(
                connection, operation_id, int(buyer["id"]), "currency", "currency.spirit_stone",
                "market.purchase", "debit", total, buyer_before, buyer_before - total, order_id, now_text,
            )
            self._market_ledger(
                connection, operation_id, int(seller["id"]), "currency", "currency.spirit_stone",
                "market.sale", "credit", total, seller_before, seller_before + total, order_id, now_text,
            )
            self._market_ledger(
                connection, operation_id, int(seller["id"]), "currency", "currency.spirit_stone",
                "market.trade_fee", "debit", fee, seller_before + total, seller_before + total - fee, order_id, now_text,
            )
            self._market_ledger(
                connection, operation_id, int(seller["id"]), "item", str(order["item_key"]),
                "market.sale", "debit", quantity, int(seller_inventory.get(order["item_key"], 0)) + quantity,
                int(seller_inventory.get(order["item_key"], 0)), order_id, now_text,
            )
            self._market_ledger(
                connection, operation_id, int(buyer["id"]), "item", str(order["item_key"]),
                "market.purchase", "credit", quantity, int(buyer_inventory.get(order["item_key"], 0)) - quantity,
                int(buyer_inventory.get(order["item_key"], 0)), order_id, now_text,
            )
            if not new_remaining:
                self._market_ledger(
                    connection, operation_id, int(seller["id"]), "item", str(order["item_key"]),
                    "market.item_unlock", "release", 0, 0, 0, order_id, now_text,
                )
            payload = self._market_payload(connection, order_id)
            self._market_record_operation(connection, operation_id, operation_name, int(buyer["id"]), request_hash, payload, now_text)
            return self._market_record_from_payload(payload)

    def _market_cancel_once(self, platform: str, platform_user_id: str, order_id: str, operation_id: str) -> MarketOrderRecord:
        operation_name = "economy.cancel_market_order"
        request_hash = self._request_hash(operation_name, {"platform": platform, "platform_user_id": platform_user_id, "order_id": order_id})
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._market_operation(connection, operation_id, operation_name, request_hash)
            if existing is not None:
                return self._market_record_from_payload(existing, replay=True)
            seller = self._require_player(connection, platform, platform_user_id)
            order = connection.execute("SELECT * FROM market_orders WHERE order_id = ?", (order_id,)).fetchone()
            if order is None or int(order["seller_player_id"]) != int(seller["id"]):
                raise MarketOrderNotFoundError("market order does not belong to seller")
            if str(order["status"]) == "expired":
                raise MarketOrderExpiredError("market order expired")
            if str(order["status"]) != "listed":
                raise MarketOrderNotListedError("only listed orders can be cancelled")
            self._market_release_lock(connection, order, operation_id, now_text)
            connection.execute("UPDATE market_orders SET status = 'cancelled', updated_at = ? WHERE order_id = ?", (now_text, order_id))
            payload = self._market_payload(connection, order_id)
            self._market_record_operation(connection, operation_id, operation_name, int(seller["id"]), request_hash, payload, now_text)
            return self._market_record_from_payload(payload)

    def _market_expire_once(self, platform: str, platform_user_id: str, order_id: str, operation_id: str) -> MarketOrderRecord:
        operation_name = "economy.expire_market_order"
        request_hash = self._request_hash(operation_name, {"platform": platform, "platform_user_id": platform_user_id, "order_id": order_id})
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._market_operation(connection, operation_id, operation_name, request_hash)
            if existing is not None:
                return self._market_record_from_payload(existing, replay=True)
            actor = self._require_player(connection, platform, platform_user_id, writable=False)
            order = connection.execute("SELECT * FROM market_orders WHERE order_id = ?", (order_id,)).fetchone()
            if order is None:
                raise MarketOrderNotFoundError("market order does not exist")
            if str(order["status"]) == "expired":
                payload = self._market_payload(connection, order_id)
                self._market_record_operation(connection, operation_id, operation_name, int(actor["id"]), request_hash, payload, now_text)
                return self._market_record_from_payload(payload)
            if str(order["status"]) != "listed":
                raise MarketOrderNotListedError("only listed orders can expire")
            if str(order["expires_at"]) > now_text:
                raise MarketOrderExpiredError("market order has not expired")
            self._market_expire_row(connection, order, operation_id, now_text)
            payload = self._market_payload(connection, order_id)
            self._market_record_operation(connection, operation_id, operation_name, int(actor["id"]), request_hash, payload, now_text)
            return self._market_record_from_payload(payload)

    def _market_list_once(self, platform: str, platform_user_id: str) -> tuple[MarketOrderRecord, ...]:
        with self._connect() as connection:
            player = self._require_player(connection, platform, platform_user_id, writable=False)
            return tuple(
                self._market_record_from_payload(self._market_payload(connection, row["order_id"]))
                for row in connection.execute(
                    "SELECT order_id FROM market_orders WHERE status = 'listed' ORDER BY created_at, id"
                ).fetchall()
            )

    def _market_expire_due(self, connection: Any, now: Any, operation_id: str, now_text: str) -> None:
        rows = connection.execute(
            "SELECT * FROM market_orders WHERE status = 'listed' AND expires_at <= ?", (now_text,)
        ).fetchall()
        for row in rows:
            self._market_expire_row(connection, row, operation_id, now_text)

    def _market_expire_row(self, connection: Any, order: Any, operation_id: str, now_text: str) -> None:
        lock = connection.execute("SELECT quantity FROM market_item_locks WHERE order_id = ?", (order["order_id"],)).fetchone()
        if lock is not None:
            self._market_ledger(
                connection, operation_id, int(order["seller_player_id"]), "item", str(order["item_key"]),
                "market.item_unlock", "release", int(lock["quantity"]), int(lock["quantity"]), 0,
                str(order["order_id"]), now_text,
            )
        connection.execute("DELETE FROM market_item_locks WHERE order_id = ?", (order["order_id"],))
        connection.execute("UPDATE market_orders SET status = 'expired', updated_at = ? WHERE order_id = ?", (now_text, order["order_id"]))

    def _market_release_lock(self, connection: Any, order: Any, operation_id: str, now_text: str) -> None:
        lock = connection.execute("SELECT quantity FROM market_item_locks WHERE order_id = ?", (order["order_id"],)).fetchone()
        if lock is not None:
            self._market_ledger(
                connection, operation_id, int(order["seller_player_id"]), "item", str(order["item_key"]),
                "market.item_unlock", "release", int(lock["quantity"]), int(lock["quantity"]), 0,
                str(order["order_id"]), now_text,
            )
        connection.execute("DELETE FROM market_item_locks WHERE order_id = ?", (order["order_id"],))

    @staticmethod
    def _market_locked_quantity(connection: Any, player_id: int, item_key: str) -> int:
        row = connection.execute(
            "SELECT COALESCE(SUM(quantity), 0) FROM market_item_locks WHERE seller_player_id = ? AND item_key = ?",
            (player_id, item_key),
        ).fetchone()
        return int(row[0])

    @staticmethod
    def _market_ledger(
        connection: Any,
        operation_id: str,
        player_id: int,
        asset_kind: str,
        asset_key: str,
        reason: str,
        direction: str,
        amount: int,
        before_value: int,
        after_value: int,
        source_id: str,
        created_at: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO economy_ledger_entries(
                operation_id, player_id, asset_kind, asset_key, reason, direction,
                amount, before_value, after_value, source_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (operation_id, player_id, asset_kind, asset_key, reason, direction, amount, before_value, after_value, source_id, created_at),
        )

    @staticmethod
    def _market_operation(connection: Any, operation_id: str, operation_name: str, request_hash: str) -> dict[str, Any] | None:
        existing = connection.execute(
            "SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id = ?", (operation_id,)
        ).fetchone()
        if existing is None:
            return None
        if existing["operation_name"] != operation_name or existing["request_hash"] != request_hash:
            raise OperationConflictError("operation input differs from its original request")
        return json.loads(existing["result_json"])

    @staticmethod
    def _market_record_operation(connection: Any, operation_id: str, operation_name: str, player_id: int, request_hash: str, payload: dict[str, Any], now_text: str) -> None:
        connection.execute(
            "INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (operation_id, operation_name, player_id, request_hash, json.dumps(payload, ensure_ascii=False, sort_keys=True), now_text),
        )

    @staticmethod
    def _market_payload(connection: Any, order_id: str) -> dict[str, Any]:
        row = connection.execute(
            """
            SELECT o.*, s.player_id AS seller_stable_id, s.platform_user_id AS seller_platform_user_id,
                   s.dao_name AS seller_dao_name, b.player_id AS buyer_stable_id,
                   b.platform_user_id AS buyer_platform_user_id
            FROM market_orders o
            JOIN players s ON s.id = o.seller_player_id
            LEFT JOIN players b ON b.id = o.buyer_player_id
            WHERE o.order_id = ?
            """,
            (order_id,),
        ).fetchone()
        if row is None:
            raise MarketOrderNotFoundError("market order does not exist")
        total_price = int(row["quantity"]) * int(row["unit_price"])
        return {
            "order_id": str(row["order_id"]),
            "status": str(row["status"]),
            "seller_player_id": str(row["seller_stable_id"]),
            "seller_platform_user_id": str(row["seller_platform_user_id"]),
            "seller_dao_name": str(row["seller_dao_name"] or "未命名"),
            "buyer_player_id": str(row["buyer_stable_id"]) if row["buyer_stable_id"] else None,
            "buyer_platform_user_id": str(row["buyer_platform_user_id"]) if row["buyer_platform_user_id"] else None,
            "item_key": str(row["item_key"]),
            "quantity": int(row["quantity"]),
            "remaining_quantity": int(row["remaining_quantity"]),
            "unit_price": int(row["unit_price"]),
            "listing_fee": int(row["listing_fee"]),
            "trade_fee": trade_fee(total_price),
            "total_price": total_price,
            "expires_at": str(row["expires_at"]),
            "created_at": str(row["created_at"]),
        }

    @staticmethod
    def _market_record_from_payload(payload: dict[str, Any], *, replay: bool = False) -> MarketOrderRecord:
        return MarketOrderRecord(
            order_id=str(payload["order_id"]),
            status=str(payload["status"]),
            seller_player_id=str(payload["seller_player_id"]),
            seller_platform_user_id=str(payload["seller_platform_user_id"]),
            seller_dao_name=str(payload["seller_dao_name"]),
            buyer_player_id=payload.get("buyer_player_id"),
            buyer_platform_user_id=payload.get("buyer_platform_user_id"),
            item_key=str(payload["item_key"]),
            quantity=int(payload["quantity"]),
            remaining_quantity=int(payload["remaining_quantity"]),
            unit_price=int(payload["unit_price"]),
            listing_fee=int(payload["listing_fee"]),
            trade_fee=int(payload["trade_fee"]),
            total_price=int(payload["total_price"]),
            expires_at=str(payload["expires_at"]),
            created_at=str(payload["created_at"]),
            already_completed=replay,
        )


__all__ = ["EconomyRepositoryMixin"]
