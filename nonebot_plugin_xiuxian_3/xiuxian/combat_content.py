"""Validate the data consumed by exploration and automatic combat.

This check closes the content boundary without changing battle selection or
settlement.  Runtime combat still freezes inline ``combat_profile.reward``;
``drop_pool_key`` is validated as a declared pool for the existing source and
reward contracts until a later consumer explicitly adopts it.
"""

from __future__ import annotations

from typing import Any

from .content import ContentBundle, ContentError
from .rewards.rules import reward_pool_outcomes


_STATUSES = {"active", "open", "locked", "planned"}
_REQUIREMENT_TYPES = {"realm", "stage_min"}


def validate_combat_content(bundle: ContentBundle) -> dict[str, int]:
    """Validate enemy prototypes, encounter pools, drops, and skill references."""

    enemies = bundle.list("enemy", include_locked=True)
    skills = bundle.list("skill", include_locked=True)
    encounters = bundle.list("encounter_pool", include_locked=True)
    if not enemies:
        raise ContentError("combat content has no enemy records")
    if not encounters:
        raise ContentError("combat content has no encounter pools")

    enemy_keys = {row.get("key") for row in enemies}
    skill_keys = {row.get("key") for row in skills}
    active_enemy_keys = {
        row["key"] for row in enemies if row.get("status") in {"active", "open"}
    }
    profile_count = 0
    drop_pool_keys: set[str] = set()
    enemy_skill_keys: set[str] = set()
    for row in enemies:
        key = _record_key(row, "enemy")
        _labels(row, f"enemy {key}")
        _status(row, key, "enemy")
        _non_empty(row.get("location_key"), f"enemy {key} requires location_key")
        # Tower fights use stable virtual locations owned by tower content;
        # ordinary enemies must resolve to a map location record.
        if not bundle.has("location", row["location_key"], include_locked=True) and not row["location_key"].startswith("tower."):
            raise ContentError(f"enemy {key} references unknown location {row['location_key']}")
        _validate_requirements(row.get("requirements"), bundle, key)
        _validate_stats(row.get("stats"), key, require_agility=isinstance(row.get("combat_profile"), dict))
        skills_value = row.get("skills")
        if not isinstance(skills_value, list) or not skills_value:
            raise ContentError(f"enemy {key} requires a non-empty skills list")
        for skill_key in skills_value:
            _non_empty(skill_key, f"enemy {key} has an invalid skill reference")
            enemy_skill_keys.add(skill_key)
            skill = bundle.get("skill", skill_key, include_locked=False)
            if skill is None or skill.get("owner_type") != "enemy":
                raise ContentError(f"enemy {key} references unavailable enemy skill {skill_key}")

        reward_refs = row.get("reward_refs", [])
        if not isinstance(reward_refs, list) or any(not isinstance(ref, str) or not ref for ref in reward_refs):
            raise ContentError(f"enemy {key} reward_refs must be a string list")
        for reward_key in reward_refs:
            if not bundle.has("reward", reward_key, include_locked=False):
                raise ContentError(f"enemy {key} references unavailable reward {reward_key}")

        profile = row.get("combat_profile")
        if not isinstance(profile, dict):
            continue
        profile_count += 1
        _non_empty(profile.get("random_pool_key"), f"enemy {key} requires combat_profile.random_pool_key")
        reward = profile.get("reward", {})
        _validate_reward_map(reward, f"enemy {key} combat reward")
        party = profile.get("party_profile", {})
        if not isinstance(party, dict):
            raise ContentError(f"enemy {key} party_profile must be an object")
        if "reward" in party:
            _validate_reward_map(party["reward"], f"enemy {key} party reward")
        drop_pool = profile.get("drop_pool_key")
        if drop_pool is not None:
            _non_empty(drop_pool, f"enemy {key} drop_pool_key")
            if not bundle.has("reward", drop_pool, include_locked=False):
                raise ContentError(f"enemy {key} references unavailable drop pool {drop_pool}")
            reward_pool_outcomes(drop_pool, bundle)
            drop_pool_keys.add(drop_pool)

    if enemy_skill_keys - skill_keys:
        raise ContentError(f"enemy skills are not registered: {sorted(enemy_skill_keys - skill_keys)}")

    encounter_count = 0
    candidate_count = 0
    for row in encounters:
        key = _record_key(row, "encounter pool")
        _labels(row, f"encounter pool {key}")
        _status(row, key, "encounter pool")
        candidates = row.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            raise ContentError(f"encounter pool {key} requires candidates")
        seen: set[str] = set()
        total_weight = 0
        for candidate in candidates:
            if not isinstance(candidate, dict):
                raise ContentError(f"encounter pool {key} has a malformed candidate")
            enemy_key = candidate.get("enemy_key")
            _non_empty(enemy_key, f"encounter pool {key} candidate enemy_key")
            if enemy_key not in active_enemy_keys:
                raise ContentError(f"encounter pool {key} references unavailable enemy {enemy_key}")
            if enemy_key in seen:
                raise ContentError(f"encounter pool {key} contains duplicate enemy {enemy_key}")
            seen.add(enemy_key)
            weight = candidate.get("weight")
            _positive_int(weight, f"encounter pool {key} candidate weight")
            total_weight += weight
            candidate_count += 1
        if total_weight <= 0:
            raise ContentError(f"encounter pool {key} has no positive candidate weight")
        encounter_count += 1

    consumed_pools: set[str] = set()
    for mode in bundle.list("exploration_mode", include_locked=False):
        pool_key = mode.get("enemy_pool_key")
        if pool_key is None:
            continue
        _non_empty(pool_key, f"exploration {mode.get('key')} enemy_pool_key")
        if not bundle.has("encounter_pool", pool_key, include_locked=False):
            raise ContentError(f"exploration {mode.get('key')} references unavailable encounter pool {pool_key}")
        consumed_pools.add(pool_key)

    for source in bundle.list("source", include_locked=False):
        for channel in source.get("channels", []):
            if not isinstance(channel, dict) or channel.get("operation") != "battle.claim":
                continue
            reference = channel.get("reference")
            _non_empty(reference, f"source {source.get('key')} battle reference")
            if not bundle.has("reward", reference, include_locked=False):
                raise ContentError(f"source {source.get('key')} references unavailable battle reward {reference}")
            if not str(reference).startswith("reward_pool.enemy."):
                raise ContentError(f"source {source.get('key')} battle reference is not an enemy pool")
            reward_pool_outcomes(reference, bundle)

    return {
        "enemies": len(enemies),
        "enemy_profiles": profile_count,
        "encounters": encounter_count,
        "candidates": candidate_count,
        "drop_pools": len(drop_pool_keys),
        "consumed_encounters": len(consumed_pools),
        "enemy_skills": len(enemy_skill_keys),
    }


def _validate_requirements(value: Any, bundle: ContentBundle, key: str) -> None:
    if not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], dict):
        raise ContentError(f"enemy {key} requires one structured requirement")
    requirement = value[0]
    kind = requirement.get("type", "realm" if "realm_key" in requirement else "stage_min")
    if kind not in _REQUIREMENT_TYPES:
        raise ContentError(f"enemy {key} has unsupported requirement type {kind!r}")
    if kind == "realm":
        realm_key = requirement.get("realm_key")
        _non_empty(realm_key, f"enemy {key} requirement realm_key")
        realm = bundle.get("realm", realm_key, include_locked=False)
        if realm is None:
            raise ContentError(f"enemy {key} references unavailable realm {realm_key}")
        layer = requirement.get("min_layer")
        _positive_int(layer, f"enemy {key} requirement min_layer")
        if layer < int(realm.get("layer_min", 1)) or layer > int(realm.get("layer_max", 1)):
            raise ContentError(f"enemy {key} requirement layer is outside realm {realm_key}")
    else:
        _non_empty(requirement.get("stage"), f"enemy {key} requirement stage")


def _validate_stats(value: Any, key: str, *, require_agility: bool) -> None:
    if not isinstance(value, dict):
        raise ContentError(f"enemy {key} stats must be an object")
    fields = ("hp", "attack", "initiative", "agility") if require_agility else ("hp", "attack", "initiative")
    for field in fields:
        amount = value.get(field)
        if isinstance(amount, bool) or not isinstance(amount, int) or amount < 0:
            raise ContentError(f"enemy {key} stats.{field} must be a non-negative integer")


def _validate_reward_map(value: Any, context: str) -> None:
    if not isinstance(value, dict):
        raise ContentError(f"{context} must be an object")
    for key, amount in value.items():
        if not isinstance(key, str) or not key.strip() or isinstance(amount, bool) or not isinstance(amount, int) or amount < 0:
            raise ContentError(f"{context} contains an invalid reward")


def _record_key(row: dict[str, Any], kind: str) -> str:
    key = row.get("key")
    _non_empty(key, f"{kind} requires a stable key")
    return key


def _labels(row: dict[str, Any], context: str) -> None:
    for field in ("name", "desc"):
        _non_empty(row.get(field), f"{context} requires non-empty {field}")


def _status(row: dict[str, Any], key: str, kind: str) -> None:
    if row.get("status") not in _STATUSES:
        raise ContentError(f"{kind} {key} has invalid status {row.get('status')!r}")


def _non_empty(value: Any, message: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ContentError(message)


def _positive_int(value: Any, message: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ContentError(message)


__all__ = ["validate_combat_content"]
