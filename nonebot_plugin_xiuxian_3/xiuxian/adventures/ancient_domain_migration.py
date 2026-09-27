"""Schema for resumable ancient-domain party runs."""

from __future__ import annotations

import sqlite3


def ensure_ancient_domain_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS ancient_domain_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL UNIQUE,
            party_id TEXT NOT NULL REFERENCES parties(party_id),
            status TEXT NOT NULL CHECK (status IN ('routing', 'combat_pending', 'cleared', 'failed', 'expired', 'settled', 'system_aborted')),
            node_index INTEGER NOT NULL CHECK (node_index BETWEEN 0 AND 8),
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
        "CREATE INDEX IF NOT EXISTS idx_ancient_domain_party ON ancient_domain_runs(party_id, status, created_at)"
    )
    connection.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_ancient_domain_party_active "
        "ON ancient_domain_runs(party_id) WHERE status IN ('routing', 'combat_pending', 'cleared')"
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS ancient_domain_members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL REFERENCES ancient_domain_runs(run_id),
            player_id INTEGER NOT NULL REFERENCES players(id),
            quota_key TEXT NOT NULL,
            member_order INTEGER NOT NULL,
            first_clear INTEGER NOT NULL CHECK (first_clear IN (0, 1)),
            status TEXT NOT NULL CHECK (status IN ('active', 'cleared', 'failed', 'expired', 'released')),
            reward_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE (run_id, player_id),
            UNIQUE (player_id, quota_key)
        )
        """
    )
    connection.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_ancient_domain_member_active "
        "ON ancient_domain_members(player_id) WHERE status='active'"
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS ancient_domain_energy_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL REFERENCES ancient_domain_runs(run_id),
            battle_id TEXT NOT NULL,
            player_id INTEGER NOT NULL REFERENCES players(id),
            round_no INTEGER NOT NULL,
            amount INTEGER NOT NULL CHECK (amount > 0),
            created_at TEXT NOT NULL,
            UNIQUE (run_id, player_id, round_no)
        )
        """
    )


__all__ = ["ensure_ancient_domain_schema"]
