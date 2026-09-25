"""Transport-neutral records for the v0.5 void archive slice."""

from __future__ import annotations

from dataclasses import dataclass, field

from ...contracts import PlayerView


@dataclass(frozen=True, slots=True)
class VoidArchiveStatusRecord:
    player: PlayerView
    week_id: str
    week_ends_at: str
    tasks: dict[str, dict[str, object]]
    unlocked: bool
    unlock_expires_at: str | None


@dataclass(frozen=True, slots=True)
class VoidArchiveRunRecord:
    player: PlayerView
    run_id: str
    battle_id: str
    route_session_id: str
    outcome: str
    reward: dict[str, int] = field(default_factory=dict)
    already_completed: bool = False


@dataclass(frozen=True, slots=True)
class VoidArchiveTaskClaimRecord:
    player: PlayerView
    week_id: str
    task_key: str
    progress: int
    target: int
    reward: dict[str, int]
    unlock_activated: bool
    already_completed: bool = False


__all__ = [
    "VoidArchiveRunRecord",
    "VoidArchiveStatusRecord",
    "VoidArchiveTaskClaimRecord",
]
