"""Immutable records for the endgame final arena."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FinalArenaTierState:
    key: str
    label: str
    tier_no: int
    enemy_key: str
    required_best_tier: int
    unlocked: bool
    cleared: bool
    title_key: str | None = None


@dataclass(frozen=True, slots=True)
class FinalArenaPreviewRecord:
    location_key: str
    round_id: str
    starts_at: str
    ends_at: str
    claim_expires_at: str
    open: bool
    at_location: bool
    qualified: bool
    missing: tuple[str, ...]
    attempt_limit: int
    attempts_used: int
    best_tier: int
    summit_cleared: bool
    tiers: tuple[FinalArenaTierState, ...]


@dataclass(frozen=True, slots=True)
class FinalArenaChallengeRecord:
    challenge_id: str
    tier_key: str
    label: str
    tier_no: int
    enemy_key: str
    round_id: str
    starts_at: str
    ends_at: str
    attempts_used: int
    attempt_limit: int
    best_tier: int
    status: str
    outcome: str
    reason: str
    summit_cleared: bool
    title_granted: str | None
    already_completed: bool = False


__all__ = [
    "FinalArenaChallengeRecord",
    "FinalArenaPreviewRecord",
    "FinalArenaTierState",
]
