"""Pure rules for the first short-haul livelihood route."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from .rules import CONTENT_VERSION, RULE_VERSION


ROUTE_NEW_TOWN_OUTSKIRTS = "route.new_town_outskirts"


@dataclass(frozen=True, slots=True)
class RouteDefinition:
    key: str
    label: str
    source_location: str
    destination_location: str
    duration_seconds: int
    stamina_cost: int
    reward_stones: int
    local_reputation: int
    daily_limit: int
    delay_chance_bp: int
    delay_seconds: int
    max_cargo_value: int
    random_pool: str
    content_version: str = CONTENT_VERSION
    rule_version: str = RULE_VERSION


ROUTE_DEFINITIONS = {
    ROUTE_NEW_TOWN_OUTSKIRTS: RouteDefinition(
        key=ROUTE_NEW_TOWN_OUTSKIRTS,
        label="青石镇至近郊短途运输",
        source_location="xuantian.new_town",
        destination_location="xuantian.outskirts",
        duration_seconds=10 * 60,
        stamina_cost=2,
        reward_stones=12,
        local_reputation=2,
        daily_limit=3,
        delay_chance_bp=1000,
        delay_seconds=10 * 60,
        max_cargo_value=100,
        random_pool="route.town.v0.1",
    ),
}

ROUTE_ALIASES = {
    ROUTE_NEW_TOWN_OUTSKIRTS: ROUTE_NEW_TOWN_OUTSKIRTS,
    "短途运输": ROUTE_NEW_TOWN_OUTSKIRTS,
    "青石镇至近郊短途运输": ROUTE_NEW_TOWN_OUTSKIRTS,
    "青石镇近郊运输": ROUTE_NEW_TOWN_OUTSKIRTS,
}

# v0.1 has no market price system; these frozen unit values bound the cargo
# snapshot without creating a second wallet or trading implementation.
CARGO_VALUES = {
    "item.food.coarse_spirit_rice": 5,
    "item.food.spirit_rice": 12,
    "item.herb.blood_grass": 10,
    "item.herb.spirit_leaf": 18,
    "item.mat.wood": 8,
    "item.ore.ironstone": 15,
    "item.mat.array_sand": 20,
}

CARGO_ALIASES = {
    "粗糙灵米": "item.food.coarse_spirit_rice",
    "灵米饭": "item.food.spirit_rice",
    "止血草": "item.herb.blood_grass",
    "血草": "item.herb.blood_grass",
    "灵叶": "item.herb.spirit_leaf",
    "木材": "item.mat.wood",
    "木头": "item.mat.wood",
    "铁石": "item.ore.ironstone",
    "阵砂": "item.mat.array_sand",
}

CARGO_LABELS = {
    "item.food.coarse_spirit_rice": "粗糙灵米",
    "item.food.spirit_rice": "灵米饭",
    "item.herb.blood_grass": "止血草",
    "item.herb.spirit_leaf": "灵叶",
    "item.mat.wood": "木材",
    "item.ore.ironstone": "铁石",
    "item.mat.array_sand": "阵砂",
}


def route_definition(value: str | None = None) -> RouteDefinition:
    key = ROUTE_ALIASES.get((value or ROUTE_NEW_TOWN_OUTSKIRTS).strip(), (value or ROUTE_NEW_TOWN_OUTSKIRTS).strip())
    try:
        return ROUTE_DEFINITIONS[key]
    except KeyError as exc:
        raise ValueError(f"unsupported route key: {value}") from exc


def resolve_route(value: str | None = None) -> str | None:
    normalized = (value or "").strip()
    if not normalized:
        return ROUTE_NEW_TOWN_OUTSKIRTS
    return ROUTE_ALIASES.get(normalized)


def resolve_cargo(value: str | None = None) -> str | None:
    normalized = (value or "").strip()
    if normalized in CARGO_VALUES:
        return normalized
    return CARGO_ALIASES.get(normalized)


def cargo_unit_value(cargo_key: str) -> int:
    try:
        return int(CARGO_VALUES[cargo_key])
    except KeyError as exc:
        raise ValueError(f"unsupported cargo key: {cargo_key}") from exc


def route_delay_roll_bp(operation_id: str) -> int:
    digest = hashlib.blake2b(operation_id.encode("utf-8"), digest_size=2).digest()
    return int.from_bytes(digest, "big") % 10_000


def cargo_label(cargo_key: str) -> str:
    return CARGO_LABELS.get(cargo_key, cargo_key)


__all__ = [
    "CARGO_ALIASES",
    "CARGO_LABELS",
    "CARGO_VALUES",
    "ROUTE_ALIASES",
    "ROUTE_DEFINITIONS",
    "ROUTE_NEW_TOWN_OUTSKIRTS",
    "RouteDefinition",
    "cargo_label",
    "cargo_unit_value",
    "resolve_cargo",
    "resolve_route",
    "route_delay_roll_bp",
    "route_definition",
]
