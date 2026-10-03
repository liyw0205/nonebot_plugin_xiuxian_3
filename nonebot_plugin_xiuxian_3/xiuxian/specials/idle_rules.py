"""Content-backed rules for server-timed idle assignments."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..content import ContentBundle, ContentError, bundled_content
from ..rewards.rules import (
    RewardContentError,
    local_reputation_maximum,
    reward_pool_map,
    reward_pool_outcomes,
)


MAX_CLAIM_EXTENSION_SECONDS = 24 * 60 * 60
ABSOLUTE_MAX_SECONDS = 48 * 60 * 60
CANCEL_WINDOW_SECONDS = 60


@dataclass(frozen=True, slots=True)
class IdleRouteDefinition:
    key: str
    label: str
    description: str
    aliases: tuple[str, ...]
    duration_seconds: int
    stamina_cost: int
    energy_cost: int
    daily_limit: int
    pool_key: str
    fallback_pool_key: str
    required_stage: str
    required_location: str | None
    required_local_reputation: tuple[tuple[str, int], ...]
    required_residence: bool
    required_tool_keys: tuple[str, ...]
    facility_kind: str | None
    durability_cost_bp: int


_STAGE_ORDER = {
    "new_user": 0,
    "mortal": 1,
    "seeker": 2,
    "cultivator": 3,
}
_IDLE_REWARD_PREFIXES = ("item.", "local.", "codex.")


def idle_route_definitions(content: ContentBundle | None = None) -> dict[str, IdleRouteDefinition]:
    bundle = content or bundled_content()
    definitions: dict[str, IdleRouteDefinition] = {}
    selectors: dict[str, str] = {}
    for row in bundle.list("livelihood", include_locked=False):
        if row.get("record_type") != "idle_route":
            continue
        definition = _parse_route(row, bundle)
        if definition.key in definitions:
            raise ContentError(f"idle route {definition.key} is duplicated")
        for selector in {definition.key, definition.label, *definition.aliases}:
            if selector in selectors:
                raise ContentError(f"idle route {definition.key} has a duplicate name or alias")
            selectors[selector] = definition.key
        definitions[definition.key] = definition
    return definitions


def idle_route_order(content: ContentBundle | None = None) -> tuple[IdleRouteDefinition, ...]:
    return tuple(idle_route_definitions(content).values())


def resolve_route(value: str | None, content: ContentBundle | None = None) -> IdleRouteDefinition:
    definitions = idle_route_definitions(content)
    selectors = {
        selector: definition
        for definition in definitions.values()
        for selector in (definition.key, definition.label, *definition.aliases)
    }
    try:
        return selectors[(value or "").strip()]
    except KeyError as exc:
        raise ValueError(f"unsupported idle route: {value}") from exc


def reward_for(
    definition: IdleRouteDefinition,
    seed: str,
    *,
    fallback: bool,
    content: ContentBundle | None = None,
) -> dict[str, int]:
    pool_key = definition.fallback_pool_key if fallback else definition.pool_key
    return reward_pool_map(pool_key, seed, content)


def reward_local_reputation_maximums(
    definition: IdleRouteDefinition,
    content: ContentBundle | None = None,
) -> dict[str, int]:
    bundle = content or bundled_content()
    keys = {
        key
        for pool_key in (definition.pool_key, definition.fallback_pool_key)
        for _, outcome in reward_pool_outcomes(pool_key, bundle)
        for key in outcome
        if key.startswith("local.")
    }
    return {key: local_reputation_maximum(key, bundle) for key in keys}


def _parse_route(row: dict[str, Any], bundle: ContentBundle) -> IdleRouteDefinition:
    key = row.get("key")
    name = row.get("name")
    description = row.get("desc")
    if not isinstance(key, str) or not key or not isinstance(name, str) or not name.strip():
        raise ContentError("idle route requires key and name")
    if not isinstance(description, str) or not description.strip():
        raise ContentError(f"idle route {key} requires desc")
    aliases = row.get("aliases")
    if not isinstance(aliases, list) or any(not isinstance(value, str) or not value.strip() for value in aliases):
        raise ContentError(f"idle route {key} aliases must be non-empty strings")

    duration = _positive_integer(row.get("duration_seconds"), key, "duration_seconds")
    daily_limit = _positive_integer(row.get("daily_limit"), key, "daily_limit")
    durability_cost = _non_negative_integer(row.get("durability_cost_bp"), key, "durability_cost_bp")
    costs = row.get("cost")
    if not isinstance(costs, dict) or set(costs) != {"stamina", "energy"}:
        raise ContentError(f"idle route {key} cost requires stamina and energy")
    stamina_cost = _non_negative_integer(costs["stamina"], key, "cost.stamina")
    energy_cost = _non_negative_integer(costs["energy"], key, "cost.energy")

    requirements = row.get("requirements")
    if not isinstance(requirements, dict):
        raise ContentError(f"idle route {key} requirements must be an object")
    required_stage = requirements.get("stage")
    if required_stage not in _STAGE_ORDER:
        raise ContentError(f"idle route {key} has an unsupported stage requirement")
    required_location = requirements.get("location_key")
    if required_location is not None:
        _require_active_record(bundle, "location", required_location, key, "requirements.location_key")
    reputation = requirements.get("local_reputation", {})
    if not isinstance(reputation, dict):
        raise ContentError(f"idle route {key} local_reputation must be an object")
    required_reputation: list[tuple[str, int]] = []
    for reputation_key, minimum in reputation.items():
        try:
            local_reputation_maximum(reputation_key, bundle)
        except (RewardContentError, TypeError) as exc:
            raise ContentError(f"idle route {key} has invalid local reputation reference") from exc
        required_reputation.append(
            (reputation_key, _non_negative_integer(minimum, key, f"requirements.local_reputation.{reputation_key}"))
        )
    required_residence = requirements.get("active_residence", False)
    if not isinstance(required_residence, bool):
        raise ContentError(f"idle route {key} active_residence must be boolean")
    tool_keys = requirements.get("tool_item_keys", [])
    if not isinstance(tool_keys, list) or any(not isinstance(value, str) or not value for value in tool_keys):
        raise ContentError(f"idle route {key} tool_item_keys must be stable item keys")
    for item_key in tool_keys:
        _require_active_record(bundle, "item", item_key, key, "requirements.tool_item_keys")
    facility_kind = requirements.get("facility_kind")
    if facility_kind is not None and (not isinstance(facility_kind, str) or not facility_kind):
        raise ContentError(f"idle route {key} facility_kind must be a non-empty string")
    if tool_keys and not facility_kind:
        raise ContentError(f"idle route {key} tool routes require a facility kind")

    pool_key = _required_string(row.get("reward_pool_key"), key, "reward_pool_key")
    fallback_pool_key = _required_string(row.get("fallback_reward_pool_key"), key, "fallback_reward_pool_key")
    _validate_pool(pool_key, bundle, key, fallback=False)
    _validate_pool(fallback_pool_key, bundle, key, fallback=True)
    return IdleRouteDefinition(
        key=key,
        label=name.strip(),
        description=description.strip(),
        aliases=tuple(value.strip() for value in aliases),
        duration_seconds=duration,
        stamina_cost=stamina_cost,
        energy_cost=energy_cost,
        daily_limit=daily_limit,
        pool_key=pool_key,
        fallback_pool_key=fallback_pool_key,
        required_stage=str(required_stage),
        required_location=required_location,
        required_local_reputation=tuple(required_reputation),
        required_residence=required_residence,
        required_tool_keys=tuple(tool_keys),
        facility_kind=facility_kind,
        durability_cost_bp=durability_cost,
    )


def _validate_pool(pool_key: str, bundle: ContentBundle, route_key: str, *, fallback: bool) -> None:
    try:
        outcomes = reward_pool_outcomes(pool_key, bundle)
    except (RewardContentError, KeyError) as exc:
        raise ContentError(f"idle route {route_key} references invalid reward pool {pool_key}") from exc
    if fallback and len(outcomes) != 1:
        raise ContentError(f"idle route {route_key} fallback pool must have one outcome")
    if any(not rewards for _, rewards in outcomes):
        raise ContentError(f"idle route {route_key} reward pools cannot contain empty outcomes")
    for _, rewards in outcomes:
        if any(key != "spirit_stones" and not key.startswith(_IDLE_REWARD_PREFIXES) for key in rewards):
            raise ContentError(f"idle route {route_key} reward pool contains a forbidden reward")


def _require_active_record(
    bundle: ContentBundle,
    kind: str,
    key: Any,
    route_key: str,
    field: str,
) -> None:
    if not isinstance(key, str) or not key:
        raise ContentError(f"idle route {route_key} {field} must be a stable key")
    try:
        bundle.require(kind, key, include_locked=False)
    except KeyError as exc:
        raise ContentError(f"idle route {route_key} references inactive {kind} {key}") from exc


def _required_string(value: Any, route_key: str, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ContentError(f"idle route {route_key} requires {field}")
    return value


def _positive_integer(value: Any, route_key: str, field: str) -> int:
    result = _non_negative_integer(value, route_key, field)
    if result == 0:
        raise ContentError(f"idle route {route_key} {field} must be positive")
    return result


def _non_negative_integer(value: Any, route_key: str, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ContentError(f"idle route {route_key} {field} must be a non-negative integer")
    return value


__all__ = [
    "ABSOLUTE_MAX_SECONDS",
    "CANCEL_WINDOW_SECONDS",
    "MAX_CLAIM_EXTENSION_SECONDS",
    "IdleRouteDefinition",
    "idle_route_definitions",
    "idle_route_order",
    "reward_local_reputation_maximums",
    "resolve_route",
    "reward_for",
]
