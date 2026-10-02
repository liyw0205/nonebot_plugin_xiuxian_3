"""Pure rules for exploration modes."""

from __future__ import annotations


import hashlib

from ..content import ContentBundle
from ..rewards.rules import (
    RewardContentError,
    reward_pool_battle_failure_rewards,
    reward_pool_map,
)
from ..utils.assets import inventory_amount
from ..utils.player import split_player_rewards
from .models import ExplorationDefinition


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
    "explore.demon_abyss": "enemy.demon_ruins_scout",
    "explore.beast_hunt": "enemy.beast_guardian",
    "explore.ancestral_lake": "enemy.ancestral_spirit",
}

EXPLORATION_REWARD_POOLS = {
    "explore.gather_outskirts": "reward_pool.exploration.gather_outskirts",
    "explore.trial_outskirts": "reward_pool.exploration.trial_outskirts",
    "explore.spring_gather": "reward_pool.exploration.spring_gather",
    "explore.mist_grotto": "reward_pool.exploration.mist_grotto",
    "explore.cloud_mine": "reward_pool.exploration.cloud_mine",
    "explore.mist_grotto_2": "reward_pool.exploration.mist_grotto_2",
    "explore.cloud_boat_trial": "reward_pool.exploration.cloud_boat_trial",
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
        random_pool="gather.outskirts",
        battle_chance_bp=1000,
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
        random_pool="trial.outskirts",
        battle_chance_bp=2000,
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
        random_pool="gather.spirit_field",
        battle_chance_bp=0,
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
        random_pool="cave.mist_grotto",
        battle_chance_bp=2500,
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
        random_pool="gather.cloud_mine",
        battle_chance_bp=3000,
        energy_cost=2,
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
        random_pool="cave.mist_grotto_2",
        battle_chance_bp=4000,
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
        random_pool="trial.cloud_boat",
        battle_chance_bp=0,
    ),
    "explore.demon_threshold": ExplorationDefinition(
        key="explore.demon_threshold",
        label="深渊门备材",
        location_key="demon.abyss_gate",
        duration_seconds=4 * 60,
        stamina_cost=8,
        required_realm="golden_core",
        required_layer=9,
        daily_limit=6,
        random_pool="gather.demon_threshold",
        battle_chance_bp=0,
        energy_cost=2,
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
        random_pool="loot.demon.abyss",
        battle_chance_bp=10000,
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
        random_pool="loot.beast.hills",
        battle_chance_bp=10000,
    ),
    "explore.ancestral_lake": ExplorationDefinition(
        key="explore.ancestral_lake",
        label="祖灵湖探索",
        location_key="beast.ancestral_lake",
        duration_seconds=20 * 60,
        stamina_cost=25,
        required_realm="soul_transformation",
        required_layer=1,
        daily_limit=2,
        random_pool="event.ancestral_lake",
        battle_chance_bp=3500,
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
    "深渊门备材": "explore.demon_threshold",
    "深渊门采集": "explore.demon_threshold",
    "魔界堕落遗迹探索": "explore.demon_abyss",
    "堕落遗迹探索": "explore.demon_abyss",
    "万兽山狩猎": "explore.beast_hunt",
    "妖界万兽山探索": "explore.beast_hunt",
    "祖灵湖探索": "explore.ancestral_lake",
    "祖灵湖": "explore.ancestral_lake",
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


def exploration_reward_pool(mode_key: str) -> str | None:
    return EXPLORATION_REWARD_POOLS.get(mode_key)


def has_cloud_mine_access(*, subprofession_key: str | None, inventory: dict[str, int], intro_flags: set[str]) -> bool:
    """Return whether the player has the mining/commission gate.

    ``mining`` is accepted as a forward-compatible sub-class key even though
    the first path picker only exposes the three production sub-professions.
    Existing commission and permit flows can grant one of the stable flags or
    item keys without adding a second player column.
    """

    if str(subprofession_key or "") in {"mining", "mining.t2", "artifice.mining"}:
        return True
    if CLOUD_MINE_ACCESS_FLAGS & {str(flag) for flag in intro_flags}:
        return True
    return any(inventory_amount(inventory, key) > 0 for key in CLOUD_MINE_ACCESS_ITEMS)


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


def weighted_value_with_item_bonus(
    seed: str,
    values: tuple[int, ...],
    weights: tuple[int, ...],
    *,
    item_values: frozenset[int],
    bonus_bp: int,
) -> int:
    if isinstance(bonus_bp, bool) or not isinstance(bonus_bp, int) or bonus_bp < 0:
        raise ValueError("item drop weight bonus must be a non-negative integer")
    if bonus_bp == 0:
        return weighted_value(seed, values, weights)
    scaled_weights = tuple(
        weight * (10_000 + bonus_bp) if value in item_values else weight * 10_000
        for value, weight in zip(values, weights, strict=True)
    )
    return weighted_value(seed, values, scaled_weights)


def battle_roll_bp(seed: str) -> int:
    digest = hashlib.blake2b(seed.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big") % 10000


def cloud_boat_storm_roll_bp(seed: str) -> int:
    return battle_roll_bp(seed + ":storm")


def settlement_result(
    mode_key: str,
    seed: str,
    *,
    drop_weight_bp: int = 0,
    content: ContentBundle | None = None,
) -> dict[str, int]:
    reward_pool_key = exploration_reward_pool(mode_key)
    if reward_pool_key is not None:
        result = reward_pool_map(reward_pool_key, seed, content)
        parts = split_player_rewards(result)
        if set(parts.value_delta) - {"cultivation", "total_cultivation"}:
            raise RewardContentError(
                f"exploration reward pool {reward_pool_key} contains unsupported state"
            )
        return result
    if mode_key == "explore.demon_threshold":
        return {"item.soul_crystal": 1, "item.demon_core": 1}
    if mode_key == "explore.demon_abyss":
        # Keep the pool stable in the session snapshot: the final 10% is the
        # documented heart-demon encounter, whose separate event flow remains
        # closed in this slice and therefore yields no asset here.
        reward = weighted_value_with_item_bonus(
            seed + ":reward", (0, 1, 2, 3), (45, 30, 15, 10),
            item_values=frozenset({0, 2}), bonus_bp=drop_weight_bp,
        )
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
        reward = weighted_value_with_item_bonus(
            seed + ":reward", (0, 1, 2, 3), (45, 30, 15, 10),
            item_values=frozenset({0, 2}), bonus_bp=drop_weight_bp,
        )
        if reward == 0:
            return {"item.beast_blood": 1}
        if reward == 1:
            return {"faction_reputation.beast": 15}
        if reward == 2:
            return {"item.clue.beast_bloodline": 1}
        return {}
    if mode_key == "explore.ancestral_lake":
        return {
            "item.ancestral_blood": 1,
            "faction_reputation.beast": 30,
        }
    raise ValueError(f"unsupported exploration mode: {mode_key}")


def settlement_failure_result(
    mode_key: str,
    *,
    content: ContentBundle | None = None,
) -> dict[str, int]:
    reward_pool_key = exploration_reward_pool(mode_key)
    if reward_pool_key is None:
        return {}
    result = reward_pool_battle_failure_rewards(reward_pool_key, content)
    parts = split_player_rewards(result)
    if set(parts.value_delta) - {"cultivation", "total_cultivation"}:
        raise RewardContentError(
            f"exploration reward pool {reward_pool_key} contains unsupported state"
        )
    return result


__all__ = [
    "DEFINITIONS",
    "BATTLE_ENEMY_BY_MODE",
    "battle_roll_bp",
    "CLOUD_MINE_ACCESS_FLAGS",
    "CLOUD_MINE_ACCESS_ITEMS",
    "exploration_definition",
    "exploration_enemy_key",
    "exploration_reward_pool",
    "EXPLORATION_REWARD_POOLS",
    "has_cloud_mine_access",
    "meets_realm",
    "resolve_exploration_mode",
    "settlement_failure_result",
    "settlement_result",
    "weighted_value",
    "weighted_value_with_item_bonus",
]
