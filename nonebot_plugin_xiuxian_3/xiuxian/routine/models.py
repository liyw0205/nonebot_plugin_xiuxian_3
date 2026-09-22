"""Immutable records exchanged by the routine application."""

from __future__ import annotations

from dataclasses import dataclass, field

from ...contracts import PlayerView


@dataclass(frozen=True, slots=True)
class RoutineClaimRecord:
    player: PlayerView
    activity_key: str
    target_date: str
    reward: dict[str, int] = field(default_factory=dict)
    energy_spent: int = 0
    spirit_stones_spent: int = 0
    consecutive_days: int = 0
    makeup: bool = False
    already_completed: bool = False


@dataclass(frozen=True, slots=True)
class SpiritTreeRecord:
    player: PlayerView
    status: str
    water_count: int
    energy_spent: int = 0
    reward: dict[str, int] = field(default_factory=dict)
    cooldown_until: str | None = None
    already_completed: bool = False


@dataclass(frozen=True, slots=True)
class SevenDayGoalView:
    day_number: int
    goal_key: str
    label: str
    target_date: str
    state: str
    reward: dict[str, int] = field(default_factory=dict)
    source_operation_id: str | None = None


@dataclass(frozen=True, slots=True)
class SevenDayStatusRecord:
    player: PlayerView
    start_date: str
    current_day: int
    status: str
    goals: tuple[SevenDayGoalView, ...]


@dataclass(frozen=True, slots=True)
class SevenDayGoalRecord:
    player: PlayerView
    day_number: int
    goal_key: str
    target_date: str
    reward: dict[str, int]
    source_operation_id: str
    campaign_complete: bool
    already_completed: bool = False


__all__ = [
    "RoutineClaimRecord",
    "SpiritTreeRecord",
    "SevenDayGoalView",
    "SevenDayStatusRecord",
    "SevenDayGoalRecord",
]
