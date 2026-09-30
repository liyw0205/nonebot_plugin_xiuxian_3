"""灵兽实体的短事务持久化。"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime
from typing import Any
from uuid import uuid4

from ...contracts import serialize_datetime
from ..persistence.errors import (
    CompanionAlreadyBondedError,
    CompanionCapacityError,
    CompanionGearError,
    CompanionInjuredError,
    CompanionNotFoundError,
    CompanionRequirementError,
    OperationConflictError,
    PlayerNotFoundError,
    PlayerSuspendedError,
    ResourceInsufficientError,
)
from ..utils.assets import spend_player_assets
from ..utils.player import player_field, player_values
from .models import CompanionMutationRecord, CompanionSnapshot, CompanionStatusRecord, CompanionView
from .rules import CompanionDefinition, companion_definition, level_after_experience


class CompanionRepositoryMixin:
    """保存灵兽实体，并提供只读战斗快照。"""

    async def list_companions(self, *, platform: str, platform_user_id: str) -> CompanionStatusRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._list_companions_sync, platform, platform_user_id)

    async def bond_companion(
        self,
        *,
        platform: str,
        platform_user_id: str,
        companion_key: str,
        operation_id: str,
    ) -> CompanionMutationRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._bond_companion_sync,
                platform,
                platform_user_id,
                companion_key,
                operation_id,
            )

    async def feed_companion(
        self,
        *,
        platform: str,
        platform_user_id: str,
        companion_ref: str,
        operation_id: str,
    ) -> CompanionMutationRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._feed_companion_sync,
                platform,
                platform_user_id,
                companion_ref,
                operation_id,
            )

    async def rest_companion(
        self,
        *,
        platform: str,
        platform_user_id: str,
        companion_ref: str,
        operation_id: str,
    ) -> CompanionMutationRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._rest_companion_sync,
                platform,
                platform_user_id,
                companion_ref,
                operation_id,
            )

    async def equip_companion_gear(
        self,
        *,
        platform: str,
        platform_user_id: str,
        companion_ref: str,
        gear_key: str,
        operation_id: str,
    ) -> CompanionMutationRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._equip_companion_gear_sync,
                platform,
                platform_user_id,
                companion_ref,
                gear_key,
                operation_id,
            )

    def companion_battle_snapshot(
        self, connection: sqlite3.Connection, player_id: int
    ) -> CompanionSnapshot:
        """读取出战实体的冻结数据；此方法不写玩家或灵兽状态。"""

        rows = connection.execute(
            "SELECT * FROM companion_instances WHERE player_id = ? AND status IN ('active', 'available') AND deployed = 1 ORDER BY id",
            (player_id,),
        ).fetchall()
        snapshots: list[dict[str, object]] = []
        for row in rows:
            definition = companion_definition(str(row["companion_key"]), getattr(self, "content", None))
            gear = self._gear_snapshot(connection, int(row["id"]))
            snapshots.append(
                {
                    "instance_id": str(row["instance_id"]),
                    "companion_key": definition.key,
                    "kind": definition.kind,
                    "level": int(row["level"]),
                    "experience": int(row["experience"]),
                    "affinity": int(row["affinity"]),
                    "effect": dict(definition.effect or {}),
                    "gear": gear,
                }
            )
        player = connection.execute("SELECT player_id FROM players WHERE id = ?", (player_id,)).fetchone()
        return CompanionSnapshot(
            player_id=str(player["player_id"]) if player is not None else "",
            companions=tuple(snapshots),
        )

    def _list_companions_sync(self, platform: str, platform_user_id: str) -> CompanionStatusRecord:
        with self._connect() as connection:
            player = self._require_player(connection, platform, platform_user_id, writable=False)
            return CompanionStatusRecord(
                player=self._row_to_player(player),
                companions=tuple(self._view_rows(connection, player["id"])),
            )

    def _bond_companion_sync(
        self, platform: str, platform_user_id: str, companion_key: str, operation_id: str
    ) -> CompanionMutationRecord:
        definition = companion_definition(companion_key, getattr(self, "content", None))
        if definition.kind not in {"beast", "mount"}:
            raise CompanionRequirementError("gear cannot be bonded as a companion")
        operation_name = "companion.bond"
        request_hash = self._request_hash(operation_name, {"platform": platform, "platform_user_id": platform_user_id, "key": definition.key})
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._companion_operation(connection, operation_id, operation_name, request_hash)
            if replay is not None:
                return self._mutation_from_payload(replay, replay=True)
            player = self._require_player(connection, platform, platform_user_id)
            if not self._source_available(connection, player, definition):
                raise CompanionRequirementError("companion source is unavailable")
            count = connection.execute(
                "SELECT COUNT(*) AS count FROM companion_instances WHERE player_id = ? AND kind = ? AND status <> 'retired'",
                (player["id"], definition.kind),
            ).fetchone()
            if count is not None and int(count["count"]) >= definition.capacity:
                raise CompanionCapacityError("companion capacity reached")
            deployed = connection.execute(
                "SELECT 1 FROM companion_instances WHERE player_id = ? AND kind = ? AND status IN ('active', 'available') AND deployed = 1 LIMIT 1",
                (player["id"], definition.kind),
            ).fetchone() is None
            instance_id = uuid4().hex
            status = "active" if definition.kind == "beast" else "available"
            connection.execute(
                "INSERT INTO companion_instances(instance_id, player_id, companion_key, kind, status, level, experience, affinity, stamina, deployed, snapshot_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, 0, 0, ?, ?, '{}', ?, ?)",
                (instance_id, player["id"], definition.key, definition.kind, status, definition.level_min, definition.stamina, int(deployed), now_text, now_text),
            )
            return self._store_companion_operation(
                connection,
                operation_id,
                operation_name,
                request_hash,
                player,
                instance_id,
                now_text,
                spent={},
            )

    def _feed_companion_sync(
        self, platform: str, platform_user_id: str, companion_ref: str, operation_id: str
    ) -> CompanionMutationRecord:
        operation_name = "companion.feed"
        request_hash = self._request_hash(operation_name, {"platform": platform, "platform_user_id": platform_user_id, "companion_ref": companion_ref})
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._companion_operation(connection, operation_id, operation_name, request_hash)
            if replay is not None:
                return self._mutation_from_payload(replay, replay=True)
            player = self._require_player(connection, platform, platform_user_id)
            instance = self._find_instance(connection, player["id"], companion_ref)
            definition = companion_definition(str(instance["companion_key"]), getattr(self, "content", None))
            if definition.kind != "beast" or not definition.feed_item_key:
                raise CompanionRequirementError("this entity cannot be fed")
            if str(instance["status"]) in {"injured", "resting", "retired"}:
                raise CompanionInjuredError("companion is resting")
            spent = {definition.feed_item_key: 1}
            try:
                next_assets = spend_player_assets(connection, player, spent, now_text)
            except ValueError as exc:
                raise ResourceInsufficientError("feed item is insufficient") from exc
            experience = int(instance["experience"]) + definition.feed_experience
            level = level_after_experience(definition, experience)
            connection.execute(
                "UPDATE companion_instances SET experience = ?, level = ?, updated_at = ? WHERE id = ?",
                (experience, level, now_text, instance["id"]),
            )
            return self._store_companion_operation(
                connection,
                operation_id,
                operation_name,
                request_hash,
                player,
                str(instance["instance_id"]),
                now_text,
                spent=spent,
            )

    def _rest_companion_sync(
        self, platform: str, platform_user_id: str, companion_ref: str, operation_id: str
    ) -> CompanionMutationRecord:
        operation_name = "companion.rest"
        request_hash = self._request_hash(operation_name, {"platform": platform, "platform_user_id": platform_user_id, "companion_ref": companion_ref})
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._companion_operation(connection, operation_id, operation_name, request_hash)
            if replay is not None:
                return self._mutation_from_payload(replay, replay=True)
            player = self._require_player(connection, platform, platform_user_id)
            instance = self._find_instance(connection, player["id"], companion_ref)
            status = str(instance["status"])
            if status == "retired":
                raise CompanionNotFoundError("companion is retired")
            if status not in {"resting", "injured"}:
                raise CompanionRequirementError("companion does not need rest")
            injury_until = player_field(instance, "injury_until")
            if injury_until and datetime.fromisoformat(str(injury_until)) > self._now():
                raise CompanionInjuredError("companion injury has not recovered")
            connection.execute(
                "UPDATE companion_instances SET status = ?, injury_until = NULL, updated_at = ? WHERE id = ?",
                ("active" if str(instance["kind"]) == "beast" else "available", now_text, instance["id"]),
            )
            return self._store_companion_operation(
                connection, operation_id, operation_name, request_hash, player, str(instance["instance_id"]), now_text, spent={}
            )

    def _equip_companion_gear_sync(
        self, platform: str, platform_user_id: str, companion_ref: str, gear_key: str, operation_id: str
    ) -> CompanionMutationRecord:
        operation_name = "companion.equip_gear"
        request_hash = self._request_hash(operation_name, {"platform": platform, "platform_user_id": platform_user_id, "companion_ref": companion_ref, "gear_key": gear_key})
        now_text = serialize_datetime(self._now())
        content = getattr(self, "content", None)
        bundle = content
        if bundle is None:
            from ..content import bundled_content

            bundle = bundled_content()
        gear = bundle.get("companion", str(gear_key), include_locked=False)
        if gear is None:
            aliases = {str(row.get("name")): str(row["key"]) for row in bundle.list("companion", include_locked=False)}
            resolved = aliases.get(str(gear_key), str(gear_key))
            gear = bundle.get("companion", resolved, include_locked=False)
        if gear is None or gear.get("kind") not in {"beast_gear", "mount_tack"}:
            raise CompanionGearError("gear is unavailable")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._companion_operation(connection, operation_id, operation_name, request_hash)
            if replay is not None:
                return self._mutation_from_payload(replay, replay=True)
            player = self._require_player(connection, platform, platform_user_id)
            instance = self._find_instance(connection, player["id"], companion_ref)
            expected_kind = "beast" if gear["kind"] == "beast_gear" else "mount"
            if str(instance["kind"]) != expected_kind:
                raise CompanionGearError("gear does not fit this entity")
            try:
                next_assets = spend_player_assets(
                    connection,
                    player,
                    {str(gear["key"]): 1},
                    now_text,
                )
            except ValueError as exc:
                raise ResourceInsufficientError("gear is not in inventory") from exc
            old = connection.execute(
                "SELECT id FROM companion_gear_instances WHERE companion_instance_id = ? AND status = 'equipped' LIMIT 1",
                (instance["id"],),
            ).fetchone()
            if old is not None:
                raise CompanionGearError("companion already has gear")
            gear_instance_id = uuid4().hex
            connection.execute(
                "INSERT INTO companion_gear_instances(gear_instance_id, player_id, companion_instance_id, gear_key, status, durability_bp, operation_id, created_at, updated_at) VALUES (?, ?, ?, ?, 'equipped', ?, ?, ?, ?)",
                (gear_instance_id, player["id"], instance["id"], str(gear["key"]), int(gear.get("durability_bp", 0)), operation_id, now_text, now_text),
            )
            return self._store_companion_operation(
                connection, operation_id, operation_name, request_hash, player, str(instance["instance_id"]), now_text, spent={str(gear["key"]): 1}
            )

    def _source_available(self, connection: sqlite3.Connection, player: sqlite3.Row, definition: CompanionDefinition) -> bool:
        flags = set(self._json_object(player["intro_json"], {}).get("flags", []))
        for source in definition.source:
            if source == str(player["location_key"]) or source in flags:
                return True
            if connection.execute(
                "SELECT 1 FROM activity_events WHERE player_id = ? AND event_key = ? LIMIT 1",
                (player["id"], source),
            ).fetchone() is not None:
                return True
        return False

    def _find_instance(self, connection: sqlite3.Connection, player_id: int, reference: str) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM companion_instances WHERE player_id = ? AND (instance_id = ? OR companion_key = ?) AND status <> 'retired' ORDER BY id LIMIT 1",
            (player_id, str(reference), str(reference)),
        ).fetchone()
        if row is None:
            raise CompanionNotFoundError("companion does not exist")
        return row

    def _view_rows(self, connection: sqlite3.Connection, player_id: int) -> list[CompanionView]:
        rows = connection.execute(
            "SELECT * FROM companion_instances WHERE player_id = ? AND status <> 'retired' ORDER BY id",
            (player_id,),
        ).fetchall()
        result = []
        for row in rows:
            definition = companion_definition(str(row["companion_key"]), getattr(self, "content", None))
            result.append(
                CompanionView(
                    instance_id=str(row["instance_id"]),
                    companion_key=definition.key,
                    name=definition.label,
                    kind=definition.kind,
                    level=int(row["level"]),
                    experience=int(row["experience"]),
                    affinity=int(row["affinity"]),
                    stamina=int(row["stamina"]),
                    status=str(row["status"]),
                    deployed=bool(row["deployed"]),
                    gear=tuple(self._gear_snapshot(connection, int(row["id"]))),
                )
            )
        return result

    def _gear_snapshot(self, connection: sqlite3.Connection, companion_id: int) -> list[dict[str, object]]:
        rows = connection.execute(
            "SELECT gear_instance_id, gear_key, status, durability_bp FROM companion_gear_instances WHERE companion_instance_id = ? AND status = 'equipped' ORDER BY id",
            (companion_id,),
        ).fetchall()
        return [
            {
                "instance_id": str(row["gear_instance_id"]),
                "gear_key": str(row["gear_key"]),
                "status": str(row["status"]),
                "durability_bp": int(row["durability_bp"]),
            }
            for row in rows
        ]

    def _companion_operation(self, connection: sqlite3.Connection, operation_id: str, operation_name: str, request_hash: str) -> dict[str, Any] | None:
        existing = connection.execute(
            "SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id = ?",
            (operation_id,),
        ).fetchone()
        if existing is None:
            return None
        if existing["operation_name"] != operation_name or existing["request_hash"] != request_hash:
            raise OperationConflictError("operation input differs from its original request")
        return json.loads(existing["result_json"])

    def _store_companion_operation(
        self, connection: sqlite3.Connection, operation_id: str, operation_name: str, request_hash: str,
        player: sqlite3.Row, instance_id: str, now_text: str, *, spent: dict[str, int]
    ) -> CompanionMutationRecord:
        updated = connection.execute("SELECT * FROM players WHERE id = ?", (player["id"],)).fetchone()
        instance = connection.execute("SELECT * FROM companion_instances WHERE instance_id = ?", (instance_id,)).fetchone()
        if updated is None or instance is None:
            raise RuntimeError("companion operation returned no entity")
        view = self._view_rows(connection, updated["id"])
        companion = next(item for item in view if item.instance_id == instance_id)
        payload = {
            "player": self._player_payload(self._row_to_player(updated)),
            "instance_id": instance_id,
            "companion": self._companion_payload(companion),
            "changed": True,
            "spent": spent,
        }
        connection.execute(
            "INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (operation_id, operation_name, updated["id"], request_hash, json.dumps(payload, ensure_ascii=False, sort_keys=True), now_text),
        )
        return CompanionMutationRecord(self._row_to_player(updated), companion, True, False, dict(spent))

    def _mutation_from_payload(self, payload: dict[str, Any], *, replay: bool) -> CompanionMutationRecord:
        return CompanionMutationRecord(
            player=self._row_to_player(payload["player"]),
            companion=self._companion_from_payload(payload["companion"]),
            changed=bool(payload.get("changed", True)),
            already_completed=replay,
            spent={str(key): int(value) for key, value in payload.get("spent", {}).items()},
        )

    @staticmethod
    def _companion_payload(view: CompanionView) -> dict[str, Any]:
        return {
            "instance_id": view.instance_id,
            "companion_key": view.companion_key,
            "name": view.name,
            "kind": view.kind,
            "level": view.level,
            "experience": view.experience,
            "affinity": view.affinity,
            "stamina": view.stamina,
            "status": view.status,
            "deployed": view.deployed,
            "gear": [dict(item) for item in view.gear],
        }

    @staticmethod
    def _companion_from_payload(payload: dict[str, Any]) -> CompanionView:
        return CompanionView(
            instance_id=str(payload["instance_id"]),
            companion_key=str(payload["companion_key"]),
            name=str(payload["name"]),
            kind=str(payload["kind"]),
            level=int(payload["level"]),
            experience=int(payload["experience"]),
            affinity=int(payload["affinity"]),
            stamina=int(payload["stamina"]),
            status=str(payload["status"]),
            deployed=bool(payload.get("deployed", False)),
            gear=tuple(dict(item) for item in payload.get("gear", [])),
        )


__all__ = ["CompanionRepositoryMixin"]
