"""Pure rules for exploration modes."""

from __future__ import annotations


import hashlib
from typing import Any

from ..companions.rules import companion_exploration_discovery_bp
from ..content import ContentBundle, ContentError, bundled_content
from ..rewards.rules import (
    RewardContentError,
    reward_pool_battle_failure_rewards,
    reward_pool_map,
    reward_pool_outcomes,
    reward_pool_uses_item_weight_bonus,
)
from ..utils.assets import inventory_amount
from ..utils.player import split_player_rewards
from ..utils.randomness import deterministic_weighted_choice
from .models import ExplorationDefinition


CLOUD_BOAT_STORM_CHANCE_BP = 2500
CLOUD_BOAT_STORM_WAIT_SECONDS = 2 * 60
CLOUD_BOAT_STORM_PAY_COST = 100
CLOUD_BOAT_STORM_CHOICES = ("wait", "pay", "turn_back")
MAX_EXPLORATION_DISCOVERY_BP = 5_000
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
def _content(content: ContentBundle | None = None) -> ContentBundle:
    return content or bundled_content()


def _definitions(content: ContentBundle | None = None) -> dict[str, ExplorationDefinition]:
    bundle = _content(content)
    definitions: dict[str, ExplorationDefinition] = {}
    for row in bundle.list("exploration_mode", include_locked=False):
        key = row.get("key")
        required_realm = row.get("required_realm")
        required_layer = row.get("required_layer")
        if not isinstance(key, str) or not key.startswith("explore."):
            raise ContentError(f"exploration mode has invalid key: {key!r}")
        for field in ("name", "desc", "location_key", "random_pool", "reward_pool_key"):
            if not isinstance(row.get(field), str) or not row[field].strip():
                raise ContentError(f"exploration mode {key} requires {field}")
        aliases = row.get("aliases", [])
        if not isinstance(aliases, list) or any(not isinstance(alias, str) or not alias.strip() for alias in aliases):
            raise ContentError(f"exploration mode {key} aliases must be non-empty strings")
        if not isinstance(required_realm, str) or not bundle.has("realm", required_realm, include_locked=False):
            raise ContentError(f"exploration mode {key} references an unavailable realm")
        if not isinstance(required_layer, int) or isinstance(required_layer, bool) or required_layer < 0:
            raise ContentError(f"exploration mode {key} has invalid required_layer")
        if not bundle.has("location", row["location_key"], include_locked=False):
            raise ContentError(f"exploration mode {key} references an unavailable location")
        if not bundle.has("reward", row["reward_pool_key"], include_locked=False):
            raise ContentError(f"exploration mode {key} references an unavailable reward pool")
        access_any = row.get("access_any", [])
        if not isinstance(access_any, list) or any(not isinstance(item, dict) for item in access_any):
            raise ContentError(f"exploration mode {key} access_any must be a list of objects")
        for access in access_any:
            access_type = access.get("type")
            if access_type == "item":
                item_key = access.get("item_key")
                quantity = access.get("quantity")
                if not isinstance(item_key, str) or not bundle.has("item", item_key, include_locked=False):
                    raise ContentError(f"exploration mode {key} references an unavailable access item")
                if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
                    raise ContentError(f"exploration mode {key} access item quantity must be positive")
            elif access_type in {"subprofession", "intro_flag"}:
                if not isinstance(access.get("value"), str) or not access["value"].strip():
                    raise ContentError(f"exploration mode {key} access value must be non-empty")
            else:
                raise ContentError(f"exploration mode {key} has unsupported access type")
        enemy_pool_key = row.get("enemy_pool_key")
        if enemy_pool_key is not None:
            if not isinstance(enemy_pool_key, str) or not enemy_pool_key.strip():
                raise ContentError(f"exploration mode {key} has invalid enemy_pool_key")
            pool = bundle.get("encounter_pool", enemy_pool_key, include_locked=False)
            if pool is None or not isinstance(pool.get("candidates"), list) or not pool["candidates"]:
                raise ContentError(f"exploration mode {key} references an empty encounter pool")
        definitions[key] = ExplorationDefinition(
            key=key,
            label=row["name"].strip(),
            location_key=row["location_key"],
            duration_seconds=_positive_int(row, "duration_seconds", key),
            stamina_cost=_positive_int(row, "stamina_cost", key, allow_zero=True),
            required_realm=required_realm,
            required_layer=required_layer,
            daily_limit=_positive_int(row, "daily_limit", key),
            random_pool=row["random_pool"],
            battle_chance_bp=_bounded_int(row, "battle_chance_bp", key),
            energy_cost=_positive_int(row, "energy_cost", key, allow_zero=True),
        )
    return definitions


def _positive_int(row: dict[str, Any], field: str, key: str, *, allow_zero: bool = False) -> int:
    value = row.get(field)
    if isinstance(value, bool) or not isinstance(value, int) or value < (0 if allow_zero else 1):
        raise ContentError(f"exploration mode {key} has invalid {field}")
    return value


def _bounded_int(row: dict[str, Any], field: str, key: str) -> int:
    value = _positive_int(row, field, key, allow_zero=True)
    if value > 10000:
        raise ContentError(f"exploration mode {key} has invalid {field}")
    return value


def _aliases(content: ContentBundle | None = None) -> dict[str, str]:
    result: dict[str, str] = {}
    bundle = _content(content)
    for row in bundle.list("exploration_mode", include_locked=False):
        key = row["key"]
        for alias in [row["name"], *row.get("aliases", [])]:
            if not isinstance(alias, str) or not alias.strip():
                raise ContentError(f"exploration mode {key} has invalid alias")
            previous = result.setdefault(alias, key)
            if previous != key:
                raise ContentError(f"ambiguous exploration alias: {alias}")
    return result


DEFINITIONS = _definitions()
ALIASES = _aliases()
BATTLE_ENEMY_BY_MODE = {
    key: next(iter(_content().require("encounter_pool", row["enemy_pool_key"])["candidates"]), {}).get("enemy_key")
    for key, row in ((row["key"], row) for row in _content().list("exploration_mode", include_locked=False))
    if row.get("enemy_pool_key")
}
EXPLORATION_REWARD_POOLS = {
    row["key"]: row["reward_pool_key"]
    for row in _content().list("exploration_mode", include_locked=False)
}


def resolve_exploration_mode(value: str, content: ContentBundle | None = None) -> str | None:
    normalized = value.strip()
    definitions = _definitions(content) if content is not None else DEFINITIONS
    aliases = _aliases(content) if content is not None else ALIASES
    if normalized in definitions:
        return normalized
    return aliases.get(normalized)


def exploration_definition(mode_key: str, content: ContentBundle | None = None) -> ExplorationDefinition:
    try:
        return (_definitions(content) if content is not None else DEFINITIONS)[mode_key]
    except KeyError as exc:
        raise ValueError(f"unsupported exploration mode: {mode_key}") from exc


def exploration_enemy_key(mode_key: str, content: ContentBundle | None = None) -> str | None:
    bundle = _content(content)
    row = bundle.get("exploration_mode", mode_key, include_locked=False)
    if row is None or not row.get("enemy_pool_key"):
        return None
    pool = bundle.require("encounter_pool", str(row["enemy_pool_key"]), include_locked=False)
    candidates = pool.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise ContentError(f"encounter pool {row['enemy_pool_key']} has no candidates")
    enemy_key = candidates[0].get("enemy_key") if isinstance(candidates[0], dict) else None
    if not isinstance(enemy_key, str) or not bundle.has("enemy", enemy_key, include_locked=False):
        raise ContentError(f"encounter pool {row['enemy_pool_key']} has an invalid enemy")
    return enemy_key


def exploration_encounter_selection(
    mode_key: str,
    *,
    seed: str,
    realm_key: str,
    realm_layer: int,
    content: ContentBundle | None = None,
) -> tuple[str | None, list[dict[str, Any]]]:
    """Choose and return a weighted encounter candidate list eligible to the actor."""

    if not isinstance(seed, str) or not seed:
        raise ValueError("exploration encounter seed must be a non-empty string")
    if isinstance(realm_layer, bool) or not isinstance(realm_layer, int) or realm_layer < 0:
        raise ValueError("exploration encounter realm layer must be non-negative")
    bundle = _content(content)
    mode = bundle.get("exploration_mode", mode_key, include_locked=False)
    if mode is None or not mode.get("enemy_pool_key"):
        return None, []
    pool = bundle.require("encounter_pool", str(mode["enemy_pool_key"]), include_locked=False)
    candidates = pool.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise ContentError(f"encounter pool {pool['key']} has no candidates")
    rank_row = bundle.get("realm", realm_key, include_locked=False)
    if rank_row is None or isinstance(rank_row.get("rank"), bool) or not isinstance(rank_row.get("rank"), int):
        raise ContentError(f"exploration encounter has unavailable realm {realm_key}")
    player_rank = int(rank_row["rank"])
    eligible: list[dict[str, Any]] = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            raise ContentError(f"encounter pool {pool['key']} has a malformed candidate")
        enemy_key = candidate.get("enemy_key")
        weight = candidate.get("weight")
        if (
            not isinstance(enemy_key, str)
            or not enemy_key
            or isinstance(weight, bool)
            or not isinstance(weight, int)
            or weight <= 0
        ):
            raise ContentError(f"encounter pool {pool['key']} has an invalid candidate")
        enemy = bundle.require("enemy", enemy_key, include_locked=False)
        requirement = next(
            (
                item for item in enemy.get("requirements", [])
                if isinstance(item, dict) and item.get("type", "realm") == "realm"
            ),
            None,
        )
        if requirement is not None:
            required_realm = requirement.get("realm_key")
            required_layer = requirement.get("min_layer", 1)
            required = bundle.get("realm", required_realm, include_locked=False) if isinstance(required_realm, str) else None
            if (
                required is None
                or isinstance(required_layer, bool)
                or not isinstance(required_layer, int)
                or (player_rank, realm_layer) < (int(required.get("rank", -1)), required_layer)
            ):
                continue
        eligible.append({"enemy_key": enemy_key, "weight": weight})
    if not eligible:
        raise ContentError(f"encounter pool {pool['key']} has no candidates for {realm_key}:{realm_layer}")
    selected = deterministic_weighted_choice(
        tuple((item["weight"], item["enemy_key"]) for item in eligible), seed
    )
    return selected, eligible


def exploration_reward_pool(mode_key: str, content: ContentBundle | None = None) -> str | None:
    row = _content(content).get("exploration_mode", mode_key, include_locked=False)
    return str(row["reward_pool_key"]) if row is not None else None


def has_cloud_mine_access(*, subprofession_key: str | None, inventory: dict[str, int], intro_flags: set[str]) -> bool:
    """Check the mining path, carried tools/permit or registered permit flags."""

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
    reward_pool_key = exploration_reward_pool(mode_key, content)
    if reward_pool_key is not None:
        uses_item_weight_bonus = reward_pool_uses_item_weight_bonus(reward_pool_key, content)
        result = reward_pool_map(
            reward_pool_key,
            f"{seed}:reward" if uses_item_weight_bonus else seed,
            content,
            item_weight_bonus_bp=drop_weight_bp if uses_item_weight_bonus else 0,
        )
        parts = split_player_rewards(result)
        if set(parts.value_delta) - {"cultivation", "total_cultivation"}:
            raise RewardContentError(
                f"exploration reward pool {reward_pool_key} contains unsupported state"
            )
        return result
    raise ValueError(f"unsupported exploration mode: {mode_key}")


def exploration_discovery_weight_bp(
    constitution_effect: object,
    companions: list[dict[str, Any]] | tuple[dict[str, Any], ...],
) -> int:
    """Combine frozen discovery effects under the shared exploration cap."""

    constitution_bonus = 0
    if isinstance(constitution_effect, dict) and constitution_effect.get("type") == "drop_weight_bp":
        value = constitution_effect.get("value")
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise RewardContentError("constitution exploration weight bonus is invalid")
        constitution_bonus = value
    return min(
        MAX_EXPLORATION_DISCOVERY_BP,
        constitution_bonus + companion_exploration_discovery_bp(companions),
    )


def settlement_failure_result(
    mode_key: str,
    *,
    content: ContentBundle | None = None,
) -> dict[str, int]:
    reward_pool_key = exploration_reward_pool(mode_key, content)
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
    "exploration_discovery_weight_bp",
    "exploration_enemy_key",
    "exploration_encounter_selection",
    "exploration_reward_pool",
    "EXPLORATION_REWARD_POOLS",
    "has_cloud_mine_access",
    "meets_realm",
    "resolve_exploration_mode",
    "settlement_failure_result",
    "settlement_result",
]
