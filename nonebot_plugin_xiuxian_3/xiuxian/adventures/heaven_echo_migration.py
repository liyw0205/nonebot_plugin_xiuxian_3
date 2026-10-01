"""SQLite schema owned by the heaven-echo secret-realm domain."""

from __future__ import annotations

import sqlite3


def ensure_heaven_echo_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS heaven_echo_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL UNIQUE,
            player_id INTEGER NOT NULL REFERENCES players(id),
            status TEXT NOT NULL CHECK (status IN ('routing', 'cleared', 'expired', 'settled', 'system_aborted')),
            node_index INTEGER NOT NULL CHECK (node_index >= 0),
            starts_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            snapshot_json TEXT NOT NULL,
            result_json TEXT NOT NULL DEFAULT '{}',
            entry_operation_id TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_heaven_echo_player_status
            ON heaven_echo_runs(player_id, status, created_at);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_heaven_echo_player_active
            ON heaven_echo_runs(player_id) WHERE status IN ('routing', 'cleared');
        """
    )


__all__ = ["ensure_heaven_echo_schema"]
