"""Schema owned by the secret-realm adventure domain."""

from __future__ import annotations

import sqlite3


def _create_runs_table(connection: sqlite3.Connection, table_name: str = "secret_realm_runs") -> None:
    connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {table_name} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL UNIQUE,
            player_id INTEGER NOT NULL REFERENCES players(id),
            instance_key TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('entered', 'routing', 'combat_pending', 'cleared', 'failed', 'expired', 'settled')),
            node_index INTEGER NOT NULL CHECK (node_index >= 0),
            battle_id TEXT,
            starts_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            quota_period TEXT NOT NULL,
            quota_key TEXT NOT NULL,
            ticket_key TEXT,
            ticket_locked INTEGER NOT NULL DEFAULT 0 CHECK (ticket_locked >= 0),
            stamina_locked INTEGER NOT NULL DEFAULT 0 CHECK (stamina_locked >= 0),
            snapshot_json TEXT NOT NULL DEFAULT '{{}}',
            result_json TEXT NOT NULL DEFAULT '{{}}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )


def ensure_secret_realm_schema(connection: sqlite3.Connection) -> None:
    _create_runs_table(connection)
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_secret_realm_runs_player ON secret_realm_runs(player_id, status, created_at)"
    )
    connection.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_secret_realm_runs_active ON secret_realm_runs(player_id) WHERE status IN ('entered', 'routing', 'combat_pending', 'cleared', 'failed')"
    )


__all__ = ["ensure_secret_realm_schema"]
