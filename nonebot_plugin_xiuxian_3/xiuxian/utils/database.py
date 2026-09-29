"""Shared SQLite connection initialization."""

from __future__ import annotations

import sqlite3
from pathlib import Path


def connect_sqlite(database_path: str | Path, *, busy_timeout_ms: int) -> sqlite3.Connection:
    path = Path(database_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(
        path,
        timeout=busy_timeout_ms / 1000,
        isolation_level=None,
    )
    connection.row_factory = sqlite3.Row
    connection.execute(f"PRAGMA busy_timeout = {int(busy_timeout_ms)}")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA synchronous = NORMAL")
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


__all__ = ["connect_sqlite"]
