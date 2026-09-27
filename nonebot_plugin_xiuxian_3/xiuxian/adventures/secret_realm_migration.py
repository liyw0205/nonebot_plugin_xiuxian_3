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
            content_version TEXT NOT NULL,
            rule_version TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )


def _remove_legacy_quota_unique(connection: sqlite3.Connection) -> None:
    row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='secret_realm_runs'"
    ).fetchone()
    if row is None or "UNIQUE (player_id, instance_key, quota_key)" not in str(row[0]):
        return
    connection.execute("DROP INDEX IF EXISTS idx_secret_realm_runs_player")
    connection.execute("DROP INDEX IF EXISTS idx_secret_realm_runs_active")
    _create_runs_table(connection, "secret_realm_runs_v01_new")
    connection.execute(
        """
        INSERT INTO secret_realm_runs_v01_new(
            id, run_id, player_id, instance_key, status, node_index, battle_id,
            starts_at, expires_at, quota_period, quota_key, ticket_key,
            ticket_locked, stamina_locked, snapshot_json, result_json,
            content_version, rule_version, created_at, updated_at
        )
        SELECT
            id, run_id, player_id, instance_key, status, node_index, battle_id,
            starts_at, expires_at, quota_period, quota_key, ticket_key,
            ticket_locked, stamina_locked, snapshot_json, result_json,
            content_version, rule_version, created_at, updated_at
        FROM secret_realm_runs
        """
    )
    connection.execute("DROP TABLE secret_realm_runs")
    connection.execute("ALTER TABLE secret_realm_runs_v01_new RENAME TO secret_realm_runs")


def ensure_secret_realm_schema(connection: sqlite3.Connection) -> None:
    _create_runs_table(connection)
    _remove_legacy_quota_unique(connection)
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_secret_realm_runs_player ON secret_realm_runs(player_id, status, created_at)"
    )
    connection.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_secret_realm_runs_active ON secret_realm_runs(player_id) WHERE status IN ('entered', 'routing', 'combat_pending', 'cleared', 'failed')"
    )


__all__ = ["ensure_secret_realm_schema"]
