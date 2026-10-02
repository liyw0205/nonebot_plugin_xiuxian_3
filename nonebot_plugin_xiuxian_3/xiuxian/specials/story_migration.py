"""Schema migration owned by the branching story."""

from __future__ import annotations

import sqlite3


def ensure_story_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS story_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            story_run_id TEXT NOT NULL UNIQUE,
            player_id INTEGER NOT NULL REFERENCES players(id),
            story_key TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('active', 'ending_pending', 'ended')),
            current_node TEXT NOT NULL,
            selected_route TEXT,
            start_operation_id TEXT NOT NULL UNIQUE,
            choice_operation_id TEXT UNIQUE,
            claim_operation_id TEXT UNIQUE,
            snapshot_json TEXT NOT NULL DEFAULT '{}',
            result_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE (player_id, story_key)
        );
        CREATE INDEX IF NOT EXISTS idx_story_runs_player_status
            ON story_runs(player_id, story_key, status);
        CREATE TABLE IF NOT EXISTS story_ending_claims (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            story_run_id TEXT NOT NULL UNIQUE REFERENCES story_runs(story_run_id),
            player_id INTEGER NOT NULL REFERENCES players(id),
            story_key TEXT NOT NULL,
            ending_key TEXT NOT NULL,
            route_key TEXT NOT NULL,
            operation_id TEXT NOT NULL UNIQUE,
            snapshot_json TEXT NOT NULL,
            reward_json TEXT NOT NULL,
            claimed_at TEXT NOT NULL,
            UNIQUE (player_id, story_key)
        );
        """
    )


__all__ = ["ensure_story_schema"]
