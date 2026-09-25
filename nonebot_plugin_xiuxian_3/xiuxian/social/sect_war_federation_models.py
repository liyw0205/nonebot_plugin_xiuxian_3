"""DTOs for cross-server sect-war snapshots and imported results."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SectWarFederationSnapshotRecord:
    snapshot_id: str
    round_id: str
    shard_key: str
    sect_id: str
    roster_size: int
    frozen_at: str
    already_completed: bool = False


@dataclass(frozen=True, slots=True)
class SectWarFederationResultRecord:
    result_id: str
    round_id: str
    shard_key: str
    sect_id: str
    score: int
    winner: bool
    already_completed: bool = False


__all__ = ["SectWarFederationResultRecord", "SectWarFederationSnapshotRecord"]
