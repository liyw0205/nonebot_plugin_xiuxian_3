"""Pure residence definitions for the first livelihood slice."""

from __future__ import annotations

from dataclasses import dataclass


TOWN_ROOM = "residence.town_room"
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
    content_version: str = CONTENT_VERSION
    rule_version: str = RULE_VERSION


RESIDENCE_DEFINITIONS = {
    TOWN_ROOM: ResidenceDefinition(
        key=TOWN_ROOM,
        label="青石镇客房",
        rent_cost=20,
        lease_days=3,
        required_stage="mortal",
    ),
}

RESIDENCE_ALIASES = {
    "客房": TOWN_ROOM,
    "青石镇客房": TOWN_ROOM,
    "小屋": TOWN_ROOM,
}


def residence_definition(value: str | None = None) -> ResidenceDefinition:
    key = RESIDENCE_ALIASES.get((value or "客房").strip(), value or TOWN_ROOM)
    try:
        return RESIDENCE_DEFINITIONS[key]
    except KeyError as exc:
        raise ValueError(f"unsupported residence key: {value}") from exc


__all__ = ["CONTENT_VERSION", "RESIDENCE_DEFINITIONS", "RULE_VERSION", "TOWN_ROOM", "ResidenceDefinition", "residence_definition"]
