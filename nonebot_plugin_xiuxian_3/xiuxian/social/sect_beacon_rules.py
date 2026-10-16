"""Rules for the void beacon extension."""

from __future__ import annotations

from .social_content import sect_beacon_record

_BEACON = sect_beacon_record()

VOID_BEACON_ANCHOR_COST = int(_BEACON["anchor_cost"])
VOID_BEACON_SAND_COST = int(_BEACON["sand_cost"])
VOID_BEACON_BUILD_SECONDS = int(_BEACON["build_seconds"])
VOID_BEACON_MAINTENANCE_ANCHOR_COST = int(_BEACON["maintenance_anchor_cost"])
VOID_BEACON_ROUTE_DISCOUNT = int(_BEACON["route_discount"])


__all__ = [
    "VOID_BEACON_ANCHOR_COST",
    "VOID_BEACON_BUILD_SECONDS",
    "VOID_BEACON_MAINTENANCE_ANCHOR_COST",
    "VOID_BEACON_ROUTE_DISCOUNT",
    "VOID_BEACON_SAND_COST",
]
