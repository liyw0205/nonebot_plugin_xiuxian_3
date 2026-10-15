"""Contract for the solo demon-abyss secret realm (content-backed)."""

from __future__ import annotations

import hashlib

from .secret_realm_content import node_aliases, secret_realm_record

DEMON_ABYSS_KEY = "instance.secret_realm.demon_abyss"

_RECORD = secret_realm_record(DEMON_ABYSS_KEY)

DEMON_ABYSS_LABEL = str(_RECORD["label"])
DEMON_ABYSS_LOCATION = str(_RECORD["location_key"])
DEMON_ABYSS_REQUIRED_FLAG = str(_RECORD["required_flag"])
DEMON_ABYSS_STAMINA_COST = int(_RECORD["stamina_cost"])
DEMON_ABYSS_QUOTA_LIMIT = int(_RECORD["quota_limit"])
DEMON_ABYSS_EXPIRY_SECONDS = int(_RECORD["expiry_seconds"])
DEMON_ABYSS_RISK_BASE_BP = int(_RECORD["risk_base_bp"])
DEMON_ABYSS_RISK_MODIFIER_BP = int(_RECORD["risk_modifier_bp"])

DEMON_ABYSS_NODES = tuple(str(node["key"]) for node in _RECORD["nodes"])
DEMON_ABYSS_NODE_ALIASES = node_aliases(_RECORD)
DEMON_ABYSS_REALM_ALIASES = {
    DEMON_ABYSS_KEY: DEMON_ABYSS_KEY,
    **{
        alias: DEMON_ABYSS_KEY
        for alias in (*_RECORD.get("aliases", ()), DEMON_ABYSS_LABEL)
    },
}
DEMON_ABYSS_ENEMIES = {
    str(node["key"]): str(node["enemy_key"])
    for node in _RECORD["nodes"]
    if node.get("enemy_key")
}
DEMON_ABYSS_FIRST_REWARD = dict(_RECORD["first_reward"])
DEMON_ABYSS_REPEAT_REWARD = dict(_RECORD["repeat_reward"])


def resolve_demon_abyss(value: str) -> str | None:
    return DEMON_ABYSS_REALM_ALIASES.get(value.strip())


def resolve_demon_abyss_node(value: str) -> str | None:
    return DEMON_ABYSS_NODE_ALIASES.get(value.strip())


def demon_abyss_risk_roll_bp(seed: str) -> int:
    digest = hashlib.blake2b(seed.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big") % 10_000


def demon_abyss_risk_applies(roll_bp: int, risk_bp: int) -> bool:
    return 0 <= int(roll_bp) < max(0, min(10_000, int(risk_bp)))


__all__ = [
    "DEMON_ABYSS_ENEMIES",
    "DEMON_ABYSS_EXPIRY_SECONDS",
    "DEMON_ABYSS_FIRST_REWARD",
    "DEMON_ABYSS_KEY",
    "DEMON_ABYSS_LABEL",
    "DEMON_ABYSS_LOCATION",
    "DEMON_ABYSS_NODES",
    "DEMON_ABYSS_QUOTA_LIMIT",
    "DEMON_ABYSS_REPEAT_REWARD",
    "DEMON_ABYSS_REQUIRED_FLAG",
    "DEMON_ABYSS_RISK_BASE_BP",
    "DEMON_ABYSS_RISK_MODIFIER_BP",
    "DEMON_ABYSS_STAMINA_COST",
    "demon_abyss_risk_roll_bp",
    "demon_abyss_risk_applies",
    "resolve_demon_abyss",
    "resolve_demon_abyss_node",
]
