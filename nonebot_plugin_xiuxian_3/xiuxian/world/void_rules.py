"""Versioned definitions and deterministic rules for void navigation."""

from __future__ import annotations

import math
from hashlib import blake2b

from .void_models import VoidRouteDefinition

RULE_VERSION = "world-0.5.0"
CONTENT_VERSION = "content-0.5"
VOID_ROUTE_DURATION_SECONDS = 30 * 60
VOID_ROUTE_STORM_CHANCE_BP = 1500
VOID_INSTABILITY_SECONDS = 48 * 60 * 60

ROUTES = {
    "void.first_route": VoidRouteDefinition("void.first_route", "虚空第一航道", VOID_ROUTE_DURATION_SECONDS, 35, 3, "void.route.void.first_route.v0.5"),
    "void.archive_ruins": VoidRouteDefinition("void.archive_ruins", "虚空档案遗迹", 45 * 60, 40, 4, "void.route.void.archive_ruins.v0.5"),
    "void.sect_fortress": VoidRouteDefinition("void.sect_fortress", "虚空堡垒", VOID_ROUTE_DURATION_SECONDS, 20, 2, "void.route.void.sect_fortress.v0.5"),
    "void.void_market": VoidRouteDefinition("void.void_market", "虚空集市", VOID_ROUTE_DURATION_SECONDS, 10, 2, "void.route.void_market.v0.5"),
}

ALIASES = {
    "第一航道": "void.first_route",
    "虚空第一航道": "void.first_route",
    "void.first_route": "void.first_route",
    "档案遗迹": "void.archive_ruins",
    "虚空档案遗迹": "void.archive_ruins",
    "void.archive_ruins": "void.archive_ruins",
    "虚空堡垒": "void.sect_fortress",
    "void.sect_fortress": "void.sect_fortress",
    "虚空集市": "void.void_market",
    "void.void_market": "void.void_market",
}


def resolve_void_route(value: str) -> str | None:
    return ALIASES.get(value.strip())


def void_route_definition(route_key: str) -> VoidRouteDefinition:
    return ROUTES[route_key]


def navigation_anchor_cost(route_anchor_cost: int, resistance_bp: int, unstable: bool) -> int:
    resistance = max(0, min(7500, int(resistance_bp)))
    cost = max(1, math.ceil(int(route_anchor_cost) * (20_000 - resistance) / 20_000))
    if unstable:
        cost = math.ceil(cost * 13_000 / 10_000)
    return max(1, cost)


def void_route_roll_bp(operation_id: str) -> int:
    return int.from_bytes(blake2b(operation_id.encode("utf-8"), digest_size=2).digest(), "big") % 10_000


__all__ = [
    "CONTENT_VERSION",
    "RULE_VERSION",
    "VOID_INSTABILITY_SECONDS",
    "VOID_ROUTE_STORM_CHANCE_BP",
    "navigation_anchor_cost",
    "resolve_void_route",
    "void_route_definition",
    "void_route_roll_bp",
]
