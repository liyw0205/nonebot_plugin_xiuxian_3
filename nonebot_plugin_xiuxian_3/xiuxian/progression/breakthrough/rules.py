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
    rule_version="progression-0.1.4",
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


def qi_gathering_breakthrough() -> BreakthroughDefinition:
    return QI_GATHERING_BREAKTHROUGH


def foundation_breakthrough() -> BreakthroughDefinition:
    return FOUNDATION_BREAKTHROUGH


def golden_core_breakthrough() -> BreakthroughDefinition:
    return GOLDEN_CORE_BREAKTHROUGH


def breakthrough_definition(target_realm: str) -> BreakthroughDefinition:
    if target_realm == QI_GATHERING_BREAKTHROUGH.target_realm:
        return QI_GATHERING_BREAKTHROUGH
    if target_realm == FOUNDATION_BREAKTHROUGH.target_realm:
        return FOUNDATION_BREAKTHROUGH
    if target_realm == GOLDEN_CORE_BREAKTHROUGH.target_realm:
        return GOLDEN_CORE_BREAKTHROUGH
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
    "breakthrough_definition",
    "breakthrough_roll_bp",
    "foundation_breakthrough",
    "golden_core_breakthrough",
    "next_pity_bp",
    "qi_gathering_breakthrough",
    "retained_cultivation",
    "success_bp",
]
