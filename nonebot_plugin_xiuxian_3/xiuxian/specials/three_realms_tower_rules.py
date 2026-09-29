"""Versioned rules for the single-player three-realms tower."""

from __future__ import annotations


import hashlib
from dataclasses import dataclass
from datetime import timedelta


CONTENT_VERSION = ""
RULE_VERSION = ""
TOWER_KEY = "tower.three_realms"
V03_MAX_FLOOR = 20
MAX_FLOOR = 40
WEEKLY_ATTEMPT_LIMIT = 2
FACTIONS = ("xuantian", "demon", "beast")
REBUILD_REPUTATION_KEYS = (
    "local.domain_refuge",
    "local.abyss_outpost",
    "local.ancestral_habitat",
)


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
        required_realm="nascent_soul" if floor_no <= V03_MAX_FLOOR else "soul_transformation",
        required_layer=1,
        stamina_cost=12,
        weekly_limit=WEEKLY_ATTEMPT_LIMIT,
    )


def rebuild_reputation_total(values: dict[str, object]) -> int:
    total = 0
    for key in REBUILD_REPUTATION_KEYS:
        try:
            total += max(0, int(values.get(key, 0)))
        except (TypeError, ValueError):
            continue
    return total


def enemy_key_for(floor_no: int, faction: str) -> str:
    floor_definition(floor_no)
    if faction not in FACTIONS:
        raise ValueError(f"unsupported three-realms faction: {faction}")
    if floor_no == 10:
        encounter = "floor_10_boss"
    elif floor_no == 20:
        encounter = "floor_20_boss"
    elif floor_no == 30:
        encounter = "floor_30_boss"
    elif floor_no == 40:
        encounter = "floor_40_boss"
    elif floor_no <= 9:
        encounter = "vanguard"
    elif floor_no <= 19:
        encounter = "veteran"
    elif floor_no <= 29:
        encounter = "domain_vanguard"
    else:
        encounter = "domain_veteran"
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
    "REBUILD_REPUTATION_KEYS",
    "RULE_VERSION",
    "TOWER_KEY",
    "WEEKLY_ATTEMPT_LIMIT",
    "V03_MAX_FLOOR",
    "ThreeRealmsTowerFloorDefinition",
    "enemy_key_for",
    "floor_definition",
    "rebuild_reputation_total",
    "reward_for",
    "week_start",
]
