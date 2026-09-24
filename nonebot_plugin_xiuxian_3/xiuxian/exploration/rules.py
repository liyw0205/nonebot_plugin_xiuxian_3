"""Pure, versioned rules for the v0.1 exploration modes."""

from __future__ import annotations

import hashlib

from .models import ExplorationDefinition


RULE_VERSION = "exploration-0.1.0"
BATTLE_ENEMY_BY_MODE = {
    "explore.gather_outskirts": "enemy.wood_rat",
    # Short training is available at qi-sensing L2; the L3 iron boar remains
    # reserved for later named encounters.
    "explore.trial_outskirts": "enemy.wood_rat",
    "explore.mist_grotto": "enemy.mist_guardian",
}

DEFINITIONS = {
    "explore.gather_outskirts": ExplorationDefinition(
        key="explore.gather_outskirts",
        label="近郊采集",
        location_key="xuantian.outskirts",
        duration_seconds=30,
        stamina_cost=3,
        required_realm="mortal",
        required_layer=0,
        daily_limit=12,
        random_pool="gather.outskirts.v0.1",
        battle_chance_bp=1000,
        rule_version=RULE_VERSION,
    ),
    "explore.trial_outskirts": ExplorationDefinition(
        key="explore.trial_outskirts",
        label="近郊短历练",
        location_key="xuantian.outskirts",
        duration_seconds=60,
        stamina_cost=5,
        required_realm="qi_sensing",
        required_layer=2,
        daily_limit=8,
        random_pool="trial.outskirts.v0.1",
        battle_chance_bp=2000,
        rule_version=RULE_VERSION,
    ),
    "explore.spring_gather": ExplorationDefinition(
        key="explore.spring_gather",
        label="灵泉采集",
        location_key="xuantian.spirit_field",
        duration_seconds=90,
        stamina_cost=6,
        required_realm="qi_sensing",
        required_layer=2,
        daily_limit=6,
        random_pool="gather.spirit_field.v0.1",
        battle_chance_bp=0,
        rule_version=RULE_VERSION,
    ),
    "explore.mist_grotto": ExplorationDefinition(
        key="explore.mist_grotto",
        label="雾隐洞天探索",
        location_key="cave.mist_grotto",
        duration_seconds=5 * 60,
        stamina_cost=10,
        required_realm="qi_gathering",
        required_layer=4,
        daily_limit=2,
        random_pool="cave.mist_grotto.v0.1",
        battle_chance_bp=2500,
        rule_version=RULE_VERSION,
    ),
}

ALIASES = {
    "近郊采集": "explore.gather_outskirts",
    "采集": "explore.gather_outskirts",
    "短历练": "explore.trial_outskirts",
    "近郊历练": "explore.trial_outskirts",
    "灵泉采集": "explore.spring_gather",
    "雾隐洞天探索": "explore.mist_grotto",
    "洞天探索": "explore.mist_grotto",
}


def resolve_exploration_mode(value: str) -> str | None:
    normalized = value.strip()
    if normalized in DEFINITIONS:
        return normalized
    return ALIASES.get(normalized)


def exploration_definition(mode_key: str) -> ExplorationDefinition:
    try:
        return DEFINITIONS[mode_key]
    except KeyError as exc:
        raise ValueError(f"unsupported exploration mode: {mode_key}") from exc


def exploration_enemy_key(mode_key: str) -> str | None:
    return BATTLE_ENEMY_BY_MODE.get(mode_key)


def realm_rank(realm_key: str) -> int:
    return {
        "mortal": 0,
        "qi_sensing": 1,
        "qi_gathering": 2,
        "foundation": 3,
        "golden_core": 4,
        "nascent_soul": 5,
        "soul_transformation": 6,
    }.get(realm_key, -1)


def meets_realm(realm_key: str, layer: int, required_realm: str | None, required_layer: int) -> bool:
    if required_realm is None:
        return True
    return (realm_rank(realm_key), int(layer)) >= (realm_rank(required_realm), required_layer)


def weighted_value(seed: str, values: tuple[int, ...], weights: tuple[int, ...]) -> int:
    if not values or len(values) != len(weights) or sum(weights) <= 0:
        raise ValueError("invalid weighted pool")
    roll = int.from_bytes(hashlib.blake2b(seed.encode("utf-8"), digest_size=8).digest(), "big")
    cursor = roll % sum(weights)
    for value, weight in zip(values, weights, strict=True):
        if cursor < weight:
            return value
        cursor -= weight
    return values[-1]


def battle_roll_bp(seed: str) -> int:
    digest = hashlib.blake2b(seed.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big") % 10000


def settlement_result(mode_key: str, seed: str) -> dict[str, int]:
    if mode_key == "explore.gather_outskirts":
        return {
            "item.herb.blood_grass": 1 + weighted_value(seed + ":blood", (0, 1, 2), (35, 45, 20)),
            "item.ore.ironstone": weighted_value(seed + ":iron", (0, 1, 2), (50, 35, 15)),
        }
    if mode_key == "explore.trial_outskirts":
        return {
            "cultivation": weighted_value(seed + ":cultivation", (40, 60, 80), (30, 45, 25)),
            "spirit_stones": weighted_value(seed + ":stones", (10, 20, 30), (40, 40, 20)),
        }
    if mode_key == "explore.spring_gather":
        return {
            "item.herb.spirit_leaf": 1 + weighted_value(seed + ":leaf", (0, 1), (60, 40)),
            "item.mat.array_sand": weighted_value(seed + ":sand", (0, 1), (60, 40)),
        }
    if mode_key == "explore.mist_grotto":
        material = weighted_value(
            seed + ":material",
            (0, 1, 2),
            (45, 30, 25),
        )
        keys = ("item.herb.spirit_leaf", "item.mat.array_sand", "item.ore.ironstone")
        return {
            "cultivation": weighted_value(seed + ":cultivation", (300, 400, 500), (30, 45, 25)),
            keys[material]: weighted_value(seed + ":quantity", (1, 2, 3), (45, 35, 20)),
        }
    raise ValueError(f"unsupported exploration mode: {mode_key}")


__all__ = [
    "DEFINITIONS",
    "BATTLE_ENEMY_BY_MODE",
    "RULE_VERSION",
    "battle_roll_bp",
    "exploration_definition",
    "exploration_enemy_key",
    "meets_realm",
    "resolve_exploration_mode",
    "settlement_result",
    "weighted_value",
]
