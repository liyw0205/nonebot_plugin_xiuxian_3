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
    retention_bp=8000,
    weakness_seconds=2 * 60 * 60,
    protection_key="item.pill.qi_guard",
    protection_retention_bp=9000,
    protection_weakness_seconds=30 * 60,
    rule_version="progression-0.1.3",
    random_pool="breakthrough.qi_gathering.v0.1",
)


def qi_gathering_breakthrough() -> BreakthroughDefinition:
    return QI_GATHERING_BREAKTHROUGH


def breakthrough_roll_bp(operation_id: str) -> int:
    """Return a deterministic roll in [0, 9999] for operation replay."""

    digest = blake2b(operation_id.encode("utf-8"), digest_size=2).digest()
    return int.from_bytes(digest, "big") % 10000


def success_bp(definition: BreakthroughDefinition, pity_bp: int) -> int:
    return max(
        definition.minimum_success_bp,
        min(definition.maximum_success_bp, definition.base_success_bp + max(0, pity_bp)),
    )


def retained_cultivation(value: int, retention_bp: int, maximum: int) -> int:
    return max(0, min(maximum, (max(0, value) * retention_bp) // 10000))


def next_pity_bp(definition: BreakthroughDefinition, current: int, success: bool) -> int:
    if success:
        return 0
    return min(definition.pity_cap_bp, max(0, current) + 300)


__all__ = [
    "QI_GATHERING_BREAKTHROUGH",
    "breakthrough_roll_bp",
    "next_pity_bp",
    "qi_gathering_breakthrough",
    "retained_cultivation",
    "success_bp",
]
