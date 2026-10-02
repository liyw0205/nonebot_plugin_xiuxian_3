"""Frozen rules for the six-node party secret realm."""

from __future__ import annotations

from dataclasses import dataclass


BOUNDARY_RIFT_KEY = "instance.secret_realm.boundary_rift"
BOUNDARY_RIFT_LOCATION = "cave.boundary_realm"
BOUNDARY_RIFT_PARTY_TYPE = "secret_realm_boundary"
BOUNDARY_RIFT_NODES = (
    "rift_approach",
    "shattered_path",
    "cross_realm_sentinel",
    "soul_current",
    "boundary_watcher",
    "rift_seal",
)
BOUNDARY_RIFT_ENEMIES = {
    "cross_realm_sentinel": "enemy.cross_realm_sentinel",
    "boundary_watcher": "enemy.boundary_watcher",
}
BOUNDARY_RIFT_STAMINA_COST = 30
BOUNDARY_RIFT_TICKET = "item.soul_crystal"
BOUNDARY_RIFT_TICKET_COST = 1
BOUNDARY_RIFT_WEEKLY_LIMIT = 1
BOUNDARY_RIFT_EXPIRY_SECONDS = 60 * 60
BOUNDARY_RIFT_FIRST_REWARD = {"item.soul_crystal": 1}
BOUNDARY_RIFT_REPEAT_REWARD = {"item.soul_crystal": 1}


@dataclass(frozen=True, slots=True)
class BoundaryRiftNode:
    key: str
    label: str
    enemy_key: str | None = None


BOUNDARY_RIFT_NODE_DEFINITIONS = (
    BoundaryRiftNode("rift_approach", "裂隙入口"),
    BoundaryRiftNode("shattered_path", "破碎岔路"),
    BoundaryRiftNode("cross_realm_sentinel", "跨界哨卫", BOUNDARY_RIFT_ENEMIES["cross_realm_sentinel"]),
    BoundaryRiftNode("soul_current", "神魂潮汐"),
    BoundaryRiftNode("boundary_watcher", "界隙守望者", BOUNDARY_RIFT_ENEMIES["boundary_watcher"]),
    BoundaryRiftNode("rift_seal", "裂隙封印"),
)

BOUNDARY_RIFT_ALIASES = {
    "rift_approach": "rift_approach",
    "裂隙入口": "rift_approach",
    "shattered_path": "shattered_path",
    "破碎岔路": "shattered_path",
    "cross_realm_sentinel": "cross_realm_sentinel",
    "跨界哨卫": "cross_realm_sentinel",
    "soul_current": "soul_current",
    "神魂潮汐": "soul_current",
    "boundary_watcher": "boundary_watcher",
    "界隙守望者": "boundary_watcher",
    "rift_seal": "rift_seal",
    "裂隙封印": "rift_seal",
}


def resolve_boundary_rift_node(value: str) -> str | None:
    return BOUNDARY_RIFT_ALIASES.get(value.strip())


__all__ = [
    "BOUNDARY_RIFT_ENEMIES",
    "BOUNDARY_RIFT_EXPIRY_SECONDS",
    "BOUNDARY_RIFT_FIRST_REWARD",
    "BOUNDARY_RIFT_KEY",
    "BOUNDARY_RIFT_LOCATION",
    "BOUNDARY_RIFT_NODE_DEFINITIONS",
    "BOUNDARY_RIFT_NODES",
    "BOUNDARY_RIFT_PARTY_TYPE",
    "BOUNDARY_RIFT_REPEAT_REWARD",
    "BOUNDARY_RIFT_STAMINA_COST",
    "BOUNDARY_RIFT_TICKET",
    "BOUNDARY_RIFT_TICKET_COST",
    "BOUNDARY_RIFT_WEEKLY_LIMIT",
    "resolve_boundary_rift_node",
]
