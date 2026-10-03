"""Records returned by daily task use cases."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ...contracts import PlayerView


@dataclass(frozen=True, slots=True)
class DailyTaskView:
    task_key: str
    name: str
    description: str
    progress: int
    target: int
    status: str


@dataclass(frozen=True, slots=True)
class DailyQuestRecord:
    player: PlayerView
    round_id: str
    business_date: str
    starts_at: str
    ends_at: str
    claim_expires_at: str
    status: str
    completed_count: int
    completion_threshold: int
    tasks: tuple[DailyTaskView, ...]
    reward: dict[str, int] = field(default_factory=dict)
    snapshot: dict[str, Any] = field(default_factory=dict)
    already_completed: bool = False


__all__ = ["DailyQuestRecord", "DailyTaskView"]
