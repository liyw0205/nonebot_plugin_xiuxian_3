"""Pure, versioned rules for the first automatic training battle."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Mapping


CONTENT_VERSION = "content-0.1"
RULE_VERSION = "combat-0.1.0"
V03_CONTENT_VERSION = "content-0.3"
V03_RULE_VERSION = "combat-0.3.0"
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

WOOD_RAT = EnemyDefinition(
    key="enemy.wood_rat",
    label="木鼠",
    location_key="xuantian.outskirts",
    required_realm="mortal",
    required_layer=0,
    max_hp=45,
    attack=8,
    initiative=10,
    agility=8,
    skill_key="enemy_skill.scratch",
    random_pool="battle.enemy.wood_rat.v0.1",
    reward={},
)

IRON_BOAR = EnemyDefinition(
    key="enemy.iron_boar",
    label="铁鬃野猪",
    location_key="xuantian.outskirts",
    required_realm="qi_sensing",
    required_layer=3,
    max_hp=100,
    attack=15,
    initiative=7,
    agility=8,
    skill_key="enemy_skill.charge",
    random_pool="battle.enemy.iron_boar.v0.1",
    reward={},
)

MIST_GUARDIAN = EnemyDefinition(
    key="enemy.mist_guardian",
    label="雾隐守卫",
    location_key="cave.mist_grotto",
    required_realm="qi_gathering",
    required_layer=4,
    max_hp=320,
    attack=42,
    initiative=10,
    agility=14,
    skill_key="enemy_skill.mist_shield",
    random_pool="battle.enemy.mist_guardian.v0.1",
    reward={},
)

CLOUD_BEAST = EnemyDefinition(
    key="enemy.cloud_beast",
    label="云铁矿兽",
    location_key="xuantian.cloud_mine",
    required_realm="foundation",
    required_layer=1,
    max_hp=700,
    attack=85,
    initiative=14,
    agility=14,
    skill_key="enemy_skill.cloud_armor",
    random_pool="battle.enemy.cloud_beast.v0.2",
    # Exploration owns the frozen reward. Keeping this empty prevents the
    # generic battle reward claim from duplicating exploration materials.
    reward={},
)

MIST_ELITE = EnemyDefinition(
    key="enemy.mist_elite",
    label="雾隐精英",
    location_key="cave.mist_grotto_2",
    required_realm="golden_core",
    required_layer=1,
    max_hp=1800,
    attack=190,
    initiative=15,
    agility=18,
    skill_key="enemy_skill.mist_exposed",
    random_pool="battle.enemy.mist_elite.v0.2",
    reward={},
)

DEMON_OVERLORD = EnemyDefinition(
    key="enemy.demon_overlord",
    label="魔界堕落领主",
    location_key="demon.fallen_ruins",
    required_realm="nascent_soul",
    required_layer=1,
    max_hp=8000,
    attack=520,
    initiative=22,
    agility=24,
    skill_key="skill.demonic.abyss_communion",
    random_pool="combat.demon_overlord.v0.3",
    reward={},
)

BEAST_GUARDIAN = EnemyDefinition(
    key="enemy.beast_guardian",
    label="万兽山守山兽",
    location_key="beast.ten_thousand_hills",
    required_realm="nascent_soul",
    required_layer=1,
    max_hp=7500,
    attack=480,
    initiative=22,
    agility=24,
    skill_key="skill.beast.guardian_roar",
    random_pool="combat.beast_guardian.v0.3",
    reward={},
)

BEAST_ANCESTOR = EnemyDefinition(
    key="enemy.beast_ancestor",
    label="万兽始祖",
    location_key="beast.ten_thousand_hills",
    required_realm="nascent_soul",
    required_layer=1,
    max_hp=7500,
    attack=480,
    initiative=22,
    agility=24,
    skill_key="skill.beast.ancestral_form",
    random_pool="combat.beast_ancestor.v0.3",
    reward={},
)

DEMON_WAR_FRONT = EnemyDefinition(
    key="enemy.demon_war_front",
    label="魔界战场先锋",
    location_key="xuantian.war_front",
    required_realm="nascent_soul",
    required_layer=1,
    max_hp=600,
    attack=35,
    initiative=12,
    agility=10,
    skill_key="skill.demonic.war_front_strike",
    random_pool="combat.demon_war_front.v0.3",
    reward={},
)

CROSS_REALM_SENTINEL = EnemyDefinition(
    key="enemy.cross_realm_sentinel",
    label="跨界守门人",
    location_key="cave.boundary_realm",
    required_realm="nascent_soul",
    required_layer=1,
    max_hp=180,
    attack=22,
    initiative=14,
    agility=12,
    skill_key="enemy_skill.boundary_sweep",
    random_pool="battle.enemy.cross_realm_sentinel.v0.4",
    reward={},
)

BOUNDARY_WATCHER = EnemyDefinition(
    key="enemy.boundary_watcher",
    label="界隙守望者",
    location_key="cave.boundary_realm",
    required_realm="nascent_soul",
    required_layer=1,
    max_hp=10_000,
    attack=600,
    initiative=24,
    agility=28,
    skill_key="enemy_skill.boundary_impact",
    random_pool="combat.boundary_watcher.v0.3",
    reward={},
)

BOUNDARY_TRIAL_GUARDIAN = EnemyDefinition(
    key="enemy.boundary_trial_guardian",
    label="界壁试炼守卫",
    location_key="void.portal",
    required_realm="soul_transformation",
    required_layer=1,
    max_hp=240,
    attack=28,
    initiative=16,
    agility=14,
    skill_key="enemy_skill.boundary_wall",
    random_pool="battle.enemy.boundary_trial_guardian.v0.5",
    reward={},
)

ENEMIES = {
    TRAINING_DUMMY.key: TRAINING_DUMMY,
    WOOD_RAT.key: WOOD_RAT,
    IRON_BOAR.key: IRON_BOAR,
    MIST_GUARDIAN.key: MIST_GUARDIAN,
    CLOUD_BEAST.key: CLOUD_BEAST,
    MIST_ELITE.key: MIST_ELITE,
    DEMON_OVERLORD.key: DEMON_OVERLORD,
    BEAST_GUARDIAN.key: BEAST_GUARDIAN,
    BEAST_ANCESTOR.key: BEAST_ANCESTOR,
    DEMON_WAR_FRONT.key: DEMON_WAR_FRONT,
    CROSS_REALM_SENTINEL.key: CROSS_REALM_SENTINEL,
    BOUNDARY_WATCHER.key: BOUNDARY_WATCHER,
    BOUNDARY_TRIAL_GUARDIAN.key: BOUNDARY_TRIAL_GUARDIAN,
}


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
    "V03_CONTENT_VERSION",
    "V03_RULE_VERSION",
    "ENEMIES",
    "MAX_TURNS",
    "RULE_VERSION",
    "TURN_TIMEOUT_SECONDS",
    "EnemyDefinition",
    "CLOUD_BEAST",
    "DEMON_OVERLORD",
    "BEAST_GUARDIAN",
    "BEAST_ANCESTOR",
    "DEMON_WAR_FRONT",
    "IRON_BOAR",
    "MIST_ELITE",
    "MIST_GUARDIAN",
    "WOOD_RAT",
    "battle_roll_bp",
    "clamp",
    "enemy_definition",
    "hit_chance_bp",
    "player_goes_first",
    "player_stat_snapshot",
]
