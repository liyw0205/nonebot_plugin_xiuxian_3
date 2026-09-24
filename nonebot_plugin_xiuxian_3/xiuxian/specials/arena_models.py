"""Adapter-neutral records for asynchronous arena matches."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class ArenaSnapshotRecord:
    snapshot_id: str
    status: str
    public_summary: dict[str, object]
    rating: int
    matchable_at: str
    expires_at: str
    already_completed: bool = False


@dataclass(frozen=True, slots=True)
class ArenaMatchRecord:
    match_id: str
    outcome: str
    rounds: int
    score_counted: bool
    challenger_rating: int
    defender_rating: int
    challenger_rating_delta: int
    defender_rating_delta: int
    opponent_summary: dict[str, object]
    already_completed: bool = False


@dataclass(frozen=True, slots=True)
class ArenaReplayRecord:
    match_id: str
    status: str
    outcome: str
    rounds: int
    score_counted: bool
    snapshot: dict[str, object]
    result: dict[str, object]
    actions: tuple[dict[str, object], ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class ArenaClaimRecord:
    match_id: str
    reward: dict[str, int]
    already_completed: bool = False


__all__ = [
    "ArenaClaimRecord",
    "ArenaMatchRecord",
    "ArenaReplayRecord",
    "ArenaSnapshotRecord",
]
