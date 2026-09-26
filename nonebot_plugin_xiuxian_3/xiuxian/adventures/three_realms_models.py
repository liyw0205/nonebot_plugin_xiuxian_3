"""Records returned by the three-realms mainline application."""

from __future__ import annotations

from dataclasses import dataclass

from ...contracts import PlayerView
from .mainline_models import MainlineClaimRecord, MainlineStageView, MainlineStartRecord


@dataclass(frozen=True, slots=True)
class ThreeRealmsLaneProgress:
    lane: str
    completed: int
    total: int
    next_stage: int | None


@dataclass(frozen=True, slots=True)
class ThreeRealmsStatusRecord:
    player: PlayerView
    lanes: tuple[ThreeRealmsLaneProgress, ...]
    stages: tuple[MainlineStageView, ...]


__all__ = [
    "MainlineClaimRecord",
    "MainlineStageView",
    "MainlineStartRecord",
    "ThreeRealmsLaneProgress",
    "ThreeRealmsStatusRecord",
]
