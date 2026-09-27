"""SQLite schema owned by dispatch tasks."""

from __future__ import annotations

import sqlite3


def ensure_dispatch_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS dispatch_assignments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            assignment_id TEXT NOT NULL UNIQUE,
            player_id INTEGER NOT NULL REFERENCES players(id),
            operation_id TEXT NOT NULL UNIQUE,
            dispatch_key TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('accepted', 'running', 'settled', 'cancelled')),
            outcome TEXT NOT NULL CHECK (outcome IN ('success', 'delayed', 'partial', 'failed')),
            business_date TEXT NOT NULL,
            accepted_at TEXT NOT NULL,
            running_at TEXT NOT NULL,
            ends_at TEXT NOT NULL,
            cancel_until TEXT NOT NULL,
            costs_json TEXT NOT NULL DEFAULT '{}',
            snapshot_json TEXT NOT NULL DEFAULT '{}',
            result_json TEXT NOT NULL DEFAULT '{}',
            settle_operation_id TEXT UNIQUE,
            cancel_operation_id TEXT UNIQUE,
            settled_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_dispatch_assignments_player_day
            ON dispatch_assignments(player_id, dispatch_key, business_date);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_dispatch_assignments_active
            ON dispatch_assignments(player_id) WHERE status IN ('accepted', 'running');
        """
    )


__all__ = ["ensure_dispatch_schema"]
