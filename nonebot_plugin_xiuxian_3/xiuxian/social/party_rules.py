"""Pure rules for the v0.1 two-player exploration party slice."""

from __future__ import annotations

from dataclasses import dataclass


PARTY_TYPE_EXPLORATION_PAIR = "exploration_pair"
PARTY_TYPE_ARENA_TRIO = "arena_trio"
PARTY_MAX_MEMBERS = 2
ARENA_TRIO_MAX_MEMBERS = 3
PARTY_CONFIRMATION_TTL_SECONDS = 5 * 60
PARTY_CONTENT_VERSION = "content-0.1"
PARTY_RULE_VERSION = "social-0.1.0"


@dataclass(frozen=True, slots=True)
class PartyDefinition:
    party_type: str = PARTY_TYPE_EXPLORATION_PAIR
    max_members: int = PARTY_MAX_MEMBERS
    confirmation_ttl_seconds: int = PARTY_CONFIRMATION_TTL_SECONDS
    distribution_key: str = "contribution"
    content_version: str = PARTY_CONTENT_VERSION
    rule_version: str = PARTY_RULE_VERSION


PARTY_DEFINITION = PartyDefinition()
ARENA_TRIO_DEFINITION = PartyDefinition(
    party_type=PARTY_TYPE_ARENA_TRIO,
    max_members=ARENA_TRIO_MAX_MEMBERS,
    distribution_key="arena_rating",
    content_version="content-0.6",
    rule_version="social-0.6.0",
)


def party_definition_for(party_type: str) -> PartyDefinition:
    if party_type == PARTY_TYPE_ARENA_TRIO:
        return ARENA_TRIO_DEFINITION
    return PARTY_DEFINITION


__all__ = [
    "PARTY_CONFIRMATION_TTL_SECONDS",
    "PARTY_CONTENT_VERSION",
    "PARTY_DEFINITION",
    "ARENA_TRIO_DEFINITION",
    "ARENA_TRIO_MAX_MEMBERS",
    "PARTY_MAX_MEMBERS",
    "PARTY_RULE_VERSION",
    "PARTY_TYPE_EXPLORATION_PAIR",
    "PARTY_TYPE_ARENA_TRIO",
    "PartyDefinition",
    "party_definition_for",
]
