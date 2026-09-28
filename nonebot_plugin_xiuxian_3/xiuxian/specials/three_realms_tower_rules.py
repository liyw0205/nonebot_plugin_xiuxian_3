"""Versioned rules for the first, single-player three-realms tower release."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import timedelta


CONTENT_VERSION = "content-0.3"
RULE_VERSION = "specials-0.3.0"
TOWER_KEY = "tower.three_realms"
MAX_FLOOR = 20
WEEKLY_ATTEMPT_LIMIT = 2
FACTIONS = ("xuantian", "demon", "beast")


@dataclass(frozen=True, slots=True)
class ThreeRealmsTowerFloorDefinition:
    floor_no: int
    required_realm: str
    required_layer: int
    stamina_cost: int
    weekly_limit: int


def floor_definition(floor_no: int) -> ThreeRealmsTowerFloorDefinition:
    if not isinstance(floor_no, int) or isinstance(floor_no, bool) or not 1 <= floor_no <= MAX_FLOOR:
        raise ValueError(f"three-realms tower floor must be between 1 and {MAX_FLOOR}")
    return ThreeRealmsTowerFloorDefinition(
        floor_no=floor_no,
        required_realm="nascent_soul",
        required_layer=1,
        stamina_cost=12,
        weekly_limit=WEEKLY_ATTEMPT_LIMIT,
    )


def enemy_key_for(floor_no: int, faction: str) -> str:
    floor_definition(floor_no)
    if faction not in FACTIONS:
        raise ValueError(f"unsupported three-realms faction: {faction}")
    encounter = (
        "floor_10_boss" if floor_no == 10 else
        "floor_20_boss" if floor_no == 20 else
        "vanguard" if floor_no < 10 else "veteran"
    )
    return f"enemy.three_realms_tower.{faction}.{encounter}"


def reward_for(floor_no: int, seed: str, *, first_clear: bool) -> dict[str, int]:
    floor_definition(floor_no)
    if first_clear:
        return {"item.mat.array_sand": 2, "spirit_stones": 60}
    roll = int.from_bytes(hashlib.blake2b(seed.encode("utf-8"), digest_size=8).digest(), "big")
    return {"item.mat.array_sand": 1} if roll % 2 else {}


def week_start(value) -> str:
    return (value.date() - timedelta(days=value.weekday())).isoformat()


__all__ = [
    "CONTENT_VERSION",
    "FACTIONS",
    "MAX_FLOOR",
    "RULE_VERSION",
    "TOWER_KEY",
    "WEEKLY_ATTEMPT_LIMIT",
    "ThreeRealmsTowerFloorDefinition",
    "enemy_key_for",
    "floor_definition",
    "reward_for",
    "week_start",
]
