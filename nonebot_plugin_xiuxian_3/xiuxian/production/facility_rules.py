"""Rules and stable keys for the v0.2 cave facility slots."""

from __future__ import annotations

from dataclasses import dataclass


FACILITY_LOCATION = "cave.mist_grotto_2"
FACILITY_MAINTENANCE_FEE = 100
FACILITY_DURATION_BONUS_BP = 1000
FACILITY_CONTENT_VERSION = "content-0.2"
FACILITY_RULE_VERSION = "production-0.2.0"


@dataclass(frozen=True, slots=True)
class FacilityDefinition:
    slot_key: str
    name: str
    facility_kind: str
    slot_index: int
    location_key: str = FACILITY_LOCATION


FACILITY_DEFINITIONS: tuple[FacilityDefinition, ...] = (
    *(FacilityDefinition(f"facility.mist_field.{index}", f"灵田{index}", "field", index) for index in range(1, 5)),
    FacilityDefinition("facility.alchemy_room.1", "炼丹房", "alchemy", 1),
    FacilityDefinition("facility.artifice_table.1", "炼器台", "artifice", 1),
    FacilityDefinition("facility.array_base.1", "阵基", "array", 1),
)

FACILITY_BY_KEY = {item.slot_key: item for item in FACILITY_DEFINITIONS}
FACILITY_ALIASES = {
    **{f"灵田{index}": f"facility.mist_field.{index}" for index in range(1, 5)},
    "灵田": "facility.mist_field.1",
    "炼丹房": "facility.alchemy_room.1",
    "炼丹": "facility.alchemy_room.1",
    "炼器台": "facility.artifice_table.1",
    "炼器": "facility.artifice_table.1",
    "阵基": "facility.array_base.1",
    "布阵": "facility.array_base.1",
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
    "FACILITY_CONTENT_VERSION",
    "FACILITY_DURATION_BONUS_BP",
    "FACILITY_DEFINITIONS",
    "FACILITY_LOCATION",
    "FACILITY_MAINTENANCE_FEE",
    "FACILITY_RULE_VERSION",
    "FacilityDefinition",
    "facility_for_kind",
    "resolve_facility",
]
