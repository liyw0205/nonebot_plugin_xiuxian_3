"""SQLite schema for time-fort team runs."""

from __future__ import annotations

import sqlite3


def ensure_time_fort_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS time_fort_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL UNIQUE,
            party_id TEXT NOT NULL REFERENCES parties(party_id),
            status TEXT NOT NULL CHECK (status IN ('routing', 'combat_pending', 'cleared', 'failed', 'expired', 'settled', 'system_aborted')),
            node_index INTEGER NOT NULL CHECK (node_index >= 0),
            battle_id TEXT,
            quota_key TEXT NOT NULL,
            starts_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            stamina_cost INTEGER NOT NULL CHECK (stamina_cost >= 0),
            snapshot_json TEXT NOT NULL,
            result_json TEXT NOT NULL DEFAULT '{}',
            entry_operation_id TEXT NOT NULL UNIQUE,
            content_version TEXT NOT NULL,
            rule_version TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_time_fort_party_status
            ON time_fort_runs(party_id, status, id);

        CREATE TABLE IF NOT EXISTS time_fort_members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL REFERENCES time_fort_runs(run_id),
            player_id INTEGER NOT NULL REFERENCES players(id),
            quota_key TEXT NOT NULL,
            member_order INTEGER NOT NULL CHECK (member_order >= 0),
            first_clear INTEGER NOT NULL CHECK (first_clear IN (0, 1)),
            status TEXT NOT NULL CHECK (status IN ('active', 'failed', 'expired', 'settled', 'system_aborted')),
            reward_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE (run_id, player_id)
        );
        CREATE INDEX IF NOT EXISTS idx_time_fort_member_quota
            ON time_fort_members(player_id, quota_key, status);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_time_fort_member_active
            ON time_fort_members(player_id) WHERE status='active';
        """
    )


__all__ = ["ensure_time_fort_schema"]
