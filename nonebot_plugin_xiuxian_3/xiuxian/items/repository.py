"""SQLite transactions for consumable production item effects."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from datetime import timedelta
from uuid import uuid4

from ...contracts import serialize_datetime
from ..content import bundled_content
from ..persistence.errors import *  # noqa: F401,F403
from ..utils.assets import inventory_amount, reserved_inventory_quantity, spend_player_items
from ..utils.player import change_player_state_actual, player_integer, player_inventory
from .models import ItemUseRecord
from .rules import (
    resolve_item,
)


# Bound by the persistence composition root after all repository mixins load.
SQLitePlayerRepository = None


class ItemRepositoryMixin:
    async def replay_item_use(
        self,
        *,
        platform: str,
        platform_user_id: str,
        operation_id: str,
        request_args: tuple[str, ...],
    ) -> ItemUseRecord | None:
        """Replay before resolving a name that may have left the content pack."""

        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._replay_item_use_with_retry,
                platform,
                platform_user_id,
                operation_id,
                request_args,
            )

    def _replay_item_use_with_retry(
        self,
        platform: str,
        platform_user_id: str,
        operation_id: str,
        request_args: tuple[str, ...],
    ) -> ItemUseRecord | None:
        last_error: Exception | None = None
        for attempt in range(5):
            try:
                return self._replay_item_use_once(platform, platform_user_id, operation_id, request_args)
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc).lower():
                    raise
                if attempt == 4:
                    raise RepositoryBusyError("database remained locked") from exc
                last_error = exc
                time.sleep(0.01 * (2**attempt))
        raise RepositoryBusyError("database remained locked") from last_error

    def _replay_item_use_once(
        self,
        platform: str,
        platform_user_id: str,
        operation_id: str,
        request_args: tuple[str, ...],
    ) -> ItemUseRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT o.operation_name, o.result_json, p.platform, p.platform_user_id
                FROM operations AS o
                JOIN players AS p ON p.id = o.player_id
                WHERE o.operation_id = ?
                """,
                (operation_id,),
            ).fetchone()
        if row is None:
            return None
        if (
            row["operation_name"] != "items.use"
            or row["platform"] != platform
            or row["platform_user_id"] != platform_user_id
        ):
            raise OperationConflictError("operation input differs from its original request")
        try:
            payload = json.loads(row["result_json"])
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError("item operation snapshot is invalid") from exc
        if not isinstance(payload, dict):
            raise ValueError("item operation snapshot must be an object")
        self._item_use_from_payload(payload)
        if not self._item_request_matches(payload, request_args):
            raise OperationConflictError("operation input differs from its original request")
        return self._item_use_from_payload(payload, replay=True)

    @staticmethod
    def _item_request_matches(payload: dict[str, object], request_args: tuple[str, ...]) -> bool:
        stored = payload.get("request_args")
        if not isinstance(stored, list) or any(not isinstance(value, str) for value in stored):
            return False
        if len(stored) != len(request_args) or not request_args:
            return False
        accepted_item_references = {stored[0], str(payload.get("item_key", ""))}
        historical_references = payload.get("item_references")
        if isinstance(historical_references, list):
            accepted_item_references.update(
                value for value in historical_references if isinstance(value, str)
            )
        if request_args[0] not in accepted_item_references:
            return False
        if len(request_args) == 1:
            return True
        effect = payload.get("effect")
        accepted_second = {stored[1]}
        if isinstance(effect, dict):
            for key in ("resource", "location_key"):
                value = effect.get(key)
                if isinstance(value, str):
                    accepted_second.add(value)
        return request_args[1] in accepted_second

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
        request_args: tuple[str, ...],
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
                request_args,
            )

    def _use_item_with_retry(
        self,
        platform: str,
        platform_user_id: str,
        item_key: str,
        location_key: str | None,
        operation_id: str,
        request_args: tuple[str, ...],
    ) -> ItemUseRecord:
        last_error: Exception | None = None
        for attempt in range(5):
            try:
                return self._use_item_once(
                    platform, platform_user_id, item_key, location_key, operation_id, request_args
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
        request_args: tuple[str, ...],
    ) -> ItemUseRecord:
        try:
            definition = resolve_item(item_key, self.content)
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
            inventory = player_inventory(row)
            owned = inventory_amount(inventory, definition.key)
            if owned < 1:
                raise ItemInsufficientError("item is missing")
            if owned - reserved_inventory_quantity(connection, int(row["id"]), definition.key) < 1:
                raise ItemReservedError("item is committed to an active trade order")

            effect: dict[str, object]
            if definition.effect_type == "restore_choice":
                choice = normalized_location
                if choice not in definition.resources:
                    raise ItemLocationRequiredError("food must name one of its configured recovery resources")
                cooldown = connection.execute(
                    "SELECT cooldown_until FROM item_use_cooldowns WHERE player_id = ? AND item_key = ?",
                    (row["id"], definition.key),
                ).fetchone()
                if cooldown is not None and str(cooldown["cooldown_until"]) > now_text:
                    raise ItemCooldownError("item recovery is still cooling down")
                maximum = player_integer(row, f"{choice}_max")
                actual = change_player_state_actual(
                    connection,
                    row,
                    updated_at=now_text,
                    asset_values={definition.key: 1},
                    asset_mode="spend",
                    value_delta={choice: definition.effect_value},
                    maximums={choice: maximum},
                )
                cooldown_until = serialize_datetime(
                    now + timedelta(seconds=int(definition.cooldown_seconds or 0))
                )
                connection.execute(
                    "INSERT INTO item_use_cooldowns(player_id, item_key, cooldown_until, operation_id, updated_at) "
                    "VALUES (?, ?, ?, ?, ?) "
                    "ON CONFLICT(player_id, item_key) DO UPDATE SET cooldown_until=excluded.cooldown_until, "
                    "operation_id=excluded.operation_id, updated_at=excluded.updated_at",
                    (row["id"], definition.key, cooldown_until, operation_id, now_text),
                )
                effect = {
                    "type": definition.effect_type,
                    "resource": choice,
                    "requested": definition.effect_value,
                    "restored": actual.get(choice, 0),
                    "cooldown_until": cooldown_until,
                }
            elif definition.effect_type == "next_cultivation_state_bonus_bp":
                effects = self._json_object(row["item_effects_json"], {})
                if effects.get("pending") is not None:
                    raise ItemEffectAlreadyPendingError("a cultivation effect is already pending")
                effects = {
                    "pending": {
                        "type": definition.effect_type,
                        "value": definition.effect_value,
                        "operation_id": operation_id,
                        "consumed_at": now_text,
                    }
                }
                spend_player_items(
                    connection,
                    row,
                    {definition.key: 1},
                    now_text,
                    player_values={
                        "item_effects_json": json.dumps(effects, ensure_ascii=False, sort_keys=True)
                    },
                )
                effect = {
                    "type": definition.effect_type,
                    "state_bp_bonus": definition.effect_value,
                    "pending": True,
                }
            elif definition.effect_type == "exploration_risk_reduction_bp":
                target_location = definition.location_key
                if target_location is None:
                    raise ItemNotUsableError("item effect has no target location")
                if str(row["location_key"]) != target_location:
                    raise ItemLocationRequiredError("item must be deployed from its configured location")
                target = normalized_location or str(row["location_key"])
                if target != target_location:
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
                barrier_id = uuid4().hex
                duration_seconds = definition.duration_seconds
                if duration_seconds is None:
                    raise RuntimeError(f"usable item {definition.key} has no configured duration")
                expires_at = serialize_datetime(now + timedelta(seconds=duration_seconds))
                connection.execute(
                    "INSERT INTO mist_barrier_instances(barrier_id, player_id, operation_id, location_key, status, starts_at, expires_at, snapshot_json, created_at, updated_at) VALUES (?, ?, ?, ?, 'active', ?, ?, ?, ?, ?)",
                    (barrier_id, row["id"], operation_id, target, now_text, expires_at, json.dumps({"risk_reduction_bp": definition.effect_value}, ensure_ascii=False, sort_keys=True), now_text, now_text),
                )
                spend_player_items(connection, row, {definition.key: 1}, now_text)
                effect = {
                    "type": definition.effect_type,
                    "barrier_id": barrier_id,
                    "location_key": target,
                    "location_name": (self.content or bundled_content()).label("location", target),
                    "risk_reduction_bp": definition.effect_value,
                    "expires_at": expires_at,
                }
            else:
                raise ItemNotUsableError("item has no active use effect")

            updated = connection.execute("SELECT * FROM players WHERE id = ?", (row["id"],)).fetchone()
            if updated is None:
                raise RuntimeError("item use returned no player")
            payload = {
                "player": self._player_payload(self._row_to_player(updated)),
                "item_key": definition.key,
                "item_name": definition.name,
                "item_references": [definition.key, definition.name, *definition.aliases],
                "quantity": 1,
                "effect": effect,
                "request_args": list(request_args),
            }
            connection.execute(
                "INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (operation_id, operation_name, row["id"], request_hash, json.dumps(payload, ensure_ascii=False, sort_keys=True), now_text),
            )
            return self._item_use_from_payload(payload)

    @staticmethod
    def _item_use_from_payload(payload: dict[str, object], *, replay: bool = False) -> ItemUseRecord:
        if not isinstance(payload.get("player"), dict):
            raise ValueError("item operation snapshot player is invalid")
        if not isinstance(payload.get("item_key"), str) or not str(payload["item_key"]).strip():
            raise ValueError("item operation snapshot key is invalid")
        if not isinstance(payload.get("item_name"), str) or not str(payload["item_name"]).strip():
            raise ValueError("item operation snapshot name is invalid")
        quantity = payload.get("quantity")
        if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity <= 0:
            raise ValueError("item operation snapshot quantity is invalid")
        request_args = payload.get("request_args")
        references = payload.get("item_references")
        if (
            not isinstance(request_args, list)
            or not request_args
            or any(not isinstance(value, str) for value in request_args)
            or not isinstance(references, list)
            or any(not isinstance(value, str) or not value for value in references)
        ):
            raise ValueError("item operation snapshot references are invalid")
        effect = payload.get("effect")
        if not isinstance(effect, dict) or effect.get("type") not in {
            "restore_choice",
            "next_cultivation_state_bonus_bp",
            "exploration_risk_reduction_bp",
        }:
            raise ValueError("item operation snapshot effect is invalid")
        effect_type = effect["type"]
        if effect_type == "restore_choice":
            if (
                effect.get("resource") not in {"stamina", "energy"}
                or not isinstance(effect.get("requested"), int)
                or isinstance(effect.get("requested"), bool)
                or not isinstance(effect.get("restored"), int)
                or isinstance(effect.get("restored"), bool)
                or not isinstance(effect.get("cooldown_until"), str)
            ):
                raise ValueError("item operation snapshot recovery effect is invalid")
        elif effect_type == "next_cultivation_state_bonus_bp":
            if not isinstance(effect.get("state_bp_bonus"), int) or isinstance(effect.get("state_bp_bonus"), bool):
                raise ValueError("item operation snapshot cultivation effect is invalid")
        elif not all(
            isinstance(effect.get(key), str) and str(effect[key]).strip()
            for key in ("barrier_id", "location_key", "location_name", "expires_at")
        ) or not isinstance(effect.get("risk_reduction_bp"), int) or isinstance(effect.get("risk_reduction_bp"), bool):
            raise ValueError("item operation snapshot barrier effect is invalid")
        return ItemUseRecord(
            player=SQLitePlayerRepository._row_to_player(payload["player"]),
            item_key=str(payload["item_key"]),
            item_name=str(payload["item_name"]),
            quantity=int(payload.get("quantity", 1)),
            effect=effect,
            already_completed=replay,
        )


__all__ = ["ItemRepositoryMixin"]
