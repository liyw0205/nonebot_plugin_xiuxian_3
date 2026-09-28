"""Versioned rules for the first open slice of the void spire tower."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import timedelta

from ..versions import module_versions


TOWER_KEY = "tower.void_spire"
MAX_FLOOR = 30
DESIGN_MAX_FLOOR = 90
WEEKLY_ATTEMPT_LIMIT = 2
STAMINA_COST = 20
REQUIRED_REALM = "void_refining"
REQUIRED_LAYER = 1
SUPPLY_REPUTATION_KEY = "local.void_supply"
SUPPLY_REPUTATION_REQUIRED = 600


@dataclass(frozen=True, slots=True)
class VoidSpireFloorDefinition:
    floor_no: int
    required_realm: str
    required_layer: int
    stamina_cost: int
    weekly_limit: int
    route_no: int
    route_key: str
    enemy_key: str
    boss: bool


def floor_definition(floor_no: int) -> VoidSpireFloorDefinition:
    if not isinstance(floor_no, int) or isinstance(floor_no, bool) or not 1 <= floor_no <= MAX_FLOOR:
        raise ValueError(f"void spire floor must be between 1 and {MAX_FLOOR}")
    route_no = 1 if floor_no <= 15 else 2
    route_key = "storm" if route_no == 1 else "echo"
    if floor_no == 15:
        enemy_key, boss = "enemy.void_spire.route_storm_boss", True
    elif floor_no == 30:
        enemy_key, boss = "enemy.void_spire.route_echo_boss", True
    elif floor_no <= 7:
        enemy_key, boss = "enemy.void_spire.scout", False
    elif floor_no <= 14:
        enemy_key, boss = "enemy.void_spire.sentinel", False
    elif floor_no <= 22:
        enemy_key, boss = "enemy.void_spire.watcher", False
    else:
        enemy_key, boss = "enemy.void_spire.warlord", False
    return VoidSpireFloorDefinition(
        floor_no=floor_no,
        required_realm=REQUIRED_REALM,
        required_layer=REQUIRED_LAYER,
        stamina_cost=STAMINA_COST,
        weekly_limit=WEEKLY_ATTEMPT_LIMIT,
        route_no=route_no,
        route_key=route_key,
        enemy_key=enemy_key,
        boss=boss,
    )


def versions_for_floor(floor_no: int) -> tuple[str, str]:
    floor_definition(floor_no)
    return module_versions(__name__)


def week_start(value) -> str:
    return (value.date() - timedelta(days=value.weekday())).isoformat()


def reward_for(floor_no: int, seed: str, *, first_clear: bool) -> dict[str, int]:
    definition = floor_definition(floor_no)
    if first_clear:
        reward = {"spirit_stones": 120, "item.mat.array_sand": 3}
        if definition.boss:
            reward["local.void_supply"] = 30
        return reward
    roll = int.from_bytes(hashlib.blake2b(seed.encode("utf-8"), digest_size=8).digest(), "big")
    return {"item.mat.array_sand": 1} if roll % 2 else {}


__all__ = [
    "DESIGN_MAX_FLOOR",
    "MAX_FLOOR",
    "REQUIRED_LAYER",
    "REQUIRED_REALM",
    "STAMINA_COST",
    "SUPPLY_REPUTATION_KEY",
    "SUPPLY_REPUTATION_REQUIRED",
    "TOWER_KEY",
    "VoidSpireFloorDefinition",
    "WEEKLY_ATTEMPT_LIMIT",
    "floor_definition",
    "reward_for",
    "versions_for_floor",
    "week_start",
]
