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
    energy_cost: int = 0
    state_bp: int = 10000
    cloud_tea_effect_bp: int = 0
    already_completed: bool = False


@dataclass(frozen=True, slots=True)
class CultivationMode:
    """Frozen parameters used when a cultivation session is created."""

    key: str
    label: str
    stamina_cost: int
    energy_cost: int
    duration_seconds: int
    base_cultivation: int
    environment_bp: int
    daily_limit: int | None
    rule_version: str
    required_location: str | None = None
    required_realm: str | None = None
    required_layer: int = 0
    requires_solitude: bool = False
    soul_power_gain: int = 0


@dataclass(frozen=True, slots=True)
class CultivationSettlementRecord:
    player: PlayerView
    session_id: str
    cultivation_gain: int
    mode_key: str = ""
    soul_power_gain: int = 0
    already_completed: bool = False


@dataclass(frozen=True, slots=True)
class CultivationRecoveryRecord:
    """A late settlement recovered from a session outside its normal window."""

    player: PlayerView
    session_id: str
    cultivation_gain: int
    mode_key: str = ""
    soul_power_gain: int = 0
    already_completed: bool = False


@dataclass(frozen=True, slots=True)
class CultivationCancelRecord:
    player: PlayerView
    session_id: str
    stamina_refund: int
    energy_refund: int = 0
    already_completed: bool = False


@dataclass(frozen=True, slots=True)
class LayerAdvanceRecord:
    player: PlayerView
    changed: bool
    already_completed: bool = False
    unlocks: tuple["LayerUnlock", ...] = ()


@dataclass(frozen=True, slots=True)
class LayerUnlock:
    """A content capability or preview unlocked at a progression milestone."""

    key: str
    title: str
    description: str
    status: str = "preview"


@dataclass(frozen=True, slots=True)
class ResourceRecoveryRecord:
    player: PlayerView
    periods: int
    recovered_stamina: int
    recovered_energy: int
    changed: bool
    already_completed: bool = False
    recovered_void_power: int = 0


__all__ = [
    "CultivationCancelRecord",
    "CultivationRecoveryRecord",
    "CultivationMode",
    "CultivationSessionRecord",
    "CultivationSettlementRecord",
    "LayerUnlock",
    "LayerAdvanceRecord",
    "ResourceRecoveryRecord",
]
