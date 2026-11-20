"""Additive player-owned field survey persistence."""

from __future__ import annotations


def ensure_survey_schema(connection):
    connection.executescript("""
        CREATE TABLE IF NOT EXISTS field_surveys (
            player_id INTEGER NOT NULL REFERENCES players(id),
            site_key TEXT NOT NULL,
            start_operation_id TEXT NOT NULL UNIQUE REFERENCES operations(operation_id),
            last_operation_id TEXT NOT NULL UNIQUE REFERENCES operations(operation_id),
            status TEXT NOT NULL CHECK(status IN ('active', 'resting', 'completed')),
            step INTEGER NOT NULL CHECK(step >= 0),
            attempts INTEGER NOT NULL CHECK(attempts >= 0),
            ready_at TEXT NOT NULL,
            snapshot_json TEXT NOT NULL,
            PRIMARY KEY(player_id, site_key)
        );
    """)
