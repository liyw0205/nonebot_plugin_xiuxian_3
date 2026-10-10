"""灵兽实体的短事务持久化。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
from datetime import datetime, timedelta
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
    OperationResultMalformedError,
    PlayerNotFoundError,
    PlayerSuspendedError,
    ResourceInsufficientError,
)
from ..utils.assets import (
    AssetDeltaError,
    player_available_assets_missing,
    spend_player_assets,
    spend_player_items,
)
from ..utils.json_cache import decode_json_strict
from ..utils.operations import operation_replay
from ..utils.player import PLAYER_NUMERIC_FIELDS, player_field
from .models import CompanionMutationRecord, CompanionSnapshot, CompanionStatusRecord, CompanionView
from .rules import (
    CompanionDefinition,
    companion_definition,
    companion_evolution_definition,
    level_after_experience,
)


_COMPANION_MUTATION_FIELDS = frozenset(
    {"player", "instance_id", "companion", "changed", "spent", "outcome", "evolution_key"}
)
_COMPANION_VIEW_FIELDS = frozenset(
    {
        "instance_id",
        "companion_key",
        "name",
        "kind",
        "level",
        "experience",
        "affinity",
        "stamina",
        "status",
        "deployed",
        "evolution_stage",
        "skill_slots",
        "gear",
    }
)
_COMPANION_GEAR_FIELDS = frozenset({"instance_id", "gear_key", "status", "durability_bp"})
_COMPANION_STATUSES = frozenset({"active", "available", "resting", "injured", "bonded", "travelling"})
_COMPANION_OUTCOMES = frozenset({"changed", "evolved", "failed"})
_COMPANION_PLAYER_JSON_FIELDS = frozenset(
    {"qualification_json", "inventory_json", "durability_json", "intro_json", "faction_reputation_json"}
)


def _operation_mentions_instance(value: Any, instance_id: str) -> bool:
    if isinstance(value, dict):
        if any(value.get(key) == instance_id for key in ("instance_id", "mount_instance_id")):
            return True
        return any(_operation_mentions_instance(item, instance_id) for item in value.values())
    if isinstance(value, list):
        return any(_operation_mentions_instance(item, instance_id) for item in value)
    return False


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

    async def evolve_companion(
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
                self._evolve_companion_sync,
                platform,
                platform_user_id,
                companion_ref,
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
                    "evolution_stage": str(player_field(row, "evolution_stage", "base")),
                    "skill_slots": int(player_field(row, "skill_slots", 0) or 0),
                    "effect": dict(definition.effect or {}),
                    "gear": gear,
                }
            )
        player = connection.execute("SELECT player_id FROM players WHERE id = ?", (player_id,)).fetchone()
        return CompanionSnapshot(
            player_id=str(player["player_id"]) if player is not None else "",
            companions=tuple(snapshots),
        )

    def companion_carry_snapshot(self, connection: sqlite3.Connection, player_id: int) -> list[dict[str, object]]:
        rows = connection.execute(
            "SELECT g.gear_instance_id, g.gear_key, g.durability_bp "
            "FROM companion_gear_instances g JOIN companion_instances c ON c.id=g.companion_instance_id "
            "WHERE g.player_id=? AND g.status='equipped' AND g.durability_bp>0 "
            "AND c.kind='beast' AND c.deployed=1 AND c.status IN ('active', 'available') ORDER BY g.id",
            (player_id,),
        ).fetchall()
        result: list[dict[str, object]] = []
        for row in rows:
            definition = companion_definition(str(row["gear_key"]), self.content)
            effect = definition.effect or {}
            if effect.get("type") != "carry_capacity":
                continue
            value = effect.get("value")
            if type(value) is not int or value < 0:
                raise ValueError("companion carry effect is invalid")
            result.append({
                "instance_id": str(row["gear_instance_id"]), "gear_key": definition.key,
                "durability_bp": int(row["durability_bp"]), "carry_capacity": value,
            })
        return result

    def companion_carry_capacity(self, connection: sqlite3.Connection, player_id: int) -> int:
        return sum(int(item["carry_capacity"]) for item in self.companion_carry_snapshot(connection, player_id))

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
        operation_name = "companion.bond"
        request_hash = self._request_hash(
            operation_name,
            {"platform": platform, "platform_user_id": platform_user_id, "key": companion_key},
        )
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._companion_operation(connection, operation_id, operation_name, request_hash)
            if replay is not None:
                return self._mutation_from_payload(replay, replay=True)
            definition = companion_definition(companion_key, getattr(self, "content", None))
            if definition.kind not in {"beast", "mount"}:
                raise CompanionRequirementError("gear cannot be bonded as a companion")
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
                if player_available_assets_missing(connection, player, spent):
                    raise AssetDeltaError("feed item is unavailable")
                spend_player_items(connection, player, spent, now_text)
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
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._companion_operation(connection, operation_id, operation_name, request_hash)
            if replay is not None:
                return self._mutation_from_payload(replay, replay=True)
            bundle = getattr(self, "content", None)
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
            player = self._require_player(connection, platform, platform_user_id)
            instance = self._find_instance(connection, player["id"], companion_ref)
            expected_kind = "beast" if gear["kind"] == "beast_gear" else "mount"
            if str(instance["kind"]) != expected_kind:
                raise CompanionGearError("gear does not fit this entity")
            if str(instance["status"]) == "travelling":
                raise CompanionRequirementError("travelling companion cannot change gear")
            try:
                spend_player_items(
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

    def _evolve_companion_sync(
        self,
        platform: str,
        platform_user_id: str,
        companion_ref: str,
        operation_id: str,
    ) -> CompanionMutationRecord:
        operation_name = "companion.evolve"
        request_hash = self._request_hash(
            operation_name,
            {
                "platform": platform,
                "platform_user_id": platform_user_id,
                "companion_ref": companion_ref,
            },
        )
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._companion_operation(connection, operation_id, operation_name, request_hash)
            if replay is not None:
                return self._mutation_from_payload(replay, replay=True)
            player = self._require_player(connection, platform, platform_user_id)
            instance = self._find_instance(connection, player["id"], companion_ref)
            try:
                evolution = companion_evolution_definition(
                    str(instance["companion_key"]), getattr(self, "content", None)
                )
            except ValueError as exc:
                raise CompanionRequirementError("companion has no available evolution") from exc
            source = companion_definition(str(instance["companion_key"]), getattr(self, "content", None))
            if evolution.kind != source.kind:
                raise CompanionRequirementError("evolution kind does not match companion")
            if str(instance["status"]) == "travelling":
                raise CompanionRequirementError("travelling companion cannot evolve")
            if str(instance["status"]) in {"resting", "injured", "retired"}:
                raise CompanionInjuredError("companion is resting")
            if str(player_field(instance, "evolution_stage", "base")) == "evolved":
                raise CompanionRequirementError("companion has already evolved")
            if int(instance["level"]) < evolution.required_level:
                raise CompanionRequirementError("companion level is insufficient")
            if int(instance["affinity"]) < evolution.required_affinity:
                raise CompanionRequirementError("companion affinity is insufficient")
            try:
                if player_available_assets_missing(connection, player, evolution.costs):
                    raise AssetDeltaError("evolution assets are unavailable")
                spend_player_assets(connection, player, evolution.costs, now_text)
            except AssetDeltaError as exc:
                raise ResourceInsufficientError("evolution materials are insufficient") from exc

            roll = int.from_bytes(
                hashlib.sha256(f"{operation_id}:evolution".encode("utf-8")).digest()[:4],
                "big",
            ) % 10_000
            success = roll < evolution.success_bp
            snapshot = {
                "operation_id": operation_id,
                "evolution_key": evolution.key,
                "source_key": evolution.source_key,
                "target_key": evolution.target_key,
                "level": int(instance["level"]),
                "affinity": int(instance["affinity"]),
                "costs": dict(evolution.costs),
                "success_bp": evolution.success_bp,
                "roll_bp": roll,
            }
            if success:
                target = companion_definition(evolution.target_key, getattr(self, "content", None))
                if target.kind != evolution.kind:
                    raise CompanionRequirementError("evolution target kind does not match companion")
                connection.execute(
                    "UPDATE companion_instances SET companion_key = ?, evolution_stage = 'evolved', skill_slots = ?, snapshot_json = ?, updated_at = ? WHERE id = ?",
                    (
                        target.key,
                        evolution.skill_slots,
                        json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
                        now_text,
                        instance["id"],
                    ),
                )
                outcome = "evolved"
            else:
                injury_until = (
                    now + timedelta(seconds=evolution.failure_recovery_seconds)
                    if evolution.failure_recovery_seconds
                    else None
                )
                connection.execute(
                    "UPDATE companion_instances SET evolution_stage = 'failed', status = ?, injury_until = ?, snapshot_json = ?, updated_at = ? WHERE id = ?",
                    (
                        "injured" if injury_until is not None else str(instance["status"]),
                        serialize_datetime(injury_until) if injury_until is not None else None,
                        json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
                        now_text,
                        instance["id"],
                    ),
                )
                outcome = "failed"
            return self._store_companion_operation(
                connection,
                operation_id,
                operation_name,
                request_hash,
                player,
                str(instance["instance_id"]),
                now_text,
                spent=dict(evolution.costs),
                outcome=outcome,
                evolution_key=evolution.key,
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
                    evolution_stage=str(player_field(row, "evolution_stage", "base")),
                    skill_slots=int(player_field(row, "skill_slots", 0) or 0),
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

    def _companion_operation(
        self,
        connection: sqlite3.Connection,
        operation_id: str,
        operation_name: str,
        request_hash: str,
    ) -> dict[str, Any] | None:
        existing = connection.execute(
            "SELECT rowid AS operation_rowid, player_id, created_at FROM operations WHERE operation_id = ?",
            (operation_id,),
        ).fetchone()
        if existing is None:
            return None
        try:
            player_id = int(existing["player_id"])
        except (TypeError, ValueError) as exc:
            raise OperationResultMalformedError("companion operation owner is invalid") from exc
        payload = operation_replay(
            connection,
            operation_id,
            operation_name,
            request_hash,
            player_id=player_id,
        )
        if payload is None:
            return None
        self._validate_companion_mutation_payload(
            connection,
            operation_name,
            player_id,
            payload,
            operation_created_at=str(existing["created_at"]),
            operation_rowid=int(existing["operation_rowid"]),
            operation_id=operation_id,
        )
        return payload

    def _validate_companion_mutation_payload(
        self,
        connection: sqlite3.Connection,
        operation_name: str,
        player_id: int,
        payload: dict[str, Any],
        operation_created_at: str,
        operation_rowid: int,
        operation_id: str,
    ) -> None:
        if set(payload) != _COMPANION_MUTATION_FIELDS:
            raise OperationResultMalformedError("companion operation result has an invalid shape")
        if payload["changed"] is not True:
            raise OperationResultMalformedError("companion operation changed flag is invalid")
        if not isinstance(payload["instance_id"], str) or not payload["instance_id"]:
            raise OperationResultMalformedError("companion operation instance is invalid")
        if type(payload["outcome"]) is not str or payload["outcome"] not in _COMPANION_OUTCOMES:
            raise OperationResultMalformedError("companion operation outcome is invalid")
        if payload["evolution_key"] is not None and (
            not isinstance(payload["evolution_key"], str) or not payload["evolution_key"]
        ):
            raise OperationResultMalformedError("companion operation evolution is invalid")

        spent = payload["spent"]
        if not isinstance(spent, dict) or any(
            not isinstance(key, str)
            or not key
            or type(value) is not int
            or value < 0
            for key, value in spent.items()
        ):
            raise OperationResultMalformedError("companion operation spending is invalid")
        if operation_name in {"companion.bond", "companion.rest"} and spent:
            raise OperationResultMalformedError("companion operation spending differs from its action")
        instance_row = connection.execute(
            "SELECT * FROM companion_instances WHERE instance_id = ? AND player_id = ?",
            (payload["instance_id"], player_id),
        ).fetchone()
        if instance_row is None:
            raise OperationResultMalformedError("companion operation instance does not belong to its owner")
        later_operations = connection.execute(
            "SELECT result_json FROM operations WHERE player_id = ? AND rowid > ? ORDER BY rowid",
            (player_id, operation_rowid),
        ).fetchall()
        has_later_instance_write = False
        for later in later_operations:
            try:
                later_payload = decode_json_strict(str(later["result_json"]))
            except (TypeError, ValueError):
                continue
            if _operation_mentions_instance(later_payload, payload["instance_id"]):
                has_later_instance_write = True
                break
        if operation_name == "companion.feed":
            if len(spent) != 1 or next(iter(spent.values()), None) != 1:
                raise OperationResultMalformedError("companion feed spending differs from its action")
        if operation_name == "companion.equip_gear":
            if len(spent) != 1 or next(iter(spent.values()), None) != 1:
                raise OperationResultMalformedError("companion gear spending differs from its action")
        if operation_name == "companion.evolve" and payload["evolution_key"] is None:
            raise OperationResultMalformedError("companion evolution operation is missing its key")
        if operation_name != "companion.evolve" and payload["evolution_key"] is not None:
            raise OperationResultMalformedError("non-evolution companion operation has an evolution key")
        if operation_name != "companion.evolve" and payload["outcome"] != "changed":
            raise OperationResultMalformedError("companion operation outcome differs from its action")
        if operation_name == "companion.evolve" and payload["outcome"] not in {"evolved", "failed"}:
            raise OperationResultMalformedError("companion evolution outcome is invalid")

        owner = connection.execute("SELECT * FROM players WHERE id = ?", (player_id,)).fetchone()
        if owner is None:
            raise OperationResultMalformedError("companion operation owner does not exist")
        player = payload["player"]
        if not isinstance(player, dict):
            raise OperationResultMalformedError("companion operation player is invalid")
        expected_player_fields = set(self._player_payload(self._row_to_player(owner)))
        if set(player) != expected_player_fields:
            raise OperationResultMalformedError("companion operation player fields are invalid")
        if (
            player.get("id") != player.get("player_id")
            or player.get("player_id") != str(owner["player_id"])
            or player.get("platform") != str(owner["platform"])
            or player.get("platform_user_id") != str(owner["platform_user_id"])
        ):
            raise OperationResultMalformedError("companion operation player differs from its owner")
        for field in PLAYER_NUMERIC_FIELDS:
            value = player.get(field)
            if type(value) is not int or value < 0:
                raise OperationResultMalformedError("companion operation player numeric field is invalid")
        for field in _COMPANION_PLAYER_JSON_FIELDS:
            raw = player.get(field)
            if not isinstance(raw, str):
                raise OperationResultMalformedError("companion operation player JSON field is invalid")
            try:
                decoded = decode_json_strict(raw)
            except (TypeError, ValueError) as exc:
                raise OperationResultMalformedError("companion operation player JSON is invalid") from exc
            if not isinstance(decoded, dict):
                raise OperationResultMalformedError("companion operation player JSON must be an object")
        try:
            self._row_to_player(player)
        except (TypeError, ValueError, KeyError) as exc:
            raise OperationResultMalformedError("companion operation player projection is invalid") from exc

        companion = payload["companion"]
        if not isinstance(companion, dict) or set(companion) != _COMPANION_VIEW_FIELDS:
            raise OperationResultMalformedError("companion operation companion fields are invalid")
        text_fields = ("instance_id", "companion_key", "name", "kind", "status", "evolution_stage")
        if any(not isinstance(companion[field], str) or not companion[field] for field in text_fields):
            raise OperationResultMalformedError("companion operation companion text is invalid")
        if (
            type(companion["kind"]) is not str
            or type(companion["status"]) is not str
            or companion["kind"] not in {"beast", "mount"}
            or companion["status"] not in _COMPANION_STATUSES
        ):
            raise OperationResultMalformedError("companion operation companion state is invalid")
        if companion["kind"] != str(instance_row["kind"]):
            raise OperationResultMalformedError("companion operation kind differs from its instance")
        for field in ("level", "experience", "affinity", "stamina", "skill_slots"):
            if type(companion[field]) is not int or companion[field] < 0:
                raise OperationResultMalformedError("companion operation companion numeric field is invalid")
        if type(companion["deployed"]) is not bool:
            raise OperationResultMalformedError("companion operation companion deployed flag is invalid")
        if companion["instance_id"] != payload["instance_id"]:
            raise OperationResultMalformedError("companion operation instance differs from its projection")
        gear = companion["gear"]
        if not isinstance(gear, list):
            raise OperationResultMalformedError("companion operation gear is invalid")
        for item in gear:
            if not isinstance(item, dict) or set(item) != _COMPANION_GEAR_FIELDS:
                raise OperationResultMalformedError("companion operation gear fields are invalid")
            if any(not isinstance(item[field], str) or not item[field] for field in ("instance_id", "gear_key", "status")):
                raise OperationResultMalformedError("companion operation gear text is invalid")
            if (
                item["status"] != "equipped"
                or type(item["durability_bp"]) is not int
                or not 0 <= item["durability_bp"] <= 10_000
            ):
                raise OperationResultMalformedError("companion operation gear state is invalid")
        if operation_name == "companion.equip_gear":
            gear_keys = {str(item["gear_key"]) for item in gear}
            if set(spent) - gear_keys:
                raise OperationResultMalformedError("companion gear result does not match its spending")

        if companion["evolution_stage"] not in {"base", "evolved", "failed"}:
            raise OperationResultMalformedError("companion operation evolution stage is invalid")
        if operation_name == "companion.evolve" and companion["evolution_stage"] != payload["outcome"]:
            raise OperationResultMalformedError("companion evolution stage differs from its outcome")

        if operation_name == "companion.evolve":
            try:
                stored_snapshot = decode_json_strict(str(player_field(instance_row, "snapshot_json", "{}")))
            except (TypeError, ValueError) as exc:
                raise OperationResultMalformedError("companion evolution snapshot is invalid") from exc
            if not isinstance(stored_snapshot, dict):
                raise OperationResultMalformedError("companion evolution snapshot must be an object")
            if stored_snapshot.get("operation_id") == operation_id:
                if stored_snapshot.get("evolution_key") != payload["evolution_key"]:
                    raise OperationResultMalformedError("companion evolution key differs from its snapshot")
                stored_costs = stored_snapshot.get("costs")
                if not isinstance(stored_costs, dict) or spent != stored_costs:
                    raise OperationResultMalformedError("companion evolution spending differs from its snapshot")
            elif not has_later_instance_write:
                raise OperationResultMalformedError("companion evolution snapshot belongs to another operation")

        # Only compare against the live projection while this operation is still
        # the latest write for the affected row. Older snapshots remain valid.
        live_instance_projection = (
            str(instance_row["updated_at"]) == operation_created_at and not has_later_instance_write
        )
        if live_instance_projection:
            persisted = {
                "instance_id": str(instance_row["instance_id"]),
                "companion_key": str(instance_row["companion_key"]),
                "kind": str(instance_row["kind"]),
                "level": int(instance_row["level"]),
                "experience": int(instance_row["experience"]),
                "affinity": int(instance_row["affinity"]),
                "stamina": int(instance_row["stamina"]),
                "status": str(instance_row["status"]),
                "deployed": bool(instance_row["deployed"]),
                "evolution_stage": str(player_field(instance_row, "evolution_stage", "base")),
                "skill_slots": int(player_field(instance_row, "skill_slots", 0) or 0),
            }
            if any(companion[field] != value for field, value in persisted.items()):
                raise OperationResultMalformedError("companion operation projection differs from storage")

        gear_rows = connection.execute(
            "SELECT gear_instance_id, gear_key, status, durability_bp, updated_at "
            "FROM companion_gear_instances WHERE companion_instance_id = ? AND status = 'equipped' ORDER BY id",
            (instance_row["id"],),
        ).fetchall()
        if live_instance_projection:
            current_gear = [
                {
                    "instance_id": str(row["gear_instance_id"]),
                    "gear_key": str(row["gear_key"]),
                    "status": str(row["status"]),
                    "durability_bp": int(row["durability_bp"]),
                }
                for row in gear_rows
            ]
            if current_gear != gear:
                raise OperationResultMalformedError("companion gear projection differs from storage")
        elif operation_name == "companion.equip_gear":
            matching = [row for row in gear_rows if str(row["updated_at"]) == operation_created_at]
            if matching and [
                {
                    "instance_id": str(row["gear_instance_id"]),
                    "gear_key": str(row["gear_key"]),
                    "status": str(row["status"]),
                    "durability_bp": int(row["durability_bp"]),
                }
                for row in matching
            ] != gear:
                raise OperationResultMalformedError("companion gear projection differs from storage")

        player_projection_is_current = not later_operations and (
            operation_name in {"companion.bond", "companion.rest"}
            or str(owner["updated_at"]) == operation_created_at
        )
        if player_projection_is_current:
            try:
                if self._player_payload(self._row_to_player(owner)) != player:
                    raise OperationResultMalformedError("companion operation player projection differs from storage")
            except (TypeError, ValueError, KeyError) as exc:
                raise OperationResultMalformedError("companion operation player projection is invalid") from exc

    def _store_companion_operation(
        self, connection: sqlite3.Connection, operation_id: str, operation_name: str, request_hash: str,
        player: sqlite3.Row, instance_id: str, now_text: str, *, spent: dict[str, int],
        outcome: str = "changed", evolution_key: str | None = None,
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
            "outcome": outcome,
            "evolution_key": evolution_key,
        }
        connection.execute(
            "INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (operation_id, operation_name, updated["id"], request_hash, json.dumps(payload, ensure_ascii=False, sort_keys=True), now_text),
        )
        return CompanionMutationRecord(
            self._row_to_player(updated),
            companion,
            True,
            False,
            dict(spent),
            outcome,
            evolution_key,
        )

    def _mutation_from_payload(self, payload: dict[str, Any], *, replay: bool) -> CompanionMutationRecord:
        return CompanionMutationRecord(
            player=self._row_to_player(payload["player"]),
            companion=self._companion_from_payload(payload["companion"]),
            changed=payload["changed"],
            already_completed=replay,
            spent=dict(payload["spent"]),
            outcome=payload["outcome"],
            evolution_key=payload["evolution_key"],
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
            "evolution_stage": view.evolution_stage,
            "skill_slots": view.skill_slots,
            "gear": [dict(item) for item in view.gear],
        }

    @staticmethod
    def _companion_from_payload(payload: dict[str, Any]) -> CompanionView:
        return CompanionView(
            instance_id=payload["instance_id"],
            companion_key=payload["companion_key"],
            name=payload["name"],
            kind=payload["kind"],
            level=payload["level"],
            experience=payload["experience"],
            affinity=payload["affinity"],
            stamina=payload["stamina"],
            status=payload["status"],
            deployed=payload["deployed"],
            evolution_stage=payload["evolution_stage"],
            skill_slots=payload["skill_slots"],
            gear=tuple(dict(item) for item in payload["gear"]),
        )


__all__ = ["CompanionRepositoryMixin"]
