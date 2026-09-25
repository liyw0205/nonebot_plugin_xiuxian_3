"""SQLite migration for v0.5 void archive runs and weekly claims."""

from __future__ import annotations

import sqlite3


def ensure_void_archive_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS void_archive_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL UNIQUE,
            player_id INTEGER NOT NULL REFERENCES players(id),
            week_id TEXT NOT NULL,
            route_session_id TEXT NOT NULL UNIQUE REFERENCES void_route_sessions(session_id),
            battle_id TEXT NOT NULL UNIQUE REFERENCES battle_sessions(battle_id),
            operation_id TEXT NOT NULL UNIQUE,
            outcome TEXT NOT NULL CHECK (outcome IN ('won', 'lost')),
            reward_json TEXT NOT NULL DEFAULT '{}',
            snapshot_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_void_archive_runs_player_week
            ON void_archive_runs(player_id, week_id, outcome);
        CREATE TABLE IF NOT EXISTS void_archive_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            player_id INTEGER NOT NULL REFERENCES players(id),
            week_id TEXT NOT NULL,
            task_key TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('claimed')),
            progress INTEGER NOT NULL CHECK (progress >= 0),
            target INTEGER NOT NULL CHECK (target > 0),
            reward_json TEXT NOT NULL DEFAULT '{}',
            operation_id TEXT NOT NULL UNIQUE,
            claimed_at TEXT NOT NULL,
            UNIQUE (player_id, week_id, task_key)
        );
        CREATE INDEX IF NOT EXISTS idx_void_archive_tasks_player_week
            ON void_archive_tasks(player_id, week_id, task_key);
        CREATE TABLE IF NOT EXISTS void_archive_unlocks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            player_id INTEGER NOT NULL REFERENCES players(id),
            week_id TEXT NOT NULL,
            event_key TEXT NOT NULL,
            starts_at TEXT NOT NULL,
            ends_at TEXT NOT NULL,
            operation_id TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL,
            UNIQUE (player_id, week_id, event_key)
        );
        CREATE INDEX IF NOT EXISTS idx_void_archive_unlocks_player
            ON void_archive_unlocks(player_id, week_id, event_key);
        """
    )


__all__ = ["ensure_void_archive_schema"]
