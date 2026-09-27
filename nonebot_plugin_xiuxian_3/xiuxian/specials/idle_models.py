"""Adapter-neutral records for server-timed idle assignments."""

from __future__ import annotations

from dataclasses import dataclass, field

from ...contracts import PlayerView


@dataclass(frozen=True, slots=True)
class IdleRoutePreviewRecord:
    route_key: str
    label: str
    duration_seconds: int
    stamina_cost: int
    energy_cost: int
    daily_limit: int
    daily_used: int
    ready: bool
    missing: tuple[str, ...] = ()
    requirements: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class IdleAssignmentRecord:
    player: PlayerView
    assignment_id: str
    route_key: str
    status: str
    starts_at: str
    claim_at: str
    max_claim_at: str
    cancel_until: str
    cost: dict[str, int]
    tool_key: str | None = None
    facility_slot_key: str | None = None
    result: dict[str, int] = field(default_factory=dict)
    fallback: bool = False
    already_completed: bool = False


@dataclass(frozen=True, slots=True)
class IdleSettlementRecord:
    player: PlayerView
    assignment_id: str
    route_key: str
    status: str
    reward: dict[str, int]
    fallback: bool
    tool_durability_before: int | None = None
    tool_durability_after: int | None = None
    already_completed: bool = False


@dataclass(frozen=True, slots=True)
class IdleCancelRecord:
    player: PlayerView
    assignment_id: str
    route_key: str
    status: str
    refunded: dict[str, int]
    returned_tool_key: str | None = None
    already_completed: bool = False


__all__ = [
    "IdleAssignmentRecord",
    "IdleCancelRecord",
    "IdleRoutePreviewRecord",
    "IdleSettlementRecord",
]
