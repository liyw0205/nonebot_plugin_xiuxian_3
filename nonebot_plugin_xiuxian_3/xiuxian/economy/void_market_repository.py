"""SQLite transactions for the weekly void market.

Stock is derived from the purchase ledger instead of a materialised counter:
remaining stock for an offer is ``stock - SUM(quantity)`` over the current
``week_id``.  ``BEGIN IMMEDIATE`` therefore serialises competing purchases, so
two buyers can never be granted the same slot, and a read-only preview never
has to write.
"""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from typing import Any
from uuid import uuid4

from ...contracts import serialize_datetime
from ..utils.assets import apply_player_asset_transition, inventory_amount, player_currency
from ..utils.player import player_integer, player_inventory
from ..persistence.errors import (
    OperationConflictError,
    ResourceInsufficientError,
    VoidMarketDailyCapError,
    VoidMarketRequirementError,
    VoidMarketStockError,
)
from .void_market_models import (
    VoidMarketOfferState,
    VoidMarketPreviewRecord,
    VoidMarketPurchaseRecord,
)
from .void_market_rules import (
    DEFINITIONS,
    VoidMarketDefinition,
    VoidMarketOffer,
    business_date,
    void_market_definition,
    void_market_missing_requirements,
    week_id,
    week_refresh_at,
)


class VoidMarketRepositoryMixin:
    """Persistence operations for ``market.void_weekly.<week_id>``."""

    async def preview_void_market(
        self, *, platform: str, platform_user_id: str
    ) -> VoidMarketPreviewRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._preview_void_market_once, platform, platform_user_id)

    def _preview_void_market_once(
        self, platform: str, platform_user_id: str
    ) -> VoidMarketPreviewRecord:
        definition = self._void_market_definition()
        now = self._now()
        current_week = week_id(now, definition)
        today = business_date(now)
        with self._connect() as connection:
            row = self._require_player(connection, platform, platform_user_id)
            sold = self._void_market_sold(connection, current_week)
            daily_used = self._void_market_daily_used(connection, int(row["id"]), today)
            missing = void_market_missing_requirements(
                realm_key=str(row["realm_key"]),
                realm_layer=player_integer(row, "realm_layer"),
                void_merit=player_integer(row, "void_merit"),
                definition=definition,
            )
            return VoidMarketPreviewRecord(
                location_key=definition.location_key,
                week_id=current_week,
                refresh_at=serialize_datetime(week_refresh_at(now, definition)),
                stock_slots=definition.stock_slots,
                stock_remaining=max(0, definition.stock_slots - sum(sold.values())),
                daily_limit=definition.daily_purchase_limit,
                daily_used=daily_used,
                at_market=str(row["location_key"]) == definition.location_key,
                qualified=not missing,
                missing=missing,
                offers=tuple(
                    VoidMarketOfferState(
                        key=offer.key,
                        label=offer.label,
                        item_key=offer.item_key,
                        quantity=offer.quantity,
                        price_spirit_stones=offer.price_spirit_stones,
                        stock=offer.stock,
                        remaining=max(0, offer.stock - sold.get(offer.key, 0)),
                    )
                    for offer in definition.offers
                ),
            )

    async def purchase_void_market_offer(
        self,
        *,
        platform: str,
        platform_user_id: str,
        offer_key: str,
        quantity: int,
        operation_id: str,
    ) -> VoidMarketPurchaseRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._purchase_void_market_once,
                platform,
                platform_user_id,
                offer_key,
                quantity,
                operation_id,
            )

    def _purchase_void_market_once(
        self,
        platform: str,
        platform_user_id: str,
        offer_key: str,
        quantity: int,
        operation_id: str,
    ) -> VoidMarketPurchaseRecord:
        definition = self._void_market_definition()
        offer = definition.offer(offer_key)
        operation_name = "economy.void_market_purchase"
        request_payload = {
            "platform": platform,
            "platform_user_id": platform_user_id,
            "offer_key": offer_key,
            "quantity": quantity,
        }
        request_hash = self._request_hash(operation_name, request_payload)
        now = self._now()
        now_text = serialize_datetime(now)
        current_week = week_id(now, definition)
        today = business_date(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            if existing is not None:
                if existing["operation_name"] != operation_name or existing["request_hash"] != request_hash:
                    raise OperationConflictError("operation input differs from its original request")
                return self._void_market_purchase_from_payload(
                    json.loads(existing["result_json"]), replay=True
                )

            row = self._require_player(connection, platform, platform_user_id)
            if str(row["location_key"]) != definition.location_key:
                raise VoidMarketRequirementError("the player is not at the void market")
            missing = void_market_missing_requirements(
                realm_key=str(row["realm_key"]),
                realm_layer=player_integer(row, "realm_layer"),
                void_merit=player_integer(row, "void_merit"),
                definition=definition,
            )
            if missing:
                raise VoidMarketRequirementError("void market entry requirements are missing")

            daily_used = self._void_market_daily_used(connection, int(row["id"]), today)
            if daily_used + quantity > definition.daily_purchase_limit:
                raise VoidMarketDailyCapError("void market daily purchase cap is reached")

            sold = self._void_market_sold(connection, current_week)
            remaining = offer.stock - sold.get(offer.key, 0)
            if quantity > remaining:
                raise VoidMarketStockError("void market stock is sold out")

            total_cost = offer.price_spirit_stones * quantity
            if player_currency(row) < total_cost:
                raise ResourceInsufficientError("spirit stones are insufficient")

            binding_expires_at = serialize_datetime(now + timedelta(seconds=definition.binding_seconds))
            purchase_id = f"void-market-{uuid4().hex}"
            snapshot = {
                "offer_key": offer.key,
                "item_key": offer.item_key,
                "quantity": quantity,
                "unit_price": offer.price_spirit_stones,
                "total_cost": total_cost,
                "week_id": current_week,
                "business_date": today,
                "location_key": definition.location_key,
                "daily_limit": definition.daily_purchase_limit,
                "daily_used_before": daily_used,
                "stock_before": remaining,
                "binding_expires_at": binding_expires_at,
            }
            transition = apply_player_asset_transition(
                connection,
                row,
                {offer.item_key: quantity, "spirit_stones": -total_cost},
                now_text,
            )
            connection.execute(
                """
                INSERT INTO void_market_purchases(
                    purchase_id, player_id, offer_key, week_id, business_date, item_key,
                    quantity, unit_price, total_cost, snapshot_json, operation_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    purchase_id,
                    int(row["id"]),
                    offer.key,
                    current_week,
                    today,
                    offer.item_key,
                    quantity,
                    offer.price_spirit_stones,
                    total_cost,
                    json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
                    operation_id,
                    now_text,
                ),
            )
            self._void_market_ledger(
                connection,
                operation_id,
                int(row["id"]),
                "currency",
                "currency.spirit_stone",
                "void_market.purchase",
                "debit",
                total_cost,
                transition.before.currency,
                transition.after.currency,
                purchase_id,
                now_text,
            )
            self._void_market_ledger(
                connection,
                operation_id,
                int(row["id"]),
                "item",
                offer.item_key,
                "void_market.purchase",
                "credit",
                quantity,
                inventory_amount(transition.before.inventory, offer.item_key),
                inventory_amount(transition.after.inventory, offer.item_key),
                purchase_id,
                now_text,
            )
            payload = {
                "purchase_id": purchase_id,
                "offer_key": offer.key,
                "label": offer.label,
                "item_key": offer.item_key,
                "quantity": quantity,
                "unit_price": offer.price_spirit_stones,
                "total_cost": total_cost,
                "week_id": current_week,
                "business_date": today,
                "daily_used": daily_used + quantity,
                "daily_limit": definition.daily_purchase_limit,
                "remaining": remaining - quantity,
                "binding_expires_at": binding_expires_at,
            }
            connection.execute(
                "INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    operation_id,
                    operation_name,
                    int(row["id"]),
                    request_hash,
                    json.dumps(payload, ensure_ascii=False, sort_keys=True),
                    now_text,
                ),
            )
            connection.execute(
                """
                INSERT INTO void_market_item_bindings(
                    source_operation_id, player_id, item_key, quantity, bound_until, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (operation_id, int(row["id"]), offer.item_key, quantity, binding_expires_at, now_text),
            )
            return self._void_market_purchase_from_payload(payload, replay=False)

    def _void_market_definition(self) -> VoidMarketDefinition:
        return void_market_definition(self.content) if self.content is not None else DEFINITIONS

    @staticmethod
    def _void_market_sold(connection: Any, current_week: str) -> dict[str, int]:
        rows = connection.execute(
            """
            SELECT offer_key, COALESCE(SUM(quantity), 0) AS quantity
            FROM void_market_purchases WHERE week_id = ? GROUP BY offer_key
            """,
            (current_week,),
        ).fetchall()
        return {str(row["offer_key"]): int(row["quantity"]) for row in rows}

    @staticmethod
    def _void_market_daily_used(connection: Any, player_id: int, today: str) -> int:
        row = connection.execute(
            """
            SELECT COALESCE(SUM(quantity), 0) AS quantity
            FROM void_market_purchases WHERE player_id = ? AND business_date = ?
            """,
            (player_id, today),
        ).fetchone()
        return int(row["quantity"] if row is not None else 0)

    @staticmethod
    def _void_market_ledger(
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
            (
                operation_id,
                player_id,
                asset_kind,
                asset_key,
                reason,
                direction,
                amount,
                before_value,
                after_value,
                source_id,
                created_at,
            ),
        )

    @staticmethod
    def _void_market_purchase_from_payload(
        payload: dict[str, Any], replay: bool = False
    ) -> VoidMarketPurchaseRecord:
        return VoidMarketPurchaseRecord(
            purchase_id=str(payload["purchase_id"]),
            offer_key=str(payload["offer_key"]),
            label=str(payload["label"]),
            item_key=str(payload["item_key"]),
            quantity=int(payload["quantity"]),
            unit_price=int(payload["unit_price"]),
            total_cost=int(payload["total_cost"]),
            week_id=str(payload["week_id"]),
            business_date=str(payload["business_date"]),
            daily_used=int(payload["daily_used"]),
            daily_limit=int(payload["daily_limit"]),
            remaining=int(payload["remaining"]),
            binding_expires_at=str(payload["binding_expires_at"]),
            already_completed=replay,
        )


__all__ = ["VoidMarketRepositoryMixin"]
