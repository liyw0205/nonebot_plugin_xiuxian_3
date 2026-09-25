"""Schema compatibility for the cross-server social recovery ledger."""

from __future__ import annotations

import sqlite3


def ensure_social_recovery_schema(connection: sqlite3.Connection) -> None:
    """Create the recovery event ledger for databases from before v0.5."""

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS social_recovery_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_key TEXT NOT NULL,
            request_id TEXT NOT NULL,
            operation_id TEXT NOT NULL,
            artifact_id TEXT NOT NULL,
            content_version TEXT NOT NULL,
            rule_version TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('requested', 'verified', 'snapshot_created', 'restoring', 'integrity_checked', 'active', 'failed')),
            result_json TEXT NOT NULL DEFAULT '{}',
            failure_reason TEXT NOT NULL DEFAULT '',
            elapsed_ms INTEGER NOT NULL DEFAULT 0 CHECK (elapsed_ms >= 0),
            created_at TEXT NOT NULL,
            UNIQUE (event_key, operation_id)
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_social_recovery_events_operation "
        "ON social_recovery_events(operation_id, created_at)"
    )


__all__ = ["ensure_social_recovery_schema"]
