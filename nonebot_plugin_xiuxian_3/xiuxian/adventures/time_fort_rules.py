"""Contract for the time-fort party secret realm (content-backed)."""

from __future__ import annotations

from .secret_realm_content import node_aliases, node_labels, secret_realm_record

TIME_FORT_KEY = "instance.secret_realm.time_fort"

_RECORD = secret_realm_record(TIME_FORT_KEY)

TIME_FORT_LOCATION = str(_RECORD["location_key"])
TIME_FORT_PARTY_TYPE = str(_RECORD["party_type"])
TIME_FORT_STAMINA_COST = int(_RECORD["stamina_cost"])
TIME_FORT_MIN_MEMBERS = int(_RECORD["min_members"])
TIME_FORT_MAX_MEMBERS = int(_RECORD["max_members"])
TIME_FORT_WEEKLY_LIMIT = int(_RECORD["weekly_limit"])
TIME_FORT_EXPIRY_SECONDS = int(_RECORD["expiry_seconds"])
TIME_FORT_PERMISSION = str(_RECORD["permission"])
TIME_FORT_STORY_FLAG = str(_RECORD["story_flag"])
TIME_FORT_FIRST_REWARD = dict(_RECORD["first_reward"])
TIME_FORT_REPEAT_REWARD = dict(_RECORD["repeat_reward"])
TIME_FORT_STORM_INTERVAL = int(_RECORD["storm_interval_rounds"])
TIME_FORT_STORM_DAMAGE_BP = int(_RECORD["storm_damage_bp"])
TIME_FORT_ENEMY = str(_RECORD["enemy_key"])

TIME_FORT_NODES = tuple(str(node["key"]) for node in _RECORD["nodes"])

TIME_FORT_NODE_LABELS = node_labels(_RECORD)
TIME_FORT_NODE_ALIASES = node_aliases(_RECORD)

TIME_FORT_REALM = str(_RECORD["realm_key"])
TIME_FORT_REALM_LAYER = int(_RECORD["realm_layer"])


def resolve_time_fort_node(value: str) -> str | None:
    return TIME_FORT_NODE_ALIASES.get(value.strip())


__all__ = [
    "TIME_FORT_ENEMY",
    "TIME_FORT_EXPIRY_SECONDS",
    "TIME_FORT_FIRST_REWARD",
    "TIME_FORT_KEY",
    "TIME_FORT_LOCATION",
    "TIME_FORT_MAX_MEMBERS",
    "TIME_FORT_MIN_MEMBERS",
    "TIME_FORT_NODE_LABELS",
    "TIME_FORT_NODES",
    "TIME_FORT_PARTY_TYPE",
    "TIME_FORT_PERMISSION",
    "TIME_FORT_REALM",
    "TIME_FORT_REALM_LAYER",
    "TIME_FORT_REPEAT_REWARD",
    "TIME_FORT_STAMINA_COST",
    "TIME_FORT_STORM_DAMAGE_BP",
    "TIME_FORT_STORM_INTERVAL",
    "TIME_FORT_STORY_FLAG",
    "TIME_FORT_WEEKLY_LIMIT",
    "resolve_time_fort_node",
]
