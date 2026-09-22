"""Pure v0.4 domain selection definitions."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DomainDefinition:
    path_key: str
    domain_key: str
    label: str
    energy_cost: int
    pollution_delta: int = 0
    bloodline_delta: int = 0


DOMAIN_DEFINITIONS = {
    "body": DomainDefinition("body", "domain.mountain_body", "山岳真身", 30),
    "spell": DomainDefinition("spell", "domain.elemental_sea", "元素之海", 35),
    "device": DomainDefinition("device", "domain.machine_city", "机关天城", 30),
    "demonic": DomainDefinition("demonic", "domain.abyss_shadow", "深渊暗影", 30, pollution_delta=15),
    "beast": DomainDefinition("beast", "domain.ancestral_wild", "祖灵荒野", 30, bloodline_delta=-10),
    "support": DomainDefinition("support", "domain.artisan_realm", "百艺天工", 25),
}

ALIASES = {
    "体修": "body", "山岳真身": "body", "domain.mountain_body": "body",
    "法修": "spell", "元素之海": "spell", "domain.elemental_sea": "spell",
    "器修": "device", "机关天城": "device", "domain.machine_city": "device",
    "魔修": "demonic", "深渊暗影": "demonic", "domain.abyss_shadow": "demonic",
    "妖修": "beast", "祖灵荒野": "beast", "domain.ancestral_wild": "beast",
    "辅修": "support", "百艺天工": "support", "domain.artisan_realm": "support",
}


def resolve_domain(value: str) -> str | None:
    return value if value in DOMAIN_DEFINITIONS else ALIASES.get(value.strip())


def domain_definition(path_key: str) -> DomainDefinition:
    return DOMAIN_DEFINITIONS[path_key]


__all__ = ["DOMAIN_DEFINITIONS", "DomainDefinition", "domain_definition", "resolve_domain"]
