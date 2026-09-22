"""Pure, deterministic rules for the v0.1 retreat slice."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass


RETREAT_BASIC = "progression.retreat.basic"
RETREAT_RESTFUL = "progression.retreat.restful"
CONTENT_VERSION = "content-0.1"
RULE_VERSION = "advancement-0.1.0"
BASIC_RANDOM_POOL = "retreat.basic.v0.1"
BASIC_DURATION_SECONDS = 2 * 60 * 60
RESTFUL_DURATION_SECONDS = 4 * 60 * 60
MAX_SETTLEMENT_SECONDS = 8 * 60 * 60
MAX_OFFLINE_SECONDS = 24 * 60 * 60
BASIC_ENERGY_COST = 4
RESTFUL_ENERGY_COST = 2
BASIC_ITEM_COST = {"item.food.coarse_spirit_rice": 1}
BASIC_DAILY_LIMIT = 3
RESTFUL_DAILY_LIMIT = 1


@dataclass(frozen=True, slots=True)
class RetreatDefinition:
    key: str
    label: str
    description: str
    duration_seconds: int
    energy_cost: int
    item_cost: tuple[tuple[str, int], ...]
    daily_limit: int
    required_stage: str
    required_item: str | None
    random_pool: str | None
    content_version: str = CONTENT_VERSION
    rule_version: str = RULE_VERSION

    def item_cost_map(self) -> dict[str, int]:
        return {key: int(value) for key, value in self.item_cost}


RETREAT_DEFINITIONS = {
    RETREAT_BASIC: RetreatDefinition(
        key=RETREAT_BASIC,
        label="基础闭关",
        description="以基础引气诀闭关调息，积累境内修为。",
        duration_seconds=BASIC_DURATION_SECONDS,
        energy_cost=BASIC_ENERGY_COST,
        item_cost=tuple(BASIC_ITEM_COST.items()),
        daily_limit=BASIC_DAILY_LIMIT,
        required_stage="cultivator",
        required_item="item.manual.basic_qi",
        random_pool=BASIC_RANDOM_POOL,
    ),
    RETREAT_RESTFUL: RetreatDefinition(
        key=RETREAT_RESTFUL,
        label="静养闭关",
        description="在居所中静养，恢复精力，不增加修为。",
        duration_seconds=RESTFUL_DURATION_SECONDS,
        energy_cost=RESTFUL_ENERGY_COST,
        item_cost=(),
        daily_limit=RESTFUL_DAILY_LIMIT,
        required_stage="mortal",
        required_item=None,
        random_pool=None,
    ),
}

RETREAT_ALIASES = {
    "基础": RETREAT_BASIC,
    "基础闭关": RETREAT_BASIC,
    "修炼": RETREAT_BASIC,
    "静养": RETREAT_RESTFUL,
    "静养闭关": RETREAT_RESTFUL,
    "休养": RETREAT_RESTFUL,
}


def retreat_definition(value: str | None) -> RetreatDefinition:
    key = (value or "基础").strip()
    key = RETREAT_ALIASES.get(key, key)
    try:
        return RETREAT_DEFINITIONS[key]
    except KeyError as exc:
        raise ValueError(f"unsupported retreat key: {value}") from exc


def weighted_value(seed: str, values: tuple[int, ...], weights: tuple[int, ...]) -> int:
    if not values or len(values) != len(weights) or sum(weights) <= 0:
        raise ValueError("invalid retreat reward pool")
    digest = hashlib.blake2b(seed.encode("utf-8"), digest_size=8).digest()
    cursor = int.from_bytes(digest, "big") % sum(weights)
    for value, weight in zip(values, weights, strict=True):
        if cursor < weight:
            return value
        cursor -= weight
    return values[-1]


def retreat_reward(retreat_key: str, seed: str) -> dict[str, int]:
    """Resolve the frozen reward from the session's stable random seed."""

    definition = retreat_definition(retreat_key)
    if definition.key == RETREAT_BASIC:
        return {
            "cultivation": weighted_value(
                f"{seed}:cultivation",
                (80, 100, 120),
                (25, 50, 25),
            )
        }
    if definition.key == RETREAT_RESTFUL:
        return {"energy": 8}
    raise ValueError(f"unsupported retreat key: {retreat_key}")


def retreat_mode_key(value: str | None) -> str:
    return retreat_definition(value).key


__all__ = [
    "BASIC_DAILY_LIMIT",
    "BASIC_DURATION_SECONDS",
    "BASIC_RANDOM_POOL",
    "CONTENT_VERSION",
    "MAX_OFFLINE_SECONDS",
    "MAX_SETTLEMENT_SECONDS",
    "RESTFUL_DAILY_LIMIT",
    "RESTFUL_DURATION_SECONDS",
    "RETREAT_BASIC",
    "RETREAT_DEFINITIONS",
    "RETREAT_RESTFUL",
    "RULE_VERSION",
    "RetreatDefinition",
    "retreat_definition",
    "retreat_mode_key",
    "retreat_reward",
    "weighted_value",
]
