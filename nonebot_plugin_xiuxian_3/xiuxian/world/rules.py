"""Versioned movement definitions for the first world slice."""

from __future__ import annotations

from dataclasses import dataclass


RULE_VERSION = "world-0.1.0"
CAVE_LOCATION = "cave.mist_grotto"
CAVE_PASS = "item.cave_pass_basic"


@dataclass(frozen=True, slots=True)
class DestinationDefinition:
    key: str
    label: str
    duration_seconds: int
    stamina_cost: int
    currency_cost: int
    required_realm: str | None = None
    required_layer: int = 0
    pass_key: str | None = None
    pass_quantity: int = 0
    source_locations: tuple[str, ...] = ()
    content_version: str = "content-0.1"


DESTINATIONS = {
    "xuantian.new_town": DestinationDefinition(
        "xuantian.new_town", "青石镇", 30, 1, 0,
        source_locations=("xuantian.outskirts", "xuantian.sect_gate", "xuantian.spirit_field"),
    ),
    "xuantian.outskirts": DestinationDefinition(
        "xuantian.outskirts", "玄天近郊", 30, 2, 0,
        source_locations=("xuantian.new_town",),
    ),
    "xuantian.sect_gate": DestinationDefinition(
        "xuantian.sect_gate", "宗门山门", 60, 3, 0,
        required_realm="qi_gathering", required_layer=4,
        source_locations=("xuantian.new_town", "xuantian.outskirts"),
    ),
    "xuantian.spirit_field": DestinationDefinition(
        "xuantian.spirit_field", "灵泉谷", 90, 4, 0,
        required_realm="qi_sensing", required_layer=2,
        source_locations=("xuantian.new_town", "xuantian.outskirts"),
    ),
    CAVE_LOCATION: DestinationDefinition(
        CAVE_LOCATION, "雾隐洞天·一层", 120, 5, 10,
        required_realm="qi_gathering", required_layer=4,
        pass_key=CAVE_PASS, pass_quantity=1,
        source_locations=("xuantian.new_town", "xuantian.sect_gate", "xuantian.spirit_field"),
    ),
}

ALIASES = {
    "新手城": "xuantian.new_town",
    "青石镇": "xuantian.new_town",
    "近郊": "xuantian.outskirts",
    "玄天近郊": "xuantian.outskirts",
    "宗门山门": "xuantian.sect_gate",
    "灵泉谷": "xuantian.spirit_field",
    "雾隐洞天": CAVE_LOCATION,
    "雾隐洞天一层": CAVE_LOCATION,
    "雾隐洞天·一层": CAVE_LOCATION,
}


def resolve_destination(value: str) -> str | None:
    normalized = value.strip()
    if normalized in DESTINATIONS:
        return normalized
    return ALIASES.get(normalized)


def destination_definition(destination: str) -> DestinationDefinition:
    try:
        return DESTINATIONS[destination]
    except KeyError as exc:
        raise ValueError(f"unsupported destination: {destination}") from exc


def realm_rank(realm_key: str) -> int:
    return {
        "mortal": 0,
        "qi_sensing": 1,
        "qi_gathering": 2,
        "foundation": 3,
        "golden_core": 4,
        "nascent_soul": 5,
        "soul_transformation": 6,
    }.get(realm_key, -1)


def meets_realm(realm_key: str, layer: int, required_realm: str | None, required_layer: int) -> bool:
    if required_realm is None:
        return True
    return (realm_rank(realm_key), int(layer)) >= (realm_rank(required_realm), required_layer)
