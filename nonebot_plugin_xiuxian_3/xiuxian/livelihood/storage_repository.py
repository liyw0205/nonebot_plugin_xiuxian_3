"""SQLite transactions for the residence storage box."""

from __future__ import annotations

import asyncio
from typing import Any

from ...contracts import serialize_datetime
from ..content import bundled_content
from ..items.rules import item_records
from ..persistence.errors import (
    ResidenceRequiredError,
    ResourceInsufficientError,
    StorageCapacityError,
    StorageItemNotFoundError,
    StorageQuantityError,
)
from ..utils.assets import inventory_amount
from ..utils.operations import operation_replay, record_operation
from ..utils.player import (
    grant_player_reward,
    player_inventory,
    spend_player_state,
)
from .models import StorageItemView, StorageRecord


class StorageRepositoryMixin:
    """Own the residence storage deposit and withdrawal transactions."""

    def _storage_labels(self, keys: list[str]) -> dict[str, str]:
        records = item_records(getattr(self, "content", None) or bundled_content())
        return {
            key: records[key].name if key in records else "未知物品"
            for key in keys
        }

    def _storage_used(self, connection: Any, player_id: int) -> int:
        row = connection.execute(
            "SELECT COUNT(*) AS count FROM residence_storage WHERE player_id = ?",
            (player_id,),
        ).fetchone()
        return int(row["count"])

    def _storage_capacity(self, connection: Any, player_id: int, now: Any, now_text: str) -> int:
        residence = self._active_residence(connection, player_id, now, now_text)
        if residence is None:
            return 0
        return int(self._residence_snapshot(residence)["storage_slots"])

    async def deposit_storage(
        self,
        *,
        platform: str,
        platform_user_id: str,
        item_key: str,
        quantity: int,
        operation_id: str,
    ) -> StorageRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._deposit_storage_once,
                platform,
                platform_user_id,
                item_key,
                quantity,
                operation_id,
            )

    def _deposit_storage_once(
        self,
        platform: str,
        platform_user_id: str,
        item_key: str,
        quantity: int,
        operation_id: str,
    ) -> StorageRecord:
        operation_name = "livelihood.deposit_storage"
        request_hash = self._request_hash(
            operation_name,
            {
                "platform": platform,
                "platform_user_id": platform_user_id,
                "item_key": item_key,
                "quantity": quantity,
            },
        )
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = operation_replay(connection, operation_id, operation_name, request_hash)
            if existing is not None:
                return self._storage_from_payload(existing, replay=True)
            row = self._require_player(connection, platform, platform_user_id)
            player_id = int(row["id"])
            residence = self._active_residence(connection, player_id, now, now_text)
            if residence is None:
                raise ResidenceRequiredError("deposit requires an active residence")
            snapshot = self._residence_snapshot(residence)
            capacity = int(snapshot["storage_slots"])
            stored = connection.execute(
                "SELECT item_key, quantity FROM residence_storage WHERE player_id = ? "
                "ORDER BY item_key",
                (player_id,),
            ).fetchall()
            used_slots = len(stored)
            existing_quantity = 0
            for entry in stored:
                if str(entry["item_key"]) == item_key:
                    existing_quantity = int(entry["quantity"])
            if existing_quantity == 0 and used_slots >= capacity:
                raise StorageCapacityError("storage box is full")
            if inventory_amount(player_inventory(row), item_key) < quantity:
                raise ResourceInsufficientError("inventory is insufficient")
            spend_player_state(connection, row, {item_key: quantity}, now_text)
            connection.execute(
                """
                INSERT INTO residence_storage(player_id, item_key, quantity, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(player_id, item_key) DO UPDATE SET
                    quantity = residence_storage.quantity + excluded.quantity,
                    updated_at = excluded.updated_at
                """,
                (player_id, item_key, quantity, now_text, now_text),
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (player_id,)).fetchone()
            if updated is None:
                raise RuntimeError("storage deposit returned no player")
            stored_quantity = existing_quantity + quantity
            payload = {
                "player": self._player_payload(self._row_to_player(updated)),
                "capacity": capacity,
                "used_slots": used_slots + (1 if existing_quantity == 0 else 0),
                "item_key": item_key,
                "label": self._storage_labels([item_key])[item_key],
                "quantity": quantity,
                "stored_quantity": stored_quantity,
                "inventory_quantity": inventory_amount(player_inventory(updated), item_key),
            }
            record_operation(connection, operation_id, operation_name, player_id, request_hash, payload, now_text)
            return self._storage_from_payload(payload)

    async def withdraw_storage(
        self,
        *,
        platform: str,
        platform_user_id: str,
        item_key: str,
        quantity: int,
        operation_id: str,
    ) -> StorageRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._withdraw_storage_once,
                platform,
                platform_user_id,
                item_key,
                quantity,
                operation_id,
            )

    def _withdraw_storage_once(
        self,
        platform: str,
        platform_user_id: str,
        item_key: str,
        quantity: int,
        operation_id: str,
    ) -> StorageRecord:
        operation_name = "livelihood.withdraw_storage"
        request_hash = self._request_hash(
            operation_name,
            {
                "platform": platform,
                "platform_user_id": platform_user_id,
                "item_key": item_key,
                "quantity": quantity,
            },
        )
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = operation_replay(connection, operation_id, operation_name, request_hash)
            if existing is not None:
                return self._storage_from_payload(existing, replay=True)
            row = self._require_player(connection, platform, platform_user_id)
            player_id = int(row["id"])
            entry = connection.execute(
                "SELECT item_key, quantity FROM residence_storage "
                "WHERE player_id = ? AND item_key = ?",
                (player_id, item_key),
            ).fetchone()
            if entry is None:
                raise StorageItemNotFoundError("stored item is missing")
            stored_quantity = int(entry["quantity"])
            if quantity > stored_quantity:
                raise StorageQuantityError("stored quantity is insufficient")
            grant_player_reward(connection, row, {item_key: quantity}, now_text)
            remaining = stored_quantity - quantity
            if remaining:
                connection.execute(
                    "UPDATE residence_storage SET quantity = ?, updated_at = ? "
                    "WHERE player_id = ? AND item_key = ?",
                    (remaining, now_text, player_id, item_key),
                )
            else:
                connection.execute(
                    "DELETE FROM residence_storage WHERE player_id = ? AND item_key = ?",
                    (player_id, item_key),
                )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (player_id,)).fetchone()
            if updated is None:
                raise RuntimeError("storage withdrawal returned no player")
            payload = {
                "player": self._player_payload(self._row_to_player(updated)),
                "capacity": self._storage_capacity(connection, player_id, now, now_text),
                "used_slots": self._storage_used(connection, player_id),
                "item_key": item_key,
                "label": self._storage_labels([item_key])[item_key],
                "quantity": quantity,
                "stored_quantity": remaining,
                "inventory_quantity": inventory_amount(player_inventory(updated), item_key),
            }
            record_operation(connection, operation_id, operation_name, player_id, request_hash, payload, now_text)
            return self._storage_from_payload(payload)

    async def get_storage(self, *, platform: str, platform_user_id: str) -> StorageRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._get_storage_sync, platform, platform_user_id)

    def _get_storage_sync(self, platform: str, platform_user_id: str) -> StorageRecord:
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = self._require_player(connection, platform, platform_user_id, writable=False)
            player_id = int(row["id"])
            entries = connection.execute(
                "SELECT item_key, quantity FROM residence_storage WHERE player_id = ? "
                "ORDER BY item_key",
                (player_id,),
            ).fetchall()
            labels = self._storage_labels([str(entry["item_key"]) for entry in entries])
            items: list[StorageItemView] = []
            for entry in entries:
                quantity = entry["quantity"]
                if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
                    raise ValueError("invalid storage quantity")
                key = str(entry["item_key"])
                items.append(StorageItemView(key, labels[key], quantity))
            return StorageRecord(
                player=self._row_to_player(row),
                capacity=self._storage_capacity(connection, player_id, now, now_text),
                used_slots=len(items),
                items=tuple(items),
            )

    def _storage_from_payload(self, payload: dict[str, Any], *, replay: bool = False) -> StorageRecord:
        if (
            any(
                isinstance(payload[field], bool)
                or not isinstance(payload[field], int)
                or payload[field] < 0
                for field in ("capacity", "used_slots", "quantity", "stored_quantity", "inventory_quantity")
            )
            or not isinstance(payload["item_key"], str)
            or not isinstance(payload["label"], str)
            or not payload["label"].strip()
        ):
            raise ValueError("invalid storage result")
        player = self._row_to_player(payload["player"])
        return StorageRecord(
            player=player,
            capacity=int(payload["capacity"]),
            used_slots=int(payload["used_slots"]),
            item_key=str(payload["item_key"]),
            label=str(payload["label"]),
            quantity=int(payload["quantity"]),
            stored_quantity=int(payload["stored_quantity"]),
            inventory_quantity=int(payload["inventory_quantity"]),
            already_completed=replay,
        )


__all__ = ["StorageRepositoryMixin"]
