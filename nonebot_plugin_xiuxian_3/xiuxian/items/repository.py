"""SQLite transactions for consumable production item effects."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from datetime import timedelta
from uuid import uuid4

from ...contracts import serialize_datetime
from ..persistence.errors import *  # noqa: F401,F403
from .models import ItemUseRecord
from .rules import (
    CLOUD_TEA_STATE_BP_BONUS,
    CONTENT_VERSION,
    MIST_BARRIER_DURATION_SECONDS,
    MIST_BARRIER_RISK_REDUCTION_BP,
    RULE_VERSION,
    resolve_item,
)


# Bound by the persistence composition root after all repository mixins load.
SQLitePlayerRepository = None


class ItemRepositoryMixin:
    async def expire_mist_barriers(self) -> int:
        """Mark elapsed barrier instances terminal; safe to run repeatedly."""

        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._expire_mist_barriers_once)

    def _expire_mist_barriers_once(self) -> int:
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            changed = connection.execute(
                "UPDATE mist_barrier_instances SET status = 'expired', updated_at = ? WHERE status = 'active' AND expires_at <= ?",
                (now_text, now_text),
            ).rowcount
            return int(changed)

    async def use_item(
        self,
        *,
        platform: str,
        platform_user_id: str,
        item_key: str,
        location_key: str | None,
        operation_id: str,
    ) -> ItemUseRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._use_item_with_retry,
                platform,
                platform_user_id,
                item_key,
                location_key,
                operation_id,
            )

    def _use_item_with_retry(
        self,
        platform: str,
        platform_user_id: str,
        item_key: str,
        location_key: str | None,
        operation_id: str,
    ) -> ItemUseRecord:
        last_error: Exception | None = None
        for attempt in range(5):
            try:
                return self._use_item_once(
                    platform, platform_user_id, item_key, location_key, operation_id
                )
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc).lower():
                    raise
                if attempt == 4:
                    raise RepositoryBusyError("database remained locked") from exc
                last_error = exc
                time.sleep(0.01 * (2**attempt))
        raise RepositoryBusyError("database remained locked") from last_error

    def _use_item_once(
        self,
        platform: str,
        platform_user_id: str,
        item_key: str,
        location_key: str | None,
        operation_id: str,
    ) -> ItemUseRecord:
        try:
            definition = resolve_item(item_key)
        except ValueError as exc:
            raise ItemNotUsableError("item has no active use effect") from exc
        operation_name = "items.use"
        normalized_location = (location_key or "").strip() or None
        operation_payload = {
            "platform": platform,
            "platform_user_id": platform_user_id,
            "item_key": definition.key,
            "location_key": normalized_location,
        }
        request_hash = self._request_hash(operation_name, operation_payload)
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
                return self._item_use_from_payload(json.loads(existing["result_json"]), replay=True)

            row = self._require_player(connection, platform, platform_user_id)
            inventory = self._json_object(row["inventory_json"], {})
            if int(inventory.get(definition.key, 0)) < 1:
                raise ItemInsufficientError("item is missing")

            effect: dict[str, object]
            if definition.kind == "cloud_tea":
                effects = self._json_object(row["item_effects_json"], {})
                if int(effects.get("cloud_tea_state_bp", 0)) > 0 or effects.get("cloud_tea_operation_id"):
                    raise ItemEffectAlreadyPendingError("cloud tea effect is already pending")
                inventory[definition.key] = int(inventory[definition.key]) - 1
                if inventory[definition.key] <= 0:
                    inventory.pop(definition.key, None)
                effects = {
                    "cloud_tea_state_bp": CLOUD_TEA_STATE_BP_BONUS,
                    "cloud_tea_operation_id": operation_id,
                    "content_version": CONTENT_VERSION,
                    "rule_version": RULE_VERSION,
                    "consumed_at": now_text,
                }
                connection.execute(
                    "UPDATE players SET inventory_json = ?, item_effects_json = ?, updated_at = ? WHERE id = ?",
                    (json.dumps(inventory, ensure_ascii=False, sort_keys=True), json.dumps(effects, ensure_ascii=False, sort_keys=True), now_text, row["id"]),
                )
                effect = {"state_bp_bonus": CLOUD_TEA_STATE_BP_BONUS, "pending": True}
            elif definition.kind == "mist_barrier":
                if str(row["location_key"]) != "cave.mist_grotto_2":
                    raise ItemLocationRequiredError("mist barrier must be deployed from mist grotto two")
                target = normalized_location or str(row["location_key"])
                if target != "cave.mist_grotto_2":
                    raise ItemLocationRequiredError("mist barrier target is unsupported")
                connection.execute(
                    "UPDATE mist_barrier_instances SET status = 'expired', updated_at = ? WHERE player_id = ? AND status = 'active' AND expires_at <= ?",
                    (now_text, row["id"], now_text),
                )
                active = connection.execute(
                    "SELECT barrier_id FROM mist_barrier_instances WHERE player_id = ? AND location_key = ? AND status = 'active' AND expires_at > ? LIMIT 1",
                    (row["id"], target, now_text),
                ).fetchone()
                if active is not None:
                    raise ItemEffectAlreadyActiveError("a mist barrier is already active at this location")
                inventory[definition.key] = int(inventory[definition.key]) - 1
                if inventory[definition.key] <= 0:
                    inventory.pop(definition.key, None)
                barrier_id = uuid4().hex
                expires_at = serialize_datetime(now + timedelta(seconds=MIST_BARRIER_DURATION_SECONDS))
                connection.execute(
                    "INSERT INTO mist_barrier_instances(barrier_id, player_id, operation_id, location_key, status, starts_at, expires_at, snapshot_json, created_at, updated_at) VALUES (?, ?, ?, ?, 'active', ?, ?, ?, ?, ?)",
                    (barrier_id, row["id"], operation_id, target, now_text, expires_at, json.dumps({"risk_reduction_bp": MIST_BARRIER_RISK_REDUCTION_BP, "content_version": CONTENT_VERSION, "rule_version": RULE_VERSION}, ensure_ascii=False, sort_keys=True), now_text, now_text),
                )
                connection.execute(
                    "UPDATE players SET inventory_json = ?, updated_at = ? WHERE id = ?",
                    (json.dumps(inventory, ensure_ascii=False, sort_keys=True), now_text, row["id"]),
                )
                effect = {"barrier_id": barrier_id, "location_key": target, "risk_reduction_bp": MIST_BARRIER_RISK_REDUCTION_BP, "expires_at": expires_at}
            else:
                raise ItemNotUsableError("item has no active use effect")

            updated = connection.execute("SELECT * FROM players WHERE id = ?", (row["id"],)).fetchone()
            if updated is None:
                raise RuntimeError("item use returned no player")
            payload = {
                "player": self._player_payload(self._row_to_player(updated)),
                "item_key": definition.key,
                "item_name": definition.name,
                "quantity": 1,
                "effect": effect,
                "content_version": CONTENT_VERSION,
                "rule_version": RULE_VERSION,
            }
            connection.execute(
                "INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (operation_id, operation_name, row["id"], request_hash, json.dumps(payload, ensure_ascii=False, sort_keys=True), now_text),
            )
            return self._item_use_from_payload(payload)

    @staticmethod
    def _item_use_from_payload(payload: dict[str, object], *, replay: bool = False) -> ItemUseRecord:
        return ItemUseRecord(
            player=SQLitePlayerRepository._row_to_player(payload["player"]),
            item_key=str(payload["item_key"]),
            item_name=str(payload["item_name"]),
            quantity=int(payload.get("quantity", 1)),
            effect=dict(payload.get("effect", {})),
            already_completed=replay,
        )


__all__ = ["ItemRepositoryMixin"]
