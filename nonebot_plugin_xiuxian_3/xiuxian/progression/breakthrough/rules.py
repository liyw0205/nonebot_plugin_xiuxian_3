"""Pure, versioned rules for the first cross-realm breakthrough."""

from __future__ import annotations

from hashlib import blake2b

from .models import BreakthroughDefinition


QI_GATHERING_BREAKTHROUGH = BreakthroughDefinition(
    key="progression.breakthrough_qi_gathering",
    target_realm="qi_gathering",
    source_realm="qi_sensing",
    required_total_cultivation=1360,
    duration_seconds=3 * 60,
    materials={
        "item.pill.focus_low": 1,
        "item.herb.spirit_leaf": 3,
    },
    currency_cost=100,
    base_success_bp=8000,
    minimum_success_bp=8000,
    maximum_success_bp=9000,
    pity_cap_bp=900,
    pity_increment_bp=300,
    quality_bonus_divisor=0,
    quality_bonus_cap_bp=0,
    technique_bonus_bp=0,
    formation_bonus_bp=0,
    retention_bp=8000,
    weakness_seconds=2 * 60 * 60,
    protection_key="item.pill.qi_guard",
    protection_retention_bp=9000,
    protection_weakness_seconds=30 * 60,
    rule_version="progression-0.1.3",
    random_pool="breakthrough.qi_gathering.v0.1",
    reward_currency=80,
    reward_stamina=5,
    source_cultivation_cap=1360,
)

FOUNDATION_BREAKTHROUGH = BreakthroughDefinition(
    key="progression.breakthrough_foundation",
    target_realm="foundation",
    source_realm="qi_gathering",
    required_total_cultivation=4260,
    duration_seconds=5 * 60,
    materials={
        "item.pill.foundation_draft": 1,
        "item.mat.array_sand": 3,
        "item.ore.ironstone": 3,
    },
    currency_cost=500,
    base_success_bp=7500,
    minimum_success_bp=7500,
    maximum_success_bp=9000,
    pity_cap_bp=1200,
    pity_increment_bp=400,
    quality_bonus_divisor=10,
    quality_bonus_cap_bp=1000,
    technique_bonus_bp=300,
    formation_bonus_bp=300,
    retention_bp=7000,
    weakness_seconds=6 * 60 * 60,
    protection_key="item.pill.foundation_guard",
    protection_retention_bp=8500,
    protection_weakness_seconds=2 * 60 * 60,
    rule_version="progression-0.1.6",
    random_pool="breakthrough.foundation.v0.1",
    reward_world_merit=50,
    reward_items={"item.cave_pass_basic": 1},
    source_cultivation_cap=2900,
)

GOLDEN_CORE_BREAKTHROUGH = BreakthroughDefinition(
    key="progression.breakthrough_golden_core",
    target_realm="golden_core",
    source_realm="foundation",
    required_total_cultivation=11960,
    duration_seconds=5 * 60,
    materials={
        "item.pill.core_condense": 1,
        "item.material.cloud_iron": 3,
    },
    currency_cost=1000,
    base_success_bp=4000,
    minimum_success_bp=4000,
    maximum_success_bp=8500,
    pity_cap_bp=1500,
    pity_increment_bp=500,
    quality_bonus_divisor=5,
    quality_bonus_cap_bp=2000,
    technique_bonus_bp=300,
    formation_bonus_bp=0,
    retention_bp=4000,
    weakness_seconds=12 * 60 * 60,
    protection_key="item.pill.golden_core_guard",
    protection_retention_bp=7000,
    protection_weakness_seconds=4 * 60 * 60,
    rule_version="progression-0.2.0",
    random_pool="breakthrough.golden_core.v0.2",
    reward_world_merit=100,
    reward_local_reputation=50,
    reward_items={},
    source_cultivation_cap=7700,
    content_version="content-0.2",
    required_foundation_quality=4000,
    location_bonus_bp=300,
    support_bonus_bp=300,
    support_key="item.token.faction_seal",
)

NASCENT_SOUL_BREAKTHROUGH = BreakthroughDefinition(
    key="progression.breakthrough_nascent_soul",
    target_realm="nascent_soul",
    source_realm="golden_core",
    required_total_cultivation=58_960,
    duration_seconds=30 * 60,
    materials={
        "item.pill.soul_condense": 1,
        "item.soul_crystal": 5,
    },
    currency_cost=5_000,
    base_success_bp=5_500,
    minimum_success_bp=5_500,
    maximum_success_bp=9_000,
    pity_cap_bp=1_200,
    pity_increment_bp=400,
    quality_bonus_divisor=10,
    quality_bonus_cap_bp=1_000,
    technique_bonus_bp=300,
    formation_bonus_bp=300,
    retention_bp=6_500,
    weakness_seconds=0,
    protection_key="item.pill.soul_restore",
    protection_retention_bp=6_500,
    protection_weakness_seconds=0,
    rule_version="progression-0.3.0",
    random_pool="breakthrough.nascent_soul.v0.3",
    reward_world_merit=200,
    reward_items={},
    source_cultivation_cap=47_000,
    content_version="content-0.3",
    required_foundation_quality=5_500,
)

SOUL_TRANSFORMATION_BREAKTHROUGH = BreakthroughDefinition(
    key="progression.breakthrough_soul_transformation",
    target_realm="soul_transformation",
    source_realm="nascent_soul",
    required_total_cultivation=248_960,
    duration_seconds=10 * 60,
    materials={
        "item.soul_seed": 1,
        "item.domain_core": 1,
        "item.ancient_fruit": 3,
    },
    currency_cost=20_000,
    base_success_bp=6_500,
    minimum_success_bp=6_500,
    maximum_success_bp=9_000,
    pity_cap_bp=900,
    pity_increment_bp=300,
    quality_bonus_divisor=0,
    quality_bonus_cap_bp=0,
    technique_bonus_bp=0,
    formation_bonus_bp=0,
    retention_bp=7_000,
    weakness_seconds=0,
    protection_key="item.pill.domain_restore",
    protection_retention_bp=8_500,
    protection_weakness_seconds=8 * 60 * 60,
    rule_version="progression-0.4.0",
    random_pool="breakthrough.soul_transformation.v0.4",
    reward_world_merit=300,
    reward_items={"item.domain_core": 1},
    source_cultivation_cap=190_000,
    content_version="content-0.4",
)

VOID_REFINING_BREAKTHROUGH = BreakthroughDefinition(
    key="progression.breakthrough_void_refining",
    target_realm="void_refining",
    source_realm="soul_transformation",
    required_total_cultivation=848_960,
    duration_seconds=15 * 60,
    materials={"item.void_crystal": 5, "item.void_anchor": 2},
    currency_cost=80_000,
    base_success_bp=7_500,
    minimum_success_bp=7_500,
    maximum_success_bp=9_200,
    pity_cap_bp=750,
    pity_increment_bp=250,
    quality_bonus_divisor=0,
    quality_bonus_cap_bp=0,
    technique_bonus_bp=0,
    formation_bonus_bp=0,
    retention_bp=7_500,
    weakness_seconds=48 * 60 * 60,
    protection_key="",
    protection_retention_bp=7_500,
    protection_weakness_seconds=48 * 60 * 60,
    rule_version="progression-0.5.0",
    random_pool="breakthrough.void_refining.v0.5",
    reward_world_merit=500,
    reward_items={"item.void_anchor": 3},
    source_cultivation_cap=600_000,
    content_version="content-0.5",
)


def qi_gathering_breakthrough() -> BreakthroughDefinition:
    return QI_GATHERING_BREAKTHROUGH


def foundation_breakthrough() -> BreakthroughDefinition:
    return FOUNDATION_BREAKTHROUGH


def golden_core_breakthrough() -> BreakthroughDefinition:
    return GOLDEN_CORE_BREAKTHROUGH


def nascent_soul_breakthrough() -> BreakthroughDefinition:
    return NASCENT_SOUL_BREAKTHROUGH


def soul_transformation_breakthrough() -> BreakthroughDefinition:
    return SOUL_TRANSFORMATION_BREAKTHROUGH


def void_refining_breakthrough() -> BreakthroughDefinition:
    return VOID_REFINING_BREAKTHROUGH


def breakthrough_definition(target_realm: str) -> BreakthroughDefinition:
    if target_realm == "void_refinement":
        target_realm = "void_refining"
    if target_realm == QI_GATHERING_BREAKTHROUGH.target_realm:
        return QI_GATHERING_BREAKTHROUGH
    if target_realm == FOUNDATION_BREAKTHROUGH.target_realm:
        return FOUNDATION_BREAKTHROUGH
    if target_realm == GOLDEN_CORE_BREAKTHROUGH.target_realm:
        return GOLDEN_CORE_BREAKTHROUGH
    if target_realm == NASCENT_SOUL_BREAKTHROUGH.target_realm:
        return NASCENT_SOUL_BREAKTHROUGH
    if target_realm == SOUL_TRANSFORMATION_BREAKTHROUGH.target_realm:
        return SOUL_TRANSFORMATION_BREAKTHROUGH
    if target_realm == VOID_REFINING_BREAKTHROUGH.target_realm:
        return VOID_REFINING_BREAKTHROUGH
    raise ValueError(f"unsupported breakthrough target: {target_realm}")


def breakthrough_roll_bp(operation_id: str) -> int:
    """Return a deterministic roll in [0, 9999] for operation replay."""

    digest = blake2b(operation_id.encode("utf-8"), digest_size=2).digest()
    return int.from_bytes(digest, "big") % 10000


def success_bp(definition: BreakthroughDefinition, pity_bp: int, preparation_bp: int = 0) -> int:
    return max(
        definition.minimum_success_bp,
        min(
            definition.maximum_success_bp,
            definition.base_success_bp + max(0, pity_bp) + max(0, preparation_bp),
        ),
    )


def retained_cultivation(value: int, retention_bp: int, maximum: int) -> int:
    return max(0, min(maximum, (max(0, value) * retention_bp) // 10000))


def next_pity_bp(definition: BreakthroughDefinition, current: int, success: bool) -> int:
    if success:
        return 0
    return min(definition.pity_cap_bp, max(0, current) + definition.pity_increment_bp)


__all__ = [
    "QI_GATHERING_BREAKTHROUGH",
    "FOUNDATION_BREAKTHROUGH",
    "GOLDEN_CORE_BREAKTHROUGH",
    "NASCENT_SOUL_BREAKTHROUGH",
    "SOUL_TRANSFORMATION_BREAKTHROUGH",
    "VOID_REFINING_BREAKTHROUGH",
    "breakthrough_definition",
    "breakthrough_roll_bp",
    "foundation_breakthrough",
    "golden_core_breakthrough",
    "nascent_soul_breakthrough",
    "soul_transformation_breakthrough",
    "void_refining_breakthrough",
    "next_pity_bp",
    "qi_gathering_breakthrough",
    "retained_cultivation",
    "success_bp",
]
