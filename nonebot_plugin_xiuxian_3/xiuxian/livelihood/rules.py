"""Pure rules for residence and the first livelihood crop slice."""

from __future__ import annotations

from dataclasses import dataclass


TOWN_ROOM = "residence.town_room"
COURTYARD = "residence.courtyard"
CONTENT_VERSION = "content-0.1"
RULE_VERSION = "livelihood-0.1.0"


@dataclass(frozen=True, slots=True)
class ResidenceDefinition:
    key: str
    label: str
    rent_cost: int
    lease_days: int
    required_stage: str
    required_local_reputation: int = 0
    plot_count: int = 0
    content_version: str = CONTENT_VERSION
    rule_version: str = RULE_VERSION


RESIDENCE_DEFINITIONS = {
    TOWN_ROOM: ResidenceDefinition(
        key=TOWN_ROOM,
        label="青石镇客房",
        rent_cost=20,
        lease_days=3,
        required_stage="mortal",
        plot_count=1,
    ),
    COURTYARD: ResidenceDefinition(
        key=COURTYARD,
        label="小院",
        rent_cost=80,
        lease_days=7,
        required_stage="mortal",
        required_local_reputation=40,
        plot_count=1,
    ),
}

RESIDENCE_ALIASES = {
    "客房": TOWN_ROOM,
    "青石镇客房": TOWN_ROOM,
    "小屋": TOWN_ROOM,
    "小院": COURTYARD,
}


def residence_definition(value: str | None = None) -> ResidenceDefinition:
    key = RESIDENCE_ALIASES.get((value or "客房").strip(), value or TOWN_ROOM)
    try:
        return RESIDENCE_DEFINITIONS[key]
    except KeyError as exc:
        raise ValueError(f"unsupported residence key: {value}") from exc


BLOOD_GRASS = "crop.blood_grass"


@dataclass(frozen=True, slots=True)
class CropDefinition:
    key: str
    label: str
    seed_key: str
    growth_seconds: int
    maintenance_energy: int
    required_maintenance: int
    maintained_harvest: dict[str, int]
    unmaintained_harvest: dict[str, int]
    daily_limit: int
    residence_key: str | None = None
    content_version: str = CONTENT_VERSION
    rule_version: str = RULE_VERSION


CROP_DEFINITIONS = {
    BLOOD_GRASS: CropDefinition(
        key=BLOOD_GRASS,
        label="止血草",
        seed_key="item.herb.blood_grass",
        growth_seconds=4 * 60 * 60,
        maintenance_energy=1,
        required_maintenance=1,
        maintained_harvest={"item.herb.blood_grass": 3},
        unmaintained_harvest={"item.herb.blood_grass": 1},
        daily_limit=2,
    ),
}

CROP_ALIASES = {"止血草": BLOOD_GRASS, "血草": BLOOD_GRASS, "blood_grass": BLOOD_GRASS}


def crop_definition(value: str | None = None) -> CropDefinition:
    key = CROP_ALIASES.get((value or "止血草").strip(), value or BLOOD_GRASS)
    try:
        return CROP_DEFINITIONS[key]
    except KeyError as exc:
        raise ValueError(f"unsupported crop key: {value}") from exc


__all__ = [
    "BLOOD_GRASS",
    "CONTENT_VERSION",
    "COURTYARD",
    "CROP_DEFINITIONS",
    "CROP_ALIASES",
    "RULE_VERSION",
    "TOWN_ROOM",
    "CropDefinition",
    "ResidenceDefinition",
    "crop_definition",
    "residence_definition",
]
