"""Application records for residence and field services."""

from __future__ import annotations

from dataclasses import dataclass, field

from ...contracts import PlayerView


@dataclass(frozen=True, slots=True)
class ResidenceRecord:
    player: PlayerView
    residence_id: str
    residence_key: str
    status: str
    starts_at: str
    ends_at: str
    rent_cost: int
    already_completed: bool = False


@dataclass(frozen=True, slots=True)
class FieldPlotRecord:
    player: PlayerView
    plot_id: str
    residence_id: str
    crop_key: str | None
    status: str
    planted_at: str | None
    harvest_at: str | None
    maintenance_count: int = 0
    required_maintenance: int = 0
    harvest: dict[str, int] = field(default_factory=dict)
    local_reputation_delta: int = 0
    already_completed: bool = False


@dataclass(frozen=True, slots=True)
class TownCommissionView:
    commission_id: str
    commission_key: str
    label: str
    business_date: str
    status: str
    stock_remaining: int
    stock_total: int
    inputs: dict[str, int] = field(default_factory=dict)
    reward_stones: int = 0
    local_reputation: int = 0
    service_reputation: int = 0
    expires_at: str = ""
    accepted: bool = False
    delivered: bool = False


@dataclass(frozen=True, slots=True)
class TownCommissionRecord:
    player: PlayerView
    claim_id: str
    commission_id: str
    commission_key: str
    label: str
    business_date: str
    status: str
    stock_remaining: int
    inputs: dict[str, int] = field(default_factory=dict)
    reward_stones: int = 0
    local_reputation: int = 0
    service_reputation: int = 0
    expires_at: str = ""
    already_completed: bool = False


__all__ = ["FieldPlotRecord", "ResidenceRecord", "TownCommissionRecord", "TownCommissionView"]
