"""Content-backed rules for server-timed idle assignments."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..content import ContentBundle, ContentError, bundled_content
from ..persistence.errors import IdleRouteNotFoundError
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
    required_realm: str | None
    required_layer: int
    required_permit: str | None
    required_project_contribution: tuple[str, int] | None
    required_dao_route: bool
    required_location: str | None
    required_local_reputation: tuple[tuple[str, int], ...]
    required_residence: bool
    required_tool_keys: tuple[str, ...]
    facility_kind: str | None
    durability_cost_bp: int
    required_unlock: str | None = None
    gathering_journal: dict[str, Any] = field(default_factory=dict)
    required_companion_kind: str | None = None
    companion_progress: dict[str, int] = field(default_factory=dict)
    patrol_journal: dict[str, str] = field(default_factory=dict)


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
        raise IdleRouteNotFoundError(f"unsupported idle route: {value}") from exc


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


def reward_ranges(pool_key: str, content: ContentBundle | None = None) -> dict[str, tuple[int, int]]:
    outcomes = reward_pool_outcomes(pool_key, content or bundled_content())
    keys = dict.fromkeys(key for _, reward in outcomes for key in reward)
    return {
        key: (min(reward.get(key, 0) for _, reward in outcomes), max(reward.get(key, 0) for _, reward in outcomes))
        for key in keys
    }


def idle_reward_label(key: str, content: ContentBundle | None = None) -> str:
    bundle = content or bundled_content()
    if key == "spirit_stones":
        return "灵石"
    if key.startswith("item."):
        return bundle.label("item", key)
    if key.startswith("local."):
        return bundle.label("location", key.removeprefix("local.")) + "名望"
    if key.startswith("codex."):
        return bundle.label("codex_entry", key)
    return {"stamina": "体力", "energy": "精力"}[key]


def journal_from_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    if "gathering_journal" not in snapshot:
        return {}
    value = snapshot["gathering_journal"]
    if not isinstance(value, dict):
        raise ValueError("idle snapshot gathering_journal must be an object")
    if not value:
        return {}
    if set(value) != {"start_text", "complete_text", "expired_text", "uses"}:
        raise ValueError("idle snapshot gathering_journal has invalid fields")
    for field in ("start_text", "complete_text", "expired_text"):
        if not isinstance(value[field], str) or not value[field].strip():
            raise ValueError(f"idle snapshot gathering_journal.{field} must be non-empty text")
    uses = value["uses"]
    if not isinstance(uses, list) or not uses:
        raise ValueError("idle snapshot gathering_journal.uses must be a non-empty list")
    for use in uses:
        if (
            not isinstance(use, dict) or set(use) != {"recipe_key", "label", "command"}
            or any(not isinstance(text, str) or not text.strip() for text in use.values())
        ):
            raise ValueError("idle snapshot gathering_journal.uses contains an invalid recipe")
    return dict(value)


def patrol_journal_from_snapshot(snapshot: dict[str, Any]) -> dict[str, str]:
    value = snapshot.get("patrol_journal")
    if value is None or value == {}:
        return {}
    if not isinstance(value, dict) or set(value) != {"start_text", "complete_text", "expired_text"}:
        raise ValueError("idle snapshot patrol_journal has invalid fields")
    if any(not isinstance(value[field], str) or not value[field].strip() for field in value):
        raise ValueError("idle snapshot patrol_journal text must be non-empty")
    return {str(field): str(value[field]) for field in value}


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
    realm_requirement = requirements.get("realm")
    required_realm: str | None = None
    required_layer = 0
    if realm_requirement is not None:
        if (
            not isinstance(realm_requirement, dict)
            or set(realm_requirement) != {"key", "min_layer"}
        ):
            raise ContentError(
                f"idle route {key} requirements.realm requires key and min_layer"
            )
        realm_key = realm_requirement.get("key")
        _require_active_record(bundle, "realm", realm_key, key, "requirements.realm.key")
        layer = _positive_integer(
            realm_requirement.get("min_layer"), key, "requirements.realm.min_layer"
        )
        if layer > 10:
            raise ContentError(
                f"idle route {key} requirements.realm.min_layer must be at most 10"
            )
        required_realm = str(realm_key)
        required_layer = layer
    required_permit = requirements.get("required_permit")
    if required_permit is not None:
        if not isinstance(required_permit, str) or not required_permit:
            raise ContentError(
                f"idle route {key} requirements.required_permit must be a stable key"
            )
        _require_active_record(
            bundle, "trade_permit", required_permit, key, "requirements.required_permit"
        )
    project_requirement = requirements.get("project_contribution")
    required_project_contribution: tuple[str, int] | None = None
    if project_requirement is not None:
        if (
            not isinstance(project_requirement, dict)
            or set(project_requirement) != {"project_key", "min_points"}
        ):
            raise ContentError(
                f"idle route {key} requirements.project_contribution requires "
                "project_key and min_points"
            )
        project_key = project_requirement.get("project_key")
        if not isinstance(project_key, str) or not project_key:
            raise ContentError(
                f"idle route {key} requirements.project_contribution.project_key "
                "must be a stable key"
            )
        project = bundle.get("livelihood", project_key, include_locked=False)
        if project is None or project.get("record_type") != "public_project":
            raise ContentError(
                f"idle route {key} references inactive public project {project_key}"
            )
        min_points = _positive_integer(
            project_requirement.get("min_points"),
            key,
            "requirements.project_contribution.min_points",
        )
        required_project_contribution = (project_key, min_points)
    required_dao_route = requirements.get("dao_route", False)
    if not isinstance(required_dao_route, bool):
        raise ContentError(f"idle route {key} requirements.dao_route must be boolean")
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
    required_unlock = requirements.get("codex_unlock")
    if required_unlock is not None:
        if (
            not isinstance(required_unlock, str)
            or not required_unlock
            or not bundle.has("codex_unlock", required_unlock, include_locked=False)
        ):
            raise ContentError(f"idle route {key} references an unknown codex unlock")

    companion_kind = requirements.get("companion_kind")
    if companion_kind is not None:
        if companion_kind not in {"beast", "mount"}:
            raise ContentError(f"idle route {key} has an unsupported companion kind")
        if not any(
            row.get("kind") == companion_kind and row.get("status") in {"active", "open"}
            for row in bundle.list("companion", include_locked=False)
        ):
            raise ContentError(f"idle route {key} has no active companion of the required kind")

    companion_progress = row.get("companion_progress", {})
    if not isinstance(companion_progress, dict) or set(companion_progress) - {"experience", "affinity"}:
        raise ContentError(f"idle route {key} companion_progress has invalid fields")
    progress = {
        field: _non_negative_integer(companion_progress.get(field, 0), key, f"companion_progress.{field}")
        for field in ("experience", "affinity")
    }
    if companion_kind is None and any(progress.values()):
        raise ContentError(f"idle route {key} companion_progress requires companion_kind")
    patrol_journal = _parse_patrol_journal(row.get("patrol_journal"), key, companion_kind)

    pool_key = _required_string(row.get("reward_pool_key"), key, "reward_pool_key")
    fallback_pool_key = _required_string(row.get("fallback_reward_pool_key"), key, "fallback_reward_pool_key")
    _validate_pool(pool_key, bundle, key, fallback=False)
    _validate_pool(fallback_pool_key, bundle, key, fallback=True)
    journal = _parse_gathering_journal(row.get("gathering_journal"), bundle, key, pool_key, fallback_pool_key)
    if journal and required_location is None:
        raise ContentError(f"idle route {key} gathering_journal requires a location")
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
        required_realm=required_realm,
        required_layer=required_layer,
        required_permit=required_permit,
        required_project_contribution=required_project_contribution,
        required_dao_route=required_dao_route,
        required_location=required_location,
        required_local_reputation=tuple(required_reputation),
        required_residence=required_residence,
        required_tool_keys=tuple(tool_keys),
        facility_kind=facility_kind,
        durability_cost_bp=durability_cost,
        required_unlock=required_unlock,
        gathering_journal=journal,
        required_companion_kind=companion_kind,
        companion_progress=progress,
        patrol_journal=patrol_journal,
    )


def _parse_patrol_journal(value: Any, route_key: str, companion_kind: str | None) -> dict[str, str]:
    if value is None:
        if companion_kind is not None:
            raise ContentError(f"idle route {route_key} companion routes require patrol_journal")
        return {}
    if companion_kind is None or not isinstance(value, dict) or set(value) != {"start_text", "complete_text", "expired_text"}:
        raise ContentError(f"idle route {route_key} patrol_journal has invalid fields")
    if any(not isinstance(value[field], str) or not value[field].strip() for field in value):
        raise ContentError(f"idle route {route_key} patrol_journal text cannot be blank")
    return {field: value[field].strip() for field in value}


def _parse_gathering_journal(
    value: Any, bundle: ContentBundle, key: str, pool_key: str, fallback_pool_key: str,
) -> dict[str, Any]:
    if value is None:
        return {}
    fields = {"start_text", "complete_text", "expired_text", "recipe_keys"}
    if not isinstance(value, dict) or set(value) != fields:
        raise ContentError(f"idle route {key} gathering_journal requires {sorted(fields)}")
    journal = {
        field: _required_string(value[field], key, f"gathering_journal.{field}").strip()
        for field in fields - {"recipe_keys"}
    }
    if not all(journal.values()):
        raise ContentError(f"idle route {key} gathering_journal text cannot be blank")
    recipes = value["recipe_keys"]
    if (
        not isinstance(recipes, list) or not recipes
        or any(not isinstance(recipe, str) or not recipe for recipe in recipes)
        or len(set(recipes)) != len(recipes)
    ):
        raise ContentError(f"idle route {key} gathering_journal.recipe_keys must be unique recipe keys")
    outcomes = reward_pool_outcomes(pool_key, bundle)
    materials = {item for _, reward in outcomes for item in reward if item.startswith("item.")}
    from ..production.rules import recipe_definitions

    definitions = recipe_definitions(bundle)
    uses = []
    for recipe_key in recipes:
        _require_active_record(bundle, "recipe", recipe_key, key, "gathering_journal.recipe_keys")
        recipe = definitions[recipe_key]
        if not materials.intersection(recipe.inputs):
            raise ContentError(f"idle route {key} recipe {recipe_key} does not consume gathered materials")
        uses.append({"recipe_key": recipe_key, "label": recipe.name, "command": f"生产预览 {recipe.name}"})
    if any(any(item.startswith("codex.") for item in reward) for _, reward in reward_pool_outcomes(fallback_pool_key, bundle)):
        raise ContentError(f"idle route {key} gathering fallback cannot grant a complete journal")
    if not all(any(item.startswith("codex.") for item in reward) for _, reward in outcomes):
        raise ContentError(f"idle route {key} full gathering rewards require a journal discovery")
    return {**journal, "uses": uses}


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
    "patrol_journal_from_snapshot",
]
