"""Immutable records for the two-player party state machine."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PartyMemberRecord:
    player_id: str
    platform_user_id: str
    dao_name: str
    role: str
    status: str
    confirmed_at: str | None = None


@dataclass(frozen=True, slots=True)
class PartyRecord:
    party_id: str
    party_type: str
    status: str
    leader_player_id: str
    location_key: str
    confirmation_deadline: str
    members: tuple[PartyMemberRecord, ...]
    distribution_key: str
    already_completed: bool = False

    @property
    def ready(self) -> bool:
        active = [member for member in self.members if member.status == "active"]
        return self.status == "ready" and len(active) == 2 and all(member.confirmed_at for member in active)


@dataclass(frozen=True, slots=True)
class PartyInvitationRecord:
    party_id: str
    party_type: str
    leader_player_id: str
    location_key: str
    confirmation_deadline: str
    status: str
    already_completed: bool = False


__all__ = ["PartyInvitationRecord", "PartyMemberRecord", "PartyRecord"]
