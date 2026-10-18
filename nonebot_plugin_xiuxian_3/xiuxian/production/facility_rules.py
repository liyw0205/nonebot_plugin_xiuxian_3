"""Rules and stable keys for the cave facility slots (content-backed)."""

from __future__ import annotations

from dataclasses import dataclass

from .content_rules import facility_defaults, facility_records

_FACILITY_DEFAULTS = facility_defaults()

FACILITY_LOCATION = str(_FACILITY_DEFAULTS["location_key"])
FACILITY_MAINTENANCE_FEE = int(_FACILITY_DEFAULTS["maintenance_fee"])
FACILITY_DURATION_BONUS_BP = int(_FACILITY_DEFAULTS["duration_bonus_bp"])


@dataclass(frozen=True, slots=True)
class FacilityDefinition:
    slot_key: str
    name: str
    facility_kind: str
    slot_index: int
    location_key: str = FACILITY_LOCATION


def _definition(record: dict) -> FacilityDefinition:
    return FacilityDefinition(
        slot_key=str(record["key"]),
        name=str(record["name"]),
        facility_kind=str(record["facility_kind"]),
        slot_index=int(record["slot_index"]),
        location_key=str(record["location_key"]),
    )


FACILITY_DEFINITIONS: tuple[FacilityDefinition, ...] = tuple(
    _definition(record) for record in facility_records()
)

FACILITY_BY_KEY = {item.slot_key: item for item in FACILITY_DEFINITIONS}
FACILITY_ALIASES = {
    alias: str(record["key"])
    for record in facility_records()
    for alias in record["aliases"]
}


def resolve_facility(value: str) -> FacilityDefinition:
    key = FACILITY_ALIASES.get(value.strip(), value.strip())
    try:
        return FACILITY_BY_KEY[key]
    except KeyError as exc:
        raise ValueError("facility does not exist") from exc


def facility_for_kind(kind: str) -> tuple[FacilityDefinition, ...]:
    return tuple(item for item in FACILITY_DEFINITIONS if item.facility_kind == kind)


__all__ = [
    "FACILITY_ALIASES",
    "FACILITY_BY_KEY",
    "FACILITY_DURATION_BONUS_BP",
    "FACILITY_DEFINITIONS",
    "FACILITY_LOCATION",
    "FACILITY_MAINTENANCE_FEE",
    "FacilityDefinition",
    "facility_for_kind",
    "resolve_facility",
]
