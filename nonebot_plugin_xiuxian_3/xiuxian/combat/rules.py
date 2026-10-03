"""Pure rules for automatic combat."""

from __future__ import annotations


import hashlib
from dataclasses import dataclass
from typing import Mapping

from ..content import ContentBundle, ContentError, bundled_content

MAX_TURNS = 20
TURN_TIMEOUT_SECONDS = 60
DEFEAT_COOLDOWN_SECONDS = 15 * 60


def combat_random_pool(enemy_key: str) -> str:
    """Return the stable random stream name for the current combat rules."""

    return f"battle.{enemy_key}"


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
    random_pool=combat_random_pool("enemy.training_dummy"),
    reward={},
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
    random_pool=combat_random_pool("enemy.wood_rat"),
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
    random_pool=combat_random_pool("enemy.iron_boar"),
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
    random_pool=combat_random_pool("enemy.mist_guardian"),
    reward={},
)

SPRING_WISP = EnemyDefinition(
    key="enemy.spring_wisp",
    label="灵泉水灵",
    location_key="xuantian.spirit_field",
    required_realm="qi_sensing",
    required_layer=3,
    max_hp=110,
    attack=18,
    initiative=11,
    agility=10,
    skill_key="enemy_skill.scratch",
    random_pool=combat_random_pool("enemy.spring_wisp"),
    reward={},
)

CLOUD_BOAT_GUARDIAN = EnemyDefinition(
    key="enemy.cloud_boat_guardian",
    label="云舟守灵",
    location_key="xuantian.floating_boat",
    required_realm="golden_core",
    required_layer=1,
    max_hp=900,
    attack=120,
    initiative=16,
    agility=16,
    skill_key="enemy_skill.cloud_armor",
    random_pool=combat_random_pool("enemy.cloud_boat_guardian"),
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
    random_pool=combat_random_pool("enemy.demon_overlord"),
    reward={},
)

DEMON_RUINS_SCOUT = EnemyDefinition(
    key="enemy.demon_ruins_scout",
    label="堕落遗迹巡守魔傀",
    location_key="demon.fallen_ruins",
    required_realm="nascent_soul",
    required_layer=1,
    max_hp=120,
    attack=20,
    initiative=8,
    agility=8,
    skill_key="enemy_skill.scratch",
    random_pool=combat_random_pool("enemy.demon_ruins_scout"),
    reward={},
)

DEMON_ABYSS_ECHO_GUARDIAN = EnemyDefinition(
    key="enemy.demon_abyss_echo_guardian",
    label="深渊残响守卫",
    location_key="demon.abyss_gate",
    required_realm="foundation",
    required_layer=1,
    max_hp=700,
    attack=85,
    initiative=14,
    agility=14,
    skill_key="enemy_skill.scratch",
    random_pool=combat_random_pool("enemy.demon_abyss_echo_guardian"),
    reward={},
)

DEMON_ABYSS_HEART = EnemyDefinition(
    key="enemy.demon_abyss_heart",
    label="深渊之心",
    location_key="demon.abyss_gate",
    required_realm="foundation",
    required_layer=1,
    max_hp=1000,
    attack=120,
    initiative=18,
    agility=20,
    skill_key="enemy_skill.scratch",
    random_pool=combat_random_pool("enemy.demon_abyss_heart"),
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
    random_pool=combat_random_pool("enemy.beast_guardian"),
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
    random_pool=combat_random_pool("enemy.beast_ancestor"),
    reward={},
)

ANCESTRAL_SPIRIT = EnemyDefinition(
    key="enemy.ancestral_spirit",
    label="祖灵湖守灵",
    location_key="beast.ancestral_lake",
    required_realm="soul_transformation",
    required_layer=1,
    max_hp=16_000,
    attack=820,
    initiative=26,
    agility=30,
    skill_key="skill.beast.ancestral_form",
    random_pool=combat_random_pool("enemy.ancestral_spirit"),
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
    random_pool=combat_random_pool("enemy.demon_war_front"),
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
    random_pool=combat_random_pool("enemy.cross_realm_sentinel"),
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
    random_pool=combat_random_pool("enemy.boundary_watcher"),
    reward={},
)

ANCIENT_DOMAIN_LORD = EnemyDefinition(
    key="enemy.ancient_domain_lord",
    label="远古洞天之主",
    location_key="cave.ancient_domain",
    required_realm="soul_transformation",
    required_layer=1,
    max_hp=18_000,
    attack=900,
    initiative=30,
    agility=30,
    skill_key="enemy_skill.domain_suppress",
    random_pool="none",
    reward={},
)

VOID_RUINS_SENTINEL = EnemyDefinition(
    key="enemy.void_ruins_sentinel",
    label="裂隙哨卫",
    location_key="void.archive_ruins",
    required_realm="void_refining",
    required_layer=1,
    max_hp=8_000,
    attack=420,
    initiative=32,
    agility=28,
    skill_key="enemy_skill.scratch",
    random_pool="none",
    reward={},
)

VOID_RUINS_SENTINEL_UNSTABLE = EnemyDefinition(
    key="enemy.void_ruins_sentinel_unstable",
    label="虚蚀裂隙哨卫",
    location_key="void.archive_ruins",
    required_realm="void_refining",
    required_layer=1,
    max_hp=10_000,
    attack=525,
    initiative=36,
    agility=32,
    skill_key="enemy_skill.scratch",
    random_pool="none",
    reward={},
)

VOID_RUINS_KEEPER = EnemyDefinition(
    key="enemy.void_ruins_keeper",
    label="遗迹档案守卫",
    location_key="void.archive_ruins",
    required_realm="void_refining",
    required_layer=1,
    max_hp=12_000,
    attack=560,
    initiative=36,
    agility=30,
    skill_key="enemy_skill.scratch",
    random_pool="none",
    reward={},
)

VOID_RUINS_KEEPER_UNSTABLE = EnemyDefinition(
    key="enemy.void_ruins_keeper_unstable",
    label="虚蚀遗迹档案守卫",
    location_key="void.archive_ruins",
    required_realm="void_refining",
    required_layer=1,
    max_hp=15_000,
    attack=700,
    initiative=42,
    agility=36,
    skill_key="enemy_skill.scratch",
    random_pool="none",
    reward={},
)

TIME_FORT_KEEPER = EnemyDefinition(
    key="enemy.time_fort_keeper",
    label="时序守时者",
    location_key="void.archive_ruins",
    required_realm="void_refining",
    required_layer=1,
    max_hp=14_000,
    attack=620,
    initiative=40,
    agility=34,
    skill_key="enemy_skill.time_fort_strike",
    random_pool="none",
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
    random_pool=combat_random_pool("enemy.boundary_trial_guardian"),
    reward={},
)

ARCHIVE_KEEPER = EnemyDefinition(
    key="enemy.archive_keeper",
    label="档案守卫",
    location_key="void.archive_ruins",
    # The archive is the source of the void-refining permit.  A soul-
    # transformation character may enter after completing the three wall
    # trials; existing void-refining characters remain eligible as well.
    required_realm="soul_transformation",
    required_layer=1,
    # Keep the encounter within the existing twenty-round automatic battle contract.
    max_hp=120,
    attack=2,
    initiative=1,
    agility=1,
    skill_key="enemy_skill.archive_rule_rewrite",
    random_pool=combat_random_pool("enemy.archive_keeper"),
    reward={},
)

MIST_TRIAL_SENSING = EnemyDefinition(
    key="enemy.mist_trial.sensing",
    label="雾塔试炼影",
    location_key="tower.mist_trial",
    required_realm="qi_sensing",
    required_layer=1,
    max_hp=80,
    attack=8,
    initiative=8,
    agility=8,
    skill_key="enemy_skill.dummy_tap",
    random_pool=combat_random_pool("enemy.mist_trial.sensing"),
    reward={},
)

MIST_TRIAL_SENSING_BOSS = EnemyDefinition(
    key="enemy.mist_trial.sensing_boss",
    label="雾塔层间守将",
    location_key="tower.mist_trial",
    required_realm="qi_sensing",
    required_layer=1,
    max_hp=150,
    attack=14,
    initiative=10,
    agility=10,
    skill_key="enemy_skill.dummy_tap",
    random_pool=combat_random_pool("enemy.mist_trial.sensing_boss"),
    reward={},
)

MIST_TRIAL_GATHERING = EnemyDefinition(
    key="enemy.mist_trial.gathering",
    label="聚气层试炼影",
    location_key="tower.mist_trial",
    required_realm="qi_gathering",
    required_layer=4,
    max_hp=320,
    attack=42,
    initiative=12,
    agility=14,
    skill_key="enemy_skill.scratch",
    random_pool=combat_random_pool("enemy.mist_trial.gathering"),
    reward={},
)

MIST_TRIAL_GATHERING_BOSS = EnemyDefinition(
    key="enemy.mist_trial.gathering_boss",
    label="聚气层守将",
    location_key="tower.mist_trial",
    required_realm="qi_gathering",
    required_layer=4,
    max_hp=480,
    attack=58,
    initiative=14,
    agility=16,
    skill_key="enemy_skill.scratch",
    random_pool=combat_random_pool("enemy.mist_trial.gathering_boss"),
    reward={},
)

MIST_TRIAL_FOUNDATION = EnemyDefinition(
    key="enemy.mist_trial.foundation",
    label="筑基层试炼影",
    location_key="tower.mist_trial",
    required_realm="foundation",
    required_layer=4,
    max_hp=700,
    attack=85,
    initiative=15,
    agility=18,
    skill_key="enemy_skill.scratch",
    random_pool=combat_random_pool("enemy.mist_trial.foundation"),
    reward={},
)

MIST_TRIAL_FOUNDATION_BOSS = EnemyDefinition(
    key="enemy.mist_trial.foundation_boss",
    label="筑基层守将",
    location_key="tower.mist_trial",
    required_realm="foundation",
    required_layer=4,
    max_hp=1000,
    attack=120,
    initiative=18,
    agility=20,
    skill_key="enemy_skill.scratch",
    random_pool=combat_random_pool("enemy.mist_trial.foundation_boss"),
    reward={},
)

MIST_TRIAL_GOLDEN_CORE = EnemyDefinition(
    key="enemy.mist_trial.golden_core",
    label="金丹层试炼影",
    location_key="tower.mist_trial",
    required_realm="golden_core",
    required_layer=3,
    max_hp=2400,
    attack=250,
    initiative=20,
    agility=22,
    skill_key="enemy_skill.mist_exposed",
    random_pool=combat_random_pool("enemy.mist_trial.golden_core"),
    reward={},
)

MIST_TRIAL_GOLDEN_CORE_BOSS = EnemyDefinition(
    key="enemy.mist_trial.golden_core_boss",
    label="金丹层守将",
    location_key="tower.mist_trial",
    required_realm="golden_core",
    required_layer=3,
    max_hp=3600,
    attack=330,
    initiative=25,
    agility=28,
    skill_key="enemy_skill.mist_exposed",
    random_pool=combat_random_pool("enemy.mist_trial.golden_core_boss"),
    reward={},
)


def _content_enemy(key: str, content: ContentBundle) -> EnemyDefinition:
    record = content.require("enemy", key, include_locked=False)
    profile = record.get("combat_profile")
    requirements = record.get("requirements")
    stats = record.get("stats")
    skills = record.get("skills")
    if (
        not isinstance(profile, dict)
        or not isinstance(requirements, list)
        or len(requirements) != 1
        or not isinstance(requirements[0], dict)
        or not isinstance(stats, dict)
        or not isinstance(skills, list)
        or not skills
    ):
        raise ContentError(f"enemy {key} has an invalid combat profile")
    requirement = requirements[0]
    realm = requirement.get("realm_key", requirement.get("stage"))
    values = (stats.get("hp"), stats.get("attack"), stats.get("initiative"), stats.get("agility"))
    random_pool = profile.get("random_pool_key")
    if (
        not isinstance(realm, str)
        or any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in values)
        or not isinstance(requirement.get("min_layer", 0), int)
        or not isinstance(random_pool, str)
        or not random_pool
        or not isinstance(skills[0], str)
    ):
        raise ContentError(f"enemy {key} has invalid combat values")
    reward = profile.get("reward", {})
    if not isinstance(reward, dict) or any(
        not isinstance(reward_key, str)
        or isinstance(amount, bool)
        or not isinstance(amount, int)
        or amount < 0
        for reward_key, amount in reward.items()
    ):
        raise ContentError(f"enemy {key} has an invalid battle reward")
    return EnemyDefinition(
        key=key,
        label=str(record["name"]),
        location_key=str(record["location_key"]),
        required_realm=realm,
        required_layer=int(requirement.get("min_layer", 0)),
        max_hp=int(values[0]),
        attack=int(values[1]),
        initiative=int(values[2]),
        agility=int(values[3]),
        skill_key=skills[0],
        random_pool=random_pool,
        reward=dict(reward),
    )


def _void_spire_enemy(key: str, *, content: ContentBundle | None = None) -> EnemyDefinition:
    bundle = content if content is not None else _VOID_SPIRE_CONTENT
    if bundle is None:
        raise ValueError("void spire enemy content is unavailable")
    record = bundle.require("enemy", key, include_locked=False)
    stats = record["stats"]
    requirement = record["requirements"][0]
    return EnemyDefinition(
        key=key,
        label=str(record["name"]),
        location_key=str(record["location_key"]),
        required_realm=str(requirement.get("realm_key", requirement.get("stage"))),
        required_layer=int(requirement.get("min_layer", 0)),
        max_hp=int(stats["hp"]),
        attack=int(stats["attack"]),
        initiative=int(stats["initiative"]),
        agility=int(stats["agility"]),
        skill_key=str(record["skills"][0]),
        random_pool="battle.enemy.void_spire",
        reward={},
    )


_VOID_SPIRE_CONTENT = bundled_content()
_VOID_SPIRE_ENEMIES = {
    str(row["key"]): _void_spire_enemy(str(row["key"]))
    for row in _VOID_SPIRE_CONTENT.list("enemy", include_locked=False)
    if str(row["key"]).startswith("enemy.void_spire.")
}

ENEMIES = {
    TRAINING_DUMMY.key: TRAINING_DUMMY,
    WOOD_RAT.key: WOOD_RAT,
    IRON_BOAR.key: IRON_BOAR,
    MIST_GUARDIAN.key: MIST_GUARDIAN,
    SPRING_WISP.key: SPRING_WISP,
    CLOUD_BOAT_GUARDIAN.key: CLOUD_BOAT_GUARDIAN,
    DEMON_OVERLORD.key: DEMON_OVERLORD,
    DEMON_RUINS_SCOUT.key: DEMON_RUINS_SCOUT,
    DEMON_ABYSS_ECHO_GUARDIAN.key: DEMON_ABYSS_ECHO_GUARDIAN,
    DEMON_ABYSS_HEART.key: DEMON_ABYSS_HEART,
    BEAST_GUARDIAN.key: BEAST_GUARDIAN,
    BEAST_ANCESTOR.key: BEAST_ANCESTOR,
    ANCESTRAL_SPIRIT.key: ANCESTRAL_SPIRIT,
    DEMON_WAR_FRONT.key: DEMON_WAR_FRONT,
    CROSS_REALM_SENTINEL.key: CROSS_REALM_SENTINEL,
    BOUNDARY_WATCHER.key: BOUNDARY_WATCHER,
    ANCIENT_DOMAIN_LORD.key: ANCIENT_DOMAIN_LORD,
    VOID_RUINS_SENTINEL.key: VOID_RUINS_SENTINEL,
    VOID_RUINS_SENTINEL_UNSTABLE.key: VOID_RUINS_SENTINEL_UNSTABLE,
    VOID_RUINS_KEEPER.key: VOID_RUINS_KEEPER,
    VOID_RUINS_KEEPER_UNSTABLE.key: VOID_RUINS_KEEPER_UNSTABLE,
    TIME_FORT_KEEPER.key: TIME_FORT_KEEPER,
    BOUNDARY_TRIAL_GUARDIAN.key: BOUNDARY_TRIAL_GUARDIAN,
    ARCHIVE_KEEPER.key: ARCHIVE_KEEPER,
    MIST_TRIAL_SENSING.key: MIST_TRIAL_SENSING,
    MIST_TRIAL_SENSING_BOSS.key: MIST_TRIAL_SENSING_BOSS,
    MIST_TRIAL_GATHERING.key: MIST_TRIAL_GATHERING,
    MIST_TRIAL_GATHERING_BOSS.key: MIST_TRIAL_GATHERING_BOSS,
    MIST_TRIAL_FOUNDATION.key: MIST_TRIAL_FOUNDATION,
    MIST_TRIAL_FOUNDATION_BOSS.key: MIST_TRIAL_FOUNDATION_BOSS,
    MIST_TRIAL_GOLDEN_CORE.key: MIST_TRIAL_GOLDEN_CORE,
    MIST_TRIAL_GOLDEN_CORE_BOSS.key: MIST_TRIAL_GOLDEN_CORE_BOSS,
}
ENEMIES.update(_VOID_SPIRE_ENEMIES)

_THREE_REALMS_TOWER_FACTIONS = {
    "xuantian": "玄天",
    "demon": "魔界",
    "beast": "妖界",
}
for _faction, _faction_label in _THREE_REALMS_TOWER_FACTIONS.items():
    for _encounter, _label, _hp, _attack, _skill, _initiative, _agility in (
        ("vanguard", "试炼先锋", 120, 16, "enemy_skill.scratch", 8, 8),
        ("veteran", "试炼精锐", 130, 16, "enemy_skill.mist_exposed", 10, 10),
        ("floor_10_boss", "十层守将", 180, 18, "enemy_skill.mist_exposed", 12, 12),
        ("floor_20_boss", "二十层守将", 200, 20, "enemy_skill.mist_exposed", 14, 14),
    ):
        _key = f"enemy.three_realms_tower.{_faction}.{_encounter}"
        ENEMIES[_key] = EnemyDefinition(
            key=_key,
            label=f"{_faction_label}{_label}",
            location_key="tower.three_realms",
            # Tower entry rules are checked atomically by its repository, including
            # the completed-story permit path for lower-realm characters.
            required_realm="mortal",
            required_layer=0,
            max_hp=_hp,
            attack=_attack,
            initiative=_initiative,
            agility=_agility,
            skill_key=_skill,
            random_pool=combat_random_pool(_key),
            reward={},
        )
    for _encounter, _label, _hp, _attack, _initiative, _agility in (
        ("domain_vanguard", "领域巡守", 480, 52, 28, 22),
        ("floor_30_boss", "三十层镇关者", 820, 75, 36, 32),
        ("domain_veteran", "重建阵师", 580, 64, 32, 28),
        ("floor_40_boss", "四十层守界者", 1100, 90, 40, 36),
    ):
        _key = f"enemy.three_realms_tower.{_faction}.{_encounter}"
        ENEMIES[_key] = EnemyDefinition(
            key=_key,
            label=f"{_faction_label}{_label}",
            location_key="tower.three_realms",
            required_realm="mortal",
            required_layer=0,
            max_hp=_hp,
            attack=_attack,
            initiative=_initiative,
            agility=_agility,
            skill_key="enemy_skill.mist_exposed",
            random_pool=combat_random_pool(_key),
            reward={},
        )


def enemy_definition(enemy_key: str, *, content: ContentBundle | None = None) -> EnemyDefinition:
    bundle = content or _VOID_SPIRE_CONTENT
    if enemy_key.startswith("enemy.void_spire."):
        return _void_spire_enemy(enemy_key, content=bundle)
    record = bundle.get("enemy", enemy_key, include_locked=False)
    if record is not None and isinstance(record.get("combat_profile"), dict):
        return _content_enemy(enemy_key, bundle)
    try:
        return ENEMIES[enemy_key]
    except KeyError as exc:
        raise ValueError(f"unsupported enemy: {enemy_key}") from exc


def battle_roll_bp(seed: str) -> int:
    digest = hashlib.blake2b(seed.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big") % 10_000


def clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def hit_chance_bp(
    *,
    attacker_initiative: int,
    defender_agility: int,
    skill_hit_bp: int = 0,
    accuracy_bp: int = 0,
    evasion_bp: int = 0,
) -> int:
    return clamp(
        8_500 + attacker_initiative * 20 - defender_agility * 20 + skill_hit_bp + accuracy_bp - evasion_bp,
        2_000,
        9_800,
    )


def player_stat_snapshot(
    qualification: Mapping[str, object],
    *,
    max_hp: int,
    initiative: int,
    equipment: tuple[Mapping[str, object], ...],
    constitution_effect: Mapping[str, object] | None = None,
    manual_stat_bonus_bp: Mapping[str, int] | None = None,
) -> dict[str, int]:
    """Build combat stats from player projections and frozen equipment effects.

    The wider stat service is intentionally not invented in the combat layer;
    configured flat equipment effects are applied to the existing projections.
    """

    body = max(0, int(qualification.get("body", 0)))
    agility = max(0, int(qualification.get("agility", 0)))
    spirit = max(0, int(qualification.get("spirit", 0)))
    damage_bonus = 0
    hp_bonus = 0
    initiative_bonus = 0
    temper_bonus = 0
    flat_stats = {"physical_damage": 0, "max_hp": 0, "initiative": 0, "agility": 0,
                  "max_mana": 0, "hp_regen": 0, "mana_regen": 0}
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
            damage_bonus += max(0, int(affixes.get("damage", 0))) * durability_bp // 10_000
            hp_bonus += max(0, int(affixes.get("hp", 0))) * durability_bp // 10_000
            initiative_bonus += max(0, int(affixes.get("initiative", 0))) * durability_bp // 10_000
            for key, stat in _EQUIPMENT_AFFIX_STATS.items():
                combat_stats[stat] += max(0, int(affixes.get(key, 0))) * durability_bp // 10_000
            flat_stats["hp_regen"] += max(0, int(affixes.get("hp_regen", 0))) * durability_bp // 10_000
            flat_stats["max_mana"] += max(0, int(affixes.get("max_mana", 0))) * durability_bp // 10_000
            flat_stats["mana_regen"] += max(0, int(affixes.get("mana_regen", 0))) * durability_bp // 10_000
        if str(item.get("slot", "")) == "weapon":
            temper_bonus += max(0, int(item.get("temper_level", 0))) * 2
        effects = item.get("effects", ())
        if not isinstance(effects, (list, tuple)):
            raise ValueError(f"equipment {item.get('item_key')} effects must be a list")
        for effect in effects:
            if not isinstance(effect, Mapping) or effect.get("type") != "flat_stat":
                continue
            stat = effect.get("stat")
            value = effect.get("value")
            if not isinstance(stat, str) or isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"equipment {item.get('item_key')} has an invalid flat_stat effect")
            if stat not in flat_stats:
                raise ValueError(f"equipment {item.get('item_key')} has unsupported combat stat: {stat}")
            flat_stats[stat] += value * durability_bp // 10_000
        for effect in effects:
            if not isinstance(effect, Mapping) or effect.get("type") != "combat_stat_bp":
                continue
            stat = effect.get("stat")
            value = effect.get("value")
            if stat not in combat_stats or isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"equipment {item.get('item_key')} has an invalid combat_stat_bp effect")
            combat_stats[str(stat)] += value * durability_bp // 10_000
    base_hp = max(100 + body * 4, max(0, int(max_hp))) + hp_bonus + flat_stats["max_hp"]
    stats = {
        "max_hp": base_hp,
        "attack": 10 + body // 2 + temper_bonus + damage_bonus + flat_stats["physical_damage"],
        "initiative": max(
            8 + agility // 2 + initiative_bonus + flat_stats["initiative"],
            max(0, int(initiative)),
        ),
        "agility": agility + flat_stats["agility"],
        "max_mana": 80 + spirit * 10 + flat_stats["max_mana"],
        "hp_regen": flat_stats["hp_regen"],
        "mana_regen": flat_stats["mana_regen"],
    }
    stats.update(combat_stats)
    stats["damage_reduction_bp"] = min(7_000, stats["damage_reduction_bp"])
    stats["crit_chance_bp"] = min(5_000, stats["crit_chance_bp"])
    stats["crit_damage_bp"] = min(15_000, stats["crit_damage_bp"])
    stats["evasion_bp"] = min(7_500, stats["evasion_bp"])
    stats["accuracy_bp"] = min(5_000, stats["accuracy_bp"])
    stats["anti_crit_bp"] = min(5_000, stats["anti_crit_bp"])
    stats["damage_reflection_bp"] = min(5_000, stats["damage_reflection_bp"])
    stats["lifesteal_bp"] = min(5_000, stats["lifesteal_bp"])
    stats["mana_leech_bp"] = min(5_000, stats["mana_leech_bp"])
    stats["healing_reduction_bp"] = min(9_000, stats["healing_reduction_bp"])
    stats["recovery_reduction_bp"] = min(9_000, stats["recovery_reduction_bp"])
    for stat, value in (manual_stat_bonus_bp or {}).items():
        if stat not in stats or isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"manual has an invalid combat stat bonus: {stat}")
        stats[stat] += stats[stat] * value // 10_000
    return apply_constitution_combat_effect(stats, constitution_effect)


_EQUIPMENT_AFFIX_STATS = {
    "damage_reduction": "damage_reduction_bp",
    "crit_chance": "crit_chance_bp",
    "crit_damage": "crit_damage_bp",
    "evasion": "evasion_bp",
    "accuracy": "accuracy_bp",
    "anti_crit": "anti_crit_bp",
    "reflection": "damage_reflection_bp",
    "lifesteal": "lifesteal_bp",
    "mana_leech": "mana_leech_bp",
    "healing_reduction": "healing_reduction_bp",
    "recovery_reduction": "recovery_reduction_bp",
}


def apply_constitution_combat_effect(
    stats: Mapping[str, int], effect: Mapping[str, object] | None
) -> dict[str, int]:
    result = {str(key): int(value) for key, value in stats.items()}
    if not effect:
        return result
    effect_type = effect.get("type")
    value = effect.get("value")
    if not isinstance(effect_type, str) or isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("constitution combat effect is invalid")
    if effect_type == "max_hp_bp":
        result["max_hp"] += result.get("max_hp", 0) * value // 10_000
    elif effect_type == "max_mana_bp":
        result["max_mana"] += result.get("max_mana", 0) * value // 10_000
    elif effect_type == "initiative_bp":
        result["initiative"] += result.get("initiative", 0) * value // 10_000
    elif effect_type not in {"production_quality_bp", "drop_weight_bp"}:
        raise ValueError(f"unsupported constitution combat effect: {effect_type}")
    return result


def player_goes_first(*, player_initiative: int, enemy_initiative: int, seed: str) -> bool:
    if player_initiative != enemy_initiative:
        return player_initiative > enemy_initiative
    return battle_roll_bp(f"{seed}:initiative") < 5_000


__all__ = [
    "DEFEAT_COOLDOWN_SECONDS",
    "ENEMIES",
    "MAX_TURNS",
    "combat_random_pool",
    "TURN_TIMEOUT_SECONDS",
    "EnemyDefinition",
    "CLOUD_BOAT_GUARDIAN",
    "DEMON_OVERLORD",
    "DEMON_RUINS_SCOUT",
    "BEAST_GUARDIAN",
    "BEAST_ANCESTOR",
    "ANCESTRAL_SPIRIT",
    "DEMON_WAR_FRONT",
    "IRON_BOAR",
    "MIST_GUARDIAN",
    "SPRING_WISP",
    "WOOD_RAT",
    "ARCHIVE_KEEPER",
    "VOID_RUINS_SENTINEL",
    "VOID_RUINS_SENTINEL_UNSTABLE",
    "VOID_RUINS_KEEPER",
    "VOID_RUINS_KEEPER_UNSTABLE",
    "battle_roll_bp",
    "clamp",
    "apply_constitution_combat_effect",
    "enemy_definition",
    "hit_chance_bp",
    "player_goes_first",
    "player_stat_snapshot",
]
