"""Contract for the solo demon-abyss secret realm."""

from __future__ import annotations

import hashlib


DEMON_ABYSS_KEY = "instance.secret_realm.demon_abyss"
DEMON_ABYSS_LABEL = "魔界深渊秘境"
DEMON_ABYSS_LOCATION = "demon.abyss_gate"
DEMON_ABYSS_REQUIRED_FLAG = "access.demon_abyss_gate"
DEMON_ABYSS_STAMINA_COST = 20
DEMON_ABYSS_QUOTA_LIMIT = 1
DEMON_ABYSS_EXPIRY_SECONDS = 60 * 60
DEMON_ABYSS_RISK_BASE_BP = 0
DEMON_ABYSS_RISK_MODIFIER_BP = 50

DEMON_ABYSS_NODES = (
    "abyss_threshold",
    "pollution_seep",
    "echo_guardian",
    "abyss_heart",
)
DEMON_ABYSS_NODE_ALIASES = {
    "深渊门": "abyss_threshold",
    "abyss_threshold": "abyss_threshold",
    "污染渗流": "pollution_seep",
    "pollution_seep": "pollution_seep",
    "残响守卫": "echo_guardian",
    "echo_guardian": "echo_guardian",
    "深渊之心": "abyss_heart",
    "abyss_heart": "abyss_heart",
}
DEMON_ABYSS_REALM_ALIASES = {
    DEMON_ABYSS_KEY: DEMON_ABYSS_KEY,
    "魔界深渊": DEMON_ABYSS_KEY,
    "魔界深渊秘境": DEMON_ABYSS_KEY,
}
DEMON_ABYSS_ENEMIES = {
    "echo_guardian": "enemy.demon_abyss_echo_guardian",
    "abyss_heart": "enemy.demon_abyss_heart",
}
DEMON_ABYSS_FIRST_REWARD = {
    "faction_reputation.demon": 20,
    "item.clue.demon_abyss_echo": 1,
    "story.demon_abyss_echo": 1,
}
DEMON_ABYSS_REPEAT_REWARD = {"item.demon_core": 1}


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
