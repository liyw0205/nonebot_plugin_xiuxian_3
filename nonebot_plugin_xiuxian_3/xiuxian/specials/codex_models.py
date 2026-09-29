"""Immutable application records for codex queries and milestone claims."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CodexEntryRecord:
    entry_key: str
    category: str
    label: str
    first_seen_at: str


@dataclass(frozen=True, slots=True)
class CodexMilestoneRecord:
    milestone_key: str
    label: str
    discovered_count: int
    required_count: int
    ready: bool
    claimed: bool
    reputation_key: str | None
    reputation_reward: int
    unlocks: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CodexOverviewRecord:
    entries: tuple[CodexEntryRecord, ...]
    milestones: tuple[CodexMilestoneRecord, ...]


@dataclass(frozen=True, slots=True)
class CodexMilestoneClaimRecord:
    milestone_key: str
    reward: dict[str, int]
    unlocks: tuple[str, ...]
    already_completed: bool = False


__all__ = [
    "CodexEntryRecord",
    "CodexMilestoneClaimRecord",
    "CodexMilestoneRecord",
    "CodexOverviewRecord",
]
