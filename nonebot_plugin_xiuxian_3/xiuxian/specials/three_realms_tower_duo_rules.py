"""Versioned rules for the two-player three-realms tower challenge."""

from __future__ import annotations

from .three_realms_tower_rules import (
    CONTENT_VERSION,
    MAX_FLOOR,
    RULE_VERSION,
    TOWER_KEY,
    enemy_key_for,
    floor_definition,
    rebuild_reputation_total,
    reward_for,
    versions_for_floor,
    week_start,
)


PARTY_TYPE_THREE_REALMS_TOWER_DUO = "three_realms_tower_duo"
TOWER_DUO_CONTENT_VERSION = CONTENT_VERSION
TOWER_DUO_RULE_VERSION = "specials-0.4.1"
TOWER_DUO_STAMINA_COST = 12

__all__ = [
    "CONTENT_VERSION",
    "MAX_FLOOR",
    "PARTY_TYPE_THREE_REALMS_TOWER_DUO",
    "RULE_VERSION",
    "TOWER_DUO_CONTENT_VERSION",
    "TOWER_DUO_RULE_VERSION",
    "TOWER_DUO_STAMINA_COST",
    "TOWER_KEY",
    "enemy_key_for",
    "floor_definition",
    "rebuild_reputation_total",
    "reward_for",
    "versions_for_floor",
    "week_start",
]
