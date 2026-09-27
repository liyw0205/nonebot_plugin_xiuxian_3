"""Schema for resumable party boundary-rift runs."""

from __future__ import annotations

import sqlite3


def ensure_boundary_rift_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS boundary_rift_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL UNIQUE,
            party_id TEXT NOT NULL REFERENCES parties(party_id),
            status TEXT NOT NULL CHECK (status IN ('routing', 'combat_pending', 'cleared', 'failed', 'expired', 'settled')),
            node_index INTEGER NOT NULL CHECK (node_index BETWEEN 0 AND 6),
            battle_id TEXT,
            quota_key TEXT NOT NULL,
            starts_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            snapshot_json TEXT NOT NULL DEFAULT '{}',
            result_json TEXT NOT NULL DEFAULT '{}',
            entry_operation_id TEXT NOT NULL UNIQUE,
            content_version TEXT NOT NULL,
            rule_version TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_boundary_rift_party ON boundary_rift_runs(party_id, status, created_at)"
    )
    connection.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_boundary_rift_party_active "
        "ON boundary_rift_runs(party_id) WHERE status IN ('routing', 'combat_pending', 'cleared')"
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS boundary_rift_members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL REFERENCES boundary_rift_runs(run_id),
            player_id INTEGER NOT NULL REFERENCES players(id),
            quota_key TEXT NOT NULL,
            member_order INTEGER NOT NULL,
            first_clear INTEGER NOT NULL CHECK (first_clear IN (0, 1)),
            status TEXT NOT NULL CHECK (status IN ('active', 'cleared', 'failed', 'expired')),
            reward_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE (run_id, player_id),
            UNIQUE (player_id, quota_key)
        )
        """
    )
    connection.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_boundary_rift_member_active "
        "ON boundary_rift_members(player_id) WHERE status='active'"
    )


__all__ = ["ensure_boundary_rift_schema"]
