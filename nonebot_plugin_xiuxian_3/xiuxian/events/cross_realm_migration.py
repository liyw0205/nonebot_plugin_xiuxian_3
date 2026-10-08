"""Schema additions owned by recurring public cross-realm events."""

from __future__ import annotations

import sqlite3


def ensure_cross_realm_event_schema(connection: sqlite3.Connection) -> None:
    columns = {
        str(row[1])
        for row in connection.execute("PRAGMA table_info(world_event_rounds)").fetchall()
    }
    if "configuration_hash" not in columns:
        connection.execute(
            "ALTER TABLE world_event_rounds ADD COLUMN configuration_hash TEXT NOT NULL DEFAULT ''"
        )


__all__ = ["ensure_cross_realm_event_schema"]
