"""Adapter-neutral records for asynchronous dispatch tasks."""

from __future__ import annotations

from dataclasses import dataclass, field

from ...contracts import PlayerView


@dataclass(frozen=True, slots=True)
class DispatchPreviewRecord:
    dispatch_key: str
    label: str
    description: str
    duration_seconds: int
    daily_limit: int
    daily_used: int
    costs: dict[str, int]
    ready: bool
    missing: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DispatchAssignmentRecord:
    player: PlayerView
    assignment_id: str
    dispatch_key: str
    status: str
    outcome: str
    accepted_at: str
    running_at: str
    ends_at: str
    cancel_until: str
    costs: dict[str, int] = field(default_factory=dict)
    already_completed: bool = False


@dataclass(frozen=True, slots=True)
class DispatchSettlementRecord:
    player: PlayerView
    assignment_id: str
    dispatch_key: str
    status: str
    outcome: str
    reward: dict[str, int]
    refunded: dict[str, int] = field(default_factory=dict)
    already_completed: bool = False


@dataclass(frozen=True, slots=True)
class DispatchCancelRecord:
    player: PlayerView
    assignment_id: str
    dispatch_key: str
    status: str
    refunded: dict[str, int]
    already_completed: bool = False


__all__ = [
    "DispatchAssignmentRecord",
    "DispatchCancelRecord",
    "DispatchPreviewRecord",
    "DispatchSettlementRecord",
]
