"""SQLite transactions for v0.2 cave facility ownership and maintenance."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import date
from typing import Any

from ...contracts import serialize_datetime
from .facility_models import FacilityMaintenanceRecord, FacilitySlotRecord
from .facility_rules import FACILITY_DURATION_BONUS_BP, FACILITY_MAINTENANCE_FEE, resolve_facility
from ..persistence.errors import (
    FacilityMaintenanceUnpaidError,
    FacilityOwnerRequirementError,
    FacilitySlotNotClaimedError,
    FacilitySlotOccupiedError,
    FacilitySlotNotFoundError,
    OperationConflictError,
)


class FacilityRepositoryMixin:
    """Own facility slot claims, production reservations and maintenance."""

    async def claim_facility_slot(
        self,
        *,
        platform: str,
        platform_user_id: str,
        facility_key: str,
        owner_type: str = "personal",
        operation_id: str,
    ) -> FacilitySlotRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._claim_facility_slot_once,
                platform,
                platform_user_id,
                facility_key,
                owner_type,
                operation_id,
            )

    def _claim_facility_slot_once(
        self,
        platform: str,
        platform_user_id: str,
        facility_key: str,
        owner_type: str,
        operation_id: str,
    ) -> FacilitySlotRecord:
        try:
            definition = resolve_facility(facility_key)
        except ValueError as exc:
            raise FacilitySlotNotFoundError(str(exc)) from exc
        if owner_type not in {"personal", "sect"}:
            raise FacilityOwnerRequirementError("owner type is invalid")
        operation_name = "production.claim_facility_slot"
        request_hash = self._request_hash(
            operation_name,
            {
                "platform": platform,
                "platform_user_id": platform_user_id,
                "facility_key": definition.slot_key,
                "owner_type": owner_type,
            },
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
                return self._facility_record_from_payload(json.loads(existing["result_json"]), replay=True)
            player = self._require_player(connection, platform, platform_user_id)
            if str(player["location_key"]) != definition.location_key:
                raise FacilityOwnerRequirementError("facility claim requires cave layer two")
            owner_id = str(player["id"])
            if owner_type == "sect":
                membership = connection.execute(
                    """SELECT sm.sect_id FROM sect_members sm JOIN sects s ON s.sect_id = sm.sect_id
                    WHERE sm.player_id = ? AND sm.status = 'active' AND s.status = 'active' LIMIT 1""",
                    (player["id"],),
                ).fetchone()
                if membership is None:
                    raise FacilityOwnerRequirementError("an active sect membership is required")
                owner_id = str(membership["sect_id"])
            slot = connection.execute(
                "SELECT * FROM production_facility_slots WHERE slot_key = ?",
                (definition.slot_key,),
            ).fetchone()
            if slot is None:
                raise FacilitySlotNotFoundError("facility slot is not materialized")
            if str(slot["status"]) != "unclaimed":
                if str(slot["owner_type"]) == owner_type and str(slot["owner_id"]) == owner_id:
                    payload = self._facility_payload(slot)
                    self._record_facility_operation(connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text)
                    return self._facility_record_from_payload(payload, replay=True)
                raise FacilitySlotOccupiedError("facility slot is already claimed")
            connection.execute(
                """UPDATE production_facility_slots
                SET owner_type = ?, owner_id = ?, status = 'active', updated_at = ? WHERE id = ? AND status = 'unclaimed'""",
                (owner_type, owner_id, now_text, slot["id"]),
            )
            slot = connection.execute("SELECT * FROM production_facility_slots WHERE id = ?", (slot["id"],)).fetchone()
            payload = self._facility_payload(slot)
            self._record_facility_operation(connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text)
            return self._facility_record_from_payload(payload)

    async def maintain_facilities(self, *, business_date: str | date | None = None) -> tuple[FacilityMaintenanceRecord, ...]:
        """Charge each claimed slot at most once for a business date."""

        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._maintain_facilities_once, business_date)

    def _maintain_facilities_once(self, business_date: str | date | None) -> tuple[FacilityMaintenanceRecord, ...]:
        day = str(business_date or self.business_today())
        now_text = serialize_datetime(self._now())
        records: list[FacilityMaintenanceRecord] = []
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            slots = connection.execute(
                "SELECT * FROM production_facility_slots WHERE status IN ('active', 'inactive') ORDER BY id"
            ).fetchall()
            for slot in slots:
                owner_type = str(slot["owner_type"])
                owner_id = str(slot["owner_id"])
                existing = connection.execute(
                    "SELECT m.*, s.slot_key FROM production_facility_maintenance m JOIN production_facility_slots s ON s.id = m.slot_id WHERE m.slot_id = ? AND m.business_date = ?",
                    (slot["id"], day),
                ).fetchone()
                if existing is not None:
                    records.append(self._maintenance_record(existing, replay=True))
                    continue
                paid = False
                if owner_type == "personal":
                    owner = connection.execute("SELECT spirit_stones FROM players WHERE id = ? AND status = 'active'", (owner_id,)).fetchone()
                    if owner is not None and int(owner["spirit_stones"]) >= FACILITY_MAINTENANCE_FEE:
                        connection.execute(
                            "UPDATE players SET spirit_stones = spirit_stones - ?, updated_at = ? WHERE id = ?",
                            (FACILITY_MAINTENANCE_FEE, now_text, owner_id),
                        )
                        paid = True
                else:
                    owner = connection.execute("SELECT spirit_stones FROM sects WHERE sect_id = ? AND status = 'active'", (owner_id,)).fetchone()
                    if owner is not None and int(owner["spirit_stones"]) >= FACILITY_MAINTENANCE_FEE:
                        connection.execute(
                            "UPDATE sects SET spirit_stones = spirit_stones - ?, updated_at = ? WHERE sect_id = ?",
                            (FACILITY_MAINTENANCE_FEE, now_text, owner_id),
                        )
                        paid = True
                status = "active" if paid else "inactive"
                operation_id = f"production.facility.maintenance:{slot['slot_key']}:{day}"
                connection.execute(
                    """INSERT INTO production_facility_maintenance(
                    slot_id, business_date, owner_type, owner_id, fee, paid, status, operation_id, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (slot["id"], day, owner_type, owner_id, FACILITY_MAINTENANCE_FEE, int(paid), status, operation_id, now_text),
                )
                connection.execute(
                    "UPDATE production_facility_slots SET status = ?, last_maintenance_date = ?, updated_at = ? WHERE id = ?",
                    (status, day, now_text, slot["id"]),
                )
                created = connection.execute(
                    "SELECT m.*, s.slot_key FROM production_facility_maintenance m JOIN production_facility_slots s ON s.id = m.slot_id WHERE m.operation_id = ?", (operation_id,)
                ).fetchone()
                records.append(self._maintenance_record(created, replay=False))
        return tuple(records)

    def _facility_reserve_for_recipe(self, connection: sqlite3.Connection, row: sqlite3.Row, recipe) -> sqlite3.Row | None:
        """Find and reserve the owner's active slot before material deduction."""

        kind = getattr(recipe, "facility_kind", None)
        if not kind or str(row["location_key"]) != "cave.mist_grotto_2":
            return None
        owner_candidates: list[tuple[str, str]] = [("personal", str(row["id"]))]
        membership = connection.execute(
            "SELECT sect_id FROM sect_members WHERE player_id = ? AND status = 'active' LIMIT 1", (row["id"],)
        ).fetchone()
        if membership is not None:
            owner_candidates.append(("sect", str(membership["sect_id"])))
        inactive = False
        for owner_type, owner_id in owner_candidates:
            slots = connection.execute(
                "SELECT * FROM production_facility_slots WHERE location_key = ? AND facility_kind = ? AND owner_type = ? AND owner_id = ? ORDER BY slot_index",
                ("cave.mist_grotto_2", kind, owner_type, owner_id),
            ).fetchall()
            for slot in slots:
                if str(slot["status"]) != "active":
                    inactive = True
                    continue
                running = connection.execute(
                    "SELECT 1 FROM production_orders WHERE facility_slot_id = ? AND status = 'processing' LIMIT 1",
                    (slot["id"],),
                ).fetchone()
                if running is not None:
                    raise FacilitySlotOccupiedError("facility slot already has a running order")
                return slot
        if inactive:
            raise FacilityMaintenanceUnpaidError("facility maintenance is unpaid")
        raise FacilitySlotNotClaimedError("claim a facility slot before production")

    @staticmethod
    def _facility_duration_seconds(row: sqlite3.Row, recipe, *, base_seconds: int | None = None) -> int:
        """Apply the non-stacking gathering-array speed bonus to a bound order."""

        duration = int(base_seconds if base_seconds is not None else recipe.duration_seconds)
        if getattr(recipe, "facility_kind", None) and str(row["location_key"]) == "cave.mist_grotto_2":
            raw_inventory = row["inventory_json"]
            inventory = json.loads(raw_inventory) if isinstance(raw_inventory, str) else raw_inventory
            if not isinstance(inventory, dict):
                inventory = {}
            if int(inventory.get("item.array.gathering_basic", 0)) > 0:
                return max(1, duration * (10000 - FACILITY_DURATION_BONUS_BP) // 10000)
        return duration

    @staticmethod
    def _facility_payload(row: sqlite3.Row) -> dict[str, Any]:
        definition = resolve_facility(str(row["slot_key"]))
        return {
            "slot_key": definition.slot_key,
            "name": definition.name,
            "facility_kind": definition.facility_kind,
            "slot_index": definition.slot_index,
            "owner_type": row["owner_type"],
            "owner_id": row["owner_id"],
            "status": row["status"],
            "last_maintenance_date": row["last_maintenance_date"],
        }

    @staticmethod
    def _facility_record_from_payload(payload: dict[str, Any], *, replay: bool = False) -> FacilitySlotRecord:
        return FacilitySlotRecord(
            slot_key=str(payload["slot_key"]),
            name=str(payload["name"]),
            facility_kind=str(payload["facility_kind"]),
            slot_index=int(payload["slot_index"]),
            owner_type=str(payload["owner_type"]) if payload.get("owner_type") is not None else None,
            owner_id=str(payload["owner_id"]) if payload.get("owner_id") is not None else None,
            status=str(payload["status"]),
            last_maintenance_date=payload.get("last_maintenance_date"),
            already_completed=replay,
        )

    @staticmethod
    def _maintenance_record(row: sqlite3.Row, *, replay: bool) -> FacilityMaintenanceRecord:
        slot = row
        return FacilityMaintenanceRecord(
            slot_key=str(slot["slot_key"]),
            owner_type=str(slot["owner_type"]),
            owner_id=str(slot["owner_id"]),
            business_date=str(slot["business_date"]),
            fee=int(slot["fee"]),
            paid=bool(slot["paid"]),
            status=str(slot["status"]),
            already_completed=replay,
        )

    @staticmethod
    def _record_facility_operation(connection, operation_id: str, operation_name: str, player_id: int, request_hash: str, payload: dict[str, Any], now_text: str) -> None:
        connection.execute(
            "INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (operation_id, operation_name, player_id, request_hash, json.dumps(payload, ensure_ascii=False, sort_keys=True), now_text),
        )


__all__ = ["FacilityRepositoryMixin"]
