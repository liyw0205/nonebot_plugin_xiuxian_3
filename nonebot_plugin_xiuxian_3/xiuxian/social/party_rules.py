"""Pure rules for the v0.1 two-player exploration party slice."""

from __future__ import annotations

from dataclasses import dataclass


PARTY_TYPE_EXPLORATION_PAIR = "exploration_pair"
PARTY_MAX_MEMBERS = 2
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


__all__ = [
    "PARTY_CONFIRMATION_TTL_SECONDS",
    "PARTY_CONTENT_VERSION",
    "PARTY_DEFINITION",
    "PARTY_MAX_MEMBERS",
    "PARTY_RULE_VERSION",
    "PARTY_TYPE_EXPLORATION_PAIR",
    "PartyDefinition",
]
