"""Pure, versioned rules for social party state machines."""

from __future__ import annotations

from dataclasses import dataclass


PARTY_TYPE_EXPLORATION_PAIR = "exploration_pair"
PARTY_TYPE_ARENA_TRIO = "arena_trio"
PARTY_TYPE_BOUNDARY_REALM = "boundary_realm"
PARTY_TYPE_DEMON_REALM = "demon_realm"
PARTY_TYPE_BEAST_REALM = "beast_realm"
PARTY_TYPE_STANDARD_PVE = "standard_pve"
# Keep the implementation name used by early design notes as an input alias.
PARTY_TYPE_PARTY_BOUNDARY = "party_boundary"
PARTY_MAX_MEMBERS = 2
ARENA_TRIO_MAX_MEMBERS = 3
BOUNDARY_REALM_MIN_MEMBERS = 2
BOUNDARY_REALM_MAX_MEMBERS = 5
PARTY_CONFIRMATION_TTL_SECONDS = 5 * 60
PARTY_CONTENT_VERSION = "content-0.1"
PARTY_RULE_VERSION = "social-0.1.0"


@dataclass(frozen=True, slots=True)
class PartyDefinition:
    party_type: str = PARTY_TYPE_EXPLORATION_PAIR
    min_members: int = PARTY_MAX_MEMBERS
    max_members: int = PARTY_MAX_MEMBERS
    confirmation_ttl_seconds: int = PARTY_CONFIRMATION_TTL_SECONDS
    distribution_key: str = "contribution"
    required_location: str | None = None
    content_version: str = PARTY_CONTENT_VERSION
    rule_version: str = PARTY_RULE_VERSION


PARTY_DEFINITION = PartyDefinition()
ARENA_TRIO_DEFINITION = PartyDefinition(
    party_type=PARTY_TYPE_ARENA_TRIO,
    min_members=ARENA_TRIO_MAX_MEMBERS,
    max_members=ARENA_TRIO_MAX_MEMBERS,
    distribution_key="arena_rating",
    content_version="content-0.6",
    rule_version="social-0.6.0",
)
BOUNDARY_REALM_DEFINITION = PartyDefinition(
    party_type=PARTY_TYPE_BOUNDARY_REALM,
    min_members=BOUNDARY_REALM_MIN_MEMBERS,
    max_members=BOUNDARY_REALM_MAX_MEMBERS,
    required_location="cave.boundary_realm",
    distribution_key="contribution",
    content_version="content-0.3",
    rule_version="social-0.3.0",
)
DEMON_REALM_DEFINITION = PartyDefinition(
    party_type=PARTY_TYPE_DEMON_REALM,
    min_members=2,
    max_members=5,
    required_location="demon.fallen_ruins",
    distribution_key="contribution",
    content_version="content-0.3",
    rule_version="social-0.3.1",
)
BEAST_REALM_DEFINITION = PartyDefinition(
    party_type=PARTY_TYPE_BEAST_REALM,
    min_members=2,
    max_members=5,
    required_location="beast.ten_thousand_hills",
    distribution_key="contribution",
    content_version="content-0.3",
    rule_version="social-0.3.1",
)
STANDARD_PVE_DEFINITION = PartyDefinition(
    party_type=PARTY_TYPE_STANDARD_PVE,
    min_members=4,
    max_members=5,
    required_location=None,
    distribution_key="contribution",
    content_version="content-0.3",
    rule_version="social-0.3.2",
)


def party_definition_for(party_type: str) -> PartyDefinition:
    if party_type == PARTY_TYPE_ARENA_TRIO:
        return ARENA_TRIO_DEFINITION
    if party_type in {PARTY_TYPE_BOUNDARY_REALM, PARTY_TYPE_PARTY_BOUNDARY}:
        return BOUNDARY_REALM_DEFINITION
    if party_type == PARTY_TYPE_DEMON_REALM:
        return DEMON_REALM_DEFINITION
    if party_type == PARTY_TYPE_BEAST_REALM:
        return BEAST_REALM_DEFINITION
    if party_type == PARTY_TYPE_STANDARD_PVE:
        return STANDARD_PVE_DEFINITION
    if party_type != PARTY_TYPE_EXPLORATION_PAIR:
        raise ValueError(f"unsupported party type: {party_type}")
    return PARTY_DEFINITION


__all__ = [
    "PARTY_CONFIRMATION_TTL_SECONDS",
    "BOUNDARY_REALM_DEFINITION",
    "BEAST_REALM_DEFINITION",
    "STANDARD_PVE_DEFINITION",
    "DEMON_REALM_DEFINITION",
    "BOUNDARY_REALM_MAX_MEMBERS",
    "BOUNDARY_REALM_MIN_MEMBERS",
    "PARTY_CONTENT_VERSION",
    "PARTY_DEFINITION",
    "ARENA_TRIO_DEFINITION",
    "ARENA_TRIO_MAX_MEMBERS",
    "PARTY_MAX_MEMBERS",
    "PARTY_RULE_VERSION",
    "PARTY_TYPE_EXPLORATION_PAIR",
    "PARTY_TYPE_ARENA_TRIO",
    "PARTY_TYPE_BOUNDARY_REALM",
    "PARTY_TYPE_BEAST_REALM",
    "PARTY_TYPE_STANDARD_PVE",
    "PARTY_TYPE_DEMON_REALM",
    "PARTY_TYPE_PARTY_BOUNDARY",
    "PartyDefinition",
    "party_definition_for",
]
