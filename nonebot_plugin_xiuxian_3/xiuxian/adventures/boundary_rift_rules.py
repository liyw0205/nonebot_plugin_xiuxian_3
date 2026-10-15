"""Frozen rules for the six-node party secret realm (content-backed)."""

from __future__ import annotations

from dataclasses import dataclass

from .secret_realm_content import node_aliases, secret_realm_record

BOUNDARY_RIFT_KEY = "instance.secret_realm.boundary_rift"

_RECORD = secret_realm_record(BOUNDARY_RIFT_KEY)

BOUNDARY_RIFT_LOCATION = str(_RECORD["location_key"])
BOUNDARY_RIFT_PARTY_TYPE = str(_RECORD["party_type"])
BOUNDARY_RIFT_NODES = tuple(str(node["key"]) for node in _RECORD["nodes"])
BOUNDARY_RIFT_ENEMIES = {
    str(node["key"]): str(node["enemy_key"])
    for node in _RECORD["nodes"]
    if node.get("enemy_key")
}
BOUNDARY_RIFT_STAMINA_COST = int(_RECORD["stamina_cost"])
BOUNDARY_RIFT_TICKET = str(_RECORD["ticket_key"])
BOUNDARY_RIFT_TICKET_COST = int(_RECORD["ticket_quantity"])
BOUNDARY_RIFT_WEEKLY_LIMIT = int(_RECORD["weekly_limit"])
BOUNDARY_RIFT_EXPIRY_SECONDS = int(_RECORD["expiry_seconds"])
BOUNDARY_RIFT_FIRST_REWARD = dict(_RECORD["first_reward"])
BOUNDARY_RIFT_REPEAT_REWARD = dict(_RECORD["repeat_reward"])


@dataclass(frozen=True, slots=True)
class BoundaryRiftNode:
    key: str
    label: str
    enemy_key: str | None = None


BOUNDARY_RIFT_NODE_DEFINITIONS = tuple(
    BoundaryRiftNode(
        str(node["key"]),
        str(node["label"]),
        str(node["enemy_key"]) if node.get("enemy_key") else None,
    )
    for node in _RECORD["nodes"]
)

BOUNDARY_RIFT_ALIASES = node_aliases(_RECORD)


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
