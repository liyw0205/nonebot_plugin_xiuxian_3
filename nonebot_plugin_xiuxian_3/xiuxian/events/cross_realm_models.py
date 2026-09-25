"""Immutable DTOs for v0.3 cross-realm public events."""

from __future__ import annotations

from dataclasses import dataclass, field

from ...contracts import PlayerView


@dataclass(frozen=True, slots=True)
class CrossRealmEventRecord:
    player: PlayerView
    round_id: str
    event_key: str
    status: str
    starts_at: str
    ends_at: str
    claim_expires_at: str
    target_quantity: int
    total_contribution: int
    player_contribution: int
    success: bool | None
    reward: dict[str, int] = field(default_factory=dict)
    already_completed: bool = False


__all__ = ["CrossRealmEventRecord"]
