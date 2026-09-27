"""Versioned v0.1 mist-trial tower rules."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import timedelta


CONTENT_VERSION = "content-0.1"
RULE_VERSION = "specials-0.1.2"
TOWER_KEY = "tower.mist_trial"
MAX_FLOOR = 30


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
        raise ValueError("tower floor must be between 1 and 30")
    if floor_no <= 10:
        realm, layer, cost, limit, tier = "qi_sensing", 1, 4, 5, "sensing"
    elif floor_no <= 20:
        realm, layer, cost, limit, tier = "qi_gathering", 4, 6, 4, "gathering"
    else:
        realm, layer, cost, limit, tier = "foundation", 4, 8, 3, "foundation"
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
        else:
            reward = {"spirit_stones": 35, "item.mat.array_sand": 2}
        if floor_no in {15, 20}:
            reward["item.clue.recipe_basic"] = 1
        if floor_no in {25, 30}:
            reward["item.clue.mist_cave_route"] = 1
        if floor_no in {5, 10}:
            reward["local_reputation"] = 5
        return reward
    return {"item.mat.array_sand": 1} if roll % 2 else {}


def practice_week_start(value) -> str:
    return (value.date() - timedelta(days=value.weekday())).isoformat()


__all__ = [
    "CONTENT_VERSION",
    "MAX_FLOOR",
    "RULE_VERSION",
    "TOWER_KEY",
    "TowerFloorDefinition",
    "floor_definition",
    "practice_week_start",
    "reward_for",
]
