"""Application records for the advancement domain."""

from __future__ import annotations

from dataclasses import dataclass, field

from ...contracts import PlayerView


@dataclass(frozen=True, slots=True)
class RetreatSessionRecord:
    player: PlayerView
    session_id: str
    retreat_key: str
    status: str
    starts_at: str
    ends_at: str
    energy_cost: int
    item_cost: dict[str, int] = field(default_factory=dict)
    already_completed: bool = False


@dataclass(frozen=True, slots=True)
class RetreatSettlementRecord:
    player: PlayerView
    session_id: str
    retreat_key: str
    status: str
    result: dict[str, int] = field(default_factory=dict)
    cycles: int = 1
    expired: bool = False
    already_completed: bool = False


__all__ = ["RetreatSessionRecord", "RetreatSettlementRecord"]
