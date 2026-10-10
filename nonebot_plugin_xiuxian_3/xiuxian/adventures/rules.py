"""Data-backed bounty definitions and deterministic weighted selection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from ..content import ContentBundle, ContentError, bundled_content
from ..rewards.rules import local_reputation_maximum, reward_pool_outcomes
from ..specials.dispatch_rules import resolve_dispatch
from ..utils.randomness import deterministic_weighted_choice


_DEFAULT_CONTENT = bundled_content()
_TARGET_KINDS = frozenset(
    {
        "inventory_gain",
        "production_completed",
        "exploration_battle_wins",
        "dispatch_successes",
    }
)
_ACCESS_CONDITION_FIELDS = {
    "subprofession": frozenset({"type", "value"}),
    "intro_flag": frozenset({"type", "value"}),
    "inventory_item": frozenset({"type", "item_key", "quantity"}),
    "permit": frozenset({"type", "permit_key"}),
}


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
        if "required_realm" not in row:
            raise ContentError(f"bounty {key} requires required_realm")
        if required_realm is not None:
            if not isinstance(required_realm, str) or not required_realm:
                raise ContentError(f"bounty {key} required_realm must be a string or null")
            bundle.require("realm", required_realm)
        reputation_key = row.get("reputation_key")
        if not isinstance(reputation_key, str) or not reputation_key.startswith("local."):
            raise ContentError(f"bounty {key} requires a local reputation key")
        local_reputation_maximum(reputation_key, bundle)
        reward_pool_key = row.get("reward_pool_key")
        if not isinstance(reward_pool_key, str) or not reward_pool_key:
            raise ContentError(f"bounty {key} requires reward_pool_key")
        outcomes = _reward_outcomes(
            bundle, reward_pool_key, reputation_key=reputation_key
        )
        if any(not outcome["rewards"] for outcome in outcomes):
            raise ContentError(f"bounty {key} reward pool cannot contain empty rewards")
        path_keys = _string_tuple(row, "path_keys", key)
        for path_key in path_keys:
            bundle.require("path", path_key)
        aliases = _string_tuple(row, "aliases", key)
        access_any = row.get("access_any", [])
        _validate_access_conditions(key, access_any)
        reward_labels = row.get("reward_labels", {})
        if not isinstance(reward_labels, dict) or any(
            not isinstance(label_key, str) or not isinstance(label, str)
            for label_key, label in reward_labels.items()
        ):
            raise ContentError(f"bounty {key} reward_labels must map strings to strings")
        target_kind = row.get("target_kind")
        if not isinstance(target_kind, str) or target_kind not in _TARGET_KINDS:
            raise ContentError(f"bounty {key} has unsupported target_kind: {target_kind}")
        target_amount = _positive_int(row, "target_amount", key)
        duration = _positive_int(row, "duration_seconds", key)
        daily_limit = _positive_int(row, "daily_limit", key)
        weight = _positive_int(row, "weight", key)
        if "required_layer" not in row:
            raise ContentError(f"bounty {key} requires required_layer")
        required_layer = row["required_layer"]
        if isinstance(required_layer, bool) or not isinstance(required_layer, int) or required_layer < 0:
            raise ContentError(f"bounty {key} required_layer must be a non-negative integer")
        if "target_key" not in row:
            raise ContentError(f"bounty {key} requires target_key")
        target_key = row.get("target_key")
        if target_kind == "production_completed":
            if target_key is not None:
                raise ContentError(f"bounty {key} production target_key must be null")
        else:
            if not isinstance(target_key, str) or not target_key:
                raise ContentError(f"bounty {key} requires a target_key")
            if target_kind == "inventory_gain":
                try:
                    bundle.require("item", target_key, include_locked=False)
                except KeyError as exc:
                    raise ContentError(
                        f"bounty {key} references inactive item {target_key}"
                    ) from exc
            elif target_kind == "exploration_battle_wins":
                try:
                    bundle.require("enemy", target_key, include_locked=False)
                except KeyError as exc:
                    raise ContentError(
                        f"bounty {key} references inactive enemy {target_key}"
                    ) from exc
            elif target_kind == "dispatch_successes":
                try:
                    resolved_dispatch = resolve_dispatch(target_key, bundle)
                except ValueError as exc:
                    raise ContentError(
                        f"bounty {key} references unknown dispatch {target_key}"
                    ) from exc
                if resolved_dispatch.key != target_key:
                    raise ContentError(f"bounty {key} target must use a dispatch key")
        if "consume_target" not in row or not isinstance(row["consume_target"], bool):
            raise ContentError(f"bounty {key} consume_target must be a boolean")
        if row["consume_target"] and target_kind != "inventory_gain":
            raise ContentError(f"bounty {key} can only consume an inventory target")
        status = row.get("status")
        if not isinstance(status, str) or status not in {"open", "locked"}:
            raise ContentError(f"bounty {key} status must be open or locked")
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
                reputation_key=reputation_key,
                runtime_status=status,
                required_intro_flag=_optional_string(row, "required_intro_flag", key),
                consume_target=row["consume_target"],
                required_permit=_optional_string(row, "required_permit", key),
                path_keys=path_keys,
                aliases=aliases,
                access_any=tuple(access_any),
                reward_labels=dict(reward_labels),
            )
        )
    return tuple(definitions)


def _validate_access_conditions(bounty_key: str, conditions: Any) -> None:
    if not isinstance(conditions, list) or any(
        not isinstance(condition, dict) for condition in conditions
    ):
        raise ContentError(f"bounty {bounty_key} access_any must be a list of objects")
    for index, condition in enumerate(conditions):
        condition_type = condition.get("type")
        allowed = (
            _ACCESS_CONDITION_FIELDS.get(condition_type)
            if isinstance(condition_type, str)
            else None
        )
        if allowed is None:
            raise ContentError(
                f"bounty {bounty_key} access_any[{index}] has an unsupported type"
            )
        if condition.keys() - allowed:
            raise ContentError(
                f"bounty {bounty_key} access_any[{index}] has unused fields"
            )
        if condition_type in {"subprofession", "intro_flag"}:
            value = condition.get("value")
            if not isinstance(value, str) or not value.strip():
                raise ContentError(
                    f"bounty {bounty_key} access_any[{index}] value must be non-empty"
                )
        elif condition_type == "inventory_item":
            item_key = condition.get("item_key")
            if not isinstance(item_key, str) or not item_key:
                raise ContentError(
                    f"bounty {bounty_key} access_any[{index}] item_key is required"
                )
            quantity = condition.get("quantity", 1)
            if (
                isinstance(quantity, bool)
                or not isinstance(quantity, int)
                or quantity <= 0
            ):
                raise ContentError(
                    f"bounty {bounty_key} access_any[{index}] quantity must be positive"
                )
        elif condition_type == "permit":
            permit_key = condition.get("permit_key")
            if not isinstance(permit_key, str) or not permit_key.strip():
                raise ContentError(
                    f"bounty {bounty_key} access_any[{index}] permit_key is required"
                )


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
    reputation_key: str,
) -> tuple[dict[str, Any], ...]:
    pool = content.require("reward", pool_key, include_locked=False)
    outcomes = reward_pool_outcomes(
        pool_key,
        content,
        reward_key_aliases={"local_reputation": reputation_key},
    )
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
    for weight, rewards in outcomes:
        equipment_available = True
        for reward_key in rewards:
            if reward_key.startswith("item."):
                try:
                    item = content.require("item", reward_key, include_locked=False)
                except KeyError as exc:
                    raise ContentError(
                        f"reward pool {pool_key} references unknown item {reward_key}"
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
            normalized.append({"weight": weight, "rewards": rewards})
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


def bounty_reward_labels(
    definition: BountyDefinition,
    rewards: Mapping[str, int],
    content: ContentBundle | None = None,
) -> dict[str, str]:
    """Freeze the names needed to present one selected bounty reward."""

    bundle = _content(content)
    labels = dict(definition.reward_labels)
    if "local_reputation" in rewards:
        location_key = definition.reputation_key.removeprefix("local.")
        labels.setdefault(
            "local_reputation", f"{bundle.label('location', location_key)}名望"
        )
    for key in rewards:
        if key.startswith("item."):
            labels.setdefault(key, bundle.label("item", key))
        elif key.startswith("codex."):
            labels.setdefault(key, bundle.label("codex_entry", key))
    return labels


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
        reputation_key=definition.reputation_key,
    )
    if not outcomes:
        raise ContentError(f"reward pool {definition.reward_pool_key} has no eligible outcomes")
    selected = deterministic_weighted_choice(
        tuple((int(outcome["weight"]), outcome["rewards"]) for outcome in outcomes),
        seed,
    )
    return {str(key): int(value) for key, value in selected.items()}


def choose_bounty(
    candidates: tuple[BountyDefinition, ...] | list[BountyDefinition],
    *,
    seed: str,
) -> BountyDefinition:
    if not candidates:
        raise ValueError("no eligible bounty candidates")
    return deterministic_weighted_choice(
        tuple((definition.weight, definition) for definition in candidates),
        seed,
    )


__all__ = [
    "DEFINITIONS",
    "BountyDefinition",
    "bounty_definition",
    "bounty_definitions",
    "bounty_reward_labels",
    "choose_bounty",
    "default_content_bundle",
    "meets_realm",
    "realm_rank",
    "resolve_bounty",
    "reward_map",
]
