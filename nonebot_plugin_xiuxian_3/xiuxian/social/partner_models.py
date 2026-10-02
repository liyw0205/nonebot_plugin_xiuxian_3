"""Immutable records for the partner relationship lifecycle."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PartnerRelationRecord:
    relation_id: str
    status: str
    initiator_dao_name: str
    invitee_dao_name: str
    player_a_dao_name: str
    player_b_dao_name: str
    invited_at: str
    invitation_expires_at: str
    accepted_at: str | None = None
    dissolution_requested_by_dao_name: str | None = None
    dissolution_requested_at: str | None = None
    dissolution_expires_at: str | None = None
    dissolved_at: str | None = None
    cooldown_until: str | None = None
    already_completed: bool = False


__all__ = ["PartnerRelationRecord"]
