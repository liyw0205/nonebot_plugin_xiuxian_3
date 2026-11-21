"""Persistent player-owned automatic battle preferences."""

from __future__ import annotations

import sqlite3


def ensure_combat_tactics_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS player_combat_tactics (
            player_id INTEGER PRIMARY KEY REFERENCES players(id) ON DELETE CASCADE,
            preferred_skill_key TEXT,
            updated_at TEXT NOT NULL
        )
        """
    )


__all__ = ["ensure_combat_tactics_schema"]
