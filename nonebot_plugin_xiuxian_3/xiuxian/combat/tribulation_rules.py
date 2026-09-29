"""Frozen high-tier stats and phase rules for tribulation trials."""

from __future__ import annotations


from dataclasses import dataclass
from typing import Mapping


PROFILE_KEY = "battle_profile.tribulation_trial"
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
    body = min(15, max(0, int(qualification.get("body", 0))))
    agility = min(15, max(0, int(qualification.get("agility", 0))))
    body_scale = body * 4_000 // 3
    agility_scale = agility * 4_000 // 3
    hp_affix = damage_affix = initiative_affix = agility_bonus = temper = 0
    max_mana_bonus = hp_regen = mana_regen = 0
    combat_stats = {
        "damage_reduction_bp": 0,
        "crit_chance_bp": 0,
        "crit_damage_bp": 0,
        "evasion_bp": 0,
        "accuracy_bp": 0,
        "anti_crit_bp": 0,
        "damage_reflection_bp": 0,
        "lifesteal_bp": 0,
        "mana_leech_bp": 0,
        "healing_reduction_bp": 0,
        "recovery_reduction_bp": 0,
    }
    for item in equipment:
        durability_bp = max(0, min(10_000, int(item.get("durability_bp", 10_000))))
        affixes = item.get("affixes", {})
        if isinstance(affixes, Mapping):
            hp_affix += max(0, int(affixes.get("hp", 0))) * durability_bp // 10_000
            damage_affix += max(0, int(affixes.get("damage", 0))) * durability_bp // 10_000
            initiative_affix += max(0, int(affixes.get("initiative", 0))) * durability_bp // 10_000
        if str(item.get("slot", "")) == "weapon":
            temper += max(0, int(item.get("temper_level", 0)))
        effects = item.get("effects", ())
        if not isinstance(effects, (tuple, list)):
            continue
        for effect in effects:
            if not isinstance(effect, Mapping):
                continue
            stat = effect.get("stat")
            value = effect.get("value")
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                continue
            value = value * durability_bp // 10_000
            if effect.get("type") == "flat_stat":
                if stat == "physical_damage":
                    damage_affix += value
                elif stat == "max_hp":
                    hp_affix += value
                elif stat == "initiative":
                    initiative_affix += value
                elif stat == "agility":
                    agility_bonus += value * 10
                elif stat == "max_mana":
                    max_mana_bonus += value
                elif stat == "hp_regen":
                    hp_regen += value * 100
                elif stat == "mana_regen":
                    mana_regen += value
            elif effect.get("type") == "combat_stat_bp" and stat in combat_stats:
                combat_stats[str(stat)] += value

    stats = {
        "max_hp": 80_000 + (layer - 1) * 7_500 + body * 4_000 + hp_affix * 100,
        "attack": 8_000 + (layer - 1) * 1_000 + body_scale + damage_affix * 100 + temper * 500,
        "initiative": 1_000 + layer * 100 + agility_scale + initiative_affix * 20,
        "agility": 400 + layer * 50 + agility_scale + agility_bonus,
        "max_mana": 80 + max(0, int(qualification.get("spirit", 0))) * 10 + max_mana_bonus,
        "hp_regen": hp_regen,
        "mana_regen": mana_regen,
    }
    stats.update(combat_stats)
    for stat, maximum in (
        ("damage_reduction_bp", 7_000),
        ("crit_chance_bp", 5_000),
        ("crit_damage_bp", 15_000),
        ("evasion_bp", 7_500),
        ("accuracy_bp", 5_000),
        ("anti_crit_bp", 5_000),
        ("damage_reflection_bp", 5_000),
        ("lifesteal_bp", 5_000),
        ("mana_leech_bp", 5_000),
        ("healing_reduction_bp", 9_000),
        ("recovery_reduction_bp", 9_000),
    ):
        stats[stat] = min(maximum, stats[stat])
    return stats


def debt_shield_bp(debt: int) -> int:
    return min(2_000, max(0, int(debt)) // 10 * 200)


__all__ = [
    "ENEMY_AGILITY",
    "ENEMY_ATTACK",
    "ENEMY_INITIATIVE",
    "ENEMY_KEY",
    "ENEMY_MAX_HP",
    "PHASES",
    "PROFILE_KEY",
    "TribulationPhase",
    "debt_shield_bp",
    "phase_for_hp",
    "stat_snapshot",
]
