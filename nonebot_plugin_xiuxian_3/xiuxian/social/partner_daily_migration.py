"""Additive schema for partner daily fieldwork tasks."""


import sqlite3


def ensure_partner_daily_schema(connection: sqlite3.Connection) -> None:
    connection.executescript("""
        CREATE TABLE IF NOT EXISTS partner_daily_tasks (
            task_id TEXT PRIMARY KEY,
            relation_id TEXT NOT NULL REFERENCES partner_relations(relation_id),
            quota_day TEXT NOT NULL,
            player_a_id INTEGER NOT NULL REFERENCES players(id),
            player_b_id INTEGER NOT NULL REFERENCES players(id),
            status TEXT NOT NULL CHECK(status IN ('open', 'claimable', 'completed', 'expired')),
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            snapshot_json TEXT NOT NULL,
            snapshot_hash TEXT NOT NULL,
            create_operation_id TEXT NOT NULL UNIQUE REFERENCES operations(operation_id)
                DEFERRABLE INITIALLY DEFERRED,
            CHECK(player_a_id <> player_b_id),
            UNIQUE(relation_id, quota_day)
        );
        CREATE UNIQUE INDEX IF NOT EXISTS partner_daily_one_open_per_relation
            ON partner_daily_tasks(relation_id) WHERE status = 'open';
        CREATE TABLE IF NOT EXISTS partner_daily_evidence (
            task_id TEXT NOT NULL REFERENCES partner_daily_tasks(task_id),
            player_id INTEGER NOT NULL REFERENCES players(id),
            source_operation_id TEXT NOT NULL UNIQUE REFERENCES operations(operation_id),
            source_key TEXT NOT NULL,
            occurred_at TEXT NOT NULL,
            PRIMARY KEY(task_id, player_id, source_operation_id)
        );
        CREATE INDEX IF NOT EXISTS partner_daily_evidence_by_player
            ON partner_daily_evidence(task_id, player_id, occurred_at);
        CREATE TABLE IF NOT EXISTS partner_daily_claims (
            task_id TEXT NOT NULL REFERENCES partner_daily_tasks(task_id),
            player_id INTEGER NOT NULL REFERENCES players(id),
            reward_json TEXT NOT NULL,
            before_json TEXT NOT NULL,
            after_json TEXT NOT NULL,
            operation_id TEXT NOT NULL UNIQUE REFERENCES operations(operation_id)
                DEFERRABLE INITIALLY DEFERRED,
            claimed_at TEXT NOT NULL,
            PRIMARY KEY(task_id, player_id)
        );
    """)
