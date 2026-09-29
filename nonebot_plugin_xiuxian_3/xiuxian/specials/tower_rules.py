"""Versioned v0.1 mist-trial tower rules."""

from __future__ import annotations


import hashlib
from dataclasses import dataclass
from datetime import timedelta


CONTENT_VERSION = ""
RULE_VERSION = ""
LEGACY_CONTENT_VERSION = ""
LEGACY_RULE_VERSION = ""
TOWER_KEY = "tower.mist_trial"
MAX_FLOOR = 45


@dataclass(frozen=True, slots=True)
class TowerFloorDefinition:
    floor_no: int
    required_realm: str
    required_layer: int
    stamina_cost: int
    daily_limit: int
    enemy_key: str


def floor_definition(floor_no: int) -> TowerFloorDefinition:
    if not isinstance(floor_no, int) or isinstance(floor_no, bool) or not 1 <= floor_no <= MAX_FLOOR:
        raise ValueError(f"tower floor must be between 1 and {MAX_FLOOR}")
    if floor_no <= 10:
        realm, layer, cost, limit, tier = "qi_sensing", 1, 4, 5, "sensing"
    elif floor_no <= 20:
        realm, layer, cost, limit, tier = "qi_gathering", 4, 6, 4, "gathering"
    elif floor_no <= 30:
        realm, layer, cost, limit, tier = "foundation", 4, 8, 3, "foundation"
    else:
        realm, layer, cost, limit, tier = "golden_core", 3, 10, 3, "golden_core"
    suffix = "_boss" if floor_no % 5 == 0 else ""
    return TowerFloorDefinition(
        floor_no=floor_no,
        required_realm=realm,
        required_layer=layer,
        stamina_cost=cost,
        daily_limit=limit,
        enemy_key=f"enemy.mist_trial.{tier}{suffix}",
    )


def reward_for(floor_no: int, seed: str, *, first_clear: bool) -> dict[str, int]:
    roll = int.from_bytes(hashlib.blake2b(seed.encode("utf-8"), digest_size=8).digest(), "big")
    if first_clear:
        if floor_no <= 10:
            reward = {"spirit_stones": 10, "item.mat.array_sand": 1}
        elif floor_no <= 20:
            reward = {"spirit_stones": 20, "item.mat.array_sand": 1 + roll % 2}
        elif floor_no <= 30:
            reward = {"spirit_stones": 35, "item.mat.array_sand": 2}
        else:
            reward = {"spirit_stones": 60, "item.mat.array_sand": 2}
        if floor_no in {15, 20}:
            reward["item.clue.recipe_basic"] = 1
        if floor_no in {25, 30}:
            reward["item.clue.mist_cave_route"] = 1
        if floor_no in {35, 40, 45}:
            reward["item.clue.recipe_basic"] = 1
        if floor_no in {5, 10}:
            reward["local_reputation"] = 5
        return reward
    return {"item.mat.array_sand": 1} if roll % 2 else {}


def attempt_band_for(floor_no: int) -> tuple[int, int]:
    floor_definition(floor_no)
    if floor_no <= 10:
        return 1, 10
    if floor_no <= 20:
        return 11, 20
    if floor_no <= 30:
        return 21, 30
    return 31, 45


def practice_week_start(value) -> str:
    return (value.date() - timedelta(days=value.weekday())).isoformat()


__all__ = [
    "CONTENT_VERSION",
    "LEGACY_CONTENT_VERSION",
    "LEGACY_RULE_VERSION",
    "MAX_FLOOR",
    "RULE_VERSION",
    "TOWER_KEY",
    "TowerFloorDefinition",
    "attempt_band_for",
    "floor_definition",
    "practice_week_start",
    "reward_for",
]
