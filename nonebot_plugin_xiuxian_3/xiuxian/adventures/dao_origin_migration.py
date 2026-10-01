"""SQLite schema owned by the dao-origin secret-realm domain."""

from __future__ import annotations

import sqlite3


def ensure_dao_origin_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS dao_origin_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL UNIQUE,
            player_id INTEGER NOT NULL REFERENCES players(id),
            status TEXT NOT NULL CHECK (status IN ('routing', 'cleared', 'failed', 'expired', 'settled', 'system_aborted')),
            node_index INTEGER NOT NULL CHECK (node_index >= 0),
            quota_key TEXT NOT NULL,
            starts_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            stamina_cost INTEGER NOT NULL CHECK (stamina_cost >= 0),
            snapshot_json TEXT NOT NULL,
            result_json TEXT NOT NULL DEFAULT '{}',
            entry_operation_id TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_dao_origin_player_quota
            ON dao_origin_runs(player_id, quota_key, status);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_dao_origin_player_active
            ON dao_origin_runs(player_id) WHERE status IN ('routing', 'cleared');
        """
    )


__all__ = ["ensure_dao_origin_schema"]
