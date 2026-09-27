"""Schema migration for immutable codex milestone claims."""

from __future__ import annotations

import sqlite3


def ensure_codex_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS codex_milestone_claims (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            player_id INTEGER NOT NULL REFERENCES players(id),
            milestone_key TEXT NOT NULL,
            content_version TEXT NOT NULL,
            operation_id TEXT NOT NULL UNIQUE,
            snapshot_json TEXT NOT NULL,
            reward_json TEXT NOT NULL,
            unlocks_json TEXT NOT NULL,
            claimed_at TEXT NOT NULL,
            UNIQUE (player_id, milestone_key, content_version)
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_codex_milestone_claims_player "
        "ON codex_milestone_claims(player_id, claimed_at)"
    )


__all__ = ["ensure_codex_schema"]
