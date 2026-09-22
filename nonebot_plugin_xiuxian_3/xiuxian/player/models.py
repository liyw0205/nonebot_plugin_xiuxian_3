"""Player-specific application records."""

from __future__ import annotations

from dataclasses import dataclass
from ...contracts import PlayerView


@dataclass(frozen=True, slots=True)
class SeekingRecord:
    player: PlayerView
    created: bool
    already_completed: bool


@dataclass(frozen=True, slots=True)
class PlayerCreateRecord:
    player: PlayerView
    created: bool
    already_completed: bool


@dataclass(frozen=True, slots=True)
class RenameRecord:
    player: PlayerView
    changed: bool
    already_completed: bool


@dataclass(frozen=True, slots=True)
class IntroRecord:
    player: PlayerView
    guide_key: str
    changed: bool
    stage_advanced: bool
    item_quantity: int = 0
    selected_service: str | None = None
    already_completed: bool = False


@dataclass(frozen=True, slots=True)
class TravelRecord:
    player: PlayerView
    destination: str
    changed: bool
    stamina_cost: int
    already_completed: bool = False


@dataclass(frozen=True, slots=True)
class CultivationRecord:
    player: PlayerView
    path_key: str
    subprofession_key: str | None
    changed: bool
    already_completed: bool = False
