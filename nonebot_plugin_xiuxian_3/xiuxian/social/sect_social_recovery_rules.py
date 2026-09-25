"""Stable rules for cross-server social recovery drills."""

from __future__ import annotations

import re


SOCIAL_RECOVERY_RULE_VERSION = "social-recovery-0.1.0"
SOCIAL_RECOVERY_CONTENT_VERSION = "content-0.5"
SOCIAL_RECOVERY_ARTIFACT_ROOT = "backups/social"
SOCIAL_RECOVERY_ARTIFACT_KEY = re.compile(r"^[a-z0-9-]{1,48}$")

SOCIAL_RECOVERY_TABLES = (
    "sect_war_federation_snapshots",
    "sect_war_federation_results",
    "sect_cross_server_war_rounds",
    "sect_cross_server_war_registrations",
    "sect_cross_server_war_members",
    "sect_cross_server_war_actions",
    "sect_cross_server_war_sessions",
    "sect_cross_server_reward_boxes",
    "sect_cross_server_reward_allocations",
    "sect_cross_server_weekly_rewards",
    "sect_void_fortresses",
    "sect_void_beacons",
    "sect_alliance_contracts",
    "sect_alliance_cooldowns",
    "sect_recipe_unlocks",
    "sect_alliance_research",
    "arena_identity_routes",
    "arena_audit_events",
    "social_recovery_events",
)


def validate_social_recovery_artifact_key(value: str) -> str:
    key = str(value).strip()
    if not SOCIAL_RECOVERY_ARTIFACT_KEY.fullmatch(key):
        raise ValueError("social recovery artifact key is invalid")
    return key


__all__ = [
    "SOCIAL_RECOVERY_ARTIFACT_KEY",
    "SOCIAL_RECOVERY_ARTIFACT_ROOT",
    "SOCIAL_RECOVERY_CONTENT_VERSION",
    "SOCIAL_RECOVERY_RULE_VERSION",
    "SOCIAL_RECOVERY_TABLES",
    "validate_social_recovery_artifact_key",
]
