"""Frozen high-tier stats and phase rules for the v0.6 tribulation trials."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


CONTENT_VERSION = "content-0.6"
RULE_VERSION = "combat-0.6.1"
PROFILE_KEY = "battle_profile.tribulation_trial.v1"
ENEMY_KEY = "enemy.tribulation_heaven"
ENEMY_MAX_HP = 150_000
ENEMY_ATTACK = 5_500
ENEMY_INITIATIVE = 1_600
ENEMY_AGILITY = 650


@dataclass(frozen=True, slots=True)
class TribulationPhase:
    key: str
    min_hp_bp: int
    attack: int
    skill_key: str
    enemy_hit_bonus_bp: int
    player_damage_bp: int


PHASES = (
    TribulationPhase("thunder", 6_667, 5_500, "skill.tribulation.thunder", 0, 10_000),
    TribulationPhase("heart", 3_334, 8_000, "skill.tribulation.heart", 200, 9_500),
    TribulationPhase("dao", 0, 12_000, "skill.tribulation.dao", 400, 9_000),
)


def phase_for_hp(enemy_hp: int, enemy_max_hp: int = ENEMY_MAX_HP) -> TribulationPhase:
    hp_bp = max(0, int(enemy_hp)) * 10_000 // max(1, int(enemy_max_hp))
    return next(phase for phase in PHASES if hp_bp >= phase.min_hp_bp)


def stat_snapshot(
    qualification: Mapping[str, object],
    *,
    realm_layer: int,
    equipment: tuple[Mapping[str, object], ...],
) -> dict[str, int]:
    """Project current build inputs into the high-tier trial battle scale."""

    layer = max(1, int(realm_layer))
    body = min(2_000, max(0, int(qualification.get("body", 0))))
    agility = min(2_000, max(0, int(qualification.get("agility", 0))))
    hp_affix = damage_affix = initiative_affix = temper = 0
    for item in equipment:
        affixes = item.get("affixes", {})
        if isinstance(affixes, Mapping):
            hp_affix += max(0, int(affixes.get("hp", 0)))
            damage_affix += max(0, int(affixes.get("damage", 0)))
            initiative_affix += max(0, int(affixes.get("initiative", 0)))
        if str(item.get("slot", "")) == "weapon":
            temper += max(0, int(item.get("temper_level", 0)))

    return {
        "max_hp": 80_000 + (layer - 1) * 7_500 + body * 30 + hp_affix * 100,
        "attack": 8_000 + (layer - 1) * 1_000 + body * 10 + damage_affix * 100 + temper * 500,
        "initiative": 1_000 + layer * 100 + agility * 10 + initiative_affix * 20,
        "agility": 400 + layer * 50 + agility * 10,
    }


def debt_shield_bp(debt: int) -> int:
    return min(2_000, max(0, int(debt)) // 10 * 200)


__all__ = [
    "CONTENT_VERSION",
    "ENEMY_AGILITY",
    "ENEMY_ATTACK",
    "ENEMY_INITIATIVE",
    "ENEMY_KEY",
    "ENEMY_MAX_HP",
    "PHASES",
    "PROFILE_KEY",
    "RULE_VERSION",
    "TribulationPhase",
    "debt_shield_bp",
    "phase_for_hp",
    "stat_snapshot",
]
