"""Application records for residence services."""

from __future__ import annotations

from dataclasses import dataclass

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


__all__ = ["ResidenceRecord"]
