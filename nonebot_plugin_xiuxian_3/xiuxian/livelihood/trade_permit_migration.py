"""SQLite schema owned by trade permits."""

from __future__ import annotations

import sqlite3


def ensure_trade_permit_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS trade_permits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            permit_id TEXT NOT NULL UNIQUE,
            player_id INTEGER NOT NULL REFERENCES players(id),
            operation_id TEXT NOT NULL UNIQUE,
            permit_key TEXT NOT NULL,
            issued_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            cost INTEGER NOT NULL CHECK (cost >= 0),
            snapshot_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_trade_permits_player_expiry
            ON trade_permits(player_id, permit_key, expires_at);
        """
    )


__all__ = ["ensure_trade_permit_schema"]
