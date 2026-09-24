"""Adapter-neutral records for asynchronous 2v2 arena matches."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class TeamArenaSnapshotRecord:
    snapshot_id: str
    party_id: str
    status: str
    public_summary: dict[str, object]
    rating: int
    matchable_at: str
    expires_at: str
    already_completed: bool = False


@dataclass(frozen=True, slots=True)
class TeamArenaMatchRecord:
    match_id: str
    outcome: str
    rounds: int
    challenger_rating: int
    defender_rating: int
    opponent_summary: dict[str, object]
    already_completed: bool = False


@dataclass(frozen=True, slots=True)
class TeamArenaReplayRecord:
    match_id: str
    status: str
    outcome: str
    rounds: int
    snapshot: dict[str, object]
    result: dict[str, object]
    actions: tuple[dict[str, object], ...] = field(default_factory=tuple)


__all__ = [
    "TeamArenaMatchRecord",
    "TeamArenaReplayRecord",
    "TeamArenaSnapshotRecord",
]
