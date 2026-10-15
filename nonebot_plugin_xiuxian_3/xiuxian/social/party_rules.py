"""Pure rules for social party state machines (content-backed)."""

from __future__ import annotations

from dataclasses import dataclass

from .social_content import party_aliases, party_definitions

PARTY_TYPE_EXPLORATION_PAIR = "exploration_pair"
PARTY_TYPE_ARENA_TRIO = "arena_trio"
PARTY_TYPE_BOUNDARY_REALM = "boundary_realm"
PARTY_TYPE_DEMON_REALM = "demon_realm"
PARTY_TYPE_BEAST_REALM = "beast_realm"
PARTY_TYPE_STANDARD_PVE = "standard_pve"
PARTY_TYPE_SECRET_REALM_BOUNDARY = "secret_realm_boundary"
PARTY_TYPE_SECRET_REALM_ANCIENT = "secret_realm_ancient"
PARTY_TYPE_SECRET_REALM_VOID_RUINS = "secret_realm_void_ruins"
PARTY_TYPE_SECRET_REALM_TIME_FORT = "secret_realm_time_fort"
PARTY_TYPE_THREE_REALMS_TOWER_DUO = "three_realms_tower_duo"
# Keep the implementation name used by early design notes as an input alias.
PARTY_TYPE_PARTY_BOUNDARY = "party_boundary"

_PARTY_RECORDS = {record["party_type"]: record for record in party_definitions()}
_PARTY_ALIASES = party_aliases()

PARTY_MAX_MEMBERS = int(_PARTY_RECORDS[PARTY_TYPE_EXPLORATION_PAIR]["max_members"])
ARENA_TRIO_MAX_MEMBERS = int(_PARTY_RECORDS[PARTY_TYPE_ARENA_TRIO]["max_members"])
BOUNDARY_REALM_MIN_MEMBERS = int(_PARTY_RECORDS[PARTY_TYPE_BOUNDARY_REALM]["min_members"])
BOUNDARY_REALM_MAX_MEMBERS = int(_PARTY_RECORDS[PARTY_TYPE_BOUNDARY_REALM]["max_members"])
PARTY_CONFIRMATION_TTL_SECONDS = int(
    _PARTY_RECORDS[PARTY_TYPE_EXPLORATION_PAIR]["confirmation_ttl_seconds"]
)


@dataclass(frozen=True, slots=True)
class PartyDefinition:
    party_type: str = PARTY_TYPE_EXPLORATION_PAIR
    min_members: int = PARTY_MAX_MEMBERS
    max_members: int = PARTY_MAX_MEMBERS
    confirmation_ttl_seconds: int = PARTY_CONFIRMATION_TTL_SECONDS
    distribution_key: str = "contribution"
    required_location: str | None = None


def _definition(record: dict) -> PartyDefinition:
    return PartyDefinition(
        party_type=str(record["party_type"]),
        min_members=int(record["min_members"]),
        max_members=int(record["max_members"]),
        confirmation_ttl_seconds=int(record["confirmation_ttl_seconds"]),
        distribution_key=str(record["distribution_key"]),
        required_location=record["required_location"],
    )


PARTY_DEFINITION = _definition(_PARTY_RECORDS[PARTY_TYPE_EXPLORATION_PAIR])
ARENA_TRIO_DEFINITION = _definition(_PARTY_RECORDS[PARTY_TYPE_ARENA_TRIO])
BOUNDARY_REALM_DEFINITION = _definition(_PARTY_RECORDS[PARTY_TYPE_BOUNDARY_REALM])
SECRET_REALM_BOUNDARY_DEFINITION = _definition(
    _PARTY_RECORDS[PARTY_TYPE_SECRET_REALM_BOUNDARY]
)
SECRET_REALM_ANCIENT_DEFINITION = _definition(
    _PARTY_RECORDS[PARTY_TYPE_SECRET_REALM_ANCIENT]
)
SECRET_REALM_VOID_RUINS_DEFINITION = _definition(
    _PARTY_RECORDS[PARTY_TYPE_SECRET_REALM_VOID_RUINS]
)
SECRET_REALM_TIME_FORT_DEFINITION = _definition(
    _PARTY_RECORDS[PARTY_TYPE_SECRET_REALM_TIME_FORT]
)
DEMON_REALM_DEFINITION = _definition(_PARTY_RECORDS[PARTY_TYPE_DEMON_REALM])
BEAST_REALM_DEFINITION = _definition(_PARTY_RECORDS[PARTY_TYPE_BEAST_REALM])
STANDARD_PVE_DEFINITION = _definition(_PARTY_RECORDS[PARTY_TYPE_STANDARD_PVE])
THREE_REALMS_TOWER_DUO_DEFINITION = _definition(
    _PARTY_RECORDS[PARTY_TYPE_THREE_REALMS_TOWER_DUO]
)


def party_definition_for(party_type: str) -> PartyDefinition:
    resolved = _PARTY_ALIASES.get(party_type, party_type)
    record = _PARTY_RECORDS.get(resolved)
    if record is None:
        raise ValueError(f"unsupported party type: {party_type}")
    return _definition(record)


__all__ = [
    "PARTY_CONFIRMATION_TTL_SECONDS",
    "BOUNDARY_REALM_DEFINITION",
    "BEAST_REALM_DEFINITION",
    "STANDARD_PVE_DEFINITION",
    "DEMON_REALM_DEFINITION",
    "BOUNDARY_REALM_MAX_MEMBERS",
    "BOUNDARY_REALM_MIN_MEMBERS",
    "PARTY_DEFINITION",
    "ARENA_TRIO_DEFINITION",
    "ARENA_TRIO_MAX_MEMBERS",
    "PARTY_MAX_MEMBERS",
    "PARTY_TYPE_EXPLORATION_PAIR",
    "PARTY_TYPE_ARENA_TRIO",
    "PARTY_TYPE_BOUNDARY_REALM",
    "PARTY_TYPE_BEAST_REALM",
    "PARTY_TYPE_STANDARD_PVE",
    "PARTY_TYPE_SECRET_REALM_BOUNDARY",
    "PARTY_TYPE_SECRET_REALM_ANCIENT",
    "PARTY_TYPE_SECRET_REALM_VOID_RUINS",
    "PARTY_TYPE_SECRET_REALM_TIME_FORT",
    "PARTY_TYPE_DEMON_REALM",
    "PARTY_TYPE_THREE_REALMS_TOWER_DUO",
    "PARTY_TYPE_PARTY_BOUNDARY",
    "PartyDefinition",
    "THREE_REALMS_TOWER_DUO_DEFINITION",
    "party_definition_for",
]
