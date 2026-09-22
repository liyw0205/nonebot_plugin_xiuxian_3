"""Progression application records."""

from __future__ import annotations

from dataclasses import dataclass

from ...contracts import PlayerView


@dataclass(frozen=True, slots=True)
class CultivationSessionRecord:
    player: PlayerView
    session_id: str
    mode_key: str
    status: str
    starts_at: str
    ends_at: str
    stamina_cost: int
    already_completed: bool = False


@dataclass(frozen=True, slots=True)
class CultivationSettlementRecord:
    player: PlayerView
    session_id: str
    cultivation_gain: int
    already_completed: bool = False


@dataclass(frozen=True, slots=True)
class CultivationCancelRecord:
    player: PlayerView
    session_id: str
    stamina_refund: int
    already_completed: bool = False


@dataclass(frozen=True, slots=True)
class LayerAdvanceRecord:
    player: PlayerView
    changed: bool
    already_completed: bool = False


@dataclass(frozen=True, slots=True)
class ResourceRecoveryRecord:
    player: PlayerView
    periods: int
    recovered_stamina: int
    recovered_energy: int
    changed: bool
    already_completed: bool = False


__all__ = [
    "CultivationCancelRecord",
    "CultivationSessionRecord",
    "CultivationSettlementRecord",
    "LayerAdvanceRecord",
    "ResourceRecoveryRecord",
]
