"""Pure rules for the idle-reward routes."""

from __future__ import annotations


import hashlib
from dataclasses import dataclass


MAX_CLAIM_EXTENSION_SECONDS = 24 * 60 * 60
ABSOLUTE_MAX_SECONDS = 48 * 60 * 60
CANCEL_WINDOW_SECONDS = 60


@dataclass(frozen=True, slots=True)
class IdleRouteDefinition:
    key: str
    label: str
    duration_seconds: int
    stamina_cost: int
    energy_cost: int
    daily_limit: int
    pool_key: str
    required_stage: str = "mortal"
    required_location: str | None = None
    required_reputation: int = 0
    required_residence: bool = False
    required_tool_keys: tuple[str, ...] = ()
    facility_kind: str | None = None
    full_reward_bounds: tuple[tuple[str, int, int], ...] = ()
    fallback_reward: tuple[tuple[str, int], ...] = ()
    reputation_key: str | None = None
    reputation_full: int = 0
    reputation_fallback: int = 0
    durability_cost_bp: int = 0


TOWN_ERRAND = "idle.town_errand"
HERB_WATCH = "idle.herb_watch"
WORKSHOP_CARE = "idle.workshop_care"
ROUTE_SCOUT = "idle.route_scout"

ROUTES: dict[str, IdleRouteDefinition] = {
    TOWN_ERRAND: IdleRouteDefinition(
        key=TOWN_ERRAND,
        label="城镇跑腿/看店",
        duration_seconds=2 * 60 * 60,
        stamina_cost=0,
        energy_cost=0,
        daily_limit=2,
        pool_key="idle.town",
        required_location="xuantian.new_town",
        full_reward_bounds=(("spirit_stones", 16, 24),),
        fallback_reward=(("spirit_stones", 8),),
        reputation_key="local.xuantian.new_town",
        reputation_full=2,
        reputation_fallback=1,
    ),
    HERB_WATCH: IdleRouteDefinition(
        key=HERB_WATCH,
        label="药圃看护",
        duration_seconds=4 * 60 * 60,
        stamina_cost=0,
        energy_cost=1,
        daily_limit=1,
        pool_key="idle.herb",
        required_residence=True,
        full_reward_bounds=(
            ("item.herb.blood_grass", 2, 4),
            ("item.herb.spirit_leaf", 0, 1),
        ),
        fallback_reward=(("item.herb.blood_grass", 1),),
    ),
    WORKSHOP_CARE: IdleRouteDefinition(
        key=WORKSHOP_CARE,
        label="工具/作坊看守",
        duration_seconds=3 * 60 * 60,
        stamina_cost=0,
        energy_cost=0,
        daily_limit=1,
        pool_key="idle.workshop",
        required_tool_keys=("item.tool.basic_furnace", "item.tool.basic_hammer"),
        facility_kind="artifice",
        full_reward_bounds=(
            ("item.mat.array_sand", 1, 3),
            ("item.mat.wood", 1, 2),
        ),
        fallback_reward=(("item.mat.wood", 1),),
        durability_cost_bp=50,
    ),
    ROUTE_SCOUT: IdleRouteDefinition(
        key=ROUTE_SCOUT,
        label="商路观察",
        duration_seconds=6 * 60 * 60,
        stamina_cost=2,
        energy_cost=0,
        daily_limit=1,
        pool_key="idle.route",
        required_reputation=20,
        full_reward_bounds=(("spirit_stones", 25, 40), ("codex.route.town_road", 1, 1)),
        fallback_reward=(("spirit_stones", 12),),
    ),
}

ALIASES = {
    "城镇跑腿": TOWN_ERRAND,
    "看店": TOWN_ERRAND,
    "药圃看护": HERB_WATCH,
    "看护药圃": HERB_WATCH,
    "作坊看守": WORKSHOP_CARE,
    "工具看守": WORKSHOP_CARE,
    "商路观察": ROUTE_SCOUT,
}


def resolve_route(value: str | None) -> IdleRouteDefinition:
    normalized = (value or TOWN_ERRAND).strip()
    key = ALIASES.get(normalized, normalized)
    try:
        return ROUTES[key]
    except KeyError as exc:
        raise ValueError(f"unsupported idle route: {value}") from exc


def roll_range(seed: str, key: str, low: int, high: int) -> int:
    if low > high or low < 0:
        raise ValueError("invalid idle reward bounds")
    digest = hashlib.blake2b(f"{seed}:{key}".encode("utf-8"), digest_size=8).digest()
    return low + int.from_bytes(digest, "big") % (high - low + 1)


def reward_for(definition: IdleRouteDefinition, seed: str, *, fallback: bool) -> dict[str, int]:
    if fallback:
        return {key: quantity for key, quantity in definition.fallback_reward if quantity > 0}
    return {
        key: roll_range(seed, key, low, high)
        for key, low, high in definition.full_reward_bounds
        if high > 0
    }


__all__ = [
    "ABSOLUTE_MAX_SECONDS",
    "ALIASES",
    "CANCEL_WINDOW_SECONDS",
    "HERB_WATCH",
    "IdleRouteDefinition",
    "MAX_CLAIM_EXTENSION_SECONDS",
    "ROUTES",
    "ROUTE_SCOUT",
    "TOWN_ERRAND",
    "WORKSHOP_CARE",
    "resolve_route",
    "reward_for",
    "roll_range",
]
