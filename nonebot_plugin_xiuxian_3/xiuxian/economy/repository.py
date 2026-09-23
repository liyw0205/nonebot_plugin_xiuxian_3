"""SQLite transactions for wallets and fixed-price market orders."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
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
from .commission_models import ProductionCommissionRecord
from .rules import (
    COMMISSION_MAX_REWARD,
    COMMISSION_MIN_REWARD,
    COMMISSION_RECOVERY_GRACE_SECONDS,
    COMMISSION_RECIPES,
    COMMISSION_TTL_SECONDS,
    ECONOMY_RULE_VERSION,
    MARKET_MAX_LISTINGS,
    MARKET_ORDER_TTL_SECONDS,
    listing_fee,
    resolve_market_item,
    trade_fee,
    validate_market_listing,
    commission_failure_refund,
    commission_platform_fee,
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

    async def create_production_commission(
        self,
        *,
        platform: str,
        platform_user_id: str,
        recipe_key: str,
        reward_stones: int,
        material_mode: str,
        operation_id: str,
    ) -> ProductionCommissionRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._commission_create_once,
                platform,
                platform_user_id,
                recipe_key,
                reward_stones,
                material_mode,
                operation_id,
            )

    async def list_production_commissions(
        self, *, platform: str, platform_user_id: str
    ) -> tuple[ProductionCommissionRecord, ...]:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._commission_list_once, platform, platform_user_id)

    async def accept_production_commission(
        self,
        *,
        platform: str,
        platform_user_id: str,
        commission_id: str,
        operation_id: str,
    ) -> ProductionCommissionRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._commission_accept_once, platform, platform_user_id, commission_id, operation_id
            )

    async def deliver_production_commission(
        self,
        *,
        platform: str,
        platform_user_id: str,
        commission_id: str,
        operation_id: str,
        recovery: bool = False,
    ) -> ProductionCommissionRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._commission_deliver_once,
                platform,
                platform_user_id,
                commission_id,
                operation_id,
                recovery,
            )

    async def settle_production_commission(
        self,
        *,
        platform: str,
        platform_user_id: str,
        commission_id: str,
        operation_id: str,
    ) -> ProductionCommissionRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._commission_settle_once, platform, platform_user_id, commission_id, operation_id
            )

    async def cancel_production_commission(
        self,
        *,
        platform: str,
        platform_user_id: str,
        commission_id: str,
        operation_id: str,
    ) -> ProductionCommissionRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._commission_cancel_once, platform, platform_user_id, commission_id, operation_id
            )

    async def expire_production_commission(
        self,
        *,
        platform: str,
        platform_user_id: str,
        commission_id: str,
        operation_id: str,
    ) -> ProductionCommissionRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._commission_expire_once, platform, platform_user_id, commission_id, operation_id
            )

    async def recover_production_commission(
        self,
        *,
        platform: str,
        platform_user_id: str,
        commission_id: str,
        operation_id: str,
    ) -> ProductionCommissionRecord:
        """Settle a processing commission after its recovery grace period."""

        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._commission_deliver_once,
                platform,
                platform_user_id,
                commission_id,
                operation_id,
                True,
            )

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

    # Production commissions intentionally live beside, rather than inside,
    # the personal production repository.  They have a second actor, escrow,
    # and a delivery confirmation boundary that personal orders do not have.
    @staticmethod
    def _commission_recipe(recipe_key: str):
        from ..production.rules import recipe_definition

        try:
            recipe = recipe_definition(recipe_key)
        except ValueError as exc:
            from ..persistence.errors import CommissionRecipeForbiddenError

            raise CommissionRecipeForbiddenError("recipe is not available for commissions") from exc
        if recipe.key not in COMMISSION_RECIPES:
            from ..persistence.errors import CommissionRecipeForbiddenError

            raise CommissionRecipeForbiddenError("recipe is not available for commissions")
        return recipe

    @staticmethod
    def _commission_mode(value: str) -> str:
        aliases = {
            "producer_supplies": "producer_supplies",
            "producer": "producer_supplies",
            "生产者供料": "producer_supplies",
            "自备材料": "producer_supplies",
            "publisher_supplies": "publisher_supplies",
            "publisher": "publisher_supplies",
            "委托人供料": "publisher_supplies",
            "委托方供料": "publisher_supplies",
        }
        try:
            return aliases[value.strip()]
        except (KeyError, AttributeError) as exc:
            from ..persistence.errors import CommissionRequirementError

            raise CommissionRequirementError("unsupported material mode") from exc

    def _commission_create_once(
        self,
        platform: str,
        platform_user_id: str,
        recipe_key: str,
        reward_stones: int,
        material_mode: str,
        operation_id: str,
    ) -> ProductionCommissionRecord:
        from ..persistence.errors import CommissionEscrowConflictError, CommissionRequirementError

        recipe = self._commission_recipe(recipe_key)
        mode = self._commission_mode(material_mode)
        try:
            reward = int(reward_stones)
        except (TypeError, ValueError) as exc:
            raise CommissionRequirementError("reward is invalid") from exc
        if not COMMISSION_MIN_REWARD <= reward <= COMMISSION_MAX_REWARD:
            raise CommissionRequirementError("reward is outside the commission range")
        operation_name = "economy.create_production_commission"
        request_hash = self._request_hash(
            operation_name,
            {
                "platform": platform,
                "platform_user_id": platform_user_id,
                "recipe_key": recipe.key,
                "reward_stones": reward,
                "material_mode": mode,
            },
        )
        now = self._now()
        now_text = serialize_datetime(now)
        expires_at = serialize_datetime(now + timedelta(seconds=COMMISSION_TTL_SECONDS))
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._commission_operation(connection, operation_id, operation_name, request_hash)
            if existing is not None:
                return self._commission_record_from_payload(existing, replay=True)
            publisher = self._require_player(connection, platform, platform_user_id)
            if int(publisher["spirit_stones"]) < reward:
                raise CommissionEscrowConflictError("reward cannot be escrowed")
            inventory = self._json_object(publisher["inventory_json"], {})
            publisher_inputs = dict(recipe.inputs) if mode == "publisher_supplies" else {}
            if publisher_inputs:
                missing = {
                    key: quantity - int(inventory.get(key, 0))
                    for key, quantity in publisher_inputs.items()
                    if int(inventory.get(key, 0)) < quantity
                }
                if missing:
                    raise CommissionRequirementError("publisher materials are insufficient")
                for key, quantity in publisher_inputs.items():
                    inventory[key] = int(inventory[key]) - quantity
                    if inventory[key] <= 0:
                        inventory.pop(key, None)
            commission_id = f"commission-{uuid4().hex}"
            snapshot = {
                "recipe_key": recipe.key,
                "recipe_name": recipe.name,
                "rule_version": ECONOMY_RULE_VERSION,
                "material_mode": mode,
                "publisher_inputs": publisher_inputs,
                "producer_inputs": dict(recipe.inputs) if mode == "producer_supplies" else {},
                "publisher_player_id": int(publisher["id"]),
                "reward_stones": reward,
            }
            connection.execute(
                """
                INSERT INTO production_commission_orders(
                    commission_id, publisher_player_id, producer_player_id, recipe_key,
                    reward_stones, material_mode, status, published_at, accepted_at,
                    starts_at, ends_at, expires_at, settled_at, snapshot_json, result_json,
                    created_at, updated_at
                ) VALUES (?, ?, NULL, ?, ?, ?, 'published', ?, NULL, NULL, NULL, ?, NULL, ?, '{}', ?, ?)
                """,
                (
                    commission_id,
                    publisher["id"],
                    recipe.key,
                    reward,
                    mode,
                    now_text,
                    expires_at,
                    json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
                    now_text,
                    now_text,
                ),
            )
            if publisher_inputs:
                for key, quantity in publisher_inputs.items():
                    self._commission_insert_lock(
                        connection, commission_id, int(publisher["id"]), "item", key, quantity, now_text
                    )
            connection.execute(
                "UPDATE players SET spirit_stones = spirit_stones - ?, inventory_json = ?, updated_at = ? WHERE id = ?",
                (
                    reward,
                    json.dumps(inventory, ensure_ascii=False, sort_keys=True),
                    now_text,
                    publisher["id"],
                ),
            )
            self._commission_ledger(
                connection,
                operation_id,
                int(publisher["id"]),
                "currency",
                "currency.spirit_stone",
                "commission.escrow",
                "debit",
                reward,
                int(publisher["spirit_stones"]),
                int(publisher["spirit_stones"]) - reward,
                commission_id,
                now_text,
            )
            for key, quantity in publisher_inputs.items():
                self._commission_ledger(
                    connection,
                    operation_id,
                    int(publisher["id"]),
                    "item",
                    key,
                    "commission.material_lock",
                    "lock",
                    quantity,
                    int(inventory.get(key, 0)) + quantity,
                    int(inventory.get(key, 0)),
                    commission_id,
                    now_text,
                )
            payload = self._commission_payload(connection, commission_id)
            self._commission_record_operation(
                connection,
                operation_id,
                operation_name,
                int(publisher["id"]),
                request_hash,
                payload,
                now_text,
            )
            return self._commission_record_from_payload(payload)

    def _commission_list_once(self, platform: str, platform_user_id: str) -> tuple[ProductionCommissionRecord, ...]:
        with self._connect() as connection:
            self._require_player(connection, platform, platform_user_id, writable=False)
            now_text = serialize_datetime(self._now())
            rows = connection.execute(
                "SELECT commission_id FROM production_commission_orders WHERE status = 'published' AND expires_at > ? ORDER BY published_at, id",
                (now_text,),
            ).fetchall()
            return tuple(
                self._commission_record_from_payload(self._commission_payload(connection, row["commission_id"]))
                for row in rows
            )

    def _commission_accept_once(
        self, platform: str, platform_user_id: str, commission_id: str, operation_id: str
    ) -> ProductionCommissionRecord:
        from ..persistence.errors import (
            CommissionExpiredError,
            CommissionRequirementError,
            CommissionSelfAcceptError,
            CommissionStateConflictError,
        )
        from ..production.rules import TOOL_MAX_DURABILITY_BP, random_quality_bp

        operation_name = "economy.accept_production_commission"
        request_hash = self._request_hash(
            operation_name,
            {"platform": platform, "platform_user_id": platform_user_id, "commission_id": commission_id},
        )
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._commission_operation(connection, operation_id, operation_name, request_hash)
            if existing is not None:
                return self._commission_record_from_payload(existing, replay=True)
            producer = self._require_player(connection, platform, platform_user_id)
            order = connection.execute(
                "SELECT * FROM production_commission_orders WHERE commission_id = ?", (commission_id,)
            ).fetchone()
            if order is None:
                from ..persistence.errors import CommissionNotFoundError

                raise CommissionNotFoundError("commission does not exist")
            if int(order["publisher_player_id"]) == int(producer["id"]):
                raise CommissionSelfAcceptError("publisher cannot accept own commission")
            if str(order["status"]) != "published":
                raise CommissionStateConflictError("commission is not published")
            if now >= datetime.fromisoformat(str(order["expires_at"])):
                self._commission_expire_row(connection, order, operation_id, now_text)
                raise CommissionExpiredError("commission has expired")
            active = connection.execute(
                """
                SELECT 1 FROM production_commission_orders
                WHERE producer_player_id = ? AND status IN ('accepted', 'locked', 'processing', 'delivered')
                LIMIT 1
                """,
                (producer["id"],),
            ).fetchone()
            if active is not None:
                raise CommissionStateConflictError("producer already has an active commission")
            recipe = self._commission_recipe(str(order["recipe_key"]))
            try:
                self._check_production_requirements(producer, recipe)
            except Exception as exc:
                raise CommissionRequirementError("producer does not satisfy recipe requirements") from exc
            inventory = self._json_object(producer["inventory_json"], {})
            durability = self._json_object(producer["durability_json"], {})
            mode = str(order["material_mode"])
            producer_inputs = dict(recipe.inputs) if mode == "producer_supplies" else {}
            if producer_inputs:
                for key, quantity in producer_inputs.items():
                    available = int(inventory.get(key, 0)) - self._commission_locked_quantity(
                        connection, int(producer["id"]), "item", key
                    )
                    if available < quantity:
                        raise CommissionRequirementError("producer materials are insufficient")
                for key, quantity in producer_inputs.items():
                    inventory[key] = int(inventory[key]) - quantity
                    if inventory[key] <= 0:
                        inventory.pop(key, None)
            energy_cost = int(recipe.energy_cost)
            locked_energy = self._commission_locked_quantity(connection, int(producer["id"]), "energy", "energy")
            if int(producer["energy"]) - locked_energy < energy_cost:
                raise CommissionRequirementError("producer energy is insufficient")
            tool_before = None
            tool_after = None
            if recipe.tool_key:
                if int(inventory.get(recipe.tool_key, 0)) < 1:
                    raise CommissionRequirementError("producer tool is missing")
                tool_before = int(durability.get(recipe.tool_key, TOOL_MAX_DURABILITY_BP))
                if tool_before < recipe.tool_cost_bp:
                    raise CommissionRequirementError("producer tool durability is insufficient")
                tool_after = tool_before - recipe.tool_cost_bp
                durability[recipe.tool_key] = tool_after
            if producer_inputs:
                for key, quantity in producer_inputs.items():
                    self._commission_insert_lock(
                        connection, commission_id, int(producer["id"]), "item", key, quantity, now_text
                    )
            self._commission_insert_lock(
                connection, commission_id, int(producer["id"]), "energy", "energy", energy_cost, now_text
            )
            if recipe.tool_key:
                self._commission_insert_lock(
                    connection, commission_id, int(producer["id"]), "tool", recipe.tool_key, recipe.tool_cost_bp, now_text
                )
            starts_at = now_text
            ends_at = serialize_datetime(now + timedelta(seconds=recipe.duration_seconds))
            snapshot = self._json_object(order["snapshot_json"], {})
            snapshot.update(
                {
                    "producer_player_id": int(producer["id"]),
                    "producer_inputs": producer_inputs,
                    "energy_cost": energy_cost,
                    "tool_key": recipe.tool_key,
                    "tool_durability_before": tool_before,
                    "tool_durability_after": tool_after,
                    "random_quality_bp": random_quality_bp(operation_id),
                    "material_quality_bp": 10000,
                    "proficiency_bp": 0,
                    "starts_at": starts_at,
                    "ends_at": ends_at,
                }
            )
            connection.execute(
                """
                UPDATE players SET energy = energy - ?, inventory_json = ?, durability_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    energy_cost,
                    json.dumps(inventory, ensure_ascii=False, sort_keys=True),
                    json.dumps(durability, ensure_ascii=False, sort_keys=True),
                    now_text,
                    producer["id"],
                ),
            )
            connection.execute(
                """
                UPDATE production_commission_orders
                SET producer_player_id = ?, status = 'processing', accepted_at = ?, starts_at = ?, ends_at = ?,
                    snapshot_json = ?, updated_at = ?
                WHERE commission_id = ? AND status = 'published'
                """,
                (
                    producer["id"],
                    now_text,
                    starts_at,
                    ends_at,
                    json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
                    now_text,
                    commission_id,
                ),
            )
            self._commission_ledger(
                connection,
                operation_id,
                int(producer["id"]),
                "resource",
                "energy",
                "commission.resource_lock",
                "lock",
                energy_cost,
                int(producer["energy"]),
                int(producer["energy"]) - energy_cost,
                commission_id,
                now_text,
            )
            for key, quantity in producer_inputs.items():
                self._commission_ledger(
                    connection,
                    operation_id,
                    int(producer["id"]),
                    "item",
                    key,
                    "commission.material_lock",
                    "lock",
                    quantity,
                    int(inventory.get(key, 0)) + quantity,
                    int(inventory.get(key, 0)),
                    commission_id,
                    now_text,
                )
            if recipe.tool_key and tool_before is not None and tool_after is not None:
                self._commission_ledger(
                    connection,
                    operation_id,
                    int(producer["id"]),
                    "item",
                    recipe.tool_key,
                    "commission.tool_lock",
                    "lock",
                    recipe.tool_cost_bp,
                    tool_before,
                    tool_after,
                    commission_id,
                    now_text,
                )
            payload = self._commission_payload(connection, commission_id)
            self._commission_record_operation(
                connection,
                operation_id,
                operation_name,
                int(producer["id"]),
                request_hash,
                payload,
                now_text,
            )
            return self._commission_record_from_payload(payload)

    def _commission_deliver_once(
        self,
        platform: str,
        platform_user_id: str,
        commission_id: str,
        operation_id: str,
        recovery: bool,
    ) -> ProductionCommissionRecord:
        from ..persistence.errors import CommissionDeliveryError, CommissionExpiredError, CommissionNotFoundError
        from ..production.rules import HIGH_QUALITY_THRESHOLD_BP, QUALITY_SUCCESS_THRESHOLD_BP, production_quality, recipe_definition

        operation_name = "economy.recover_production_commission" if recovery else "economy.deliver_production_commission"
        request_hash = self._request_hash(
            operation_name,
            {"platform": platform, "platform_user_id": platform_user_id, "commission_id": commission_id},
        )
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._commission_operation(connection, operation_id, operation_name, request_hash)
            if existing is not None:
                return self._commission_record_from_payload(existing, replay=True)
            producer = self._require_player(connection, platform, platform_user_id)
            order = connection.execute(
                "SELECT * FROM production_commission_orders WHERE commission_id = ?", (commission_id,)
            ).fetchone()
            if order is None:
                raise CommissionNotFoundError("commission does not exist")
            if int(order["producer_player_id"] or 0) != int(producer["id"]):
                raise CommissionDeliveryError("only the producer can deliver the commission")
            if str(order["status"]) != "processing":
                raise CommissionDeliveryError("commission is not processing")
            ends_at = datetime.fromisoformat(str(order["ends_at"]))
            if not recovery and now < ends_at:
                raise CommissionDeliveryError("commission is not ready")
            if not recovery and now > ends_at + timedelta(seconds=COMMISSION_RECOVERY_GRACE_SECONDS):
                raise CommissionExpiredError("commission requires recovery")
            if recovery and now <= ends_at + timedelta(seconds=COMMISSION_RECOVERY_GRACE_SECONDS):
                raise CommissionDeliveryError("commission is not ready for recovery")
            recipe = recipe_definition(str(order["recipe_key"]))
            snapshot = self._json_object(order["snapshot_json"], {})
            quality = production_quality(
                material_quality_bp=int(snapshot.get("material_quality_bp", 10000)),
                proficiency_bp=int(snapshot.get("proficiency_bp", 0)),
                tool_durability_bp=int(snapshot.get("tool_durability_before", 0) or 0),
                random_quality_bp_value=int(snapshot.get("random_quality_bp", 0)),
            )
            success = quality >= QUALITY_SUCCESS_THRESHOLD_BP
            outputs: dict[str, int] = {}
            refunds: dict[str, int] = {}
            result: dict[str, Any] = {
                "quality_bp": quality,
                "random_quality_bp": int(snapshot.get("random_quality_bp", 0)),
                "success": success,
                "outputs": outputs,
                "refunds": refunds,
                "recovered": recovery,
            }
            if success:
                outputs.update(recipe.outputs)
                if quality >= HIGH_QUALITY_THRESHOLD_BP:
                    for key, quantity in recipe.high_quality_bonus.items():
                        outputs[key] = outputs.get(key, 0) + quantity
                self._commission_delete_locks(connection, commission_id)
                status = "delivered"
                result.update({"status": status, "producer_payment": 0, "publisher_refund": 0, "platform_fee": 0})
            else:
                input_owner = int(order["publisher_player_id"]) if str(order["material_mode"]) == "publisher_supplies" else int(order["producer_player_id"])
                for key, quantity in recipe.failure_refunds.items():
                    if int(quantity) > 0:
                        refunds[key] = int(quantity)
                self._commission_refund_materials(
                    connection, commission_id, input_owner, refunds, operation_id, now_text
                )
                publisher_refund = commission_failure_refund(int(order["reward_stones"]))
                self._commission_refund_escrow(
                    connection, order, publisher_refund, operation_id, now_text, reason="commission.failure_refund"
                )
                status = "failed"
                result.update(
                    {
                        "status": status,
                        "producer_payment": 0,
                        "publisher_refund": publisher_refund,
                        "platform_fee": int(order["reward_stones"]) - publisher_refund,
                    }
                )
            connection.execute(
                "UPDATE production_commission_orders SET status = ?, result_json = ?, settled_at = ?, updated_at = ? WHERE commission_id = ? AND status = 'processing'",
                (status, json.dumps(result, ensure_ascii=False, sort_keys=True), now_text, now_text, commission_id),
            )
            payload = self._commission_payload(connection, commission_id)
            self._commission_record_operation(
                connection,
                operation_id,
                operation_name,
                int(producer["id"]),
                request_hash,
                payload,
                now_text,
            )
            return self._commission_record_from_payload(payload)

    def _commission_settle_once(
        self, platform: str, platform_user_id: str, commission_id: str, operation_id: str
    ) -> ProductionCommissionRecord:
        from ..persistence.errors import CommissionDeliveryError, CommissionNotFoundError

        operation_name = "economy.settle_production_commission"
        request_hash = self._request_hash(
            operation_name,
            {"platform": platform, "platform_user_id": platform_user_id, "commission_id": commission_id},
        )
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._commission_operation(connection, operation_id, operation_name, request_hash)
            if existing is not None:
                return self._commission_record_from_payload(existing, replay=True)
            publisher = self._require_player(connection, platform, platform_user_id)
            order = connection.execute(
                "SELECT * FROM production_commission_orders WHERE commission_id = ?", (commission_id,)
            ).fetchone()
            if order is None:
                raise CommissionNotFoundError("commission does not exist")
            if int(order["publisher_player_id"]) != int(publisher["id"]):
                raise CommissionDeliveryError("only the publisher can confirm delivery")
            if str(order["status"]) != "delivered":
                raise CommissionDeliveryError("commission is not awaiting delivery confirmation")
            result = self._json_object(order["result_json"], {})
            outputs = self._json_object(result.get("outputs", {}), {})
            producer = connection.execute("SELECT * FROM players WHERE id = ?", (order["producer_player_id"],)).fetchone()
            if producer is None:
                raise CommissionNotFoundError("producer does not exist")
            publisher_inventory = self._json_object(publisher["inventory_json"], {})
            for key, quantity in outputs.items():
                publisher_inventory[key] = int(publisher_inventory.get(key, 0)) + int(quantity)
            reward = int(order["reward_stones"])
            payment = reward - commission_platform_fee(reward)
            fee = reward - payment
            producer_before = int(producer["spirit_stones"])
            connection.execute(
                "UPDATE players SET inventory_json = ?, updated_at = ? WHERE id = ?",
                (json.dumps(publisher_inventory, ensure_ascii=False, sort_keys=True), now_text, publisher["id"]),
            )
            connection.execute(
                "UPDATE players SET spirit_stones = spirit_stones + ?, updated_at = ? WHERE id = ?",
                (payment, now_text, producer["id"]),
            )
            for key, quantity in outputs.items():
                self._commission_ledger(
                    connection,
                    operation_id,
                    int(publisher["id"]),
                    "item",
                    key,
                    "commission.settlement",
                    "credit",
                    int(quantity),
                    int(publisher_inventory.get(key, 0)) - int(quantity),
                    int(publisher_inventory.get(key, 0)),
                    commission_id,
                    now_text,
                )
            self._commission_ledger(
                connection,
                operation_id,
                int(producer["id"]),
                "currency",
                "currency.spirit_stone",
                "commission.settlement",
                "credit",
                payment,
                producer_before,
                producer_before + payment,
                commission_id,
                now_text,
            )
            if fee:
                self._commission_ledger(
                    connection,
                    operation_id,
                    int(publisher["id"]),
                    "currency",
                    "currency.spirit_stone",
                    "commission.platform_fee",
                    "debit",
                    fee,
                    0,
                    0,
                    commission_id,
                    now_text,
                )
            result.update({"status": "settled", "producer_payment": payment, "platform_fee": fee})
            connection.execute(
                "UPDATE production_commission_orders SET status = 'settled', settled_at = ?, result_json = ?, updated_at = ? WHERE commission_id = ? AND status = 'delivered'",
                (now_text, json.dumps(result, ensure_ascii=False, sort_keys=True), now_text, commission_id),
            )
            payload = self._commission_payload(connection, commission_id)
            self._commission_record_operation(
                connection,
                operation_id,
                operation_name,
                int(publisher["id"]),
                request_hash,
                payload,
                now_text,
            )
            return self._commission_record_from_payload(payload)

    def _commission_cancel_once(
        self, platform: str, platform_user_id: str, commission_id: str, operation_id: str
    ) -> ProductionCommissionRecord:
        from ..persistence.errors import CommissionDeliveryError, CommissionNotFoundError, CommissionStateConflictError

        operation_name = "economy.cancel_production_commission"
        request_hash = self._request_hash(
            operation_name,
            {"platform": platform, "platform_user_id": platform_user_id, "commission_id": commission_id},
        )
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._commission_operation(connection, operation_id, operation_name, request_hash)
            if existing is not None:
                return self._commission_record_from_payload(existing, replay=True)
            actor = self._require_player(connection, platform, platform_user_id)
            order = connection.execute(
                "SELECT * FROM production_commission_orders WHERE commission_id = ?", (commission_id,)
            ).fetchone()
            if order is None:
                raise CommissionNotFoundError("commission does not exist")
            status = str(order["status"])
            is_publisher = int(order["publisher_player_id"]) == int(actor["id"])
            is_producer = int(order["producer_player_id"] or 0) == int(actor["id"])
            if status == "published" and is_publisher:
                pass
            elif status in {"accepted", "locked", "processing"} and is_producer:
                pass
            else:
                raise CommissionStateConflictError("commission cannot be cancelled by this actor")
            self._commission_restore_locks(connection, commission_id, operation_id, now_text)
            self._commission_refund_escrow(
                connection, order, int(order["reward_stones"]), operation_id, now_text, reason="commission.cancel_refund"
            )
            result = {"status": "cancelled", "publisher_refund": int(order["reward_stones"]), "producer_payment": 0, "platform_fee": 0}
            connection.execute(
                "UPDATE production_commission_orders SET status = 'cancelled', result_json = ?, settled_at = ?, updated_at = ? WHERE commission_id = ?",
                (json.dumps(result, ensure_ascii=False, sort_keys=True), now_text, now_text, commission_id),
            )
            payload = self._commission_payload(connection, commission_id)
            self._commission_record_operation(
                connection,
                operation_id,
                operation_name,
                int(actor["id"]),
                request_hash,
                payload,
                now_text,
            )
            return self._commission_record_from_payload(payload)

    def _commission_expire_once(
        self, platform: str, platform_user_id: str, commission_id: str, operation_id: str
    ) -> ProductionCommissionRecord:
        from ..persistence.errors import CommissionExpiredError, CommissionNotFoundError, CommissionStateConflictError

        operation_name = "economy.expire_production_commission"
        request_hash = self._request_hash(
            operation_name,
            {"platform": platform, "platform_user_id": platform_user_id, "commission_id": commission_id},
        )
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._commission_operation(connection, operation_id, operation_name, request_hash)
            if existing is not None:
                return self._commission_record_from_payload(existing, replay=True)
            actor = self._require_player(connection, platform, platform_user_id, writable=False)
            order = connection.execute(
                "SELECT * FROM production_commission_orders WHERE commission_id = ?", (commission_id,)
            ).fetchone()
            if order is None:
                raise CommissionNotFoundError("commission does not exist")
            if str(order["status"]) == "expired":
                payload = self._commission_payload(connection, commission_id)
                self._commission_record_operation(connection, operation_id, operation_name, int(actor["id"]), request_hash, payload, now_text)
                return self._commission_record_from_payload(payload)
            if str(order["status"]) != "published":
                raise CommissionStateConflictError("only unpublished commissions expire here")
            if now < datetime.fromisoformat(str(order["expires_at"])):
                raise CommissionExpiredError("commission has not expired")
            self._commission_expire_row(connection, order, operation_id, now_text)
            payload = self._commission_payload(connection, commission_id)
            self._commission_record_operation(connection, operation_id, operation_name, int(actor["id"]), request_hash, payload, now_text)
            return self._commission_record_from_payload(payload)

    @staticmethod
    def _commission_insert_lock(
        connection: Any,
        commission_id: str,
        player_id: int,
        asset_kind: str,
        asset_key: str,
        quantity: int,
        now_text: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO production_commission_locks(
                commission_id, player_id, asset_kind, asset_key, quantity, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (commission_id, player_id, asset_kind, asset_key, quantity, now_text, now_text),
        )

    @staticmethod
    def _commission_locked_quantity(connection: Any, player_id: int, asset_kind: str, asset_key: str) -> int:
        row = connection.execute(
            """
            SELECT COALESCE(SUM(quantity), 0) FROM production_commission_locks
            WHERE player_id = ? AND asset_kind = ? AND asset_key = ?
            """,
            (player_id, asset_kind, asset_key),
        ).fetchone()
        return int(row[0])

    def _commission_restore_locks(self, connection: Any, commission_id: str, operation_id: str, now_text: str) -> None:
        rows = connection.execute(
            "SELECT * FROM production_commission_locks WHERE commission_id = ? ORDER BY id", (commission_id,)
        ).fetchall()
        for lock in rows:
            player = connection.execute("SELECT * FROM players WHERE id = ?", (lock["player_id"],)).fetchone()
            if player is None:
                continue
            quantity = int(lock["quantity"])
            kind = str(lock["asset_kind"])
            key = str(lock["asset_key"])
            if kind == "item":
                inventory = self._json_object(player["inventory_json"], {})
                before = int(inventory.get(key, 0))
                inventory[key] = before + quantity
                connection.execute(
                    "UPDATE players SET inventory_json = ?, updated_at = ? WHERE id = ?",
                    (json.dumps(inventory, ensure_ascii=False, sort_keys=True), now_text, player["id"]),
                )
                self._commission_ledger(
                    connection, operation_id, int(player["id"]), "item", key,
                    "commission.lock_release", "release", quantity, before, before + quantity,
                    commission_id, now_text,
                )
            elif kind == "energy" and key == "energy":
                before = int(player["energy"])
                connection.execute(
                    "UPDATE players SET energy = energy + ?, updated_at = ? WHERE id = ?",
                    (quantity, now_text, player["id"]),
                )
                self._commission_ledger(
                    connection, operation_id, int(player["id"]), "resource", key,
                    "commission.lock_release", "release", quantity, before, before + quantity,
                    commission_id, now_text,
                )
            elif kind == "tool":
                durability = self._json_object(player["durability_json"], {})
                before = int(durability.get(key, 0))
                durability[key] = before + quantity
                connection.execute(
                    "UPDATE players SET durability_json = ?, updated_at = ? WHERE id = ?",
                    (json.dumps(durability, ensure_ascii=False, sort_keys=True), now_text, player["id"]),
                )
                self._commission_ledger(
                    connection, operation_id, int(player["id"]), "item", key,
                    "commission.lock_release", "release", quantity, before, before + quantity,
                    commission_id, now_text,
                )
        self._commission_delete_locks(connection, commission_id)

    @staticmethod
    def _commission_delete_locks(connection: Any, commission_id: str) -> None:
        connection.execute("DELETE FROM production_commission_locks WHERE commission_id = ?", (commission_id,))

    def _commission_refund_materials(
        self,
        connection: Any,
        commission_id: str,
        player_id: int,
        refunds: dict[str, int],
        operation_id: str,
        now_text: str,
    ) -> None:
        player = connection.execute("SELECT * FROM players WHERE id = ?", (player_id,)).fetchone()
        if player is None:
            return
        inventory = self._json_object(player["inventory_json"], {})
        for key, quantity in refunds.items():
            before = int(inventory.get(key, 0))
            inventory[key] = before + int(quantity)
            self._commission_ledger(
                connection, operation_id, player_id, "item", key,
                "commission.failure_material_refund", "credit", int(quantity), before, before + int(quantity),
                commission_id, now_text,
            )
        connection.execute(
            "UPDATE players SET inventory_json = ?, updated_at = ? WHERE id = ?",
            (json.dumps(inventory, ensure_ascii=False, sort_keys=True), now_text, player_id),
        )
        self._commission_delete_locks(connection, commission_id)

    def _commission_refund_escrow(
        self,
        connection: Any,
        order: Any,
        amount: int,
        operation_id: str,
        now_text: str,
        *,
        reason: str,
    ) -> None:
        if amount <= 0:
            return
        publisher = connection.execute("SELECT * FROM players WHERE id = ?", (order["publisher_player_id"],)).fetchone()
        if publisher is None:
            return
        before = int(publisher["spirit_stones"])
        connection.execute(
            "UPDATE players SET spirit_stones = spirit_stones + ?, updated_at = ? WHERE id = ?",
            (amount, now_text, publisher["id"]),
        )
        self._commission_ledger(
            connection, operation_id, int(publisher["id"]), "currency", "currency.spirit_stone",
            reason, "credit", amount, before, before + amount, str(order["commission_id"]), now_text,
        )

    def _commission_expire_row(self, connection: Any, order: Any, operation_id: str, now_text: str) -> None:
        self._commission_restore_locks(connection, str(order["commission_id"]), operation_id, now_text)
        self._commission_refund_escrow(
            connection,
            order,
            int(order["reward_stones"]),
            operation_id,
            now_text,
            reason="commission.expiry_refund",
        )
        result = {"status": "expired", "publisher_refund": int(order["reward_stones"]), "producer_payment": 0, "platform_fee": 0}
        connection.execute(
            "UPDATE production_commission_orders SET status = 'expired', result_json = ?, settled_at = ?, updated_at = ? WHERE commission_id = ? AND status = 'published'",
            (json.dumps(result, ensure_ascii=False, sort_keys=True), now_text, now_text, order["commission_id"]),
        )

    @staticmethod
    def _commission_ledger(
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
    def _commission_operation(connection: Any, operation_id: str, operation_name: str, request_hash: str) -> dict[str, Any] | None:
        existing = connection.execute(
            "SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id = ?", (operation_id,)
        ).fetchone()
        if existing is None:
            return None
        if existing["operation_name"] != operation_name or existing["request_hash"] != request_hash:
            raise OperationConflictError("operation input differs from its original request")
        return json.loads(existing["result_json"])

    @staticmethod
    def _commission_record_operation(
        connection: Any,
        operation_id: str,
        operation_name: str,
        player_id: int,
        request_hash: str,
        payload: dict[str, Any],
        now_text: str,
    ) -> None:
        connection.execute(
            "INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (operation_id, operation_name, player_id, request_hash, json.dumps(payload, ensure_ascii=False, sort_keys=True), now_text),
        )

    @staticmethod
    def _commission_payload(connection: Any, commission_id: str) -> dict[str, Any]:
        from ..production.rules import recipe_definition

        row = connection.execute(
            """
            SELECT o.*, p.player_id AS publisher_stable_id, p.platform_user_id AS publisher_platform_user_id,
                   p.dao_name AS publisher_dao_name, q.player_id AS producer_stable_id,
                   q.platform_user_id AS producer_platform_user_id, q.dao_name AS producer_dao_name
            FROM production_commission_orders o
            JOIN players p ON p.id = o.publisher_player_id
            LEFT JOIN players q ON q.id = o.producer_player_id
            WHERE o.commission_id = ?
            """,
            (commission_id,),
        ).fetchone()
        if row is None:
            from ..persistence.errors import CommissionNotFoundError

            raise CommissionNotFoundError("commission does not exist")
        result = json.loads(str(row["result_json"] or "{}"))
        recipe = recipe_definition(str(row["recipe_key"]))
        return {
            "commission_id": str(row["commission_id"]),
            "status": str(row["status"]),
            "publisher_player_id": str(row["publisher_stable_id"]),
            "publisher_platform_user_id": str(row["publisher_platform_user_id"]),
            "publisher_dao_name": str(row["publisher_dao_name"] or "未命名"),
            "producer_player_id": str(row["producer_stable_id"]) if row["producer_stable_id"] else None,
            "producer_platform_user_id": str(row["producer_platform_user_id"]) if row["producer_platform_user_id"] else None,
            "producer_dao_name": str(row["producer_dao_name"] or "未命名") if row["producer_stable_id"] else None,
            "recipe_key": str(row["recipe_key"]),
            "recipe_name": recipe.name,
            "reward_stones": int(row["reward_stones"]),
            "material_mode": str(row["material_mode"]),
            "starts_at": str(row["starts_at"]) if row["starts_at"] else None,
            "ends_at": str(row["ends_at"]) if row["ends_at"] else None,
            "expires_at": str(row["expires_at"]),
            "outputs": {str(key): int(value) for key, value in result.get("outputs", {}).items()},
            "refunds": {str(key): int(value) for key, value in result.get("refunds", {}).items()},
            "producer_payment": int(result.get("producer_payment", 0)),
            "publisher_refund": int(result.get("publisher_refund", 0)),
            "platform_fee": int(result.get("platform_fee", 0)),
            "quality_bp": int(result["quality_bp"]) if result.get("quality_bp") is not None else None,
        }

    @staticmethod
    def _commission_record_from_payload(payload: dict[str, Any], *, replay: bool = False) -> ProductionCommissionRecord:
        return ProductionCommissionRecord(
            commission_id=str(payload["commission_id"]),
            status=str(payload["status"]),
            publisher_player_id=str(payload["publisher_player_id"]),
            publisher_platform_user_id=str(payload["publisher_platform_user_id"]),
            publisher_dao_name=str(payload["publisher_dao_name"]),
            producer_player_id=payload.get("producer_player_id"),
            producer_platform_user_id=payload.get("producer_platform_user_id"),
            producer_dao_name=payload.get("producer_dao_name"),
            recipe_key=str(payload["recipe_key"]),
            recipe_name=str(payload["recipe_name"]),
            reward_stones=int(payload["reward_stones"]),
            material_mode=str(payload["material_mode"]),
            starts_at=payload.get("starts_at"),
            ends_at=payload.get("ends_at"),
            expires_at=str(payload["expires_at"]),
            outputs={str(key): int(value) for key, value in payload.get("outputs", {}).items()},
            refunds={str(key): int(value) for key, value in payload.get("refunds", {}).items()},
            producer_payment=int(payload.get("producer_payment", 0)),
            publisher_refund=int(payload.get("publisher_refund", 0)),
            platform_fee=int(payload.get("platform_fee", 0)),
            quality_bp=int(payload["quality_bp"]) if payload.get("quality_bp") is not None else None,
            already_completed=replay,
        )


__all__ = ["EconomyRepositoryMixin"]
