"""Data-backed bounty definitions and deterministic weighted selection."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Mapping

from ..content import ContentBundle, ContentError, bundled_content


_DEFAULT_CONTENT = bundled_content()
_TARGET_KINDS = frozenset(
    {
        "inventory_gain",
        "production_completed",
        "exploration_battle_wins",
        "dispatch_successes",
    }
)


@dataclass(frozen=True, slots=True)
class BountyDefinition:
    key: str
    label: str
    description: str
    required_realm: str | None
    required_layer: int
    duration_seconds: int
    daily_limit: int
    target_kind: str
    target_key: str | None
    target_amount: int
    reward_pool_key: str
    weight: int
    reputation_key: str
    runtime_status: str
    required_intro_flag: str | None
    consume_target: bool
    required_permit: str | None
    path_keys: tuple[str, ...]
    aliases: tuple[str, ...]
    access_any: tuple[Mapping[str, Any], ...]
    reward_labels: Mapping[str, str]


def _content(content: ContentBundle | None) -> ContentBundle:
    return content or _DEFAULT_CONTENT


def default_content_bundle() -> ContentBundle:
    return _DEFAULT_CONTENT


def bounty_definitions(content: ContentBundle | None = None) -> tuple[BountyDefinition, ...]:
    bundle = _content(content)
    definitions: list[BountyDefinition] = []
    for row in bundle.list("bounty"):
        key = row.get("key")
        name = row.get("name")
        description = row.get("desc")
        if not isinstance(key, str) or not key or not isinstance(name, str) or not name.strip():
            raise ContentError(f"bounty record requires key and name: {row!r}")
        if not isinstance(description, str) or not description.strip():
            raise ContentError(f"bounty {key} requires desc")
        required_realm = row.get("required_realm")
        if required_realm is not None:
            bundle.require("realm", str(required_realm))
        reward_pool_key = row.get("reward_pool_key")
        if not isinstance(reward_pool_key, str) or not reward_pool_key:
            raise ContentError(f"bounty {key} requires reward_pool_key")
        _reward_outcomes(bundle, reward_pool_key)
        path_keys = _string_tuple(row, "path_keys", key)
        for path_key in path_keys:
            bundle.require("path", path_key)
        aliases = _string_tuple(row, "aliases", key)
        access_any = row.get("access_any", [])
        if not isinstance(access_any, list) or any(not isinstance(item, dict) for item in access_any):
            raise ContentError(f"bounty {key} access_any must be a list of objects")
        reward_labels = row.get("reward_labels", {})
        if not isinstance(reward_labels, dict) or any(
            not isinstance(label_key, str) or not isinstance(label, str)
            for label_key, label in reward_labels.items()
        ):
            raise ContentError(f"bounty {key} reward_labels must map strings to strings")
        target_kind = row.get("target_kind")
        if target_kind not in _TARGET_KINDS:
            raise ContentError(f"bounty {key} has unsupported target_kind: {target_kind}")
        target_amount = _positive_int(row, "target_amount", key)
        duration = _positive_int(row, "duration_seconds", key)
        daily_limit = _positive_int(row, "daily_limit", key)
        weight = _positive_int(row, "weight", key)
        required_layer = row.get("required_layer", 0)
        if not isinstance(required_layer, int) or required_layer < 0:
            raise ContentError(f"bounty {key} required_layer must be a non-negative integer")
        target_key = row.get("target_key")
        if target_key is not None and not isinstance(target_key, str):
            raise ContentError(f"bounty {key} target_key must be a string or null")
        definitions.append(
            BountyDefinition(
                key=key,
                label=name.strip(),
                description=description.strip(),
                required_realm=required_realm,
                required_layer=required_layer,
                duration_seconds=duration,
                daily_limit=daily_limit,
                target_kind=str(target_kind),
                target_key=target_key,
                target_amount=target_amount,
                reward_pool_key=reward_pool_key,
                weight=weight,
                reputation_key=str(row.get("reputation_key", "local.xuantian.new_town")),
                runtime_status=str(row.get("status", "locked")),
                required_intro_flag=_optional_string(row, "required_intro_flag", key),
                consume_target=bool(row.get("consume_target", False)),
                required_permit=_optional_string(row, "required_permit", key),
                path_keys=path_keys,
                aliases=aliases,
                access_any=tuple(access_any),
                reward_labels=dict(reward_labels),
            )
        )
    return tuple(definitions)


def _string_tuple(row: Mapping[str, Any], field: str, key: str) -> tuple[str, ...]:
    value = row.get(field, [])
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ContentError(f"bounty {key} {field} must be a string list")
    return tuple(value)


def _optional_string(row: Mapping[str, Any], field: str, key: str) -> str | None:
    value = row.get(field)
    if value is not None and not isinstance(value, str):
        raise ContentError(f"bounty {key} {field} must be a string or null")
    return value


def _positive_int(row: Mapping[str, Any], field: str, key: str) -> int:
    value = row.get(field)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ContentError(f"bounty {key} {field} must be a positive integer")
    return value


def _reward_outcomes(
    content: ContentBundle,
    pool_key: str,
    *,
    path_key: str | None = None,
    realm_key: str | None = None,
    realm_layer: int | None = None,
) -> tuple[dict[str, Any], ...]:
    pool = content.require("reward", pool_key, include_locked=False)
    outcomes = pool.get("outcomes")
    if pool.get("pool_type") != "weighted" or not isinstance(outcomes, list) or not outcomes:
        raise ContentError(f"reward pool {pool_key} must define weighted outcomes")
    equipment_quality_weights = pool.get("equipment_reward_qualities", {})
    if not isinstance(equipment_quality_weights, dict) or any(
        quality not in {"common", "uncommon", "rare", "heaven", "mythic"}
        or isinstance(weight, bool)
        or not isinstance(weight, int)
        or weight <= 0
        for quality, weight in equipment_quality_weights.items()
    ):
        raise ContentError(f"reward pool {pool_key} has invalid equipment_reward_qualities")
    normalized: list[dict[str, Any]] = []
    for index, outcome in enumerate(outcomes):
        if not isinstance(outcome, dict):
            raise ContentError(f"reward pool {pool_key} outcome {index} must be an object")
        weight = outcome.get("weight")
        rewards = outcome.get("rewards")
        if not isinstance(weight, int) or isinstance(weight, bool) or weight <= 0:
            raise ContentError(f"reward pool {pool_key} outcome {index} has invalid weight")
        if not isinstance(rewards, dict) or not rewards:
            raise ContentError(f"reward pool {pool_key} outcome {index} requires rewards")
        if any(not isinstance(key, str) or not isinstance(amount, int) or amount <= 0 for key, amount in rewards.items()):
            raise ContentError(f"reward pool {pool_key} outcome {index} rewards must be positive integer quantities")
        equipment_available = True
        for reward_key in rewards:
            if reward_key.startswith("item."):
                try:
                    item = content.require("item", reward_key, include_locked=False)
                except KeyError as exc:
                    raise ContentError(
                        f"reward pool {pool_key} outcome {index} references unknown item {reward_key}"
                    ) from exc
                if item.get("item_type") in {"weapon", "armor", "accessory"} and (
                    path_key is not None or realm_key is not None
                ):
                    if item.get("path_key") not in {None, path_key} or (
                        realm_key is not None
                        and not _equipment_meets_realm(
                            item, realm_key, int(realm_layer or 0), content
                        )
                    ):
                        equipment_available = False
        if equipment_available:
            normalized.append({"weight": weight, "rewards": dict(rewards)})
    if equipment_quality_weights:
        for item in content.list("item", include_locked=False):
            if item.get("item_type") not in {"weapon", "armor", "accessory"}:
                continue
            quality = item.get("quality")
            if quality not in equipment_quality_weights:
                continue
            if (path_key is not None or realm_key is not None) and item.get("path_key") not in {
                None,
                path_key,
            }:
                continue
            if realm_key is not None and not _equipment_meets_realm(
                item, realm_key, int(realm_layer or 0), content
            ):
                continue
            normalized.append(
                {
                    "weight": int(equipment_quality_weights[quality]),
                    "rewards": {str(item["key"]): 1},
                }
            )
    return tuple(normalized)


def _equipment_meets_realm(
    item: dict[str, Any], realm_key: str, realm_layer: int, content: ContentBundle
) -> bool:
    for requirement in item.get("requirements", []):
        if isinstance(requirement, dict) and requirement.get("type") == "realm":
            required_realm = requirement.get("realm_key")
            required_layer = requirement.get("min_layer", 1)
            return (
                isinstance(required_realm, str)
                and isinstance(required_layer, int)
                and not isinstance(required_layer, bool)
                and meets_realm(
                    realm_key, realm_layer, required_realm, required_layer, content
                )
            )
    return True


DEFINITIONS = {definition.key: definition for definition in bounty_definitions()}


def resolve_bounty(value: str, content: ContentBundle | None = None) -> str | None:
    normalized = value.strip()
    for definition in bounty_definitions(content):
        if normalized == definition.key or normalized == definition.label or normalized in definition.aliases:
            return definition.key
    return None


def bounty_definition(key: str, content: ContentBundle | None = None) -> BountyDefinition:
    try:
        return {definition.key: definition for definition in bounty_definitions(content)}[key]
    except KeyError as exc:
        raise ValueError(f"unsupported bounty: {key}") from exc


def realm_rank(realm_key: str, content: ContentBundle | None = None) -> int:
    row = _content(content).get("realm", realm_key)
    if row is None or not isinstance(row.get("rank"), int):
        return -1
    return int(row["rank"])


def meets_realm(
    realm_key: str,
    layer: int,
    required_realm: str | None,
    required_layer: int,
    content: ContentBundle | None = None,
) -> bool:
    if required_realm is None:
        return True
    return (realm_rank(realm_key, content), int(layer)) >= (
        realm_rank(required_realm, content),
        required_layer,
    )


def reward_map(
    definition: BountyDefinition,
    content: ContentBundle | None = None,
    *,
    seed: str,
    path_key: str | None = None,
    realm_key: str | None = None,
    realm_layer: int | None = None,
) -> dict[str, int]:
    outcomes = _reward_outcomes(
        _content(content),
        definition.reward_pool_key,
        path_key=path_key,
        realm_key=realm_key,
        realm_layer=realm_layer,
    )
    if not outcomes:
        raise ContentError(f"reward pool {definition.reward_pool_key} has no eligible outcomes")
    total_weight = sum(int(item["weight"]) for item in outcomes)
    roll = int.from_bytes(hashlib.blake2b(seed.encode("utf-8"), digest_size=8).digest(), "big") % total_weight
    for outcome in outcomes:
        roll -= int(outcome["weight"])
        if roll < 0:
            return {str(key): int(value) for key, value in outcome["rewards"].items()}
    raise AssertionError("weighted reward selection fell through")


def choose_bounty(
    candidates: tuple[BountyDefinition, ...] | list[BountyDefinition],
    *,
    seed: str,
) -> BountyDefinition:
    if not candidates:
        raise ValueError("no eligible bounty candidates")
    total_weight = sum(item.weight for item in candidates)
    roll = int.from_bytes(hashlib.blake2b(seed.encode("utf-8"), digest_size=8).digest(), "big") % total_weight
    for definition in candidates:
        roll -= definition.weight
        if roll < 0:
            return definition
    raise AssertionError("weighted bounty selection fell through")


__all__ = [
    "DEFINITIONS",
    "BountyDefinition",
    "bounty_definition",
    "bounty_definitions",
    "choose_bounty",
    "default_content_bundle",
    "meets_realm",
    "realm_rank",
    "resolve_bounty",
    "reward_map",
]
