"""Immutable records for the v0.1 mentor relationship slice."""

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
    service_reputation_delta: int = 0
    already_completed: bool = False


__all__ = ["MentorRelationRecord"]
