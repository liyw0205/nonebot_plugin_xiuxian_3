"""Rules for the ancestral-hall solo secret realm (content-backed)."""

from __future__ import annotations

from .secret_realm_content import node_aliases, node_labels, secret_realm_record

ANCESTRAL_HALL_KEY = "instance.secret_realm.ancestral_hall"

_RECORD = secret_realm_record(ANCESTRAL_HALL_KEY)

ANCESTRAL_HALL_LOCATION = str(_RECORD["location_key"])
ANCESTRAL_HALL_NODES = tuple(str(node["key"]) for node in _RECORD["nodes"])
ANCESTRAL_HALL_ENEMY = str(_RECORD["enemy_key"])
ANCESTRAL_HALL_STAMINA_COST = int(_RECORD["stamina_cost"])
ANCESTRAL_HALL_WEEKLY_LIMIT = int(_RECORD["weekly_limit"])
ANCESTRAL_HALL_EXPIRY_SECONDS = int(_RECORD["expiry_seconds"])
ANCESTRAL_HALL_STORY_FLAG = str(_RECORD["story_flag"])
ANCESTRAL_HALL_CODEX_ENTRY = str(_RECORD["codex_entry_key"])

ANCESTRAL_HALL_NODE_LABELS = node_labels(_RECORD)
ANCESTRAL_HALL_NODE_ALIASES = node_aliases(_RECORD)


def resolve_ancestral_hall_node(value: str) -> str | None:
    return ANCESTRAL_HALL_NODE_ALIASES.get(value.strip())


__all__ = [
    "ANCESTRAL_HALL_CODEX_ENTRY",
    "ANCESTRAL_HALL_ENEMY",
    "ANCESTRAL_HALL_EXPIRY_SECONDS",
    "ANCESTRAL_HALL_KEY",
    "ANCESTRAL_HALL_LOCATION",
    "ANCESTRAL_HALL_NODE_ALIASES",
    "ANCESTRAL_HALL_NODE_LABELS",
    "ANCESTRAL_HALL_NODES",
    "ANCESTRAL_HALL_STAMINA_COST",
    "ANCESTRAL_HALL_STORY_FLAG",
    "ANCESTRAL_HALL_WEEKLY_LIMIT",
    "resolve_ancestral_hall_node",
]
