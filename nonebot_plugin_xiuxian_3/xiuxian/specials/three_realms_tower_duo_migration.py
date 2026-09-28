"""SQLite schema owned by the three-realms tower duo slice."""

from __future__ import annotations

import sqlite3


def ensure_three_realms_tower_duo_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS three_realms_tower_duo_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            duo_run_id TEXT NOT NULL UNIQUE,
            party_id TEXT NOT NULL REFERENCES parties(party_id),
            tower_key TEXT NOT NULL,
            floor_no INTEGER NOT NULL CHECK (floor_no BETWEEN 1 AND 40),
            status TEXT NOT NULL CHECK (status IN ('battle_running', 'reward_pending', 'won', 'lost', 'aborted')),
            battle_id TEXT UNIQUE,
            member_run_ids_json TEXT NOT NULL,
            result_json TEXT NOT NULL DEFAULT '{}',
            content_version TEXT NOT NULL,
            rule_version TEXT NOT NULL,
            start_operation_id TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_three_realms_tower_duo_party
            ON three_realms_tower_duo_runs(party_id, status, created_at);
        CREATE TABLE IF NOT EXISTS three_realms_tower_duo_member_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL UNIQUE,
            duo_run_id TEXT NOT NULL REFERENCES three_realms_tower_duo_runs(duo_run_id),
            player_id INTEGER NOT NULL REFERENCES players(id),
            floor_no INTEGER NOT NULL,
            first_clear INTEGER NOT NULL CHECK (first_clear IN (0, 1)),
            status TEXT NOT NULL CHECK (status IN ('reward_pending', 'claimed', 'lost')),
            reward_json TEXT NOT NULL DEFAULT '{}',
            claim_operation_id TEXT UNIQUE,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE (duo_run_id, player_id)
        );
        CREATE INDEX IF NOT EXISTS idx_three_realms_tower_duo_member_player
            ON three_realms_tower_duo_member_runs(player_id, floor_no, status, created_at);
        """
    )


__all__ = ["ensure_three_realms_tower_duo_schema"]
