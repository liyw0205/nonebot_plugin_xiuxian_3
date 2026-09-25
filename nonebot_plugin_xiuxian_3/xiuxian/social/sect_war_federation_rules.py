"""Rules for the closed cross-server sect-war preparation slice."""

from __future__ import annotations

from hashlib import sha256


CROSS_SERVER_SECT_WAR_KEY = "sect_war.cross_server"
CROSS_SERVER_SECT_WAR_CONTENT_VERSION = "content-0.5"
CROSS_SERVER_SECT_WAR_RULE_VERSION = "social-0.5.0"
CROSS_SERVER_ROSTER_CAP = 15


def federation_snapshot_id(round_id: str, shard_key: str, sect_id: str) -> str:
    """Create a stable private key without exposing platform identities."""

    digest = sha256(f"{round_id}:{shard_key}:{sect_id}".encode("utf-8")).hexdigest()[:24]
    return f"sect-war.federation:{digest}"


__all__ = [
    "CROSS_SERVER_ROSTER_CAP",
    "CROSS_SERVER_SECT_WAR_CONTENT_VERSION",
    "CROSS_SERVER_SECT_WAR_KEY",
    "CROSS_SERVER_SECT_WAR_RULE_VERSION",
    "federation_snapshot_id",
]
