"""Schema for immutable character attribute snapshots."""

from __future__ import annotations

import sqlite3


def ensure_stats_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS stat_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_id TEXT NOT NULL UNIQUE,
            player_id INTEGER NOT NULL REFERENCES players(id),
            purpose TEXT NOT NULL,
            base_stats_json TEXT NOT NULL,
            path_stats_json TEXT NOT NULL,
            derived_stats_json TEXT NOT NULL,
            source_refs_json TEXT NOT NULL,
            formula_fingerprint TEXT NOT NULL,
            operation_id TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL
        )
        """
    )
    connection.execute("CREATE INDEX IF NOT EXISTS idx_stat_snapshots_player ON stat_snapshots(player_id, created_at)")


__all__ = ["ensure_stats_schema"]
