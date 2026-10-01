"""Schema for resumable ancestral-hall runs."""

from __future__ import annotations

import sqlite3


def ensure_ancestral_hall_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS ancestral_hall_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL UNIQUE,
            player_id INTEGER NOT NULL REFERENCES players(id),
            status TEXT NOT NULL CHECK (status IN ('routing', 'combat_pending', 'cleared', 'failed', 'expired', 'settled', 'system_aborted')),
            node_index INTEGER NOT NULL CHECK (node_index BETWEEN 0 AND 5),
            battle_id TEXT,
            quota_key TEXT NOT NULL,
            starts_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            stamina_cost INTEGER NOT NULL CHECK (stamina_cost = 25),
            snapshot_json TEXT NOT NULL DEFAULT '{}',
            result_json TEXT NOT NULL DEFAULT '{}',
            entry_operation_id TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_ancestral_hall_player_quota "
        "ON ancestral_hall_runs(player_id, quota_key, status)"
    )
    connection.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_ancestral_hall_player_active "
        "ON ancestral_hall_runs(player_id) WHERE status IN ('routing', 'combat_pending', 'cleared')"
    )


__all__ = ["ensure_ancestral_hall_schema"]
