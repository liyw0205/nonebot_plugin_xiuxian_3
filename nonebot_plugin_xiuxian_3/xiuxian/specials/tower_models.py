"""Immutable records for tower previews, runs, and reward claims."""

from __future__ import annotations

from dataclasses import dataclass, field

from ...contracts import PlayerView


@dataclass(frozen=True, slots=True)
class TowerPreviewRecord:
    player: PlayerView
    highest_floor: int
    next_floor: int
    active_floor: int | None
    active_status: str | None
    stamina_cost: int
    daily_limit: int
    daily_used: int
    practice_used: int


@dataclass(frozen=True, slots=True)
class TowerRunRecord:
    player: PlayerView
    run_id: str
    tower_key: str
    floor_no: int
    status: str
    battle_id: str | None
    first_clear: bool
    outcome: str | None = None
    reason: str | None = None
    reward: dict[str, int] = field(default_factory=dict)
    already_completed: bool = False


@dataclass(frozen=True, slots=True)
class TowerRewardRecord:
    player: PlayerView
    run_id: str
    floor_no: int
    first_clear: bool
    reward: dict[str, int]
    already_completed: bool = False


__all__ = ["TowerPreviewRecord", "TowerRewardRecord", "TowerRunRecord"]
