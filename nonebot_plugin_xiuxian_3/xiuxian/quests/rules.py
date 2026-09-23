"""Stable keys and thresholds for v0.4/v0.5 breakthrough permits."""

from __future__ import annotations

CONTENT_VERSION = "content-0.5"
RULE_VERSION = "quests-0.5.0"

SOUL_QUEST = "quest.soul_transformation"
DOMAIN_COMMISSION = "quest.domain_material_commission"
ANCIENT_DOMAIN_LINE = "quest.ancient_domain_line"
CROSS_REALM_VICTORY = "event.cross_realm_victory"

VOID_QUEST = "quest.break_void"
VOID_WALL_TRIAL = "void_wall_trial"
VOID_ARCHIVE_DELIVERY = "void_archive_delivery"

DOMAIN_COMMISSION_TARGET = 3
ANCIENT_DOMAIN_TARGET = 3
VOID_TRIAL_TARGET = 3


def realm_rank(realm_key: str) -> int:
    return {
        "mortal": 0,
        "qi_sensing": 1,
        "qi_gathering": 2,
        "foundation": 3,
        "golden_core": 4,
        "nascent_soul": 5,
        "soul_transformation": 6,
        "void_refining": 7,
        "dao_union": 8,
        "tribulation": 9,
    }.get(realm_key, -1)


def meets_realm(realm_key: str, layer: int, required_realm: str, required_layer: int = 1) -> bool:
    return (realm_rank(realm_key), int(layer)) >= (realm_rank(required_realm), required_layer)


__all__ = [
    "ANCIENT_DOMAIN_LINE",
    "ANCIENT_DOMAIN_TARGET",
    "CONTENT_VERSION",
    "CROSS_REALM_VICTORY",
    "DOMAIN_COMMISSION",
    "DOMAIN_COMMISSION_TARGET",
    "RULE_VERSION",
    "SOUL_QUEST",
    "VOID_ARCHIVE_DELIVERY",
    "VOID_QUEST",
    "VOID_TRIAL_TARGET",
    "VOID_WALL_TRIAL",
    "meets_realm",
]
