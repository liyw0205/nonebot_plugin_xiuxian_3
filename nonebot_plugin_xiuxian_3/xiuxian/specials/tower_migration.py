"""SQLite schema owned by the mist-trial tower."""

from __future__ import annotations

import sqlite3

from ..utils.json_cache import decode_json_strict
from .tower_rules import reward_snapshot_digest


def ensure_tower_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS tower_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL UNIQUE,
            player_id INTEGER NOT NULL REFERENCES players(id),
            tower_key TEXT NOT NULL,
            floor_no INTEGER NOT NULL CHECK (floor_no > 0),
            status TEXT NOT NULL CHECK (status IN ('battle_running', 'reward_pending', 'lost', 'claimed', 'aborted')),
            battle_id TEXT UNIQUE,
            first_clear INTEGER NOT NULL CHECK (first_clear IN (0, 1)),
            enemy_key TEXT NOT NULL DEFAULT '',
            stamina_cost INTEGER NOT NULL DEFAULT 0 CHECK (stamina_cost >= 0),
            starts_at TEXT NOT NULL,
            result_json TEXT NOT NULL DEFAULT '{}',
            reward_json TEXT NOT NULL DEFAULT '{}',
            reward_maximums_json TEXT NOT NULL DEFAULT '{}',
            codex_entry_key TEXT NOT NULL DEFAULT '',
            codex_category TEXT NOT NULL DEFAULT '',
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
            claimed_at TEXT NOT NULL
        );
        """
    )
    columns = {
        str(row[1])
        for row in connection.execute("PRAGMA table_info(tower_runs)").fetchall()
    }
    additions = {
        "enemy_key": "TEXT NOT NULL DEFAULT ''",
        "stamina_cost": "INTEGER NOT NULL DEFAULT 0 CHECK (stamina_cost >= 0)",
        "reward_maximums_json": "TEXT NOT NULL DEFAULT '{}'",
        "reward_digest": "TEXT NOT NULL DEFAULT ''",
        "codex_entry_key": "TEXT NOT NULL DEFAULT ''",
        "codex_category": "TEXT NOT NULL DEFAULT ''",
    }
    for name, definition in additions.items():
        if name not in columns:
            connection.execute(f"ALTER TABLE tower_runs ADD COLUMN {name} {definition}")
    _backfill_reward_digests(connection)


def _backfill_reward_digests(connection: sqlite3.Connection) -> None:
    """Bind rows written before the integrity column existed to their stored snapshot.

    Unreadable legacy snapshots keep an empty digest so the reward path rejects them
    instead of laundering tampered or truncated JSON into a fresh grant.
    """

    rows = connection.execute(
        "SELECT id, reward_json, reward_maximums_json FROM tower_runs WHERE reward_digest=''"
    ).fetchall()
    for row_id, stored_reward, stored_maximums in rows:
        try:
            reward = decode_json_strict(str(stored_reward))
            reward_maximums = decode_json_strict(str(stored_maximums))
        except (TypeError, ValueError):
            continue
        if not isinstance(reward, dict) or not isinstance(reward_maximums, dict):
            continue
        if any(
            isinstance(amount, bool) or not isinstance(amount, int)
            for amount in (*reward.values(), *reward_maximums.values())
        ):
            continue
        connection.execute(
            "UPDATE tower_runs SET reward_digest=? WHERE id=?",
            (reward_snapshot_digest(reward, reward_maximums), row_id),
        )


__all__ = ["ensure_tower_schema"]
