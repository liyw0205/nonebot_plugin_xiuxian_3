"""Versioned rules for the v0.1 dispatch tasks."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass


CONTENT_VERSION = "content-0.1"
RULE_VERSION = "specials-0.1.0"
CANCEL_WINDOW_SECONDS = 60


@dataclass(frozen=True, slots=True)
class DispatchDefinition:
    key: str
    label: str
    duration_seconds: int
    daily_limit: int
    costs: tuple[tuple[str, int], ...]
    risk_pool: str
    risk_weights: tuple[tuple[str, int], ...]
    requirement: str
    required_permit: str | None = None
    failure_refunds: tuple[tuple[str, int], ...] = ()
    content_version: str = CONTENT_VERSION
    rule_version: str = RULE_VERSION


TOWN_DELIVERY = "dispatch.town_delivery"
HERB_SEARCH = "dispatch.herb_search"
WORKSHOP_HELP = "dispatch.workshop_help"
DEMON_RELIEF = "dispatch.demon_relief"
BEAST_RELOCATION = "dispatch.beast_relocation"

DISPATCHES: dict[str, DispatchDefinition] = {
    TOWN_DELIVERY: DispatchDefinition(
        key=TOWN_DELIVERY,
        label="城镇送货",
        duration_seconds=30 * 60,
        daily_limit=3,
        costs=(("stamina", 3),),
        risk_pool="dispatch.town.v0.1",
        risk_weights=(("success", 7500), ("delayed", 1500), ("partial", 1000)),
        requirement="mortal",
    ),
    HERB_SEARCH: DispatchDefinition(
        key=HERB_SEARCH,
        label="药材搜寻",
        duration_seconds=60 * 60,
        daily_limit=2,
        costs=(("stamina", 4),),
        risk_pool="dispatch.herb.v0.1",
        risk_weights=(("success", 7000), ("partial", 2000), ("failed", 1000)),
        requirement="guide.gather_blood_grass",
    ),
    WORKSHOP_HELP: DispatchDefinition(
        key=WORKSHOP_HELP,
        label="作坊帮工",
        duration_seconds=2 * 60 * 60,
        daily_limit=2,
        costs=(("energy", 4), ("item.mat.wood", 2)),
        risk_pool="dispatch.workshop.v0.1",
        risk_weights=(("success", 6500), ("delayed", 2000), ("failed", 1500)),
        requirement="guide.choose_service",
    ),
    DEMON_RELIEF: DispatchDefinition(
        key=DEMON_RELIEF,
        label="魔界救援",
        duration_seconds=4 * 60 * 60,
        daily_limit=3,
        costs=(("item.herb.blood_grass", 2), ("item.food.coarse_spirit_rice", 2)),
        risk_pool="dispatch.demon_relief.v0.3",
        risk_weights=(("success", 7000), ("partial", 2000), ("failed", 1000)),
        requirement="permit.demon_trade",
        required_permit="permit.demon_trade",
        failure_refunds=(("item.herb.blood_grass", 1), ("item.food.coarse_spirit_rice", 1)),
        content_version="content-0.3",
        rule_version="specials-0.3.0",
    ),
    BEAST_RELOCATION: DispatchDefinition(
        key=BEAST_RELOCATION,
        label="妖界迁徙",
        duration_seconds=4 * 60 * 60,
        daily_limit=3,
        costs=(("item.herb.spirit_leaf", 2), ("item.food.coarse_spirit_rice", 2)),
        risk_pool="dispatch.beast_relocation.v0.3",
        risk_weights=(("success", 7000), ("partial", 2000), ("failed", 1000)),
        requirement="permit.beast_trade",
        required_permit="permit.beast_trade",
        failure_refunds=(("item.herb.spirit_leaf", 1), ("item.food.coarse_spirit_rice", 1)),
        content_version="content-0.3",
        rule_version="specials-0.3.0",
    ),
}

ALIASES = {
    "城镇送货": TOWN_DELIVERY,
    "药材搜寻": HERB_SEARCH,
    "作坊帮工": WORKSHOP_HELP,
    "魔界救援": DEMON_RELIEF,
    "妖界迁徙": BEAST_RELOCATION,
}


def resolve_dispatch(value: str | None) -> DispatchDefinition:
    normalized = (value or "").strip()
    key = ALIASES.get(normalized, normalized)
    try:
        return DISPATCHES[key]
    except KeyError as exc:
        raise ValueError(f"unsupported dispatch: {value}") from exc


def roll_bp(seed: str, salt: str) -> int:
    digest = hashlib.blake2b(f"{seed}:{salt}".encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big") % 10000


def choose_outcome(definition: DispatchDefinition, seed: str) -> str:
    cursor = roll_bp(seed, "risk")
    for outcome, weight in definition.risk_weights:
        if cursor < weight:
            return outcome
        cursor -= weight
    raise ValueError(f"invalid risk pool: {definition.risk_pool}")


def roll_range(seed: str, key: str, low: int, high: int) -> int:
    if low < 0 or low > high:
        raise ValueError("invalid dispatch reward bounds")
    return low + roll_bp(seed, key) % (high - low + 1)


def reward_for(definition: DispatchDefinition, seed: str, outcome: str) -> dict[str, int]:
    if outcome == "failed":
        return {}
    if definition.key == TOWN_DELIVERY:
        if outcome == "partial":
            return {"spirit_stones": 15, "local.xuantian.new_town": 1}
        return {"spirit_stones": 30, "local.xuantian.new_town": 3}
    if definition.key == HERB_SEARCH:
        reward = {
            "item.herb.blood_grass": roll_range(seed, "blood_grass", 3, 5),
            "item.herb.spirit_leaf": roll_range(seed, "spirit_leaf", 0, 1),
            "codex.dispatch.herb_search": 1,
        }
        if outcome == "partial":
            reward = {
                key: quantity // 2
                for key, quantity in reward.items()
                if key.startswith("item.") and quantity // 2 > 0
            }
        return reward
    if definition.key == WORKSHOP_HELP:
        return {
            "spirit_stones": 45,
            "service_reputation": 2,
            "item.mat.array_sand": roll_range(seed, "array_sand", 1, 2),
        }
    if definition.key in {DEMON_RELIEF, BEAST_RELOCATION}:
        local_key = "local.demon.trade_post" if definition.key == DEMON_RELIEF else "local.beast.trade_post"
        if outcome == "partial":
            return {local_key: 3}
        clue_key = "codex.story.dispatch_demon_relief" if definition.key == DEMON_RELIEF else "codex.story.dispatch_beast_relocation"
        return {local_key: 6, clue_key: 1}
    raise ValueError(f"unsupported dispatch reward: {definition.key}")


__all__ = [
    "ALIASES",
    "BEAST_RELOCATION",
    "CANCEL_WINDOW_SECONDS",
    "CONTENT_VERSION",
    "DISPATCHES",
    "DEMON_RELIEF",
    "HERB_SEARCH",
    "RULE_VERSION",
    "TOWN_DELIVERY",
    "WORKSHOP_HELP",
    "DispatchDefinition",
    "choose_outcome",
    "resolve_dispatch",
    "reward_for",
]
