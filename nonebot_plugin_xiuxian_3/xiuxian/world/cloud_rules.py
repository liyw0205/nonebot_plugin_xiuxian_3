"""Versioned rules for the v0.2 cloud-boat and cross-realm introduction slice."""

from __future__ import annotations

from dataclasses import dataclass


CONTENT_VERSION = "content-0.2"
RULE_VERSION = "world-0.2.0"
DEMON_INTRO_QUEST = "quest.demon_intro"
DEMON_INTRO_FLAG = "access.demon_abyss_gate"
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
    content_version: str = CONTENT_VERSION
    rule_version: str = RULE_VERSION


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


__all__ = [
    "ADVANCED_CAVE_PASS",
    "ARRAY_HALL_INVITE_FLAG",
    "CLOUD_ROUTES",
    "CONTENT_VERSION",
    "DEMON_INTRO_FLAG",
    "DEMON_INTRO_QUEST",
    "RULE_VERSION",
    "CloudRouteDefinition",
    "cloud_route_definition",
    "resolve_cloud_route",
]
