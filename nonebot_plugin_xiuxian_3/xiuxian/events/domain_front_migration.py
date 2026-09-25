"""Idempotent schema migration for the domain-front slice."""

from __future__ import annotations

import sqlite3


def ensure_domain_front_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS domain_front_rounds (
            round_id TEXT PRIMARY KEY,
            activity_id TEXT NOT NULL,
            location_key TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('open', 'running', 'settled', 'failed')),
            activity_starts_at TEXT NOT NULL,
            activity_ends_at TEXT NOT NULL,
            starts_at TEXT NOT NULL,
            ends_at TEXT NOT NULL,
            claim_expires_at TEXT NOT NULL,
            target_quantity INTEGER NOT NULL CHECK (target_quantity >= 0),
            total_contribution INTEGER NOT NULL DEFAULT 0 CHECK (total_contribution >= 0),
            result_json TEXT NOT NULL DEFAULT '{}',
            rule_version TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_domain_front_rounds_lookup
            ON domain_front_rounds(status, starts_at, claim_expires_at);
        CREATE TABLE IF NOT EXISTS domain_front_participants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            round_id TEXT NOT NULL REFERENCES domain_front_rounds(round_id),
            player_id INTEGER NOT NULL REFERENCES players(id),
            sect_id TEXT NOT NULL REFERENCES sects(sect_id),
            domain_key TEXT NOT NULL,
            stamina_cost INTEGER NOT NULL CHECK (stamina_cost >= 0),
            contribution INTEGER NOT NULL DEFAULT 0 CHECK (contribution >= 0),
            status TEXT NOT NULL CHECK (status IN ('active', 'withdrawn')),
            snapshot_json TEXT NOT NULL DEFAULT '{}',
            joined_at TEXT NOT NULL,
            UNIQUE (round_id, player_id)
        );
        CREATE INDEX IF NOT EXISTS idx_domain_front_participants_sect
            ON domain_front_participants(round_id, sect_id, status);
        CREATE TABLE IF NOT EXISTS domain_front_contributions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            round_id TEXT NOT NULL REFERENCES domain_front_rounds(round_id),
            player_id INTEGER NOT NULL REFERENCES players(id),
            sect_id TEXT NOT NULL REFERENCES sects(sect_id),
            domain_key TEXT NOT NULL,
            source_operation_id TEXT NOT NULL,
            action_key TEXT NOT NULL CHECK (action_key IN ('battle', 'point')),
            quantity INTEGER NOT NULL CHECK (quantity > 0),
            operation_id TEXT NOT NULL UNIQUE,
            occurred_at TEXT NOT NULL,
            UNIQUE (round_id, player_id, source_operation_id)
        );
        CREATE INDEX IF NOT EXISTS idx_domain_front_contributions_round
            ON domain_front_contributions(round_id, domain_key, occurred_at);
        CREATE TABLE IF NOT EXISTS domain_front_battles (
            battle_id TEXT PRIMARY KEY,
            round_id TEXT NOT NULL REFERENCES domain_front_rounds(round_id),
            player_id INTEGER NOT NULL REFERENCES players(id),
            operation_id TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL CHECK (status IN ('settled', 'failed')),
            outcome TEXT NOT NULL CHECK (outcome IN ('won', 'lost')),
            snapshot_json TEXT NOT NULL DEFAULT '{}',
            result_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS domain_front_point_operations (
            point_id TEXT PRIMARY KEY,
            round_id TEXT NOT NULL REFERENCES domain_front_rounds(round_id),
            player_id INTEGER NOT NULL REFERENCES players(id),
            operation_id TEXT NOT NULL UNIQUE,
            minutes INTEGER NOT NULL CHECK (minutes BETWEEN 1 AND 30),
            status TEXT NOT NULL CHECK (status IN ('settled', 'failed')),
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS domain_front_claims (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            round_id TEXT NOT NULL REFERENCES domain_front_rounds(round_id),
            player_id INTEGER NOT NULL REFERENCES players(id),
            operation_id TEXT NOT NULL UNIQUE,
            reward_json TEXT NOT NULL DEFAULT '{}',
            claimed_at TEXT NOT NULL,
            UNIQUE (round_id, player_id)
        );
        CREATE TABLE IF NOT EXISTS domain_war_seasons (
            season_id TEXT PRIMARY KEY,
            starts_at TEXT NOT NULL,
            ends_at TEXT NOT NULL,
            claim_expires_at TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('collecting', 'frozen')),
            frozen_at TEXT,
            snapshot_json TEXT NOT NULL DEFAULT '{}',
            rule_version TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS domain_war_rankings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            season_id TEXT NOT NULL REFERENCES domain_war_seasons(season_id),
            player_id INTEGER NOT NULL REFERENCES players(id),
            rank INTEGER NOT NULL CHECK (rank > 0),
            score INTEGER NOT NULL CHECK (score > 0),
            achieved_at TEXT NOT NULL,
            anonymous_label TEXT NOT NULL,
            reward_json TEXT NOT NULL DEFAULT '{}',
            UNIQUE (season_id, player_id),
            UNIQUE (season_id, rank)
        );
        CREATE INDEX IF NOT EXISTS idx_domain_war_rankings_season
            ON domain_war_rankings(season_id, rank);
        CREATE TABLE IF NOT EXISTS domain_war_claims (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            season_id TEXT NOT NULL REFERENCES domain_war_seasons(season_id),
            player_id INTEGER NOT NULL REFERENCES players(id),
            operation_id TEXT NOT NULL UNIQUE,
            reward_json TEXT NOT NULL DEFAULT '{}',
            claimed_at TEXT NOT NULL,
            UNIQUE (season_id, player_id)
        );
        CREATE TABLE IF NOT EXISTS domain_core_redemptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            season_id TEXT NOT NULL REFERENCES domain_war_seasons(season_id),
            player_id INTEGER NOT NULL REFERENCES players(id),
            operation_id TEXT NOT NULL UNIQUE,
            redeemed_at TEXT NOT NULL,
            UNIQUE (season_id, player_id)
        );
        """
    )


__all__ = ["ensure_domain_front_schema"]
