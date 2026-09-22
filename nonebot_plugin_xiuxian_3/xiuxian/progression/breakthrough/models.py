"""Immutable records exchanged by the breakthrough application."""

from __future__ import annotations

from dataclasses import dataclass

from ....contracts import PlayerView


@dataclass(frozen=True, slots=True)
class BreakthroughDefinition:
    key: str
    target_realm: str
    source_realm: str
    required_total_cultivation: int
    duration_seconds: int
    materials: dict[str, int]
    currency_cost: int
    base_success_bp: int
    minimum_success_bp: int
    maximum_success_bp: int
    pity_cap_bp: int
    retention_bp: int
    weakness_seconds: int
    protection_key: str
    protection_retention_bp: int
    protection_weakness_seconds: int
    rule_version: str
    random_pool: str


@dataclass(frozen=True, slots=True)
class BreakthroughSessionRecord:
    player: PlayerView
    session_id: str
    target_realm: str
    status: str
    starts_at: str
    ends_at: str
    success_bp: int
    protection_key: str | None = None
    already_completed: bool = False


@dataclass(frozen=True, slots=True)
class BreakthroughSettlementRecord:
    player: PlayerView
    session_id: str
    target_realm: str
    status: str
    success: bool
    roll_bp: int
    success_bp: int
    cultivation_before: int
    cultivation_after: int
    pity_before_bp: int
    pity_after_bp: int
    protection_consumed: bool
    weakness_until: str | None
    currency_spent: int
    materials: dict[str, int]
    already_completed: bool = False


@dataclass(frozen=True, slots=True)
class WeaknessRecoveryRecord:
    player: PlayerView
    early: bool
    spirit_stones_spent: int
    medicine_consumed: bool
    already_completed: bool = False
