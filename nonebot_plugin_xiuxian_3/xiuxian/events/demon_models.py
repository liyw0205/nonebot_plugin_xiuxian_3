"""Immutable DTOs for the demon invasion event."""

from __future__ import annotations

from dataclasses import dataclass, field

from ...contracts import PlayerView


@dataclass(frozen=True, slots=True)
class DemonInvasionEventRecord:
    player: PlayerView
    round_id: str
    event_key: str
    status: str
    starts_at: str
    ends_at: str
    claim_expires_at: str
    target_quantity: int
    minimum_contribution: int
    total_contribution: int
    player_contribution: int
    success: bool | None
    base_contribution: int = 0
    route_bonus_bp: int = 0
    applied_contribution: int = 0
    reward: dict[str, int] = field(default_factory=dict)
    already_completed: bool = False


__all__ = ["DemonInvasionEventRecord"]
