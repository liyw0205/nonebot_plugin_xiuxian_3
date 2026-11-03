"""SQLite transactions for 虚空物资寄售 (``market.void_material``).

Locking is represented by the data itself: listing an item removes it from the
seller's inventory and keeps the quantity in the listing row, so a listed item
cannot be used, listed twice, or sold elsewhere.  Cancelling or expiring returns
exactly that quantity.  Every mutation runs in one ``BEGIN IMMEDIATE``
transaction with an ``operations`` row.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime
from typing import Any
from uuid import uuid4

from ...contracts import serialize_datetime
from ..content import ContentBundle, bundled_content
from ..persistence.errors import (
    OperationConflictError,
    VoidMaterialAdmissionError,
    VoidMaterialFundsError,
    VoidMaterialLimitError,
    VoidMaterialNotFoundError,
    VoidMaterialOwnListingError,
    VoidMaterialStateError,
    VoidMaterialStockError,
)
from ..utils.assets import apply_player_asset_transition, player_currency
from ..utils.player import player_integer
from .void_material_content import void_material_defaults
from .void_material_rules import (
    CANCELLED,
    EXPIRED,
    LISTED,
    SOLD,
    VoidMaterialBoard,
    VoidMaterialListing,
    VoidMaterialTrade,
    admission_missing,
    fee_for,
    is_expired,
    listing_expiry,
)

VISIBLE_STATUSES = (LISTED,)


class VoidMaterialRepositoryMixin:
    """Persistence for the void-material consignment market."""

    def _void_material_content(self) -> ContentBundle:
        content = getattr(self, "content", None)
        return content if content is not None else bundled_content()

    def _void_material_definition(self) -> dict[str, Any]:
        return void_material_defaults(self._void_material_content())

    def _void_material_label(self, kind: str, key: str) -> str:
        try:
            return str(self._void_material_content().label(kind, key))
        except KeyError:
            return key

    # ---------------------------------------------------------------- queries

    async def void_material_board(
        self, *, platform: str, platform_user_id: str
    ) -> VoidMaterialBoard:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._void_material_board_once, platform, platform_user_id
            )

    def _void_material_board_once(
        self, platform: str, platform_user_id: str
    ) -> VoidMaterialBoard:
        definition = self._void_material_definition()
        now = self._now()
        with self._connect() as connection:
            row = self._require_player(connection, platform, platform_user_id, writable=False)
            self._void_material_expire_due(connection, now=now, definition=definition)
            admission = definition["admission"]
            missing = admission_missing(
                realm_key=str(row["realm_key"]),
                realm_layer=player_integer(row, "realm_layer"),
                merit_key=str(admission["merit_key"]),
                merit=player_integer(row, str(admission["merit_key"])),
                required_realm=str(admission["realm"]),
                required_layer=int(admission["min_layer"]),
                required_merit=int(admission["min_merit"]),
            )
            listings = connection.execute(
                "SELECT l.*, p.nickname AS seller_label FROM void_material_listings l "
                "JOIN players p ON p.id = l.seller_id "
                "WHERE l.status = 'listed' ORDER BY l.unit_price, l.created_at, l.listing_id "
                "LIMIT 20"
            ).fetchall()
            own = connection.execute(
                "SELECT COUNT(*) FROM void_material_listings WHERE seller_id = ? AND status = 'listed'",
                (int(row["id"]),),
            ).fetchone()[0]
            return VoidMaterialBoard(
                name=str(definition["name"]),
                description=str(definition["description"]),
                admission_realm=str(admission["realm"]),
                admission_layer=int(admission["min_layer"]),
                admission_merit=int(admission["min_merit"]),
                fee_bp=int(definition["fee_bp"]),
                listing_hours=int(definition["listing_hours"]),
                expire_grace_minutes=int(definition["expire_grace_minutes"]),
                max_listings=int(definition["max_listings_per_player"]),
                allowed_item_keys=tuple(definition["allowed_item_keys"]),
                qualified=not missing,
                missing=tuple(missing),
                own_listings=int(own),
                listings=tuple(
                    VoidMaterialListing(
                        listing_id=str(item["listing_id"]),
                        seller_label=str(item["seller_label"]),
                        item_key=str(item["item_key"]),
                        item_label=self._void_material_label("item", str(item["item_key"])),
                        quantity=int(item["quantity"]),
                        unit_price=int(item["unit_price"]),
                        status=str(item["status"]),
                        expires_at=str(item["expires_at"]),
                    )
                    for item in listings
                ),
            )

    # ---------------------------------------------------------------- listing

    async def list_void_material(
        self,
        *,
        platform: str,
        platform_user_id: str,
        item_key: str,
        quantity: int,
        unit_price: int,
        operation_id: str,
    ) -> VoidMaterialListing:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._list_void_material_once,
                platform,
                platform_user_id,
                item_key,
                quantity,
                unit_price,
                operation_id,
            )

    def _list_void_material_once(
        self,
        platform: str,
        platform_user_id: str,
        item_key: str,
        quantity: int,
        unit_price: int,
        operation_id: str,
    ) -> VoidMaterialListing:
        definition = self._void_material_definition()
        operation_name = "economy.void_material_list"
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
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            if existing is not None:
                if existing["operation_name"] != operation_name or existing["request_hash"] != request_hash:
                    raise OperationConflictError("operation input differs from its original request")
                return self._void_material_listing_from_payload(
                    json.loads(existing["result_json"]), replay=True
                )

            row = self._require_player(connection, platform, platform_user_id)
            player_id = int(row["id"])
            self._void_material_require_admission(row, definition)
            if item_key not in tuple(definition["allowed_item_keys"]):
                raise VoidMaterialStateError("item is not on the whitelist")
            if quantity <= 0 or unit_price <= 0:
                raise VoidMaterialStateError("quantity and unit price must be positive")

            open_count = connection.execute(
                "SELECT COUNT(*) FROM void_material_listings WHERE seller_id = ? AND status = 'listed'",
                (player_id,),
            ).fetchone()[0]
            if int(open_count) >= int(definition["max_listings_per_player"]):
                raise VoidMaterialLimitError("listing limit is reached")

            held = self._void_material_held(row, item_key)
            if quantity > held:
                raise VoidMaterialStockError("the seller does not hold enough of the item")

            apply_player_asset_transition(
                connection, row, {item_key: quantity}, now_text, mode="spend"
            )
            listing_id = f"void-listing-{uuid4().hex}"
            expires_at = serialize_datetime(
                listing_expiry(created_at=now, listing_hours=int(definition["listing_hours"]))
            )
            connection.execute(
                "INSERT INTO void_material_listings(listing_id, seller_id, item_key, quantity, "
                "unit_price, status, created_at, expires_at) "
                "VALUES (?, ?, ?, ?, ?, 'listed', ?, ?)",
                (listing_id, player_id, item_key, quantity, unit_price, now_text, expires_at),
            )
            payload = {
                "listing_id": listing_id,
                "item_key": item_key,
                "item_label": self._void_material_label("item", item_key),
                "quantity": quantity,
                "unit_price": unit_price,
                "expires_at": expires_at,
            }
            self._insert_operation(
                connection,
                operation_id=operation_id,
                operation_name=operation_name,
                player_id=player_id,
                request_hash=request_hash,
                payload=payload,
                now_text=now_text,
            )
            return self._void_material_listing_from_payload(payload)

    # ------------------------------------------------------------------ trade

    async def buy_void_material(
        self,
        *,
        platform: str,
        platform_user_id: str,
        listing_id: str,
        operation_id: str,
    ) -> VoidMaterialTrade:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._buy_void_material_once,
                platform,
                platform_user_id,
                listing_id,
                operation_id,
            )

    def _buy_void_material_once(
        self, platform: str, platform_user_id: str, listing_id: str, operation_id: str
    ) -> VoidMaterialTrade:
        definition = self._void_material_definition()
        operation_name = "economy.void_material_buy"
        request_hash = self._request_hash(
            operation_name,
            {"platform": platform, "platform_user_id": platform_user_id, "listing_id": listing_id},
        )
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            if existing is not None:
                if existing["operation_name"] != operation_name or existing["request_hash"] != request_hash:
                    raise OperationConflictError("operation input differs from its original request")
                return self._void_material_trade_from_payload(
                    json.loads(existing["result_json"]), replay=True
                )

            row = self._require_player(connection, platform, platform_user_id)
            buyer_id = int(row["id"])
            listing = connection.execute(
                "SELECT * FROM void_material_listings WHERE listing_id = ?", (listing_id,)
            ).fetchone()
            if listing is None:
                raise VoidMaterialNotFoundError("listing does not exist")
            if str(listing["status"]) != LISTED:
                raise VoidMaterialNotFoundError("listing is no longer open")
            if is_expired(expires_at=str(listing["expires_at"]), now=now):
                self._void_material_expire_listing(connection, listing, now_text=now_text)
                raise VoidMaterialNotFoundError("listing has expired")
            if int(listing["seller_id"]) == buyer_id:
                raise VoidMaterialOwnListingError("a seller cannot buy their own listing")

            gross = int(listing["unit_price"]) * int(listing["quantity"])
            if player_currency(row) < gross:
                raise VoidMaterialFundsError("the buyer cannot pay the listing price")
            fee, net = fee_for(gross=gross, fee_bp=int(definition["fee_bp"]))
            seller = connection.execute(
                "SELECT * FROM players WHERE id = ?", (int(listing["seller_id"]),)
            ).fetchone()
            if seller is None:
                raise VoidMaterialNotFoundError("the seller no longer exists")

            item_key = str(listing["item_key"])
            quantity = int(listing["quantity"])
            # One delta call: paying stones and receiving goods must land in the
            # same write, otherwise the second call would rewrite the buyer row
            # from a stale snapshot and silently refund the payment.
            apply_player_asset_transition(
                connection,
                row,
                {"spirit_stones": -gross, item_key: quantity},
                now_text,
            )
            apply_player_asset_transition(
                connection, seller, {"spirit_stones": net}, now_text, mode="grant"
            )
            trade_id = f"void-trade-{uuid4().hex}"
            connection.execute(
                "UPDATE void_material_listings SET status = 'sold', closed_at = ?, buyer_id = ? "
                "WHERE listing_id = ? AND status = 'listed'",
                (now_text, buyer_id, listing_id),
            )
            connection.execute(
                "INSERT INTO void_material_trades(trade_id, listing_id, seller_id, buyer_id, "
                "item_key, quantity, gross, fee, net, operation_id, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    trade_id,
                    listing_id,
                    int(listing["seller_id"]),
                    buyer_id,
                    item_key,
                    quantity,
                    gross,
                    fee,
                    net,
                    operation_id,
                    now_text,
                ),
            )
            buyer_after = connection.execute(
                "SELECT spirit_stones FROM players WHERE id = ?", (buyer_id,)
            ).fetchone()
            seller_after = connection.execute(
                "SELECT spirit_stones FROM players WHERE id = ?", (int(listing["seller_id"]),)
            ).fetchone()
            payload = {
                "trade_id": trade_id,
                "listing_id": listing_id,
                "item_key": item_key,
                "quantity": quantity,
                "gross": gross,
                "fee": fee,
                "net": net,
                "buyer_stones_after": int(buyer_after["spirit_stones"]),
                "seller_stones_after": int(seller_after["spirit_stones"]),
            }
            self._insert_operation(
                connection,
                operation_id=operation_id,
                operation_name=operation_name,
                player_id=buyer_id,
                request_hash=request_hash,
                payload=payload,
                now_text=now_text,
            )
            return self._void_material_trade_from_payload(payload)

    async def cancel_void_material(
        self, *, platform: str, platform_user_id: str, listing_id: str, operation_id: str
    ) -> VoidMaterialListing:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._cancel_void_material_once,
                platform,
                platform_user_id,
                listing_id,
                operation_id,
            )

    def _cancel_void_material_once(
        self, platform: str, platform_user_id: str, listing_id: str, operation_id: str
    ) -> VoidMaterialListing:
        definition = self._void_material_definition()
        operation_name = "economy.void_material_cancel"
        request_hash = self._request_hash(
            operation_name,
            {"platform": platform, "platform_user_id": platform_user_id, "listing_id": listing_id},
        )
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            if existing is not None:
                if existing["operation_name"] != operation_name or existing["request_hash"] != request_hash:
                    raise OperationConflictError("operation input differs from its original request")
                return self._void_material_listing_from_payload(
                    json.loads(existing["result_json"]), replay=True
                )

            row = self._require_player(connection, platform, platform_user_id)
            seller_id = int(row["id"])
            listing = connection.execute(
                "SELECT * FROM void_material_listings WHERE listing_id = ?", (listing_id,)
            ).fetchone()
            if listing is None or int(listing["seller_id"]) != seller_id:
                raise VoidMaterialNotFoundError("listing does not exist for this seller")
            if str(listing["status"]) != LISTED:
                raise VoidMaterialNotFoundError("listing is no longer open")
            apply_player_asset_transition(
                connection,
                row,
                {str(listing["item_key"]): int(listing["quantity"])},
                now_text,
                mode="grant",
            )
            connection.execute(
                "UPDATE void_material_listings SET status = 'cancelled', closed_at = ? "
                "WHERE listing_id = ? AND status = 'listed'",
                (now_text, listing_id),
            )
            payload = {
                "listing_id": listing_id,
                "item_key": str(listing["item_key"]),
                "item_label": self._void_material_label("item", str(listing["item_key"])),
                "quantity": int(listing["quantity"]),
                "unit_price": int(listing["unit_price"]),
                "expires_at": str(listing["expires_at"]),
            }
            self._insert_operation(
                connection,
                operation_id=operation_id,
                operation_name=operation_name,
                player_id=seller_id,
                request_hash=request_hash,
                payload=payload,
                now_text=now_text,
            )
            return self._void_material_listing_from_payload(payload)

    # ---------------------------------------------------------------- helpers

    def _void_material_require_admission(self, row: Any, definition: dict[str, Any]) -> None:
        admission = definition["admission"]
        missing = admission_missing(
            realm_key=str(row["realm_key"]),
            realm_layer=player_integer(row, "realm_layer"),
            merit_key=str(admission["merit_key"]),
            merit=player_integer(row, str(admission["merit_key"])),
            required_realm=str(admission["realm"]),
            required_layer=int(admission["min_layer"]),
            required_merit=int(admission["min_merit"]),
        )
        if missing:
            raise VoidMaterialAdmissionError("the void market admission is not met")

    @staticmethod
    def _void_material_held(row: Any, item_key: str) -> int:
        inventory = row["inventory_json"]
        data = json.loads(inventory) if isinstance(inventory, str) else dict(inventory or {})
        return int(data.get(item_key, 0))

    def _void_material_expire_due(
        self, connection: sqlite3.Connection, *, now: datetime, definition: dict[str, Any]
    ) -> None:
        rows = connection.execute(
            "SELECT * FROM void_material_listings WHERE status = 'listed'"
        ).fetchall()
        for listing in rows:
            if is_expired(expires_at=str(listing["expires_at"]), now=now):
                self._void_material_expire_listing(
                    connection, listing, now_text=serialize_datetime(now)
                )

    @staticmethod
    def _void_material_expire_listing(
        connection: sqlite3.Connection, listing: sqlite3.Row, *, now_text: str
    ) -> None:
        seller = connection.execute(
            "SELECT * FROM players WHERE id = ?", (int(listing["seller_id"]),)
        ).fetchone()
        if seller is not None:
            apply_player_asset_transition(
                connection,
                seller,
                {str(listing["item_key"]): int(listing["quantity"])},
                now_text,
                mode="grant",
            )
        connection.execute(
            "UPDATE void_material_listings SET status = 'expired', closed_at = ? "
            "WHERE listing_id = ? AND status = 'listed'",
            (now_text, str(listing["listing_id"])),
        )

    @staticmethod
    def _void_material_listing_from_payload(
        payload: dict[str, Any], *, replay: bool = False
    ) -> VoidMaterialListing:
        return VoidMaterialListing(
            listing_id=str(payload["listing_id"]),
            seller_label="",
            item_key=str(payload["item_key"]),
            item_label=str(payload.get("item_label", payload["item_key"])),
            quantity=int(payload["quantity"]),
            unit_price=int(payload["unit_price"]),
            status=LISTED,
            expires_at=str(payload["expires_at"]),
        )

    @staticmethod
    def _void_material_trade_from_payload(
        payload: dict[str, Any], *, replay: bool = False
    ) -> VoidMaterialTrade:
        return VoidMaterialTrade(
            listing_id=str(payload["listing_id"]),
            trade_id=str(payload["trade_id"]),
            item_key=str(payload["item_key"]),
            quantity=int(payload["quantity"]),
            gross=int(payload["gross"]),
            fee=int(payload["fee"]),
            net=int(payload["net"]),
            seller_stones_after=int(payload["seller_stones_after"]),
            buyer_stones_after=int(payload["buyer_stones_after"]),
            already_completed=replay,
        )