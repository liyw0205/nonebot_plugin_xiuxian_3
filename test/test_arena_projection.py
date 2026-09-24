from __future__ import annotations

import json
import sqlite3
import pytest

from nonebot_plugin_xiuxian_3.xiuxian.specials.arena_projection import (
    ARENA_LOCAL_REPUTATION_KEY,
    project_arena_result,
)
from nonebot_plugin_xiuxian_3.xiuxian.specials.arena_federation import freeze_arena_season_snapshot


def _connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript(
        """
        CREATE TABLE players (
            id INTEGER PRIMARY KEY,
            player_id TEXT NOT NULL,
            platform TEXT NOT NULL,
            platform_user_id TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            arena_rating INTEGER NOT NULL DEFAULT 1000,
            arena_wins INTEGER NOT NULL DEFAULT 0,
            arena_losses INTEGER NOT NULL DEFAULT 0,
            arena_draws INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE player_reputations (
            player_id INTEGER PRIMARY KEY REFERENCES players(id),
            local_json TEXT NOT NULL DEFAULT '{}',
            service_reputation INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE activity_events (
            player_id INTEGER NOT NULL,
            event_key TEXT NOT NULL,
            source_operation_id TEXT NOT NULL,
            occurred_at TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            UNIQUE (player_id, event_key, source_operation_id)
        );
        CREATE TABLE codex_entries (
            player_id INTEGER NOT NULL REFERENCES players(id),
            entry_key TEXT NOT NULL,
            category TEXT NOT NULL,
            first_seen_operation_id TEXT NOT NULL,
            first_seen_at TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            content_version TEXT NOT NULL,
            rule_version TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            UNIQUE (player_id, entry_key)
        );
        CREATE TABLE arena_projection_events (
            match_id TEXT NOT NULL,
            player_id INTEGER NOT NULL REFERENCES players(id),
            operation_id TEXT NOT NULL,
            mode_key TEXT NOT NULL,
            side TEXT NOT NULL,
            outcome TEXT NOT NULL,
            reputation_delta INTEGER NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE (match_id, player_id),
            UNIQUE (operation_id, player_id)
        );
        CREATE TABLE arena_identity_routes (
            route_key TEXT UNIQUE, player_id INTEGER UNIQUE, shard_key TEXT,
            platform TEXT, platform_user_id TEXT, status TEXT,
            created_at TEXT, updated_at TEXT
        );
        CREATE TABLE arena_audit_events (
            event_key TEXT, match_id TEXT, operation_id TEXT, player_id INTEGER,
            mode_key TEXT, outcome TEXT, payload_json TEXT, created_at TEXT,
            UNIQUE (event_key, operation_id, player_id)
        );
        CREATE TABLE arena_season_snapshots (
            season_key TEXT, shard_key TEXT, player_id INTEGER, rating INTEGER,
            wins INTEGER, losses INTEGER, draws INTEGER, snapshot_json TEXT,
            frozen_at TEXT, created_at TEXT,
            UNIQUE (season_key, shard_key, player_id)
        );
        """
    )
    connection.executemany(
        "INSERT INTO players(id, player_id, platform, platform_user_id) VALUES (?, ?, ?, ?)",
        [(1, "stable-1", "qq.official", "same-id"), (2, "stable-2", "onebot.v11", "same-id")],
    )
    connection.commit()
    return connection


def test_arena_projection_is_idempotent_and_only_rewards_counted_wins() -> None:
    connection = _connection()
    try:
        kwargs = {
            "match_id": "arena.match:1",
            "operation_id": "arena-op-1",
            "mode_key": "arena.spar",
            "outcome": "challenger_won",
            "score_counted": True,
            "settled_at": "2026-09-25T00:00:00+00:00",
            "participants": (
                {"player_id": 1, "side": "challenger"},
                {"player_id": 2, "side": "defender"},
            ),
        }
        first = project_arena_result(connection, **kwargs)
        replay = project_arena_result(connection, **kwargs)
        assert len(first["participants"]) == len(replay["participants"]) == 2
        assert connection.execute("SELECT COUNT(*) FROM arena_projection_events").fetchone()[0] == 2
        assert connection.execute("SELECT COUNT(*) FROM codex_entries").fetchone()[0] == 4
        assert connection.execute("SELECT COUNT(*) FROM activity_events").fetchone()[0] == 4
        assert connection.execute("SELECT COUNT(*) FROM arena_identity_routes").fetchone()[0] == 2
        assert connection.execute("SELECT COUNT(*) FROM arena_audit_events").fetchone()[0] == 2
        assert freeze_arena_season_snapshot(
            connection,
            season_key="arena.test.1",
            frozen_at="2026-09-25T00:00:00+00:00",
        ) == 2
        assert freeze_arena_season_snapshot(
            connection,
            season_key="arena.test.1",
            frozen_at="2026-09-26T00:00:00+00:00",
        ) == 2
        local = json.loads(
            connection.execute(
                "SELECT local_json FROM player_reputations WHERE player_id = 1"
            ).fetchone()[0]
        )
        assert local[ARENA_LOCAL_REPUTATION_KEY] == 1
        defender_local = json.loads(
            connection.execute(
                "SELECT local_json FROM player_reputations WHERE player_id = 2"
            ).fetchone()[0]
        )
        assert defender_local[ARENA_LOCAL_REPUTATION_KEY] == 0
    finally:
        connection.close()


def test_arena_projection_failure_rolls_back_all_participants() -> None:
    connection = _connection()
    try:
        connection.execute("BEGIN")
        with pytest.raises(ValueError):
            project_arena_result(
                connection,
                match_id="arena.match:rollback",
                operation_id="arena-op-rollback",
                mode_key="arena.team",
                outcome="draw",
                score_counted=True,
                settled_at="2026-09-25T00:00:00+00:00",
                participants=(
                    {"player_id": 1, "side": "challenger"},
                    {"player_id": 999, "side": "defender"},
                ),
            )
        connection.rollback()
        assert connection.execute("SELECT COUNT(*) FROM arena_projection_events").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM codex_entries").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM activity_events").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM arena_identity_routes").fetchone()[0] == 0
    finally:
        connection.close()
