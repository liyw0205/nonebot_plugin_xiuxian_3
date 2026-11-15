"""Shared SQLite connection initialization."""

from __future__ import annotations

import sqlite3
from threading import Lock
from pathlib import Path


_WAL_READY_PATHS: set[str] = set()
_WAL_READY_LOCK = Lock()


def connect_sqlite(database_path: str | Path, *, busy_timeout_ms: int) -> sqlite3.Connection:
    path = Path(database_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(
        path,
        timeout=busy_timeout_ms / 1000,
        isolation_level=None,
        # Repositories own one connection per executor thread and close the
        # pool after all work has drained. This also lets runtime shutdown
        # release connections created by worker threads.
        check_same_thread=False,
    )
    connection.row_factory = sqlite3.Row
    connection.execute(f"PRAGMA busy_timeout = {int(busy_timeout_ms)}")
    # Probe and switch journal mode once per process/path. Repeating this
    # connection-level read on every short request adds measurable tail cost.
    # Benchmark and production settings normally pass an absolute temporary or
    # configured path. Avoid a filesystem ``resolve()`` stat on every short
    # request; relative paths still get canonicalized for compatibility.
    path_key = str(path) if path.is_absolute() else str(path.resolve())
    if path_key not in _WAL_READY_PATHS:
        with _WAL_READY_LOCK:
            if path_key not in _WAL_READY_PATHS:
                journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
                if str(journal_mode).lower() != "wal":
                    connection.execute("PRAGMA journal_mode = WAL")
                _WAL_READY_PATHS.add(path_key)
    connection.execute("PRAGMA synchronous = NORMAL")
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


__all__ = ["connect_sqlite"]
