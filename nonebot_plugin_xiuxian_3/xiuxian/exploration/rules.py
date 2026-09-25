"""Pure, versioned rules for the v0.1 exploration modes."""

from __future__ import annotations

import hashlib

from .models import ExplorationDefinition


RULE_VERSION = "exploration-0.1.0"
V02_RULE_VERSION = "exploration-0.2.0"
V02_CONTENT_VERSION = "content-0.2"
V03_RULE_VERSION = "exploration-0.3.0"
V03_CONTENT_VERSION = "content-0.3"
CLOUD_BOAT_STORM_CHANCE_BP = 2500
CLOUD_BOAT_STORM_WAIT_SECONDS = 2 * 60
CLOUD_BOAT_STORM_PAY_COST = 100
CLOUD_BOAT_STORM_CHOICES = ("wait", "pay", "turn_back")
CLOUD_MINE_ACCESS_FLAGS = frozenset({
    "permit.cloud_mine",
    "cloud_mine.permit",
    "commission.cloud_mine",
})
CLOUD_MINE_ACCESS_ITEMS = frozenset({
    "item.permit.cloud_mine",
    "item.tool.mining_pickaxe",
    "item.tool.mining_pickaxe_t2",
})
BATTLE_ENEMY_BY_MODE = {
    "explore.gather_outskirts": "enemy.wood_rat",
    # Short training is available at qi-sensing L2; the L3 iron boar remains
    # reserved for later named encounters.
    "explore.trial_outskirts": "enemy.wood_rat",
    "explore.mist_grotto": "enemy.mist_guardian",
    "explore.cloud_mine": "enemy.cloud_beast",
    "explore.mist_grotto_2": "enemy.mist_elite",
    "explore.demon_abyss": "enemy.demon_overlord",
    "explore.beast_hunt": "enemy.beast_guardian",
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
    "explore.cloud_mine": ExplorationDefinition(
        key="explore.cloud_mine",
        label="云铁矿区采集",
        location_key="xuantian.cloud_mine",
        duration_seconds=2 * 60,
        stamina_cost=8,
        required_realm="foundation",
        required_layer=1,
        daily_limit=6,
        random_pool="gather.cloud_mine.v0.2",
        battle_chance_bp=3000,
        rule_version=V02_RULE_VERSION,
        energy_cost=2,
        content_version=V02_CONTENT_VERSION,
    ),
    "explore.mist_grotto_2": ExplorationDefinition(
        key="explore.mist_grotto_2",
        label="雾隐洞天二层探索",
        location_key="cave.mist_grotto_2",
        duration_seconds=10 * 60,
        stamina_cost=15,
        required_realm="golden_core",
        required_layer=1,
        daily_limit=2,
        random_pool="cave.mist_grotto_2.v0.2",
        battle_chance_bp=4000,
        rule_version=V02_RULE_VERSION,
        content_version=V02_CONTENT_VERSION,
    ),
    "explore.cloud_boat_trial": ExplorationDefinition(
        key="explore.cloud_boat_trial",
        label="云舟试炼",
        location_key="xuantian.floating_boat",
        duration_seconds=5 * 60,
        stamina_cost=12,
        required_realm="golden_core",
        required_layer=1,
        daily_limit=3,
        random_pool="trial.cloud_boat.v0.2",
        battle_chance_bp=0,
        rule_version=V02_RULE_VERSION,
        content_version=V02_CONTENT_VERSION,
    ),
    "explore.demon_abyss": ExplorationDefinition(
        key="explore.demon_abyss",
        label="魔界堕落遗迹探索",
        location_key="demon.fallen_ruins",
        duration_seconds=15 * 60,
        stamina_cost=20,
        required_realm="nascent_soul",
        required_layer=1,
        daily_limit=2,
        random_pool="loot.demon.abyss.v0.3",
        battle_chance_bp=10000,
        rule_version=V03_RULE_VERSION,
        content_version=V03_CONTENT_VERSION,
    ),
    "explore.beast_hunt": ExplorationDefinition(
        key="explore.beast_hunt",
        label="万兽山狩猎",
        location_key="beast.ten_thousand_hills",
        duration_seconds=15 * 60,
        stamina_cost=20,
        required_realm="nascent_soul",
        required_layer=1,
        daily_limit=2,
        random_pool="loot.beast.hills.v0.3",
        battle_chance_bp=10000,
        rule_version=V03_RULE_VERSION,
        content_version=V03_CONTENT_VERSION,
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
    "云铁矿区采集": "explore.cloud_mine",
    "云铁采集": "explore.cloud_mine",
    "洞天二层探索": "explore.mist_grotto_2",
    "云舟试炼": "explore.cloud_boat_trial",
    "云舟历练": "explore.cloud_boat_trial",
    "魔界堕落遗迹探索": "explore.demon_abyss",
    "堕落遗迹探索": "explore.demon_abyss",
    "万兽山狩猎": "explore.beast_hunt",
    "妖界万兽山探索": "explore.beast_hunt",
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


def has_cloud_mine_access(*, subprofession_key: str | None, inventory: dict[str, int], intro_flags: set[str]) -> bool:
    """Return whether the player has the v0.2 mining/commission gate.

    ``mining`` is accepted as a forward-compatible sub-class key even though
    the first path picker only exposes the three production sub-professions.
    Existing commission and permit flows can grant one of the stable flags or
    item keys without adding a second player column.
    """

    if str(subprofession_key or "") in {"mining", "mining.t2", "artifice.mining"}:
        return True
    if CLOUD_MINE_ACCESS_FLAGS & {str(flag) for flag in intro_flags}:
        return True
    return any(int(inventory.get(key, 0)) > 0 for key in CLOUD_MINE_ACCESS_ITEMS)


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


def cloud_boat_storm_roll_bp(seed: str) -> int:
    return battle_roll_bp(seed + ":storm")


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
    if mode_key == "explore.cloud_mine":
        return {
            "item.material.cloud_iron": weighted_value(
                seed + ":cloud_iron", (1, 2, 3, 4), (25, 40, 25, 10)
            )
        }
    if mode_key == "explore.mist_grotto_2":
        return {
            "cultivation": weighted_value(seed + ":cultivation", (900, 1100, 1300), (30, 45, 25)),
            "item.material.cloud_iron": weighted_value(seed + ":material", (1, 2), (60, 40)),
        }
    if mode_key == "explore.cloud_boat_trial":
        return {
            "cultivation": weighted_value(seed + ":cultivation", (600, 750, 900), (30, 40, 30)),
            "item.ticket.cloud_boat_fragment": weighted_value(seed + ":ticket", (1, 2), (60, 40)),
        }
    if mode_key == "explore.demon_abyss":
        # Keep the pool stable in the session snapshot: the final 10% is the
        # documented heart-demon encounter, whose separate event flow remains
        # closed in this slice and therefore yields no asset here.
        reward = weighted_value(seed + ":reward", (0, 1, 2, 3), (45, 30, 15, 10))
        if reward == 0:
            return {"item.demon_core": 1}
        if reward == 1:
            return {"faction_reputation.demon": 15}
        if reward == 2:
            return {"item.clue.demon_contract": 1}
        return {}
    if mode_key == "explore.beast_hunt":
        # The final branch is the documented ancestor event, which remains a
        # later independent slice and therefore does not mint an asset here.
        reward = weighted_value(seed + ":reward", (0, 1, 2, 3), (45, 30, 15, 10))
        if reward == 0:
            return {"item.beast_blood": 1}
        if reward == 1:
            return {"faction_reputation.beast": 15}
        if reward == 2:
            return {"item.clue.beast_bloodline": 1}
        return {}
    raise ValueError(f"unsupported exploration mode: {mode_key}")


__all__ = [
    "DEFINITIONS",
    "BATTLE_ENEMY_BY_MODE",
    "RULE_VERSION",
    "V02_CONTENT_VERSION",
    "V02_RULE_VERSION",
    "V03_CONTENT_VERSION",
    "V03_RULE_VERSION",
    "battle_roll_bp",
    "CLOUD_MINE_ACCESS_FLAGS",
    "CLOUD_MINE_ACCESS_ITEMS",
    "exploration_definition",
    "exploration_enemy_key",
    "has_cloud_mine_access",
    "meets_realm",
    "resolve_exploration_mode",
    "settlement_result",
    "weighted_value",
]
