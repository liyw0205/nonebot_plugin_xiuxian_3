"""Rules for the cloud-boat and cross-realm introduction slice."""

from __future__ import annotations


from dataclasses import dataclass
from typing import Any

from ..content import ContentBundle, ContentError, bundled_content
from ..rewards.rules import RewardGrant, reward_definition

DEMON_INTRO_QUEST = "quest.demon_intro"
DEMON_INTRO_FLAG = "access.demon_abyss_gate"
BEAST_INTRO_QUEST = "quest.beast_intro"
BEAST_INTRO_FLAG = "access.beast_ten_thousand_hills"
ARRAY_HALL_INVITE_FLAG = "array_hall.invite"
ADVANCED_CAVE_PASS = "item.cave_pass_advanced"


@dataclass(frozen=True, slots=True)
class CloudRouteDefinition:
    key: str
    label: str
    destination: str
    duration_seconds: int
    stamina_cost: int
    currency_cost: int
    source_locations: tuple[str, ...]
    required_realm: str
    required_layer: int = 1
    pass_key: str | None = None
    pass_quantity: int = 0
    required_quest: str | None = None


@dataclass(frozen=True, slots=True)
class WorldIntroDefinition:
    """Validated, content-backed definition for a one-shot realm introduction."""

    key: str
    label: str
    description: str
    operation: str
    costs: dict[str, int]
    reward_key: str
    reward: RewardGrant
    access_flag: str
    required_location_key: str
    required_realm_key: str
    required_realm_layer: int
    arrival_route_key: str | None
    required_evidence: dict[str, Any] | None = None
    required_read_component: str | None = None


CLOUD_ROUTES = {
    "route.cloud_to_mist2": CloudRouteDefinition(
        "route.cloud_to_mist2", "云舟·洞天二层", "cave.mist_grotto_2", 5 * 60, 8, 500,
        ("xuantian.cloud_city", "xuantian.floating_boat"), "golden_core", pass_key=ADVANCED_CAVE_PASS, pass_quantity=1,
    ),
    "route.cloud_to_abyss_intro": CloudRouteDefinition(
        "route.cloud_to_abyss_intro", "云舟·魔界引导", "demon.abyss_gate", 5 * 60, 10, 500,
        ("xuantian.cloud_city", "xuantian.floating_boat"), "foundation",
    ),
    "route.cloud_return": CloudRouteDefinition(
        "route.cloud_return", "云舟·返回云城", "xuantian.cloud_city", 3 * 60, 3, 200,
        ("cave.mist_grotto_2", "demon.abyss_gate"), "foundation",
    ),
}

ROUTE_ALIASES = {
    "洞天二层": "route.cloud_to_mist2",
    "云舟洞天二层": "route.cloud_to_mist2",
    "route.cloud_to_mist2": "route.cloud_to_mist2",
    "魔界引导": "route.cloud_to_abyss_intro",
    "云舟魔界引导": "route.cloud_to_abyss_intro",
    "route.cloud_to_abyss_intro": "route.cloud_to_abyss_intro",
    "返回云城": "route.cloud_return",
    "云城": "route.cloud_return",
    "route.cloud_return": "route.cloud_return",
}


def resolve_cloud_route(value: str) -> str | None:
    normalized = value.strip()
    if normalized in CLOUD_ROUTES:
        return normalized
    return ROUTE_ALIASES.get(normalized)


def cloud_route_definition(route_key: str) -> CloudRouteDefinition:
    try:
        return CLOUD_ROUTES[route_key]
    except KeyError as exc:
        raise ValueError(f"unsupported cloud route: {route_key}") from exc


def _positive_int(value: Any, field: str, key: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ContentError(f"{key} {field} must be a positive integer")
    return value


def _required_string(value: Any, field: str, key: str, *, prefix: str | None = None) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContentError(f"{key} {field} must be a non-empty string")
    normalized = value.strip()
    if prefix is not None and not normalized.startswith(prefix):
        raise ContentError(f"{key} {field} must start with {prefix!r}")
    return normalized


def _validate_evidence(raw: Any, key: str, content: ContentBundle) -> dict[str, Any] | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ContentError(f"{key} required_evidence must be an object")
    location_key = _required_string(raw.get("location_key"), "required_evidence.location_key", key)
    location = content.get("location", location_key)
    if location is None:
        raise ContentError(f"{key} required_evidence references unknown location: {location_key}")
    mode_keys = raw.get("mode_keys")
    if not isinstance(mode_keys, list) or not mode_keys or any(
        not isinstance(item, str) or not item.strip() or not item.strip().startswith("explore.")
        for item in mode_keys
    ):
        raise ContentError(f"{key} required_evidence.mode_keys must be a non-empty string list")
    mode_records = content.list("mode")
    if mode_records and any(not content.has("mode", item.strip()) for item in mode_keys):
        raise ContentError(f"{key} required_evidence references an unknown exploration mode")
    status = _required_string(raw.get("status"), "required_evidence.status", key)
    if status not in {"settled", "completed"}:
        raise ContentError(f"{key} required_evidence.status is unsupported: {status}")
    return {
        "location_key": location_key,
        "mode_keys": tuple(item.strip() for item in mode_keys),
        "status": status,
    }


def world_intro_definition(
    key: str,
    content: ContentBundle | None = None,
    *,
    expected_operation: str | None = None,
) -> WorldIntroDefinition:
    """Load and validate one active world-introduction quest.

    Costs, rewards, access flags and all gating references are read from the
    quest record.  No gameplay value is supplied by this module as a fallback.
    """

    bundle = content or bundled_content()
    key = _required_string(key, "key", "world intro")
    try:
        row = bundle.require("quest", key, include_locked=False)
    except KeyError as exc:
        raise ContentError(f"world intro quest is not active: {key}") from exc
    name = _required_string(row.get("name"), "name", key)
    description = _required_string(row.get("desc"), "desc", key)
    status = row.get("status")
    if status not in {"active", "open"}:
        raise ContentError(f"world intro {key} status must be active or open")
    if row.get("claim_policy") != "once_per_player":
        raise ContentError(f"world intro {key} must be once_per_player")
    operation = _required_string(row.get("operation"), "operation", key, prefix="world.")
    if expected_operation is not None and operation != expected_operation:
        raise ContentError(f"world intro {key} belongs to {operation}, not {expected_operation}")
    introduction = row.get("introduction")
    if not isinstance(introduction, dict):
        raise ContentError(f"world intro {key} requires introduction object")

    raw_costs = introduction.get("costs")
    if not isinstance(raw_costs, dict) or not raw_costs:
        raise ContentError(f"world intro {key} introduction.costs must be a non-empty object")
    costs: dict[str, int] = {}
    for raw_key, raw_value in raw_costs.items():
        cost_key = _required_string(raw_key, "introduction.costs key", key)
        if cost_key not in {"currency.spirit_stone", "resource.stamina", "resource.energy"}:
            raise ContentError(f"world intro {key} has unsupported cost: {cost_key}")
        costs[cost_key] = _positive_int(raw_value, f"introduction.costs[{cost_key}]", key)

    reward_key = _required_string(introduction.get("reward_key"), "introduction.reward_key", key, prefix="reward.")
    reward = reward_definition(reward_key, bundle, operation=operation)
    access_flag = _required_string(introduction.get("access_flag"), "introduction.access_flag", key, prefix="access.")
    location_key = _required_string(
        introduction.get("required_location_key"), "introduction.required_location_key", key
    )
    location = bundle.get("location", location_key)
    if location is None:
        raise ContentError(f"world intro {key} references unknown location: {location_key}")
    location_status = location.get("status")
    if location_status not in {"active", "open", "locked", "partial"}:
        raise ContentError(f"world intro {key} references inactive location: {location_key}")
    realm_key = _required_string(
        introduction.get("required_realm_key"), "introduction.required_realm_key", key
    )
    realm = bundle.get("realm", realm_key, include_locked=False)
    if realm is None:
        raise ContentError(f"world intro {key} references unknown or inactive realm: {realm_key}")
    realm_layer = _positive_int(
        introduction.get("required_realm_layer"), "introduction.required_realm_layer", key
    )
    if "arrival_route_key" not in introduction:
        raise ContentError(f"world intro {key} requires introduction.arrival_route_key")
    raw_route_key = introduction["arrival_route_key"]
    if raw_route_key is None:
        route_key = None
    else:
        route_key = _required_string(
            raw_route_key, "introduction.arrival_route_key", key, prefix="route."
        )
        route_row = bundle.get("route", route_key)
        if route_row is not None:
            route_destination = route_row.get("destination") or route_row.get("destination_key")
            if not isinstance(route_destination, str) or not route_destination.strip():
                raise ContentError(f"route {route_key} requires destination")
        elif route_key in CLOUD_ROUTES:
            route_destination = CLOUD_ROUTES[route_key].destination
        else:
            raise ContentError(f"world intro {key} references unknown route: {route_key}")
        if route_destination != location_key:
            raise ContentError(
                f"world intro {key} route {route_key} does not arrive at {location_key}"
            )
    evidence = _validate_evidence(introduction.get("required_evidence"), key, bundle)
    read_component = introduction.get("required_read_component")
    if read_component is not None:
        read_component = _required_string(
            read_component, "introduction.required_read_component", key
        )
    return WorldIntroDefinition(
        key=key,
        label=name,
        description=description,
        operation=operation,
        costs=costs,
        reward_key=reward_key,
        reward=reward,
        access_flag=access_flag,
        required_location_key=location_key,
        required_realm_key=realm_key,
        required_realm_layer=realm_layer,
        arrival_route_key=route_key,
        required_evidence=evidence,
        required_read_component=read_component,
    )


__all__ = [
    "ADVANCED_CAVE_PASS",
    "BEAST_INTRO_FLAG",
    "BEAST_INTRO_QUEST",
    "ARRAY_HALL_INVITE_FLAG",
    "CLOUD_ROUTES",
    "DEMON_INTRO_FLAG",
    "DEMON_INTRO_QUEST",
    "CloudRouteDefinition",
    "WorldIntroDefinition",
    "cloud_route_definition",
    "resolve_cloud_route",
    "world_intro_definition",
]
