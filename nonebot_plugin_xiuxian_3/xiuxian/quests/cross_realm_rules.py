"""Versioned rules for the first cross-realm player quest."""

from __future__ import annotations

DEMON_MAINLINE = "quest.demon_main_1"
DEMON_MAINLINE_CONTENT_VERSION = "content-0.3"
DEMON_MAINLINE_RULE_VERSION = "quests-0.3.0"
DEMON_MAINLINE_EXPLORATION = "explore.demon_abyss"
DEMON_MAINLINE_EXPLORATION_TARGET = 2
DEMON_MAINLINE_REQUIRED_REPUTATION = 200
DEMON_MAINLINE_ACCESS_FLAG = "access.demon.fallen_ruins"


def demon_mainline_realm_ready(realm_key: str, layer: int) -> bool:
    ranks = {
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
    }
    return (ranks.get(realm_key, -1), int(layer)) >= (ranks["nascent_soul"], 1)


__all__ = [
    "DEMON_MAINLINE",
    "DEMON_MAINLINE_ACCESS_FLAG",
    "DEMON_MAINLINE_CONTENT_VERSION",
    "DEMON_MAINLINE_EXPLORATION",
    "DEMON_MAINLINE_EXPLORATION_TARGET",
    "DEMON_MAINLINE_REQUIRED_REPUTATION",
    "DEMON_MAINLINE_RULE_VERSION",
    "demon_mainline_realm_ready",
]
