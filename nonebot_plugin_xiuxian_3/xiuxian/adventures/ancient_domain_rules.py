"""Versioned route and reward rules for the ancient-domain party instance."""

from __future__ import annotations


ANCIENT_DOMAIN_KEY = "instance.secret_realm.ancient_domain"
ANCIENT_DOMAIN_LOCATION = "cave.ancient_domain"
ANCIENT_DOMAIN_PARTY_TYPE = "secret_realm_ancient"
ANCIENT_DOMAIN_NODES = (
    "domain_approach",
    "fractured_gallery",
    "seal_archive",
    "primordial_garden",
    "domain_spring",
    "ancient_domain_lord",
    "weathered_steps",
    "origin_seal",
)
ANCIENT_DOMAIN_ENEMY = "enemy.ancient_domain_lord"
ANCIENT_DOMAIN_STAMINA_COST = 40
ANCIENT_DOMAIN_WEEKLY_LIMIT = 1
ANCIENT_DOMAIN_EXPIRY_SECONDS = 60 * 60
ANCIENT_DOMAIN_CONTENT_VERSION = ""
ANCIENT_DOMAIN_RULE_VERSION = ""
ANCIENT_DOMAIN_FIRST_REWARD = {"item.ancient_fruit": 2}
ANCIENT_DOMAIN_REPEAT_REWARD = {"item.ancient_fruit": 1}
ANCIENT_DOMAIN_ENERGY_SUPPRESSION = 10

ANCIENT_DOMAIN_NODE_LABELS = {
    "domain_approach": "洞天入口",
    "fractured_gallery": "裂痕回廊",
    "seal_archive": "封印古藏",
    "primordial_garden": "太初灵园",
    "domain_spring": "洞天灵泉",
    "ancient_domain_lord": "远古洞天之主",
    "weathered_steps": "风化天阶",
    "origin_seal": "本源封印",
}

ANCIENT_DOMAIN_NODE_ALIASES = {
    **{key: key for key in ANCIENT_DOMAIN_NODES},
    "洞天入口": "domain_approach",
    "裂痕回廊": "fractured_gallery",
    "封印古藏": "seal_archive",
    "太初灵园": "primordial_garden",
    "洞天灵泉": "domain_spring",
    "远古洞天之主": "ancient_domain_lord",
    "风化天阶": "weathered_steps",
    "本源封印": "origin_seal",
}


def resolve_ancient_domain_node(value: str) -> str | None:
    return ANCIENT_DOMAIN_NODE_ALIASES.get(value.strip())


__all__ = [
    "ANCIENT_DOMAIN_CONTENT_VERSION",
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
    "ANCIENT_DOMAIN_RULE_VERSION",
    "ANCIENT_DOMAIN_STAMINA_COST",
    "ANCIENT_DOMAIN_WEEKLY_LIMIT",
    "resolve_ancient_domain_node",
]
