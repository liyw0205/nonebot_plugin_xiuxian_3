"""Contract for the void-ruins party secret realm (content-backed)."""

from __future__ import annotations

from .secret_realm_content import node_aliases, node_labels, secret_realm_record

VOID_RUINS_KEY = "instance.secret_realm.void_ruins"

_RECORD = secret_realm_record(VOID_RUINS_KEY)

VOID_RUINS_LOCATION = str(_RECORD["location_key"])
VOID_RUINS_PARTY_TYPE = str(_RECORD["party_type"])
VOID_RUINS_STAMINA_COST = int(_RECORD["stamina_cost"])
VOID_RUINS_ANCHOR_LOCK = int(_RECORD["anchor_lock"])
VOID_RUINS_MIN_MEMBERS = int(_RECORD["min_members"])
VOID_RUINS_MAX_MEMBERS = int(_RECORD["max_members"])
VOID_RUINS_WEEKLY_LIMIT = int(_RECORD["weekly_limit"])
VOID_RUINS_EXPIRY_SECONDS = int(_RECORD["expiry_seconds"])
VOID_RUINS_ROUTE_PERMISSION = str(_RECORD["permission"])
VOID_RUINS_CODEX = str(_RECORD["codex_entry_key"])
VOID_RUINS_REPEAT_REWARD = dict(_RECORD["repeat_reward"])

VOID_RUINS_NODES = tuple(str(node["key"]) for node in _RECORD["nodes"])

VOID_RUINS_NODE_LABELS = node_labels(_RECORD)
VOID_RUINS_NODE_ALIASES = node_aliases(_RECORD)

VOID_RUINS_ENEMIES = {
    (str(node["key"]), False): str(node["enemy_key"])
    for node in _RECORD["nodes"]
    if node.get("enemy_key")
}
VOID_RUINS_ENEMIES.update(
    {
        (str(node["key"]), True): str(node["unstable_enemy_key"])
        for node in _RECORD["nodes"]
        if node.get("unstable_enemy_key")
    }
)

VOID_RUINS_REALM = str(_RECORD["realm_key"])
VOID_RUINS_REALM_LAYER = int(_RECORD["realm_layer"])


def resolve_void_ruins_node(value: str) -> str | None:
    return VOID_RUINS_NODE_ALIASES.get(value.strip())


__all__ = [
    "VOID_RUINS_ANCHOR_LOCK",
    "VOID_RUINS_CODEX",
    "VOID_RUINS_ENEMIES",
    "VOID_RUINS_EXPIRY_SECONDS",
    "VOID_RUINS_KEY",
    "VOID_RUINS_LOCATION",
    "VOID_RUINS_MAX_MEMBERS",
    "VOID_RUINS_MIN_MEMBERS",
    "VOID_RUINS_NODES",
    "VOID_RUINS_NODE_LABELS",
    "VOID_RUINS_PARTY_TYPE",
    "VOID_RUINS_REALM",
    "VOID_RUINS_REALM_LAYER",
    "VOID_RUINS_REPEAT_REWARD",
    "VOID_RUINS_ROUTE_PERMISSION",
    "VOID_RUINS_STAMINA_COST",
    "VOID_RUINS_WEEKLY_LIMIT",
    "resolve_void_ruins_node",
]
