"""SQLite schema for the independent v0.5 void-frontier season."""

from __future__ import annotations

import sqlite3


def ensure_void_frontier_schema(connection: sqlite3.Connection) -> None:
    columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(players)").fetchall()}
    if "alliance_points" not in columns:
        connection.execute("ALTER TABLE players ADD COLUMN alliance_points INTEGER NOT NULL DEFAULT 0")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS void_frontier_seasons (
            season_id TEXT PRIMARY KEY,
            starts_at TEXT NOT NULL,
            ends_at TEXT NOT NULL,
            claim_expires_at TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('collecting', 'frozen')),
            frozen_at TEXT,
            snapshot_json TEXT NOT NULL DEFAULT '{}',
            content_version TEXT NOT NULL,
            rule_version TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS void_frontier_score_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            season_id TEXT NOT NULL REFERENCES void_frontier_seasons(season_id),
            player_id INTEGER NOT NULL REFERENCES players(id),
            sect_id TEXT REFERENCES sects(sect_id),
            score_key TEXT NOT NULL,
            points INTEGER NOT NULL CHECK (points > 0),
            source_operation_id TEXT NOT NULL,
            source_key TEXT NOT NULL,
            occurred_at TEXT NOT NULL,
            UNIQUE (season_id, player_id, source_key)
        );
        CREATE INDEX IF NOT EXISTS idx_void_frontier_score_events_season
            ON void_frontier_score_events(season_id, score_key, points DESC);
        CREATE TABLE IF NOT EXISTS void_frontier_rankings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            season_id TEXT NOT NULL REFERENCES void_frontier_seasons(season_id),
            board_key TEXT NOT NULL CHECK (board_key IN ('player_score', 'sect_score')),
            player_id INTEGER REFERENCES players(id),
            sect_id TEXT REFERENCES sects(sect_id),
            rank INTEGER NOT NULL CHECK (rank > 0),
            score INTEGER NOT NULL CHECK (score >= 0),
            achieved_at TEXT NOT NULL,
            anonymous_label TEXT NOT NULL,
            UNIQUE (season_id, board_key, player_id, sect_id)
        );
        CREATE INDEX IF NOT EXISTS idx_void_frontier_rankings_public
            ON void_frontier_rankings(season_id, board_key, rank);
        CREATE TABLE IF NOT EXISTS void_frontier_sect_priorities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            season_id TEXT NOT NULL REFERENCES void_frontier_seasons(season_id),
            sect_id TEXT NOT NULL REFERENCES sects(sect_id),
            rank INTEGER NOT NULL CHECK (rank BETWEEN 1 AND 3),
            starts_at TEXT NOT NULL,
            ends_at TEXT NOT NULL,
            UNIQUE (season_id, sect_id)
        );
        CREATE TABLE IF NOT EXISTS void_frontier_weekly_rewards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            season_id TEXT NOT NULL REFERENCES void_frontier_seasons(season_id),
            week_id TEXT NOT NULL,
            player_id INTEGER NOT NULL REFERENCES players(id),
            source_key TEXT NOT NULL,
            source_operation_id TEXT NOT NULL,
            reward_json TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL CHECK (status IN ('pending', 'claimed', 'converted')),
            claim_operation_id TEXT UNIQUE,
            created_at TEXT NOT NULL,
            claimed_at TEXT,
            UNIQUE (week_id, player_id, source_key)
        );
        CREATE INDEX IF NOT EXISTS idx_void_frontier_weekly_player
            ON void_frontier_weekly_rewards(player_id, week_id, status);
        CREATE TABLE IF NOT EXISTS void_frontier_claims (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            season_id TEXT NOT NULL REFERENCES void_frontier_seasons(season_id),
            player_id INTEGER NOT NULL REFERENCES players(id),
            operation_id TEXT NOT NULL UNIQUE,
            reward_json TEXT NOT NULL DEFAULT '{}',
            rank INTEGER NOT NULL,
            claimed_at TEXT NOT NULL,
            UNIQUE (season_id, player_id)
        );
        """
    )


__all__ = ["ensure_void_frontier_schema"]
