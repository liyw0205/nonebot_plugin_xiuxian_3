"""Deterministic rules for the v0.1 fate treasure pool."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass


FATE_POOL_KEY = "gacha.fate.basic"
FATE_CONTENT_VERSION = "content-0.1"
FATE_RULE_VERSION = "gacha-fate-0.1.0"
FATE_TICKET = "item.ticket.fate_basic"
FATE_PITY_LIMIT = 10
FATE_SINGLE_COST = 50
FATE_TEN_COST = 450


@dataclass(frozen=True, slots=True)
class FateRewardDefinition:
    key: str
    label: str
    rarity: str
    weight: int
    min_quantity: int
    max_quantity: int

    def quantity(self, seed: str, draw_index: int) -> int:
        if self.min_quantity == self.max_quantity:
            return self.min_quantity
        digest = hashlib.sha256(f"{seed}:quantity:{draw_index}".encode("utf-8")).digest()
        span = self.max_quantity - self.min_quantity + 1
        return self.min_quantity + int.from_bytes(digest[:8], "big") % span


# The pool contains only ordinary supplies and non-combat clues. Rare entries
# are deliberately kept separate so ten-pulls can guarantee one without
# introducing a second, hidden reward table.
FATE_POOL: tuple[FateRewardDefinition, ...] = (
    FateRewardDefinition("spirit_stones", "灵石返还", "common", 280, 20, 80),
    FateRewardDefinition("item.herb.blood_grass", "止血草", "common", 180, 1, 3),
    FateRewardDefinition("item.herb.spirit_leaf", "灵叶", "common", 150, 1, 2),
    FateRewardDefinition("item.ore.ironstone", "铁石", "common", 130, 1, 3),
    FateRewardDefinition("item.mat.wood", "木材", "common", 120, 1, 3),
    FateRewardDefinition("item.mat.array_sand", "阵砂", "common", 90, 1, 2),
    FateRewardDefinition("item.fragment.dao_name", "道号碎片", "rare", 25, 1, 1),
    FateRewardDefinition("item.clue.recipe_basic", "配方线索", "rare", 15, 1, 1),
    FateRewardDefinition("item.clue.manual_basic", "功法线索", "rare", 10, 1, 1),
)

_RARE_POOL = tuple(item for item in FATE_POOL if item.rarity == "rare")
_POOL_WEIGHT = sum(item.weight for item in FATE_POOL)
_RARE_POOL_WEIGHT = sum(item.weight for item in _RARE_POOL)


@dataclass(frozen=True, slots=True)
class FateDraw:
    key: str
    label: str
    rarity: str
    quantity: int
    guaranteed: bool = False


def _choose(pool: tuple[FateRewardDefinition, ...], total_weight: int, seed: str, draw_index: int) -> FateRewardDefinition:
    digest = hashlib.sha256(f"{seed}:choice:{draw_index}".encode("utf-8")).digest()
    cursor = int.from_bytes(digest[:8], "big") % total_weight
    for definition in pool:
        if cursor < definition.weight:
            return definition
        cursor -= definition.weight
    return pool[-1]


def roll_fate_pool(
    operation_id: str,
    *,
    draw_count: int,
    pity_before: int,
) -> tuple[tuple[FateDraw, ...], int, str]:
    """Roll a stable pool snapshot and return draws, pity-after, and seed hash."""

    if draw_count not in {1, 10}:
        raise ValueError("draw_count must be 1 or 10")
    if pity_before < 0 or pity_before >= FATE_PITY_LIMIT:
        raise ValueError("pity_before is outside the pool range")
    seed = f"{FATE_POOL_KEY}:{FATE_RULE_VERSION}:{operation_id}"
    seed_hash = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    pity = pity_before
    draws: list[FateDraw] = []
    rare_seen = False
    for draw_index in range(draw_count):
        guaranteed = pity >= FATE_PITY_LIMIT - 1
        if draw_count == 10 and draw_index == draw_count - 1 and not rare_seen:
            guaranteed = True
        if guaranteed:
            definition = _choose(_RARE_POOL, _RARE_POOL_WEIGHT, seed, draw_index)
        else:
            definition = _choose(FATE_POOL, _POOL_WEIGHT, seed, draw_index)
        is_rare = definition.rarity == "rare"
        draws.append(
            FateDraw(
                key=definition.key,
                label=definition.label,
                rarity=definition.rarity,
                quantity=definition.quantity(seed, draw_index),
                guaranteed=guaranteed,
            )
        )
        if is_rare:
            rare_seen = True
            pity = 0
        else:
            pity += 1
    return tuple(draws), pity, seed_hash


def reward_totals(draws: tuple[FateDraw, ...]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for draw in draws:
        totals[draw.key] = totals.get(draw.key, 0) + draw.quantity
    return totals


__all__ = [
    "FATE_CONTENT_VERSION",
    "FATE_PITY_LIMIT",
    "FATE_POOL",
    "FATE_POOL_KEY",
    "FATE_RULE_VERSION",
    "FATE_SINGLE_COST",
    "FATE_TEN_COST",
    "FATE_TICKET",
    "FateDraw",
    "FateRewardDefinition",
    "reward_totals",
    "roll_fate_pool",
]
