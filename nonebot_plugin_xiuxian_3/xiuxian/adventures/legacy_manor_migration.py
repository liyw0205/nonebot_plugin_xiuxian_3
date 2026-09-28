"""SQLite schema owned by the legacy-manor domain."""

from __future__ import annotations

import sqlite3


def ensure_legacy_manor_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS legacy_manor_runs (
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
            content_version TEXT NOT NULL,
            rule_version TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_legacy_manor_player_status
            ON legacy_manor_runs(player_id, status, created_at);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_legacy_manor_player_active
            ON legacy_manor_runs(player_id) WHERE status IN ('routing', 'cleared');
        """
    )


__all__ = ["ensure_legacy_manor_schema"]
