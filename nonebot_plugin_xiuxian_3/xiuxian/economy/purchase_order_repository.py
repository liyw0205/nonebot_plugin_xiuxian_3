"""SQLite transactions for cross-realm purchase orders.

The buyer escrow and seller item lock live in separate rows so every state
transition can release both assets atomically and be replayed by operation ID.
"""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from typing import Any
from uuid import uuid4

from ...contracts import serialize_datetime
from ..persistence.errors import (
    BalanceInsufficientError,
    ItemBindingActiveError,
    OperationConflictError,
    PlayerNotFoundError,
    PurchaseBuyerCapacityInsufficientError,
    PurchaseDeliveryExpiredError,
    PurchaseEscrowInsufficientError,
    PurchaseItemForbiddenError,
    PurchaseItemLockedError,
    PurchaseOrderCapError,
    PurchaseOrderExpiredError,
    PurchaseOrderNotFoundError,
    PurchaseOrderStateConflictError,
    PurchasePermissionDeniedError,
    PurchaseSelfMatchError,
)
from .purchase_order_models import PurchaseOrderRecord
from .purchase_order_rules import (
    CONTENT_VERSION,
    PURCHASE_ORDER_TTL_SECONDS,
    PURCHASE_MAX_LISTINGS,
    RULE_VERSION,
    delivery_deadline,
    faction_for_location,
    order_region,
    purchase_fee,
    required_faction_reputation,
    resolve_purchase_item,
    validate_purchase_order,
)


class PurchaseOrderRepositoryMixin:
    async def create_purchase_order(
        self,
        *,
        platform: str,
        platform_user_id: str,
        item_key: str,
        quantity: int,
        unit_price: int,
        operation_id: str,
        cross_realm: bool = True,
    ) -> PurchaseOrderRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._create_purchase_order_once,
                platform,
                platform_user_id,
                item_key,
                quantity,
                unit_price,
                operation_id,
                cross_realm,
            )

    async def match_purchase_order(
        self, *, platform: str, platform_user_id: str, order_id: str, operation_id: str
    ) -> PurchaseOrderRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._match_purchase_order_once, platform, platform_user_id, order_id, operation_id
            )

    async def deliver_purchase_order(
        self, *, platform: str, platform_user_id: str, order_id: str, operation_id: str
    ) -> PurchaseOrderRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._deliver_purchase_order_once, platform, platform_user_id, order_id, operation_id
            )

    async def cancel_purchase_order(
        self, *, platform: str, platform_user_id: str, order_id: str, operation_id: str
    ) -> PurchaseOrderRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._cancel_purchase_order_once, platform, platform_user_id, order_id, operation_id
            )

    async def expire_purchase_order(
        self, *, platform: str, platform_user_id: str, order_id: str, operation_id: str
    ) -> PurchaseOrderRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._expire_purchase_order_once, platform, platform_user_id, order_id, operation_id
            )

    async def recover_purchase_order(
        self, *, platform: str, platform_user_id: str, order_id: str, operation_id: str
    ) -> PurchaseOrderRecord:
        return await self.expire_purchase_order(
            platform=platform,
            platform_user_id=platform_user_id,
            order_id=order_id,
            operation_id=operation_id,
        )

    async def list_purchase_orders(
        self, *, platform: str, platform_user_id: str
    ) -> tuple[PurchaseOrderRecord, ...]:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._list_purchase_orders_once, platform, platform_user_id)

    def _create_purchase_order_once(
        self,
        platform: str,
        platform_user_id: str,
        item_key: str,
        quantity: int,
        unit_price: int,
        operation_id: str,
        cross_realm: bool,
    ) -> PurchaseOrderRecord:
        try:
            item = resolve_purchase_item(item_key)
            validate_purchase_order(int(quantity), int(unit_price))
        except ValueError as exc:
            if "item" in str(exc):
                raise PurchaseItemForbiddenError(str(exc)) from exc
            raise PurchaseOrderStateConflictError(str(exc)) from exc
        total = int(quantity) * int(unit_price)
        fee = purchase_fee(total)
        escrow = total + fee
        operation_name = "economy.create_purchase_order"
        request_hash = self._request_hash(
            operation_name,
            {
                "platform": platform,
                "platform_user_id": platform_user_id,
                "item_key": item.key,
                "quantity": int(quantity),
                "unit_price": int(unit_price),
                "cross_realm": bool(cross_realm),
            },
        )
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._purchase_operation(connection, operation_id, operation_name, request_hash)
            if existing is not None:
                return self._purchase_record_from_payload(existing, replay=True)
            buyer = self._require_player(connection, platform, platform_user_id)
            if cross_realm:
                self._check_cross_realm_permission(buyer)
            active_count = connection.execute(
                "SELECT COUNT(*) FROM purchase_orders WHERE buyer_player_id=? AND status IN ('listed', 'matched', 'delivered')",
                (buyer["id"],),
            ).fetchone()[0]
            if int(active_count) >= PURCHASE_MAX_LISTINGS:
                raise PurchaseOrderCapError("purchase order limit reached")
            if int(buyer["spirit_stones"]) < escrow:
                raise PurchaseEscrowInsufficientError("purchase escrow is insufficient")
            buyer_faction = faction_for_location(str(buyer["location_key"]))
            alliance_key = self._alliance_key(buyer)
            order_id = f"purchase-{uuid4().hex}"
            expires_at = now + timedelta(seconds=PURCHASE_ORDER_TTL_SECONDS)
            snapshot = {
                "content_version": CONTENT_VERSION,
                "rule_version": RULE_VERSION,
                "buyer_faction": buyer_faction,
                "buyer_location": str(buyer["location_key"]),
                "alliance_key": alliance_key,
                "item_key": item.key,
                "quantity": int(quantity),
                "unit_price": int(unit_price),
                "purchase_fee_bp": 800,
                "cross_realm": bool(cross_realm),
            }
            connection.execute(
                """
                INSERT INTO purchase_orders(
                    order_id, buyer_player_id, seller_player_id, item_key, quantity,
                    unit_price, purchase_fee, total_price, escrow_amount,
                    buyer_faction, seller_faction, item_region, item_source_location,
                    first_binding_expires_at, alliance_key, status, expires_at,
                    delivery_deadline, snapshot_json, result_json, created_at, updated_at
                ) VALUES (?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, NULL, ?, 'listed', ?, NULL, ?, '{}', ?, ?)
                """,
                (
                    order_id,
                    buyer["id"],
                    item.key,
                    int(quantity),
                    int(unit_price),
                    fee,
                    total,
                    escrow,
                    buyer_faction,
                    alliance_key,
                    serialize_datetime(expires_at),
                    json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
                    now_text,
                    now_text,
                ),
            )
            connection.execute(
                "INSERT INTO purchase_order_funds(order_id, buyer_player_id, amount, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (order_id, buyer["id"], escrow, now_text, now_text),
            )
            connection.execute(
                "UPDATE players SET spirit_stones=spirit_stones-?, updated_at=? WHERE id=?",
                (escrow, now_text, buyer["id"]),
            )
            self._purchase_ledger(
                connection,
                operation_id,
                int(buyer["id"]),
                "currency",
                "currency.spirit_stone",
                "purchase.escrow_lock",
                "lock",
                escrow,
                int(buyer["spirit_stones"]),
                int(buyer["spirit_stones"]) - escrow,
                order_id,
                now_text,
            )
            payload = self._purchase_payload(connection, order_id)
            self._record_purchase_operation(connection, operation_id, operation_name, int(buyer["id"]), request_hash, payload, now_text)
            return self._purchase_record_from_payload(payload)

    def _match_purchase_order_once(
        self, platform: str, platform_user_id: str, order_id: str, operation_id: str
    ) -> PurchaseOrderRecord:
        operation_name = "economy.match_purchase_order"
        request_hash = self._request_hash(
            operation_name,
            {"platform": platform, "platform_user_id": platform_user_id, "order_id": order_id},
        )
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._purchase_operation(connection, operation_id, operation_name, request_hash)
            if existing is not None:
                return self._purchase_record_from_payload(existing, replay=True)
            seller = self._require_player(connection, platform, platform_user_id)
            order = self._purchase_row(connection, order_id)
            if order is None:
                raise PurchaseOrderNotFoundError("purchase order does not exist")
            if int(order["buyer_player_id"]) == int(seller["id"]):
                raise PurchaseSelfMatchError("buyer cannot match their own order")
            if str(order["status"]) != "listed":
                raise PurchaseOrderStateConflictError("purchase order is not listed")
            if str(order["expires_at"]) <= now_text:
                raise PurchaseOrderExpiredError("purchase order expired")
            item_key = str(order["item_key"])
            quantity = int(order["quantity"])
            inventory = self._json_object(seller["inventory_json"], {})
            locked_market = connection.execute(
                "SELECT COALESCE(SUM(quantity),0) FROM market_item_locks WHERE seller_player_id=? AND item_key=?",
                (seller["id"], item_key),
            ).fetchone()[0]
            locked_auction = connection.execute(
                "SELECT COALESCE(SUM(quantity),0) FROM auction_item_locks WHERE seller_player_id=? AND item_key=?",
                (seller["id"], item_key),
            ).fetchone()[0]
            locked_purchase = connection.execute(
                "SELECT COALESCE(SUM(quantity),0) FROM purchase_item_locks WHERE seller_player_id=? AND item_key=?",
                (seller["id"], item_key),
            ).fetchone()[0]
            available = int(inventory.get(item_key, 0)) - int(locked_market) - int(locked_auction) - int(locked_purchase)
            if available < quantity:
                raise PurchaseItemLockedError("seller inventory is unavailable")
            bound = connection.execute(
                "SELECT COALESCE(SUM(quantity),0) AS quantity, MIN(bound_until) AS first_bound_until FROM item_bindings WHERE player_id=? AND item_key=? AND bound_until>?",
                (seller["id"], item_key, now_text),
            ).fetchone()
            if available - int(bound["quantity"] or 0) < quantity:
                raise ItemBindingActiveError("item binding is still active")
            seller_faction = faction_for_location(str(seller["location_key"]))
            item_region = order_region(str(seller["location_key"]))
            first_binding = str(bound["first_bound_until"]) if bound["first_bound_until"] else None
            connection.execute(
                """
                INSERT INTO purchase_item_locks(order_id, seller_player_id, item_key, quantity, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (order_id, seller["id"], item_key, quantity, now_text, now_text),
            )
            connection.execute(
                """
                UPDATE purchase_orders
                SET seller_player_id=?, seller_faction=?, item_region=?, item_source_location=?,
                    first_binding_expires_at=?, delivery_deadline=?, status='matched', updated_at=?
                WHERE order_id=? AND status='listed'
                """,
                (
                    seller["id"],
                    seller_faction,
                    item_region,
                    str(seller["location_key"]),
                    first_binding,
                    serialize_datetime(delivery_deadline(self._now())),
                    now_text,
                    order_id,
                ),
            )
            self._purchase_ledger(
                connection,
                operation_id,
                int(seller["id"]),
                "item",
                item_key,
                "purchase.item_lock",
                "lock",
                quantity,
                available,
                available - quantity,
                order_id,
                now_text,
            )
            payload = self._purchase_payload(connection, order_id)
            self._record_purchase_operation(connection, operation_id, operation_name, int(seller["id"]), request_hash, payload, now_text)
            return self._purchase_record_from_payload(payload)

    def _deliver_purchase_order_once(
        self, platform: str, platform_user_id: str, order_id: str, operation_id: str
    ) -> PurchaseOrderRecord:
        operation_name = "economy.deliver_purchase_order"
        request_hash = self._request_hash(
            operation_name,
            {"platform": platform, "platform_user_id": platform_user_id, "order_id": order_id},
        )
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._purchase_operation(connection, operation_id, operation_name, request_hash)
            if existing is not None:
                return self._purchase_record_from_payload(existing, replay=True)
            seller_actor = self._require_player(connection, platform, platform_user_id)
            order = self._purchase_row(connection, order_id)
            if order is None:
                raise PurchaseOrderNotFoundError("purchase order does not exist")
            if int(order["seller_player_id"] or 0) != int(seller_actor["id"]):
                raise PurchaseOrderStateConflictError("only the matched seller can deliver")
            if str(order["status"]) != "matched":
                raise PurchaseOrderStateConflictError("purchase order is not matched")
            item_lock = connection.execute("SELECT * FROM purchase_item_locks WHERE order_id=?", (order_id,)).fetchone()
            if item_lock is None:
                raise PurchaseItemLockedError("purchase item lock is missing")
            if str(order["expires_at"]) <= now_text or (order["delivery_deadline"] and str(order["delivery_deadline"]) <= now_text):
                self._release_item_lock(connection, order, item_lock, operation_id, now_text)
                if str(order["expires_at"]) <= now_text:
                    self._refund_funds(connection, order, operation_id, now_text)
                    next_status = "expired"
                    notice = "order_expired"
                else:
                    next_status = "listed"
                    notice = "delivery_expired"
                connection.execute(
                    "UPDATE purchase_orders SET seller_player_id=NULL, delivery_deadline=NULL, status=?, updated_at=? WHERE order_id=?",
                    (next_status, now_text, order_id),
                )
                connection.execute(
                    "UPDATE purchase_orders SET result_json=? WHERE order_id=?",
                    (json.dumps({"notice": notice}, ensure_ascii=False, sort_keys=True), order_id),
                )
                payload = self._purchase_payload(connection, order_id)
                self._record_purchase_operation(connection, operation_id, operation_name, int(seller_actor["id"]), request_hash, payload, now_text)
            else:
                buyer = connection.execute("SELECT * FROM players WHERE id=?", (order["buyer_player_id"],)).fetchone()
                seller = connection.execute("SELECT * FROM players WHERE id=?", (order["seller_player_id"],)).fetchone()
                if buyer is None or seller is None:
                    raise PlayerNotFoundError("purchase participant does not exist")
                seller_inventory = self._json_object(seller["inventory_json"], {})
                buyer_inventory = self._json_object(buyer["inventory_json"], {})
                quantity = int(order["quantity"])
                if int(seller_inventory.get(order["item_key"], 0)) < quantity:
                    self._release_item_lock(connection, order, item_lock, operation_id, now_text)
                    self._refund_funds(connection, order, operation_id, now_text)
                    connection.execute(
                        "UPDATE purchase_orders SET seller_player_id=NULL, delivery_deadline=NULL, status='failed', result_json=?, updated_at=? WHERE order_id=?",
                        (json.dumps({"notice": "delivery_failed"}, ensure_ascii=False, sort_keys=True), now_text, order_id),
                    )
                    payload = self._purchase_payload(connection, order_id)
                    self._record_purchase_operation(connection, operation_id, operation_name, int(seller_actor["id"]), request_hash, payload, now_text)
                    return self._purchase_record_from_payload(payload)
                capacity = int(buyer["carry_capacity"] or 0)
                if capacity > 0 and sum(int(value) for value in buyer_inventory.values()) + quantity > capacity:
                    raise PurchaseBuyerCapacityInsufficientError("buyer inventory capacity is insufficient")
                seller_inventory[order["item_key"]] = int(seller_inventory[order["item_key"]]) - quantity
                if seller_inventory[order["item_key"]] <= 0:
                    seller_inventory.pop(order["item_key"], None)
                buyer_inventory[order["item_key"]] = int(buyer_inventory.get(order["item_key"], 0)) + quantity
                connection.execute(
                    "UPDATE players SET inventory_json=?, spirit_stones=spirit_stones+?, updated_at=? WHERE id=?",
                    (json.dumps(seller_inventory, ensure_ascii=False, sort_keys=True), int(order["total_price"]), now_text, seller["id"]),
                )
                connection.execute(
                    "UPDATE players SET inventory_json=?, updated_at=? WHERE id=?",
                    (json.dumps(buyer_inventory, ensure_ascii=False, sort_keys=True), now_text, buyer["id"]),
                )
                connection.execute("DELETE FROM purchase_item_locks WHERE order_id=?", (order_id,))
                connection.execute("DELETE FROM purchase_order_funds WHERE order_id=?", (order_id,))
                connection.execute(
                    "UPDATE purchase_orders SET status='settled', delivery_deadline=NULL, result_json=?, updated_at=? WHERE order_id=?",
                    (json.dumps({"notice": "settled", "platform_fee": int(order["purchase_fee"])}, ensure_ascii=False, sort_keys=True), now_text, order_id),
                )
                self._purchase_ledger(connection, operation_id, int(seller["id"]), "currency", "currency.spirit_stone", "purchase.sale", "credit", int(order["total_price"]), int(seller["spirit_stones"]), int(seller["spirit_stones"]) + int(order["total_price"]), order_id, now_text)
                self._purchase_ledger(connection, operation_id, int(seller["id"]), "item", str(order["item_key"]), "purchase.sale", "debit", quantity, int(seller_inventory.get(order["item_key"], 0)) + quantity, int(seller_inventory.get(order["item_key"], 0)), order_id, now_text)
                self._purchase_ledger(connection, operation_id, int(buyer["id"]), "item", str(order["item_key"]), "purchase.delivery", "credit", quantity, int(buyer_inventory.get(order["item_key"], 0)) - quantity, int(buyer_inventory.get(order["item_key"], 0)), order_id, now_text)
                payload = self._purchase_payload(connection, order_id)
                self._record_purchase_operation(connection, operation_id, operation_name, int(seller_actor["id"]), request_hash, payload, now_text)
        return self._purchase_record_from_payload(payload)

    def _cancel_purchase_order_once(
        self, platform: str, platform_user_id: str, order_id: str, operation_id: str
    ) -> PurchaseOrderRecord:
        operation_name = "economy.cancel_purchase_order"
        request_hash = self._request_hash(operation_name, {"platform": platform, "platform_user_id": platform_user_id, "order_id": order_id})
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._purchase_operation(connection, operation_id, operation_name, request_hash)
            if existing is not None:
                return self._purchase_record_from_payload(existing, replay=True)
            buyer = self._require_player(connection, platform, platform_user_id)
            order = self._purchase_row(connection, order_id)
            if order is None or int(order["buyer_player_id"]) != int(buyer["id"]):
                raise PurchaseOrderNotFoundError("purchase order does not belong to buyer")
            if str(order["expires_at"]) <= now_text:
                raise PurchaseOrderExpiredError("purchase order expired")
            if str(order["status"]) not in {"listed", "matched"}:
                raise PurchaseOrderStateConflictError("purchase order is already closed")
            item_lock = connection.execute("SELECT * FROM purchase_item_locks WHERE order_id=?", (order_id,)).fetchone()
            if item_lock is not None:
                self._release_item_lock(connection, order, item_lock, operation_id, now_text)
            self._refund_funds(connection, order, operation_id, now_text)
            connection.execute("UPDATE purchase_orders SET status='cancelled', seller_player_id=NULL, delivery_deadline=NULL, updated_at=? WHERE order_id=?", (now_text, order_id))
            payload = self._purchase_payload(connection, order_id)
            self._record_purchase_operation(connection, operation_id, operation_name, int(buyer["id"]), request_hash, payload, now_text)
            return self._purchase_record_from_payload(payload)

    def _expire_purchase_order_once(
        self, platform: str, platform_user_id: str, order_id: str, operation_id: str
    ) -> PurchaseOrderRecord:
        operation_name = "economy.expire_purchase_order"
        request_hash = self._request_hash(operation_name, {"platform": platform, "platform_user_id": platform_user_id, "order_id": order_id})
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._purchase_operation(connection, operation_id, operation_name, request_hash)
            if existing is not None:
                return self._purchase_record_from_payload(existing, replay=True)
            actor = self._require_player(connection, platform, platform_user_id, writable=False)
            order = self._purchase_row(connection, order_id)
            if order is None:
                raise PurchaseOrderNotFoundError("purchase order does not exist")
            if str(order["status"]) in {"settled", "cancelled", "failed", "expired"}:
                payload = self._purchase_payload(connection, order_id)
                self._record_purchase_operation(connection, operation_id, operation_name, int(actor["id"]), request_hash, payload, now_text)
                return self._purchase_record_from_payload(payload)
            if str(order["expires_at"]) > now_text:
                raise PurchaseOrderStateConflictError("purchase order has not expired")
            item_lock = connection.execute("SELECT * FROM purchase_item_locks WHERE order_id=?", (order_id,)).fetchone()
            if item_lock is not None:
                self._release_item_lock(connection, order, item_lock, operation_id, now_text)
            self._refund_funds(connection, order, operation_id, now_text)
            connection.execute("UPDATE purchase_orders SET status='expired', seller_player_id=NULL, delivery_deadline=NULL, updated_at=? WHERE order_id=?", (now_text, order_id))
            payload = self._purchase_payload(connection, order_id)
            self._record_purchase_operation(connection, operation_id, operation_name, int(actor["id"]), request_hash, payload, now_text)
            return self._purchase_record_from_payload(payload)

    def _list_purchase_orders_once(self, platform: str, platform_user_id: str) -> tuple[PurchaseOrderRecord, ...]:
        with self._connect() as connection:
            self._require_player(connection, platform, platform_user_id, writable=False)
            rows = connection.execute(
                "SELECT order_id FROM purchase_orders WHERE status IN ('listed', 'matched') ORDER BY created_at, id"
            ).fetchall()
            return tuple(self._purchase_record_from_payload(self._purchase_payload(connection, row["order_id"])) for row in rows)

    def _check_cross_realm_permission(self, player: Any) -> None:
        required = required_faction_reputation(str(player["location_key"]))
        if required is None:
            return
        reputation = self._json_object(player["faction_reputation_json"], {})
        faction, minimum = required
        if int(reputation.get(faction, 0)) < minimum:
            raise PurchasePermissionDeniedError("cross-realm purchase permission is missing")

    @staticmethod
    def _alliance_key(player: Any) -> str | None:
        try:
            qualification = json.loads(str(player["qualification_json"] or "{}"))
        except (TypeError, ValueError, json.JSONDecodeError):
            qualification = {}
        for key in ("cross_realm_alliance", "alliance_key", "alliance", "盟约"):
            value = qualification.get(key)
            if value:
                return str(value)
        return None

    @staticmethod
    def _purchase_row(connection: Any, order_id: str) -> Any:
        return connection.execute("SELECT * FROM purchase_orders WHERE order_id=?", (order_id,)).fetchone()

    def _refund_funds(self, connection: Any, order: Any, operation_id: str, now_text: str) -> None:
        funds = connection.execute("SELECT * FROM purchase_order_funds WHERE order_id=?", (order["order_id"],)).fetchone()
        if funds is None:
            return
        buyer = connection.execute("SELECT * FROM players WHERE id=?", (funds["buyer_player_id"],)).fetchone()
        if buyer is None:
            raise PlayerNotFoundError("purchase buyer does not exist")
        amount = int(funds["amount"])
        connection.execute("UPDATE players SET spirit_stones=spirit_stones+?, updated_at=? WHERE id=?", (amount, now_text, buyer["id"]))
        connection.execute("DELETE FROM purchase_order_funds WHERE order_id=?", (order["order_id"],))
        self._purchase_ledger(connection, operation_id, int(buyer["id"]), "currency", "currency.spirit_stone", "purchase.escrow_release", "release", amount, int(buyer["spirit_stones"]), int(buyer["spirit_stones"]) + amount, str(order["order_id"]), now_text)

    def _release_item_lock(self, connection: Any, order: Any, item_lock: Any, operation_id: str, now_text: str) -> None:
        connection.execute("DELETE FROM purchase_item_locks WHERE order_id=?", (order["order_id"],))
        self._purchase_ledger(connection, operation_id, int(item_lock["seller_player_id"]), "item", str(item_lock["item_key"]), "purchase.item_unlock", "release", int(item_lock["quantity"]), int(item_lock["quantity"]), int(item_lock["quantity"]), str(order["order_id"]), now_text)

    @staticmethod
    def _purchase_operation(connection: Any, operation_id: str, operation_name: str, request_hash: str) -> dict[str, Any] | None:
        row = connection.execute("SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id=?", (operation_id,)).fetchone()
        if row is None:
            return None
        if row["operation_name"] != operation_name or row["request_hash"] != request_hash:
            raise OperationConflictError("operation input differs from its original request")
        return json.loads(row["result_json"])

    @staticmethod
    def _record_purchase_operation(connection: Any, operation_id: str, operation_name: str, player_id: int, request_hash: str, payload: dict[str, Any], now_text: str) -> None:
        connection.execute(
            "INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (operation_id, operation_name, player_id, request_hash, json.dumps(payload, ensure_ascii=False, sort_keys=True), now_text),
        )

    @staticmethod
    def _purchase_payload(connection: Any, order_id: str) -> dict[str, Any]:
        row = connection.execute(
            """
            SELECT o.*, b.platform_user_id AS buyer_platform_user_id, b.player_id AS buyer_stable_id,
                   b.dao_name AS buyer_dao_name, s.platform_user_id AS seller_platform_user_id,
                   s.player_id AS seller_stable_id, s.dao_name AS seller_dao_name
            FROM purchase_orders o
            JOIN players b ON b.id=o.buyer_player_id
            LEFT JOIN players s ON s.id=o.seller_player_id
            WHERE o.order_id=?
            """,
            (order_id,),
        ).fetchone()
        if row is None:
            raise PurchaseOrderNotFoundError("purchase order does not exist")
        result = json.loads(str(row["result_json"] or "{}"))
        return {
            "order_id": str(row["order_id"]),
            "status": str(row["status"]),
            "buyer_player_id": str(row["buyer_stable_id"]),
            "buyer_platform_user_id": str(row["buyer_platform_user_id"]),
            "buyer_dao_name": str(row["buyer_dao_name"] or "无名"),
            "buyer_faction": str(row["buyer_faction"]),
            "seller_player_id": str(row["seller_stable_id"]) if row["seller_stable_id"] is not None else None,
            "seller_platform_user_id": str(row["seller_platform_user_id"]) if row["seller_platform_user_id"] is not None else None,
            "seller_dao_name": str(row["seller_dao_name"] or "无名") if row["seller_stable_id"] is not None else None,
            "seller_faction": str(row["seller_faction"]) if row["seller_faction"] else None,
            "item_key": str(row["item_key"]),
            "quantity": int(row["quantity"]),
            "unit_price": int(row["unit_price"]),
            "purchase_fee": int(row["purchase_fee"]),
            "total_price": int(row["total_price"]),
            "escrow_amount": int(row["escrow_amount"]),
            "item_region": str(row["item_region"]) if row["item_region"] else None,
            "item_source_location": str(row["item_source_location"]) if row["item_source_location"] else None,
            "first_binding_expires_at": str(row["first_binding_expires_at"]) if row["first_binding_expires_at"] else None,
            "alliance_key": str(row["alliance_key"]) if row["alliance_key"] else None,
            "expires_at": str(row["expires_at"]),
            "delivery_deadline": str(row["delivery_deadline"]) if row["delivery_deadline"] else None,
            "created_at": str(row["created_at"]),
            "transition_notice": result.get("notice"),
        }

    @staticmethod
    def _purchase_record_from_payload(payload: dict[str, Any], replay: bool = False) -> PurchaseOrderRecord:
        return PurchaseOrderRecord(
            order_id=str(payload["order_id"]),
            status=str(payload["status"]),
            buyer_player_id=str(payload["buyer_player_id"]),
            buyer_platform_user_id=str(payload["buyer_platform_user_id"]),
            buyer_dao_name=str(payload["buyer_dao_name"]),
            buyer_faction=str(payload["buyer_faction"]),
            seller_player_id=payload.get("seller_player_id"),
            seller_platform_user_id=payload.get("seller_platform_user_id"),
            seller_dao_name=payload.get("seller_dao_name"),
            seller_faction=payload.get("seller_faction"),
            item_key=str(payload["item_key"]),
            quantity=int(payload["quantity"]),
            unit_price=int(payload["unit_price"]),
            purchase_fee=int(payload["purchase_fee"]),
            total_price=int(payload["total_price"]),
            escrow_amount=int(payload["escrow_amount"]),
            item_region=payload.get("item_region"),
            item_source_location=payload.get("item_source_location"),
            first_binding_expires_at=payload.get("first_binding_expires_at"),
            alliance_key=payload.get("alliance_key"),
            expires_at=str(payload["expires_at"]),
            delivery_deadline=payload.get("delivery_deadline"),
            created_at=str(payload["created_at"]),
            already_completed=replay,
            transition_notice=payload.get("transition_notice"),
        )

    @staticmethod
    def _purchase_ledger(connection: Any, operation_id: str, player_id: int, asset_kind: str, asset_key: str, reason: str, direction: str, amount: int, before_value: int, after_value: int, source_id: str, created_at: str) -> None:
        connection.execute(
            "INSERT INTO economy_ledger_entries(operation_id, player_id, asset_kind, asset_key, reason, direction, amount, before_value, after_value, source_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (operation_id, player_id, asset_kind, asset_key, reason, direction, amount, before_value, after_value, source_id, created_at),
        )


__all__ = ["PurchaseOrderRepositoryMixin"]
