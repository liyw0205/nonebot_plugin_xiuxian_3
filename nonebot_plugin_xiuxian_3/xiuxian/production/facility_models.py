"""Records returned by the production facility slice."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FacilitySlotRecord:
    slot_key: str
    name: str
    facility_kind: str
    slot_index: int
    owner_type: str | None
    owner_id: str | None
    status: str
    last_maintenance_date: str | None
    already_completed: bool = False


@dataclass(frozen=True, slots=True)
class FacilityMaintenanceRecord:
    slot_key: str
    owner_type: str
    owner_id: str
    business_date: str
    fee: int
    paid: bool
    status: str
    already_completed: bool = False


__all__ = ["FacilityMaintenanceRecord", "FacilitySlotRecord"]
