"""SQLite schema owned by the idle-reward domain."""

from __future__ import annotations

import sqlite3


def ensure_idle_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS idle_assignments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            assignment_id TEXT NOT NULL UNIQUE,
            player_id INTEGER NOT NULL REFERENCES players(id),
            operation_id TEXT NOT NULL UNIQUE,
            route_key TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('assigned', 'running', 'claimed', 'expired', 'cancelled')),
            business_date TEXT NOT NULL,
            starts_at TEXT NOT NULL,
            claim_at TEXT NOT NULL,
            max_claim_at TEXT NOT NULL,
            cancel_until TEXT NOT NULL,
            facility_slot_key TEXT,
            cost_json TEXT NOT NULL DEFAULT '{}',
            snapshot_json TEXT NOT NULL DEFAULT '{}',
            result_json TEXT NOT NULL DEFAULT '{}',
            claim_operation_id TEXT UNIQUE,
            cancel_operation_id TEXT UNIQUE,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_idle_assignments_player
            ON idle_assignments(player_id, status, starts_at);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_idle_assignments_active
            ON idle_assignments(player_id) WHERE status IN ('assigned', 'running');
        """
    )
    columns = {str(row["name"]) for row in connection.execute("PRAGMA table_info(idle_assignments)")}
    if "facility_slot_key" not in columns:
        connection.execute("ALTER TABLE idle_assignments ADD COLUMN facility_slot_key TEXT")
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_idle_assignments_facility_lock "
        "ON idle_assignments(facility_slot_key, status)"
    )


__all__ = ["ensure_idle_schema"]
