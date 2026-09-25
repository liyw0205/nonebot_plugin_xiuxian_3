"""Immutable records for the personal heart-demon event projection."""

from __future__ import annotations

from dataclasses import dataclass, field

from ...contracts import PlayerView


@dataclass(frozen=True, slots=True)
class HeartDemonEventRecord:
    player: PlayerView
    event_id: str
    event_key: str
    status: str
    breakthrough_session_id: str
    breakthrough_operation_id: str
    starts_at: str
    expires_at: str
    choice_key: str | None = None
    resolved_at: str | None = None
    snapshot: dict[str, object] = field(default_factory=dict)
    result: dict[str, object] = field(default_factory=dict)
    already_completed: bool = False


__all__ = ["HeartDemonEventRecord"]
