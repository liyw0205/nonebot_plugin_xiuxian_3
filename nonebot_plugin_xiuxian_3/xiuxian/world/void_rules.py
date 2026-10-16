"""Definitions and deterministic rules for void navigation."""

from __future__ import annotations


import math
from hashlib import blake2b

from ..content import ContentBundle, bundled_content
from .void_models import VoidRouteDefinition

VOID_ROUTE_DURATION_SECONDS = 30 * 60
VOID_ROUTE_STORM_CHANCE_BP = 1500
VOID_INSTABILITY_SECONDS = 48 * 60 * 60

def resolve_void_route(
    value: str, content: ContentBundle | None = None, *, include_locked: bool = False
) -> str | None:
    normalized = value.strip()
    bundle = content or bundled_content()
    for row in bundle.list("world_void_route", include_locked=include_locked):
        if normalized in {row["key"], row["name"], *row["aliases"]}:
            return str(row["key"])
    return None


def void_route_definition(
    route_key: str, content: ContentBundle | None = None
) -> VoidRouteDefinition:
    bundle = content or bundled_content()
    row = bundle.get("world_void_route", route_key, include_locked=False)
    if row is None:
        raise KeyError(route_key)
    return VoidRouteDefinition(
        key=route_key,
        label=str(row["name"]),
        duration_seconds=int(row["duration_seconds"]),
        stamina_cost=int(row["stamina"]),
        anchor_cost=int(row["anchor_cost"]),
        random_pool=str(row["random_pool"]),
    )


def navigation_anchor_cost(route_anchor_cost: int, resistance_bp: int, unstable: bool) -> int:
    resistance = max(0, min(7500, int(resistance_bp)))
    cost = max(1, math.ceil(int(route_anchor_cost) * (20_000 - resistance) / 20_000))
    if unstable:
        cost = math.ceil(cost * 13_000 / 10_000)
    return max(1, cost)


def void_route_roll_bp(operation_id: str) -> int:
    return int.from_bytes(blake2b(operation_id.encode("utf-8"), digest_size=2).digest(), "big") % 10_000


__all__ = [
    "VOID_INSTABILITY_SECONDS",
    "VOID_ROUTE_STORM_CHANCE_BP",
    "navigation_anchor_cost",
    "resolve_void_route",
    "void_route_definition",
    "void_route_roll_bp",
]
