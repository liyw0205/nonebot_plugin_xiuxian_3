"""Pure, versioned rules for the first automatic training battle."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Mapping


CONTENT_VERSION = "content-0.1"
RULE_VERSION = "combat-0.1.0"
MAX_TURNS = 20
TURN_TIMEOUT_SECONDS = 60
DEFEAT_COOLDOWN_SECONDS = 15 * 60


@dataclass(frozen=True, slots=True)
class EnemyDefinition:
    key: str
    label: str
    location_key: str
    required_realm: str
    required_layer: int
    max_hp: int
    attack: int
    initiative: int
    agility: int
    skill_key: str
    random_pool: str
    reward: dict[str, int]


TRAINING_DUMMY = EnemyDefinition(
    key="enemy.training_dummy",
    label="训练傀儡",
    location_key="xuantian.new_town",
    required_realm="qi_sensing",
    required_layer=1,
    max_hp=80,
    attack=8,
    initiative=8,
    agility=8,
    skill_key="enemy_skill.dummy_tap",
    random_pool="battle.enemy.training_dummy.v0.1",
    reward={"cultivation": 20, "spirit_stones": 5},
)

ENEMIES = {TRAINING_DUMMY.key: TRAINING_DUMMY}


def enemy_definition(enemy_key: str) -> EnemyDefinition:
    try:
        return ENEMIES[enemy_key]
    except KeyError as exc:
        raise ValueError(f"unsupported enemy: {enemy_key}") from exc


def battle_roll_bp(seed: str) -> int:
    digest = hashlib.blake2b(seed.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big") % 10_000


def clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def hit_chance_bp(*, attacker_initiative: int, defender_agility: int, skill_hit_bp: int = 0) -> int:
    return clamp(8_500 + attacker_initiative * 20 - defender_agility * 20 + skill_hit_bp, 2_000, 9_800)


def player_stat_snapshot(
    qualification: Mapping[str, object],
    *,
    max_hp: int,
    initiative: int,
    equipment: tuple[Mapping[str, object], ...],
) -> dict[str, int]:
    """Build the v0.1 basic-attack stats from the existing player projections.

    The wider stat service is intentionally not invented in the combat layer.
    This first slice only consumes the stable qualification, player projection,
    and equipment-instance fields that already exist.
    """

    body = max(0, int(qualification.get("body", 0)))
    agility = max(0, int(qualification.get("agility", 0)))
    damage_bonus = 0
    hp_bonus = 0
    initiative_bonus = 0
    temper_bonus = 0
    for item in equipment:
        affixes = item.get("affixes", {})
        if isinstance(affixes, Mapping):
            damage_bonus += max(0, int(affixes.get("damage", 0)))
            hp_bonus += max(0, int(affixes.get("hp", 0)))
            initiative_bonus += max(0, int(affixes.get("initiative", 0)))
        if str(item.get("slot", "")) == "weapon":
            temper_bonus += max(0, int(item.get("temper_level", 0))) * 2
    base_hp = 100 + body * 4 + hp_bonus
    return {
        "max_hp": max(base_hp, max(0, int(max_hp))),
        "attack": 10 + body // 2 + temper_bonus + damage_bonus,
        "initiative": max(8 + agility // 2 + initiative_bonus, max(0, int(initiative))),
        "agility": agility,
    }


def player_goes_first(*, player_initiative: int, enemy_initiative: int, seed: str) -> bool:
    if player_initiative != enemy_initiative:
        return player_initiative > enemy_initiative
    return battle_roll_bp(f"{seed}:initiative") < 5_000


__all__ = [
    "CONTENT_VERSION",
    "DEFEAT_COOLDOWN_SECONDS",
    "ENEMIES",
    "MAX_TURNS",
    "RULE_VERSION",
    "TURN_TIMEOUT_SECONDS",
    "EnemyDefinition",
    "battle_roll_bp",
    "clamp",
    "enemy_definition",
    "hit_chance_bp",
    "player_goes_first",
    "player_stat_snapshot",
]
