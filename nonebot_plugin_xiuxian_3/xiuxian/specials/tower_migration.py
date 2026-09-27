"""SQLite schema owned by the mist-trial tower."""

from __future__ import annotations

import sqlite3


def ensure_tower_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS tower_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL UNIQUE,
            player_id INTEGER NOT NULL REFERENCES players(id),
            tower_key TEXT NOT NULL,
            floor_no INTEGER NOT NULL CHECK (floor_no BETWEEN 1 AND 30),
            status TEXT NOT NULL CHECK (status IN ('battle_running', 'reward_pending', 'lost', 'claimed', 'aborted')),
            battle_id TEXT UNIQUE,
            first_clear INTEGER NOT NULL CHECK (first_clear IN (0, 1)),
            starts_at TEXT NOT NULL,
            result_json TEXT NOT NULL DEFAULT '{}',
            reward_json TEXT NOT NULL DEFAULT '{}',
            content_version TEXT NOT NULL,
            rule_version TEXT NOT NULL,
            claim_operation_id TEXT UNIQUE,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_tower_runs_player_floor
            ON tower_runs(player_id, tower_key, floor_no, created_at);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_tower_runs_active_player
            ON tower_runs(player_id) WHERE status IN ('battle_running', 'reward_pending');
        CREATE TABLE IF NOT EXISTS tower_reward_claims (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL UNIQUE REFERENCES tower_runs(run_id),
            player_id INTEGER NOT NULL REFERENCES players(id),
            floor_no INTEGER NOT NULL,
            first_clear INTEGER NOT NULL CHECK (first_clear IN (0, 1)),
            operation_id TEXT NOT NULL UNIQUE,
            reward_json TEXT NOT NULL,
            content_version TEXT NOT NULL,
            rule_version TEXT NOT NULL,
            claimed_at TEXT NOT NULL
        );
        """
    )


__all__ = ["ensure_tower_schema"]
