"""Immutable records exchanged by world-event use cases."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ...contracts import PlayerView


@dataclass(frozen=True, slots=True)
class SpiritSpringEventRecord:
    player: PlayerView
    round_id: str
    event_key: str
    status: str
    starts_at: str
    ends_at: str
    claim_expires_at: str
    target_quantity: int
    minimum_contribution: int
    contribution_cap: int
    source_item_key: str
    source_item_name: str
    event_name: str
    event_description: str
    total_contribution: int
    player_contribution: int
    success: bool | None
    reward: dict[str, int] = field(default_factory=dict)
    reward_snapshot: dict[str, Any] = field(default_factory=dict)
    already_completed: bool = False


__all__ = ["SpiritSpringEventRecord"]
