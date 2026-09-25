"""Persistence for the v0.5 void beacon extension."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from typing import Any, Mapping
from uuid import uuid4

from ...contracts import serialize_datetime
from ..persistence.errors import (
    CrossServerFortressRequiredError,
    OperationConflictError,
    SectNotFoundError,
    SectPermissionDeniedError,
    VoidBeaconBuildError,
    VoidBeaconRequiredError,
)
from .sect_beacon_models import VoidBeaconRecord
from .sect_beacon_rules import (
    VOID_BEACON_ANCHOR_COST,
    VOID_BEACON_BUILD_SECONDS,
    VOID_BEACON_CONTENT_VERSION,
    VOID_BEACON_MAINTENANCE_ANCHOR_COST,
    VOID_BEACON_ROUTE_DISCOUNT,
    VOID_BEACON_RULE_VERSION,
    VOID_BEACON_SAND_COST,
)


class SectBeaconRepositoryMixin:
    """Own beacon construction, maintenance and route discount reads."""

    async def get_void_beacon(self, *, platform: str, platform_user_id: str) -> VoidBeaconRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._get_void_beacon_once, platform, platform_user_id)

    async def build_void_beacon(self, *, platform: str, platform_user_id: str, operation_id: str) -> VoidBeaconRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._build_void_beacon_once, platform, platform_user_id, operation_id)

    async def maintain_void_beacon(self, *, platform: str, platform_user_id: str, operation_id: str) -> VoidBeaconRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._maintain_void_beacon_once, platform, platform_user_id, operation_id)

    get_sect_void_beacon = get_void_beacon
    build_sect_void_beacon = build_void_beacon
    maintain_sect_void_beacon = maintain_void_beacon

    def _get_void_beacon_once(self, platform: str, platform_user_id: str) -> VoidBeaconRecord:
        now = self._now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            player = self._require_player(connection, platform, platform_user_id, writable=False)
            membership = connection.execute(
                "SELECT sect_id FROM sect_members WHERE player_id=? AND status='active'",
                (player["id"],),
            ).fetchone()
            if membership is None:
                raise SectNotFoundError("player is not in a sect")
            beacon = connection.execute(
                "SELECT * FROM sect_void_beacons WHERE sect_id=?", (membership["sect_id"],)
            ).fetchone()
            if beacon is None:
                raise VoidBeaconRequiredError("void beacon is missing")
            self._beacon_prepare(connection, beacon, now)
            beacon = connection.execute(
                "SELECT * FROM sect_void_beacons WHERE sect_id=?", (membership["sect_id"],)
            ).fetchone()
            return self._beacon_from_row(beacon)

    def _build_void_beacon_once(self, platform: str, platform_user_id: str, operation_id: str) -> VoidBeaconRecord:
        operation_name = "social.sect_void_beacon.build"
        request_hash = self._request_hash(
            operation_name,
            {"platform": platform, "platform_user_id": platform_user_id},
        )
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._beacon_operation(connection, operation_id, operation_name, request_hash)
            if replay is not None:
                return self._beacon_from_payload(replay, already_completed=True)
            player = self._require_player(connection, platform, platform_user_id)
            sect, membership = self._beacon_require_manager(connection, int(player["id"]))
            self._beacon_require_active_fortress(connection, str(sect["sect_id"]), now)
            existing = connection.execute(
                "SELECT * FROM sect_void_beacons WHERE sect_id=?", (sect["sect_id"],)
            ).fetchone()
            if existing is not None:
                self._beacon_prepare(connection, existing, now)
                existing = connection.execute(
                    "SELECT * FROM sect_void_beacons WHERE sect_id=?", (sect["sect_id"],)
                ).fetchone()
                if str(existing["status"]) in {"building", "active"}:
                    raise VoidBeaconBuildError("void beacon already exists")
            warehouse = self._beacon_json_map(sect["warehouse_json"])
            if int(warehouse.get("item.void_anchor", 0)) < VOID_BEACON_ANCHOR_COST:
                raise VoidBeaconBuildError("void anchor is insufficient")
            if int(warehouse.get("item.mat.array_sand", 0)) < VOID_BEACON_SAND_COST:
                raise VoidBeaconBuildError("array sand is insufficient")
            warehouse["item.void_anchor"] = int(warehouse.get("item.void_anchor", 0)) - VOID_BEACON_ANCHOR_COST
            warehouse["item.mat.array_sand"] = int(warehouse.get("item.mat.array_sand", 0)) - VOID_BEACON_SAND_COST
            build_end = now + timedelta(seconds=VOID_BEACON_BUILD_SECONDS)
            snapshot = {
                "sect_level": int(sect["level"]),
                "anchor_cost": VOID_BEACON_ANCHOR_COST,
                "sand_cost": VOID_BEACON_SAND_COST,
                "route_discount": VOID_BEACON_ROUTE_DISCOUNT,
            }
            connection.execute(
                "UPDATE sects SET warehouse_json=?, updated_at=? WHERE sect_id=?",
                (json.dumps(warehouse, ensure_ascii=False, sort_keys=True), now_text, sect["sect_id"]),
            )
            if existing is None:
                connection.execute(
                    "INSERT INTO sect_void_beacons(sect_id,status,build_operation_id,build_ends_at,maintenance_due_at,snapshot_json,content_version,rule_version,created_at,updated_at) VALUES (?, 'building', ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        sect["sect_id"], operation_id, serialize_datetime(build_end),
                        serialize_datetime(build_end + timedelta(days=7)),
                        json.dumps(snapshot, sort_keys=True), VOID_BEACON_CONTENT_VERSION,
                        VOID_BEACON_RULE_VERSION, now_text, now_text,
                    ),
                )
            else:
                connection.execute(
                    "UPDATE sect_void_beacons SET status='building', build_operation_id=?, build_ends_at=?, maintenance_due_at=?, snapshot_json=?, content_version=?, rule_version=?, updated_at=? WHERE sect_id=?",
                    (
                        operation_id, serialize_datetime(build_end), serialize_datetime(build_end + timedelta(days=7)),
                        json.dumps(snapshot, sort_keys=True), VOID_BEACON_CONTENT_VERSION,
                        VOID_BEACON_RULE_VERSION, now_text, sect["sect_id"],
                    ),
                )
            payload = {
                "sect_id": str(sect["sect_id"]), "status": "building",
                "build_ends_at": serialize_datetime(build_end),
                "maintenance_due_at": serialize_datetime(build_end + timedelta(days=7)),
                "route_discount": VOID_BEACON_ROUTE_DISCOUNT,
            }
            self._beacon_insert_operation(connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text)
            return self._beacon_from_payload(payload)

    def _maintain_void_beacon_once(self, platform: str, platform_user_id: str, operation_id: str) -> VoidBeaconRecord:
        operation_name = "social.sect_void_beacon.maintain"
        request_hash = self._request_hash(
            operation_name,
            {"platform": platform, "platform_user_id": platform_user_id},
        )
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._beacon_operation(connection, operation_id, operation_name, request_hash)
            if replay is not None:
                return self._beacon_from_payload(replay, already_completed=True)
            player = self._require_player(connection, platform, platform_user_id)
            sect, _ = self._beacon_require_manager(connection, int(player["id"]))
            beacon = connection.execute("SELECT * FROM sect_void_beacons WHERE sect_id=?", (sect["sect_id"],)).fetchone()
            if beacon is None:
                raise VoidBeaconRequiredError("void beacon is missing")
            self._beacon_prepare(connection, beacon, now)
            beacon = connection.execute("SELECT * FROM sect_void_beacons WHERE sect_id=?", (sect["sect_id"],)).fetchone()
            if str(beacon["status"]) != "active":
                raise VoidBeaconBuildError("void beacon is not active")
            due_at = beacon["maintenance_due_at"] and datetime.fromisoformat(str(beacon["maintenance_due_at"]))
            if due_at is None or now < due_at:
                payload = self._beacon_payload(beacon)
                self._beacon_insert_operation(connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text)
                return self._beacon_from_payload(payload, already_completed=True)
            warehouse = self._beacon_json_map(sect["warehouse_json"])
            if int(warehouse.get("item.void_anchor", 0)) < VOID_BEACON_MAINTENANCE_ANCHOR_COST:
                connection.execute("UPDATE sect_void_beacons SET status='inactive', updated_at=? WHERE sect_id=?", (now_text, sect["sect_id"]))
                raise VoidBeaconBuildError("void beacon maintenance anchor is insufficient")
            warehouse["item.void_anchor"] = int(warehouse.get("item.void_anchor", 0)) - VOID_BEACON_MAINTENANCE_ANCHOR_COST
            due = now + timedelta(days=7)
            connection.execute("UPDATE sects SET warehouse_json=?, updated_at=? WHERE sect_id=?", (json.dumps(warehouse, ensure_ascii=False, sort_keys=True), now_text, sect["sect_id"]))
            connection.execute("UPDATE sect_void_beacons SET status='active', maintenance_due_at=?, updated_at=? WHERE sect_id=?", (serialize_datetime(due), now_text, sect["sect_id"]))
            beacon = connection.execute("SELECT * FROM sect_void_beacons WHERE sect_id=?", (sect["sect_id"],)).fetchone()
            payload = self._beacon_payload(beacon)
            self._beacon_insert_operation(connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text)
            return self._beacon_from_payload(payload)

    def _active_void_beacon_discount(self, connection: Any, player_id: int, now: datetime) -> int:
        """Return the frozen route discount for a member's active beacon."""

        membership = connection.execute(
            "SELECT sect_id FROM sect_members WHERE player_id=? AND status='active'", (player_id,)
        ).fetchone()
        if membership is None:
            return 0
        fortress = connection.execute(
            "SELECT status, maintenance_due_at FROM sect_void_fortresses WHERE sect_id=?", (membership["sect_id"],)
        ).fetchone()
        beacon = connection.execute(
            "SELECT * FROM sect_void_beacons WHERE sect_id=?", (membership["sect_id"],)
        ).fetchone()
        if fortress is None or beacon is None or str(fortress["status"]) != "active" or str(beacon["status"]) != "active":
            return 0
        if fortress["maintenance_due_at"] and now >= datetime.fromisoformat(str(fortress["maintenance_due_at"])):
            return 0
        if beacon["maintenance_due_at"] and now >= datetime.fromisoformat(str(beacon["maintenance_due_at"])):
            return 0
        return VOID_BEACON_ROUTE_DISCOUNT

    @staticmethod
    def _beacon_require_manager(connection: Any, player_id: int):
        membership = connection.execute("SELECT * FROM sect_members WHERE player_id=? AND status='active'", (player_id,)).fetchone()
        if membership is None:
            raise SectNotFoundError("player is not in a sect")
        if str(membership["role"]) not in {"leader", "vice_leader"}:
            raise SectPermissionDeniedError("sect leader or vice leader is required")
        sect = connection.execute("SELECT * FROM sects WHERE sect_id=? AND status='active'", (membership["sect_id"],)).fetchone()
        if sect is None:
            raise SectNotFoundError("sect does not exist")
        return sect, membership

    @staticmethod
    def _beacon_require_active_fortress(connection: Any, sect_id: str, now: datetime) -> None:
        fortress = connection.execute("SELECT * FROM sect_void_fortresses WHERE sect_id=?", (sect_id,)).fetchone()
        if fortress is None:
            raise CrossServerFortressRequiredError("active void fortress is required")
        if str(fortress["status"]) == "building" and fortress["build_ends_at"] and now >= datetime.fromisoformat(str(fortress["build_ends_at"])):
            now_text = serialize_datetime(now)
            connection.execute("UPDATE sect_void_fortresses SET status='active', updated_at=? WHERE sect_id=?", (now_text, sect_id))
            fortress = connection.execute("SELECT * FROM sect_void_fortresses WHERE sect_id=?", (sect_id,)).fetchone()
        if str(fortress["status"]) != "active" or (fortress["maintenance_due_at"] and now >= datetime.fromisoformat(str(fortress["maintenance_due_at"]))):
            raise CrossServerFortressRequiredError("active void fortress is required")

    @staticmethod
    def _beacon_prepare(connection: Any, beacon: Any, now: datetime) -> None:
        if str(beacon["status"]) == "building" and beacon["build_ends_at"] and now >= datetime.fromisoformat(str(beacon["build_ends_at"])):
            connection.execute("UPDATE sect_void_beacons SET status='active', updated_at=? WHERE sect_id=?", (serialize_datetime(now), beacon["sect_id"]))

    @staticmethod
    def _beacon_payload(row: Any) -> dict[str, object]:
        return {"sect_id": str(row["sect_id"]), "status": str(row["status"]), "build_ends_at": row["build_ends_at"], "maintenance_due_at": row["maintenance_due_at"], "route_discount": VOID_BEACON_ROUTE_DISCOUNT}

    @staticmethod
    def _beacon_from_payload(payload: Mapping[str, object], *, already_completed: bool = False) -> VoidBeaconRecord:
        return VoidBeaconRecord(str(payload["sect_id"]), str(payload["status"]), payload.get("build_ends_at") and str(payload["build_ends_at"]), payload.get("maintenance_due_at") and str(payload["maintenance_due_at"]), int(payload.get("route_discount", 0)), already_completed)

    @staticmethod
    def _beacon_from_row(row: Any) -> VoidBeaconRecord:
        return SectBeaconRepositoryMixin._beacon_from_payload(SectBeaconRepositoryMixin._beacon_payload(row))

    @staticmethod
    def _beacon_json_map(value: object) -> dict[str, Any]:
        try:
            parsed = json.loads(value) if isinstance(value, str) else value
        except (TypeError, ValueError):
            parsed = {}
        return dict(parsed) if isinstance(parsed, dict) else {}

    @staticmethod
    def _beacon_operation(connection: Any, operation_id: str, operation_name: str, request_hash: str) -> dict[str, Any] | None:
        existing = connection.execute("SELECT operation_name,request_hash,result_json FROM operations WHERE operation_id=?", (operation_id,)).fetchone()
        if existing is None:
            return None
        if str(existing["operation_name"]) != operation_name or str(existing["request_hash"]) != request_hash:
            raise OperationConflictError("operation input differs from its original request")
        return json.loads(existing["result_json"])

    @staticmethod
    def _beacon_insert_operation(connection: Any, operation_id: str, operation_name: str, player_id: int, request_hash: str, payload: Mapping[str, object], now_text: str) -> None:
        connection.execute("INSERT INTO operations(operation_id,operation_name,player_id,request_hash,result_json,created_at) VALUES (?,?,?,?,?,?)", (operation_id, operation_name, player_id, request_hash, json.dumps(dict(payload), ensure_ascii=False, sort_keys=True), now_text))


__all__ = ["SectBeaconRepositoryMixin"]
