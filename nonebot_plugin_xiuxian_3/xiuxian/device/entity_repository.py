"""SQLite transactions for 器修机关 (``device.scout_doll``).

The durable unit is ``device_instances``: one row per assembled device, with
durability, a ``deployed`` flag and a ``broken`` status.  A partial unique
index keeps at most one deployed device per player, so the battle snapshot can
never freeze two devices for the same battle.  Every mutation is one
``BEGIN IMMEDIATE`` transaction with an ``operations`` row, which makes a
retried command replay the original result instead of charging twice.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from typing import Any
from uuid import uuid4

from ...contracts import serialize_datetime
from ..content import ContentBundle, bundled_content
from ..persistence.errors import (
    DeviceBrokenError,
    DeviceLimitReachedError,
    DeviceMaterialError,
    DeviceNotFoundError,
    DeviceRequirementError,
    DeviceStateError,
    OperationConflictError,
)
from ..utils.assets import apply_player_asset_transition, player_currency
from ..utils.player import player_integer
from .entity_models import DeviceOperationRecord, DeviceStatusRecord
from .entity_rules import (
    DEFAULT_ENTITY_KEY,
    DeviceDefinition,
    device_definition,
    device_missing_requirements,
    device_view,
    repair_steps_missing,
)


class DeviceRepositoryMixin:
    """Persistence for assembled, deployed and damaged devices."""

    def _device_content(self) -> ContentBundle:
        content = getattr(self, "content", None)
        return content if content is not None else bundled_content()

    def _device_definition(self, entity_key: str) -> DeviceDefinition:
        try:
            return device_definition(self._device_content(), entity_key)
        except KeyError as exc:
            raise DeviceNotFoundError(f"unknown device entity: {entity_key}") from exc

    async def device_status(
        self, *, platform: str, platform_user_id: str, entity_key: str = DEFAULT_ENTITY_KEY
    ) -> DeviceStatusRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._device_status_once, platform, platform_user_id, entity_key
            )

    def _device_status_once(
        self, platform: str, platform_user_id: str, entity_key: str
    ) -> DeviceStatusRecord:
        definition = self._device_definition(entity_key)
        with self._connect() as connection:
            row = self._require_player(connection, platform, platform_user_id, writable=False)
            instance = self._device_instance_row(connection, int(row["id"]), definition)
            missing = device_missing_requirements(
                definition=definition,
                path_key=str(row["path_key"] or ""),
                realm_key=str(row["realm_key"]),
                realm_layer=player_integer(row, "realm_layer"),
            )
            if instance is None:
                return DeviceStatusRecord(
                    entity_key=definition.key,
                    label=definition.label,
                    description=definition.description,
                    path_key=definition.owner_path_key,
                    owned=0,
                    max_instances=definition.max_instances,
                    required_realm=definition.required_realm,
                    min_layer=definition.min_layer,
                    qualified=not missing,
                    missing=tuple(missing),
                    assembly_spirit_stones=definition.assembly_spirit_stones,
                    assembly_items=dict(definition.assembly_items),
                    maintenance_spirit_stones=definition.maintenance_spirit_stones,
                    maintenance_items=dict(definition.maintenance_items),
                    attack_multiplier_bp=definition.attack_multiplier_bp,
                    duration_rounds=definition.duration_rounds,
                    max_actions_per_battle=definition.max_actions_per_battle,
                )
            view = device_view(
                instance_id=str(instance["instance_id"]),
                definition=definition,
                durability_bp=int(instance["durability_bp"]),
                status=str(instance["status"]),
                deployed=bool(instance["deployed"]),
            )
            return DeviceStatusRecord(
                entity_key=definition.key,
                label=definition.label,
                description=definition.description,
                path_key=definition.owner_path_key,
                owned=1,
                max_instances=definition.max_instances,
                required_realm=definition.required_realm,
                min_layer=definition.min_layer,
                qualified=not missing,
                missing=tuple(missing),
                durability_bp=view.durability_bp,
                max_durability_bp=view.max_durability_bp,
                status=view.status,
                deployed=view.deployed,
                instance_id=view.instance_id,
                assembly_spirit_stones=definition.assembly_spirit_stones,
                assembly_items=dict(definition.assembly_items),
                maintenance_spirit_stones=definition.maintenance_spirit_stones,
                maintenance_items=dict(definition.maintenance_items),
                attack_multiplier_bp=definition.attack_multiplier_bp,
                duration_rounds=definition.duration_rounds,
                max_actions_per_battle=definition.max_actions_per_battle,
            )

    async def assemble_device(
        self,
        *,
        platform: str,
        platform_user_id: str,
        entity_key: str,
        operation_id: str,
    ) -> DeviceOperationRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._assemble_device_once, platform, platform_user_id, entity_key, operation_id
            )

    def _assemble_device_once(
        self, platform: str, platform_user_id: str, entity_key: str, operation_id: str
    ) -> DeviceOperationRecord:
        definition = self._device_definition(entity_key)
        operation_name = "device.assemble"
        request_hash = self._request_hash(
            operation_name,
            {"platform": platform, "platform_user_id": platform_user_id, "entity_key": definition.key},
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
                return self._device_operation_from_payload(json.loads(existing["result_json"]), replay=True)

            row = self._require_player(connection, platform, platform_user_id)
            missing = device_missing_requirements(
                definition=definition,
                path_key=str(row["path_key"] or ""),
                realm_key=str(row["realm_key"]),
                realm_layer=player_integer(row, "realm_layer"),
            )
            if missing:
                raise DeviceRequirementError("device requirements are missing")
            owned = connection.execute(
                "SELECT COUNT(*) FROM device_instances WHERE player_id = ? AND entity_key = ?",
                (int(row["id"]), definition.key),
            ).fetchone()[0]
            if int(owned) >= definition.max_instances:
                raise DeviceLimitReachedError("device instance limit is reached")

            costs: dict[str, Any] = dict(definition.assembly_items)
            costs["spirit_stones"] = definition.assembly_spirit_stones
            if player_currency(row) < definition.assembly_spirit_stones:
                raise DeviceMaterialError("spirit stones cannot cover the assembly cost")
            transition = apply_player_asset_transition(
                connection, row, costs, now_text, mode="spend"
            )
            instance_id = f"device-{uuid4().hex}"
            connection.execute(
                """
                INSERT INTO device_instances(
                    instance_id, player_id, entity_key, durability_bp, max_durability_bp,
                    status, deployed, assembly_operation_id, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'active', 0, ?, ?, ?)
                """,
                (
                    instance_id,
                    int(row["id"]),
                    definition.key,
                    definition.max_durability_bp,
                    definition.max_durability_bp,
                    operation_id,
                    now_text,
                    now_text,
                ),
            )
            payload = {
                "entity_key": definition.key,
                "label": definition.label,
                "action": "assemble",
                "instance_id": instance_id,
                "durability_bp": definition.max_durability_bp,
                "max_durability_bp": definition.max_durability_bp,
                "status": "active",
                "deployed": False,
                "spirit_stones_before": transition.before.currency,
                "spirit_stones_after": transition.after.currency,
                "items_spent": dict(definition.assembly_items),
            }
            self._insert_operation(
                connection,
                operation_id=operation_id,
                operation_name=operation_name,
                player_id=int(row["id"]),
                request_hash=request_hash,
                payload=payload,
                now_text=now_text,
            )
            return self._device_operation_from_payload(payload)

    async def deploy_device(
        self,
        *,
        platform: str,
        platform_user_id: str,
        entity_key: str,
        operation_id: str,
    ) -> DeviceOperationRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._deploy_device_once, platform, platform_user_id, entity_key, operation_id
            )

    def _deploy_device_once(
        self, platform: str, platform_user_id: str, entity_key: str, operation_id: str
    ) -> DeviceOperationRecord:
        definition = self._device_definition(entity_key)
        return self._device_transition_once(
            platform=platform,
            platform_user_id=platform_user_id,
            definition=definition,
            operation_id=operation_id,
            action="deploy",
        )

    async def recall_device(
        self,
        *,
        platform: str,
        platform_user_id: str,
        entity_key: str,
        operation_id: str,
    ) -> DeviceOperationRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._recall_device_once, platform, platform_user_id, entity_key, operation_id
            )

    def _recall_device_once(
        self, platform: str, platform_user_id: str, entity_key: str, operation_id: str
    ) -> DeviceOperationRecord:
        definition = self._device_definition(entity_key)
        return self._device_transition_once(
            platform=platform,
            platform_user_id=platform_user_id,
            definition=definition,
            operation_id=operation_id,
            action="recall",
        )

    def _device_transition_once(
        self,
        *,
        platform: str,
        platform_user_id: str,
        definition: DeviceDefinition,
        operation_id: str,
        action: str,
    ) -> DeviceOperationRecord:
        operation_name = f"device.{action}"
        request_hash = self._request_hash(
            operation_name,
            {"platform": platform, "platform_user_id": platform_user_id, "entity_key": definition.key},
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
                return self._device_operation_from_payload(json.loads(existing["result_json"]), replay=True)

            row = self._require_player(connection, platform, platform_user_id)
            instance = self._device_instance_row(connection, int(row["id"]), definition)
            if instance is None:
                raise DeviceNotFoundError("the player does not own this device")
            deployed = bool(instance["deployed"])
            if action == "deploy":
                if str(instance["status"]) == "broken":
                    raise DeviceBrokenError("a broken device must be repaired before deployment")
                if deployed:
                    raise DeviceStateError("the device is already deployed")
            elif not deployed:
                raise DeviceStateError("the device is not deployed")
            connection.execute(
                "UPDATE device_instances SET deployed = ?, updated_at = ? WHERE instance_id = ?",
                (0 if action == "recall" else 1, now_text, str(instance["instance_id"])),
            )
            payload = {
                "entity_key": definition.key,
                "label": definition.label,
                "action": action,
                "instance_id": str(instance["instance_id"]),
                "durability_bp": int(instance["durability_bp"]),
                "max_durability_bp": int(instance["max_durability_bp"]),
                "status": str(instance["status"]),
                "deployed": action == "deploy",
                "spirit_stones_before": player_currency(row),
                "spirit_stones_after": player_currency(row),
                "items_spent": {},
            }
            self._insert_operation(
                connection,
                operation_id=operation_id,
                operation_name=operation_name,
                player_id=int(row["id"]),
                request_hash=request_hash,
                payload=payload,
                now_text=now_text,
            )
            return self._device_operation_from_payload(payload)

    async def repair_device(
        self,
        *,
        platform: str,
        platform_user_id: str,
        entity_key: str,
        operation_id: str,
    ) -> DeviceOperationRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._repair_device_once, platform, platform_user_id, entity_key, operation_id
            )

    def _repair_device_once(
        self, platform: str, platform_user_id: str, entity_key: str, operation_id: str
    ) -> DeviceOperationRecord:
        definition = self._device_definition(entity_key)
        operation_name = "device.repair"
        request_hash = self._request_hash(
            operation_name,
            {"platform": platform, "platform_user_id": platform_user_id, "entity_key": definition.key},
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
                return self._device_operation_from_payload(json.loads(existing["result_json"]), replay=True)

            row = self._require_player(connection, platform, platform_user_id)
            instance = self._device_instance_row(connection, int(row["id"]), definition)
            if instance is None:
                raise DeviceNotFoundError("the player does not own this device")
            current = int(instance["durability_bp"])
            if current >= int(instance["max_durability_bp"]) and str(instance["status"]) == "active":
                raise DeviceStateError("the device is already at full durability")
            steps = repair_steps_missing(current_bp=current, definition=definition)
            costs: dict[str, Any] = {
                item_key: quantity * steps
                for item_key, quantity in definition.maintenance_items.items()
            }
            costs["spirit_stones"] = definition.maintenance_spirit_stones * steps
            if player_currency(row) < int(costs["spirit_stones"]):
                raise DeviceMaterialError("spirit stones cannot cover the repair cost")
            transition = apply_player_asset_transition(
                connection, row, costs, now_text, mode="spend"
            )
            restored = min(
                int(instance["max_durability_bp"]),
                current + steps * definition.repair_bp_per_material,
            )
            status = "active" if restored > 0 else str(instance["status"])
            connection.execute(
                "UPDATE device_instances SET durability_bp = ?, status = ?, updated_at = ? "
                "WHERE instance_id = ?",
                (restored, status, now_text, str(instance["instance_id"])),
            )
            payload = {
                "entity_key": definition.key,
                "label": definition.label,
                "action": "repair",
                "instance_id": str(instance["instance_id"]),
                "durability_bp": restored,
                "max_durability_bp": int(instance["max_durability_bp"]),
                "status": status,
                "deployed": bool(instance["deployed"]),
                "spirit_stones_before": transition.before.currency,
                "spirit_stones_after": transition.after.currency,
                "items_spent": {
                    item_key: quantity * steps
                    for item_key, quantity in definition.maintenance_items.items()
                },
                "repair_steps": steps,
            }
            self._insert_operation(
                connection,
                operation_id=operation_id,
                operation_name=operation_name,
                player_id=int(row["id"]),
                request_hash=request_hash,
                payload=payload,
                now_text=now_text,
            )
            return self._device_operation_from_payload(payload)

    def _device_instance_row(
        self, connection: sqlite3.Connection, player_id: int, definition: DeviceDefinition
    ) -> sqlite3.Row | None:
        return connection.execute(
            "SELECT * FROM device_instances WHERE player_id = ? AND entity_key = ? "
            "ORDER BY created_at, instance_id LIMIT 1",
            (player_id, definition.key),
        ).fetchone()

    def _deployed_device_snapshot(
        self, connection: sqlite3.Connection, player_id: int
    ) -> dict[str, Any] | None:
        """Return the deployed device frozen for a battle start, if any."""

        row = connection.execute(
            "SELECT * FROM device_instances WHERE player_id = ? AND deployed = 1 "
            "AND status = 'active' LIMIT 1",
            (player_id,),
        ).fetchone()
        if row is None:
            return None
        definition = self._device_definition(str(row["entity_key"]))
        from .entity_rules import device_frozen_snapshot

        return device_frozen_snapshot(
            definition=definition,
            instance_id=str(row["instance_id"]),
            durability_bp=int(row["durability_bp"]),
        )

    @staticmethod
    def _device_operation_from_payload(
        payload: dict[str, Any], *, replay: bool = False
    ) -> DeviceOperationRecord:
        return DeviceOperationRecord(
            entity_key=str(payload["entity_key"]),
            label=str(payload["label"]),
            action=str(payload["action"]),
            instance_id=str(payload["instance_id"]),
            durability_bp=int(payload["durability_bp"]),
            max_durability_bp=int(payload["max_durability_bp"]),
            status=str(payload["status"]),
            deployed=bool(payload["deployed"]),
            spirit_stones_before=int(payload["spirit_stones_before"]),
            spirit_stones_after=int(payload["spirit_stones_after"]),
            items_spent={str(key): int(value) for key, value in dict(payload.get("items_spent", {})).items()},
            already_completed=replay,
        )