"""Immutable records for the mentor relationship slice."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MentorRelationRecord:
    relation_id: str
    status: str
    master_player_id: str
    master_platform_user_id: str
    master_dao_name: str
    apprentice_player_id: str
    apprentice_platform_user_id: str
    apprentice_dao_name: str
    expires_at: str
    accepted_at: str | None = None
    graduated_at: str | None = None
    master_contribution: int = 0
    apprentice_local_reputation: int = 0
    apprentice_service_reputation_gain: int = 0
    master_service_reputation_gain: int = 0
    already_completed: bool = False


@dataclass(frozen=True, slots=True)
class MentorRelationView:
    """Read-only relationship projection for the current player."""

    relation_id: str
    role: str
    counterpart_dao_name: str
    master_dao_name: str
    apprentice_dao_name: str
    status: str
    invited_at: str
    expires_at: str
    accepted_at: str | None = None
    rejected_at: str | None = None
    graduated_at: str | None = None
    master_contribution: int = 0


__all__ = ["MentorRelationRecord", "MentorRelationView"]
