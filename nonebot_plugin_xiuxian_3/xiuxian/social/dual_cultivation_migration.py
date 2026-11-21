"""Additive, repeatable migration; existing domain rows are untouched."""

from __future__ import annotations

import sqlite3


def ensure_dual_cultivation_schema(connection: sqlite3.Connection) -> None:
    connection.execute("""
        CREATE TABLE IF NOT EXISTS partner_cultivation_invitations (
            invitation_id TEXT PRIMARY KEY,
            relation_id TEXT NOT NULL REFERENCES partner_relations(relation_id),
            initiator_id INTEGER NOT NULL REFERENCES players(id),
            invitee_id INTEGER NOT NULL REFERENCES players(id),
            location_key TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('invited','settled','rejected','cancelled','expired')),
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            snapshot_json TEXT NOT NULL,
            snapshot_hash TEXT NOT NULL,
            result_json TEXT,
            CHECK(initiator_id <> invitee_id)
        )
    """)
    connection.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_partner_cultivation_pending
        ON partner_cultivation_invitations(relation_id) WHERE status='invited'
    """)
    connection.execute("""
        CREATE TABLE IF NOT EXISTS partner_cultivation_settlements (
            invitation_id TEXT NOT NULL REFERENCES partner_cultivation_invitations(invitation_id),
            player_id INTEGER NOT NULL REFERENCES players(id),
            quota_day TEXT NOT NULL,
            operation_id TEXT NOT NULL REFERENCES operations(operation_id) DEFERRABLE INITIALLY DEFERRED,
            cost_json TEXT NOT NULL,
            gain INTEGER NOT NULL CHECK(gain > 0),
            before_json TEXT NOT NULL,
            after_json TEXT NOT NULL,
            PRIMARY KEY(invitation_id, player_id)
        )
    """)
    connection.execute("""
        CREATE INDEX IF NOT EXISTS idx_partner_cultivation_quota
        ON partner_cultivation_settlements(player_id, quota_day)
    """)
