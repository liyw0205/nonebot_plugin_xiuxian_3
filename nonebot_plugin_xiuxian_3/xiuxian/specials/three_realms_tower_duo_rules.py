"""Rules for the two-player three-realms tower challenge."""

from __future__ import annotations

from .three_realms_tower_rules import (
    MAX_FLOOR,
    TOWER_KEY,
    enemy_key_for,
    floor_definition,
    rebuild_reputation_total,
    reward_for,
    week_start,
)


PARTY_TYPE_THREE_REALMS_TOWER_DUO = "three_realms_tower_duo"
TOWER_DUO_STAMINA_COST = 12

__all__ = [
    "MAX_FLOOR",
    "PARTY_TYPE_THREE_REALMS_TOWER_DUO",
    "TOWER_DUO_STAMINA_COST",
    "TOWER_KEY",
    "enemy_key_for",
    "floor_definition",
    "rebuild_reputation_total",
    "reward_for",
    "week_start",
]
