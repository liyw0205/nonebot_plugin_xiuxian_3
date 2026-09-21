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
