"""Application records for the sect membership slice."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SectRecord:
    sect_id: str
    name: str
    motto: str
    status: str
    leader_player_id: str
    role: str
    member_count: int
    max_members: int
    construction: int
    spirit_stones: int
    created_at: str
    already_completed: bool = False


@dataclass(frozen=True, slots=True)
class SectApplicationRecord:
    application_id: str
    sect_id: str
    sect_name: str
    applicant_player_id: str
    applicant_name: str
    status: str
    reason: str
    review_reason: str
    expires_at: str
    created_at: str
    reviewer_player_id: str | None = None
    already_completed: bool = False


__all__ = ["SectApplicationRecord", "SectRecord"]
