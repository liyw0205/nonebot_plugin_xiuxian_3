"""Application records for the dao echoes mainline."""

from __future__ import annotations

from dataclasses import dataclass

from ...contracts import PlayerView
from .mainline_models import MainlineClaimRecord, MainlineStartRecord, MainlineStageView


@dataclass(frozen=True, slots=True)
class DaoEchoesLaneProgress:
    lane: str
    completed: int
    total: int
    next_stage: int | None


@dataclass(frozen=True, slots=True)
class DaoEchoesStatusRecord:
    player: PlayerView
    lanes: tuple[DaoEchoesLaneProgress, ...]
    stages: tuple[MainlineStageView, ...]


__all__ = [
    "DaoEchoesLaneProgress",
    "DaoEchoesStatusRecord",
    "MainlineClaimRecord",
    "MainlineStartRecord",
    "MainlineStageView",
]
