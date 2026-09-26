"""SQLite transactions for the v0.2 sect warehouse exchange."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, time
from typing import Any

from ...contracts import serialize_datetime
from ..persistence.errors import (
    PlayerNotFoundError,
    SectContributionInsufficientError,
    SectExchangeDailyCapError,
    SectExchangeInvalidOfferError,
    SectNotFoundError,
    SectStockInsufficientError,
)
from .sect_exchange_models import SectExchangeRecord
from .sect_exchange_rules import (
    SECT_EXCHANGE_CONTENT_VERSION,
    SECT_EXCHANGE_DAILY_CAP,
    SECT_EXCHANGE_OFFERS,
    SECT_EXCHANGE_RULE_VERSION,
)


class SectExchangeRepositoryMixin:
    """Own atomic contribution, warehouse and inventory exchange writes."""

    async def exchange_sect_item(
        self,
        *,
        platform: str,
        platform_user_id: str,
        offer_key: str,
        operation_id: str,
    ) -> SectExchangeRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._exchange_sect_item_once,
                platform,
                platform_user_id,
                offer_key,
                operation_id,
            )

    def _exchange_sect_item_once(
        self,
        platform: str,
        platform_user_id: str,
        offer_key: str,
        operation_id: str,
    ) -> SectExchangeRecord:
        offer = SECT_EXCHANGE_OFFERS.get(offer_key)
        if offer is None:
            raise SectExchangeInvalidOfferError("sect exchange offer is not registered")
        operation_name = "social.sect_exchange"
        request_hash = self._request_hash(
            operation_name,
            {
                "platform": platform,
                "platform_user_id": platform_user_id,
                "offer_key": offer.key,
            },
        )
        now = self._now()
        now_text = serialize_datetime(now)
        day_start = serialize_datetime(datetime.combine(now.date(), time.min, tzinfo=now.tzinfo))
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._sect_operation(connection, operation_id, operation_name, request_hash)
            if existing is not None:
                return self._exchange_record_from_payload(existing, replay=True)
            player = self._require_player(connection, platform, platform_user_id)
            membership = connection.execute(
                "SELECT * FROM sect_members WHERE player_id=? AND status='active' LIMIT 1",
                (player["id"],),
            ).fetchone()
            if membership is None:
                raise SectNotFoundError("player is not in a sect")
            sect = connection.execute(
                "SELECT * FROM sects WHERE sect_id=? AND status='active'",
                (membership["sect_id"],),
            ).fetchone()
            if sect is None:
                raise SectNotFoundError("sect does not exist")
            used_today = connection.execute(
                "SELECT COUNT(*) AS count FROM operations WHERE player_id=? AND operation_name=? AND created_at>=?",
                (player["id"], operation_name, day_start),
            ).fetchone()
            if int(used_today["count"]) >= SECT_EXCHANGE_DAILY_CAP:
                raise SectExchangeDailyCapError("sect exchange daily cap reached")
            if int(membership["contribution"]) < offer.contribution_cost:
                raise SectContributionInsufficientError("sect contribution is insufficient")
            warehouse = self._json_map(sect["warehouse_json"])
            warehouse_quantity = int(warehouse.get(offer.item_key, 0))
            if warehouse_quantity < offer.quantity:
                raise SectStockInsufficientError("sect warehouse stock is insufficient")
            inventory = self._json_map(player["inventory_json"])
            inventory_quantity = int(inventory.get(offer.item_key, 0)) + offer.quantity
            warehouse_quantity -= offer.quantity
            inventory[offer.item_key] = inventory_quantity
            if warehouse_quantity:
                warehouse[offer.item_key] = warehouse_quantity
            else:
                warehouse.pop(offer.item_key, None)
            connection.execute(
                "UPDATE sect_members SET contribution=contribution-?, last_action_at=?, updated_at=? WHERE id=?",
                (offer.contribution_cost, now_text, now_text, membership["id"]),
            )
            connection.execute(
                "UPDATE sects SET warehouse_json=?, updated_at=? WHERE sect_id=?",
                (json.dumps(warehouse, ensure_ascii=False, sort_keys=True), now_text, sect["sect_id"]),
            )
            connection.execute(
                "UPDATE players SET inventory_json=?, updated_at=? WHERE id=?",
                (json.dumps(inventory, ensure_ascii=False, sort_keys=True), now_text, player["id"]),
            )
            payload = {
                "offer_key": offer.key,
                "label": offer.label,
                "item_key": offer.item_key,
                "quantity": offer.quantity,
                "contribution_spent": offer.contribution_cost,
                "sect_id": str(sect["sect_id"]),
                "member_contribution": int(membership["contribution"]) - offer.contribution_cost,
                "warehouse_quantity": warehouse_quantity,
                "inventory_quantity": inventory_quantity,
                "content_version": SECT_EXCHANGE_CONTENT_VERSION,
                "rule_version": SECT_EXCHANGE_RULE_VERSION,
            }
            self._sect_record_operation(
                connection,
                operation_id,
                operation_name,
                int(player["id"]),
                request_hash,
                payload,
                now_text,
            )
            return self._exchange_record_from_payload(payload)

    @staticmethod
    def _json_map(value: Any) -> dict[str, Any]:
        try:
            decoded = json.loads(value or "{}") if isinstance(value, str) else value
        except (TypeError, ValueError):
            return {}
        return decoded if isinstance(decoded, dict) else {}

    @staticmethod
    def _exchange_record_from_payload(payload: dict[str, Any], *, replay: bool = False) -> SectExchangeRecord:
        return SectExchangeRecord(
            offer_key=str(payload["offer_key"]),
            label=str(payload["label"]),
            item_key=str(payload["item_key"]),
            quantity=int(payload["quantity"]),
            contribution_spent=int(payload["contribution_spent"]),
            sect_id=str(payload["sect_id"]),
            member_contribution=int(payload["member_contribution"]),
            warehouse_quantity=int(payload["warehouse_quantity"]),
            inventory_quantity=int(payload["inventory_quantity"]),
            content_version=str(payload.get("content_version", "content-0.2")),
            rule_version=str(payload.get("rule_version", "economy-0.2.0")),
            already_completed=replay,
        )


__all__ = ["SectExchangeRepositoryMixin"]
