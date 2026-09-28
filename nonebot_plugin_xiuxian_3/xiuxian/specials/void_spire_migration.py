"""SQLite schema and historical floor-limit migration for the void spire."""

from __future__ import annotations

import sqlite3


def _create_runs_table(connection: sqlite3.Connection, name: str = "void_spire_runs") -> None:
    connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {name} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL UNIQUE,
            player_id INTEGER NOT NULL REFERENCES players(id),
            tower_key TEXT NOT NULL,
            floor_no INTEGER NOT NULL CHECK (floor_no BETWEEN 1 AND 60),
            route_key TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('battle_running', 'reward_pending', 'lost', 'claimed', 'aborted')),
            battle_id TEXT UNIQUE,
            first_clear INTEGER NOT NULL CHECK (first_clear IN (0, 1)),
            starts_at TEXT NOT NULL,
            result_json TEXT NOT NULL DEFAULT '{{}}',
            reward_json TEXT NOT NULL DEFAULT '{{}}',
            content_version TEXT NOT NULL,
            rule_version TEXT NOT NULL,
            claim_operation_id TEXT UNIQUE,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )


def ensure_void_spire_schema(connection: sqlite3.Connection) -> None:
    _create_runs_table(connection)
    connection.executescript(
        """
        CREATE INDEX IF NOT EXISTS idx_void_spire_runs_player_floor
            ON void_spire_runs(player_id, tower_key, floor_no, created_at);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_void_spire_runs_active_player
            ON void_spire_runs(player_id) WHERE status IN ('battle_running', 'reward_pending');
        CREATE TABLE IF NOT EXISTS void_spire_reward_claims (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL UNIQUE REFERENCES void_spire_runs(run_id),
            player_id INTEGER NOT NULL REFERENCES players(id),
            floor_no INTEGER NOT NULL,
            route_key TEXT NOT NULL,
            first_clear INTEGER NOT NULL CHECK (first_clear IN (0, 1)),
            operation_id TEXT NOT NULL UNIQUE,
            reward_json TEXT NOT NULL,
            content_version TEXT NOT NULL,
            rule_version TEXT NOT NULL,
            claimed_at TEXT NOT NULL
        );
        """
    )
    schema = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='void_spire_runs'"
    ).fetchone()
    if schema is None or "BETWEEN 1 AND 60" in str(schema[0]):
        return

    foreign_keys_enabled = bool(connection.execute("PRAGMA foreign_keys").fetchone()[0])
    connection.execute("PRAGMA foreign_keys = OFF")
    try:
        connection.execute("BEGIN IMMEDIATE")
        _create_runs_table(connection, "void_spire_runs_v02")
        connection.execute("INSERT INTO void_spire_runs_v02 SELECT * FROM void_spire_runs")
        connection.execute("DROP TABLE void_spire_runs")
        connection.execute("ALTER TABLE void_spire_runs_v02 RENAME TO void_spire_runs")
        connection.execute(
            "CREATE INDEX idx_void_spire_runs_player_floor "
            "ON void_spire_runs(player_id, tower_key, floor_no, created_at)"
        )
        connection.execute(
            "CREATE UNIQUE INDEX idx_void_spire_runs_active_player "
            "ON void_spire_runs(player_id) WHERE status IN ('battle_running', 'reward_pending')"
        )
        if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise sqlite3.IntegrityError("void spire migration broke a historical foreign key")
        connection.execute("COMMIT")
    except Exception:
        connection.execute("ROLLBACK")
        raise
    finally:
        if foreign_keys_enabled:
            connection.execute("PRAGMA foreign_keys = ON")


__all__ = ["ensure_void_spire_schema"]
