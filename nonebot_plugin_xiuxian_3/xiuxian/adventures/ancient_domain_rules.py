"""Route and reward rules for the ancient-domain party instance (content-backed)."""

from __future__ import annotations

from .secret_realm_content import node_aliases, node_labels, secret_realm_record

ANCIENT_DOMAIN_KEY = "instance.secret_realm.ancient_domain"

_RECORD = secret_realm_record(ANCIENT_DOMAIN_KEY)

ANCIENT_DOMAIN_LOCATION = str(_RECORD["location_key"])
ANCIENT_DOMAIN_PARTY_TYPE = str(_RECORD["party_type"])
ANCIENT_DOMAIN_NODES = tuple(str(node["key"]) for node in _RECORD["nodes"])
ANCIENT_DOMAIN_ENEMY = str(_RECORD["enemy_key"])
ANCIENT_DOMAIN_STAMINA_COST = int(_RECORD["stamina_cost"])
ANCIENT_DOMAIN_WEEKLY_LIMIT = int(_RECORD["weekly_limit"])
ANCIENT_DOMAIN_EXPIRY_SECONDS = int(_RECORD["expiry_seconds"])
ANCIENT_DOMAIN_FIRST_REWARD = dict(_RECORD["first_reward"])
ANCIENT_DOMAIN_REPEAT_REWARD = dict(_RECORD["repeat_reward"])
ANCIENT_DOMAIN_ENERGY_SUPPRESSION = int(_RECORD["energy_suppression"])

ANCIENT_DOMAIN_NODE_LABELS = node_labels(_RECORD)
ANCIENT_DOMAIN_NODE_ALIASES = node_aliases(_RECORD)


def resolve_ancient_domain_node(value: str) -> str | None:
    return ANCIENT_DOMAIN_NODE_ALIASES.get(value.strip())


__all__ = [
    "ANCIENT_DOMAIN_ENEMY",
    "ANCIENT_DOMAIN_ENERGY_SUPPRESSION",
    "ANCIENT_DOMAIN_EXPIRY_SECONDS",
    "ANCIENT_DOMAIN_FIRST_REWARD",
    "ANCIENT_DOMAIN_KEY",
    "ANCIENT_DOMAIN_LOCATION",
    "ANCIENT_DOMAIN_NODE_LABELS",
    "ANCIENT_DOMAIN_NODES",
    "ANCIENT_DOMAIN_PARTY_TYPE",
    "ANCIENT_DOMAIN_REPEAT_REWARD",
    "ANCIENT_DOMAIN_STAMINA_COST",
    "ANCIENT_DOMAIN_WEEKLY_LIMIT",
    "resolve_ancient_domain_node",
]
