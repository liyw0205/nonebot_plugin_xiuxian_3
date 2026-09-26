"""Audited player sources for sect contribution and exchange stock."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, time, timedelta
from typing import Any

from ...contracts import serialize_datetime
from ..persistence.errors import (
    OperationConflictError,
    ResourceInsufficientError,
    SectDailyBuildAlreadyCompletedError,
    SectDailyBuildNotReadyError,
    SectExchangeInvalidOfferError,
    SectNotFoundError,
    SectPermissionDeniedError,
    SectStockInsufficientError,
    SectSupplyItemInvalidError,
    SectWarehouseFullError,
)
from .sect_exchange_rules import (
    SECT_DONATION_ITEMS,
    SECT_EXCHANGE_OFFERS,
    SECT_SUPPLY_RECIPES,
    SECT_SUPPLY_RULE_VERSION,
)
from .sect_rules import SECT_CONTENT_VERSION


class SectSupplyRepositoryMixin:
    async def build_sect_daily(self, *, platform: str, platform_user_id: str, operation_id: str) -> dict[str, Any]:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._build_sect_daily_once, platform, platform_user_id, operation_id)

    async def donate_sect_asset(
        self, *, platform: str, platform_user_id: str, item_key: str, quantity: int, operation_id: str,
    ) -> dict[str, Any]:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._donate_sect_asset_once, platform, platform_user_id, item_key, quantity, operation_id)

    async def procure_sect_stock(
        self, *, platform: str, platform_user_id: str, offer_key: str, operation_id: str,
    ) -> dict[str, Any]:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._procure_sect_stock_once, platform, platform_user_id, offer_key, operation_id)

    @staticmethod
    def _supply_member(connection: Any, player_id: int) -> tuple[Any, Any]:
        member = connection.execute(
            "SELECT * FROM sect_members WHERE player_id=? AND status='active'", (player_id,),
        ).fetchone()
        if member is None:
            raise SectNotFoundError("player is not in a sect")
        sect = connection.execute(
            "SELECT * FROM sects WHERE sect_id=? AND status='active'", (member["sect_id"],),
        ).fetchone()
        if sect is None:
            raise SectNotFoundError("sect is not active")
        return member, sect

    def _supply_replay(self, connection: Any, operation_id: str, name: str, request_hash: str) -> dict[str, Any] | None:
        previous = self._sect_operation(connection, operation_id, name, request_hash)
        if previous is not None:
            return {**previous, "idempotent_replay": True}
        return None

    def _supply_record(
        self, connection: Any, operation_id: str, name: str, player_id: int,
        sect_id: str, request_hash: str, payload: dict[str, Any], now_text: str,
        action_key: str | None = None,
    ) -> dict[str, Any]:
        self._sect_record_operation(connection, operation_id, name, player_id, request_hash, payload, now_text)
        if action_key is not None:
            connection.execute(
                "INSERT INTO sect_warehouse_supply_events(operation_id,sect_id,player_id,action_key,snapshot_json,created_at) VALUES (?,?,?,?,?,?)",
                (operation_id, sect_id, player_id, action_key, json.dumps(payload, ensure_ascii=False, sort_keys=True), now_text),
            )
        return {**payload, "idempotent_replay": False}

    def _build_sect_daily_once(self, platform: str, platform_user_id: str, operation_id: str) -> dict[str, Any]:
        name = "social.sect_daily_build"
        request_hash = self._request_hash(name, {"platform": platform, "platform_user_id": platform_user_id})
        now = self._now()
        now_text = serialize_datetime(now)
        start = serialize_datetime(datetime.combine(now.date(), time.min, tzinfo=now.tzinfo))
        end = serialize_datetime(datetime.combine(now.date() + timedelta(days=1), time.min, tzinfo=now.tzinfo))
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._supply_replay(connection, operation_id, name, request_hash)
            if replay is not None:
                return replay
            player = self._require_player(connection, platform, platform_user_id)
            member, sect = self._supply_member(connection, int(player["id"]))
            if connection.execute(
                "SELECT 1 FROM operations WHERE player_id=? AND operation_name=? AND created_at>=? AND created_at<? LIMIT 1",
                (player["id"], name, start, end),
            ).fetchone() is not None:
                raise SectDailyBuildAlreadyCompletedError("already built today")
            sources_by_session = {}
            for row in connection.execute(
                "SELECT operation_id, operation_name, result_json FROM operations WHERE player_id=? AND operation_name IN ('production.complete','production.recover','exploration.settle','exploration.settle_combat') AND created_at>=? AND created_at<? ORDER BY operation_id",
                (player["id"], start, end),
            ):
                result = json.loads(row["result_json"])
                if str(row["operation_name"]).startswith("production."):
                    eligible = result.get("success") is True
                    session_key = result.get("session_id")
                    source_kind = "production"
                else:
                    eligible = result.get("status") == "settled" and result.get("battle_outcome") in (None, "won") and not result.get("expired")
                    session_key = result.get("exploration_id")
                    source_kind = "exploration"
                if eligible and session_key:
                    sources_by_session.setdefault((source_kind, str(session_key)), str(row["operation_id"]))
            sources = sorted(sources_by_session.values())
            if len(sources) < 3:
                raise SectDailyBuildNotReadyError("three completed actions today are required")
            connection.execute(
                "UPDATE sect_members SET contribution=contribution+5,last_action_at=?,updated_at=? WHERE id=?",
                (now_text, now_text, member["id"]),
            )
            connection.execute(
                "UPDATE sects SET construction=construction+1,updated_at=? WHERE sect_id=?",
                (now_text, sect["sect_id"]),
            )
            connection.execute(
                "INSERT INTO sect_contribution_events(sect_id,player_id,source_operation_id,quantity,occurred_at) VALUES (?,?,?,?,?)",
                (sect["sect_id"], player["id"], operation_id, 5, now_text),
            )
            payload = {
                "sect_id": str(sect["sect_id"]), "contribution": int(member["contribution"]) + 5,
                "construction": int(sect["construction"]) + 1, "source_operations": sources[:3],
                "business_date": now.date().isoformat(), "content_version": SECT_CONTENT_VERSION,
                "rule_version": SECT_SUPPLY_RULE_VERSION,
            }
            return self._supply_record(connection, operation_id, name, int(player["id"]), str(sect["sect_id"]), request_hash, payload, now_text)

    def _donate_sect_asset_once(
        self, platform: str, platform_user_id: str, item_key: str, quantity: int, operation_id: str,
    ) -> dict[str, Any]:
        if (item_key == "spirit_stones" and (quantity < 100 or quantity > 9900 or quantity % 100)) or (item_key != "spirit_stones" and (quantity <= 0 or quantity > 99)):
            raise SectSupplyItemInvalidError("invalid donation quantity")
        if item_key != "spirit_stones" and item_key not in SECT_DONATION_ITEMS:
            raise SectSupplyItemInvalidError("bound or unregistered donation")
        name = "social.sect_donate"
        request_hash = self._request_hash(name, {
            "platform": platform, "platform_user_id": platform_user_id,
            "item_key": item_key, "quantity": quantity,
        })
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._supply_replay(connection, operation_id, name, request_hash)
            if replay is not None:
                return replay
            player = self._require_player(connection, platform, platform_user_id)
            member, sect = self._supply_member(connection, int(player["id"]))
            contribution_gain = quantity // 100 if item_key == "spirit_stones" else quantity
            warehouse = self._json_map(sect["warehouse_json"])
            if item_key == "spirit_stones":
                if int(player["spirit_stones"]) < quantity:
                    raise ResourceInsufficientError("not enough spirit stones")
                connection.execute("UPDATE players SET spirit_stones=spirit_stones-?,updated_at=? WHERE id=?", (quantity, now_text, player["id"]))
                connection.execute("UPDATE sects SET spirit_stones=spirit_stones+?,updated_at=? WHERE sect_id=?", (quantity, now_text, sect["sect_id"]))
                balance = int(sect["spirit_stones"]) + quantity
            else:
                inventory = self._json_map(player["inventory_json"])
                if int(inventory.get(item_key, 0)) < quantity:
                    raise ResourceInsufficientError("not enough items")
                if item_key not in warehouse and len(warehouse) >= int(sect["warehouse_capacity"]):
                    raise SectWarehouseFullError("warehouse has no free slots")
                inventory[item_key] = int(inventory[item_key]) - quantity
                if not inventory[item_key]:
                    inventory.pop(item_key)
                warehouse[item_key] = int(warehouse.get(item_key, 0)) + quantity
                connection.execute("UPDATE players SET inventory_json=?,updated_at=? WHERE id=?", (json.dumps(inventory, ensure_ascii=False, sort_keys=True), now_text, player["id"]))
                connection.execute("UPDATE sects SET warehouse_json=?,updated_at=? WHERE sect_id=?", (json.dumps(warehouse, ensure_ascii=False, sort_keys=True), now_text, sect["sect_id"]))
                balance = int(warehouse[item_key])
            connection.execute("UPDATE sect_members SET contribution=contribution+?,last_action_at=?,updated_at=? WHERE id=?", (contribution_gain, now_text, now_text, member["id"]))
            connection.execute(
                "INSERT INTO sect_contribution_events(sect_id,player_id,source_operation_id,quantity,occurred_at) VALUES (?,?,?,?,?)",
                (sect["sect_id"], player["id"], operation_id, contribution_gain, now_text),
            )
            payload = {
                "sect_id": str(sect["sect_id"]), "item_key": item_key, "quantity": quantity,
                "warehouse_balance": balance, "contribution": int(member["contribution"]) + contribution_gain,
                "contribution_gain": contribution_gain, "content_version": SECT_CONTENT_VERSION,
                "rule_version": SECT_SUPPLY_RULE_VERSION,
            }
            return self._supply_record(connection, operation_id, name, int(player["id"]), str(sect["sect_id"]), request_hash, payload, now_text, "donate_stones" if item_key == "spirit_stones" else "donate_item")

    def _procure_sect_stock_once(
        self, platform: str, platform_user_id: str, offer_key: str, operation_id: str,
    ) -> dict[str, Any]:
        if offer_key not in SECT_SUPPLY_RECIPES:
            raise SectExchangeInvalidOfferError("this offer cannot be procured")
        name = "social.sect_procure"
        request_hash = self._request_hash(name, {
            "platform": platform, "platform_user_id": platform_user_id, "offer_key": offer_key,
        })
        now_text = serialize_datetime(self._now())
        inputs, price = SECT_SUPPLY_RECIPES[offer_key]
        offer = SECT_EXCHANGE_OFFERS[offer_key]
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._supply_replay(connection, operation_id, name, request_hash)
            if replay is not None:
                return replay
            player = self._require_player(connection, platform, platform_user_id)
            member, sect = self._supply_member(connection, int(player["id"]))
            if str(member["role"]) not in {"leader", "vice_leader"}:
                raise SectPermissionDeniedError("only leaders can procure stock")
            warehouse = self._json_map(sect["warehouse_json"])
            if any(int(warehouse.get(key, 0)) < amount for key, amount in inputs.items()):
                raise SectStockInsufficientError("missing warehouse supply inputs")
            if int(sect["spirit_stones"]) < price:
                raise ResourceInsufficientError("not enough public spirit stones")
            resulting = set(warehouse) - {key for key, amount in inputs.items() if int(warehouse[key]) == amount}
            resulting.add(offer.item_key)
            if len(resulting) > int(sect["warehouse_capacity"]):
                raise SectWarehouseFullError("warehouse has no free slots")
            for key, amount in inputs.items():
                warehouse[key] = int(warehouse[key]) - amount
                if not warehouse[key]:
                    warehouse.pop(key)
            warehouse[offer.item_key] = int(warehouse.get(offer.item_key, 0)) + offer.quantity
            connection.execute(
                "UPDATE sects SET warehouse_json=?,spirit_stones=spirit_stones-?,updated_at=? WHERE sect_id=?",
                (json.dumps(warehouse, ensure_ascii=False, sort_keys=True), price, now_text, sect["sect_id"]),
            )
            payload = {
                "sect_id": str(sect["sect_id"]), "offer_key": offer.key, "item_key": offer.item_key,
                "warehouse_balance": int(warehouse[offer.item_key]), "input_items": inputs,
                "spirit_stones_spent": price, "content_version": SECT_CONTENT_VERSION,
                "rule_version": SECT_SUPPLY_RULE_VERSION,
            }
            return self._supply_record(connection, operation_id, name, int(player["id"]), str(sect["sect_id"]), request_hash, payload, now_text, "procure")


__all__ = ["SectSupplyRepositoryMixin"]
