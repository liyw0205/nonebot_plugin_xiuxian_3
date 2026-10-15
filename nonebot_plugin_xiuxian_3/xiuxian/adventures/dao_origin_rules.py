"""Contract for the dao-origin solo secret realm (content-backed)."""

from __future__ import annotations

from .secret_realm_content import node_aliases, node_labels, secret_realm_record

DAO_ORIGIN_KEY = "instance.secret_realm.dao_origin"

_RECORD = secret_realm_record(DAO_ORIGIN_KEY)

DAO_ORIGIN_LOCATION = str(_RECORD["location_key"])
DAO_ORIGIN_PERMISSION = str(_RECORD["permission"])
DAO_ORIGIN_STAMINA_COST = int(_RECORD["stamina_cost"])
DAO_ORIGIN_QUOTA_KEY = str(_RECORD["quota_key"])
DAO_ORIGIN_EXPIRY_SECONDS = int(_RECORD["expiry_seconds"])
DAO_ORIGIN_STORY_FLAG = str(_RECORD["story_flag"])
DAO_ORIGIN_CODEX = str(_RECORD["codex_entry_key"])
DAO_ORIGIN_FIRST_REWARD = dict(_RECORD["first_reward"])
DAO_ORIGIN_REPEAT_REWARD: dict[str, int] = dict(_RECORD["repeat_reward"])

DAO_ORIGIN_NODES = tuple(str(node["key"]) for node in _RECORD["nodes"])
DAO_ORIGIN_NODE_LABELS = node_labels(_RECORD)
DAO_ORIGIN_NODE_ALIASES = node_aliases(_RECORD)


def resolve_dao_origin_node(value: str) -> str | None:
    return DAO_ORIGIN_NODE_ALIASES.get(value.strip())


__all__ = [
    "DAO_ORIGIN_CODEX",
    "DAO_ORIGIN_EXPIRY_SECONDS",
    "DAO_ORIGIN_FIRST_REWARD",
    "DAO_ORIGIN_KEY",
    "DAO_ORIGIN_LOCATION",
    "DAO_ORIGIN_NODE_LABELS",
    "DAO_ORIGIN_NODES",
    "DAO_ORIGIN_PERMISSION",
    "DAO_ORIGIN_QUOTA_KEY",
    "DAO_ORIGIN_REPEAT_REWARD",
    "DAO_ORIGIN_STAMINA_COST",
    "DAO_ORIGIN_STORY_FLAG",
    "resolve_dao_origin_node",
]
