import sqlite3

from nonebot_plugin_xiuxian_3.xiuxian.persistence.sqlite_repository import SQLitePlayerRepository


def test_arena_mode_migration_upgrades_spar_only_tables_and_keeps_foreign_keys() -> None:
    connection = sqlite3.connect(":memory:", isolation_level=None)
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript(
        """
        CREATE TABLE players (id INTEGER PRIMARY KEY, player_id TEXT NOT NULL);
        INSERT INTO players(id, player_id) VALUES (1, 'p1'), (2, 'p2');
        CREATE TABLE arena_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_id TEXT NOT NULL UNIQUE,
            player_id INTEGER NOT NULL REFERENCES players(id),
            status TEXT NOT NULL CHECK (status IN ('published', 'revoked', 'expired')),
            arena_mode_key TEXT NOT NULL CHECK (arena_mode_key = 'arena.spar'),
            rating INTEGER NOT NULL CHECK (rating >= 0),
            matchable_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            snapshot_json TEXT NOT NULL DEFAULT '{}',
            public_json TEXT NOT NULL DEFAULT '{}',
            content_version TEXT NOT NULL,
            rule_version TEXT NOT NULL,
            revoked_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE arena_matches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id TEXT NOT NULL UNIQUE,
            challenger_id INTEGER NOT NULL REFERENCES players(id),
            defender_id INTEGER NOT NULL REFERENCES players(id),
            challenger_snapshot_id TEXT NOT NULL REFERENCES arena_snapshots(snapshot_id),
            defender_snapshot_id TEXT NOT NULL REFERENCES arena_snapshots(snapshot_id),
            arena_mode_key TEXT NOT NULL CHECK (arena_mode_key = 'arena.spar'),
            status TEXT NOT NULL CHECK (status IN ('settled')),
            outcome TEXT NOT NULL CHECK (outcome IN ('challenger_won', 'defender_won', 'draw')),
            rounds INTEGER NOT NULL CHECK (rounds BETWEEN 1 AND 15),
            score_counted INTEGER NOT NULL CHECK (score_counted IN (0, 1)),
            challenger_rating_delta INTEGER NOT NULL,
            defender_rating_delta INTEGER NOT NULL,
            snapshot_json TEXT NOT NULL DEFAULT '{}',
            result_json TEXT NOT NULL DEFAULT '{}',
            operation_id TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL,
            settled_at TEXT NOT NULL,
            CHECK (challenger_id <> defender_id)
        );
        CREATE TABLE arena_actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action_id TEXT NOT NULL UNIQUE,
            match_id TEXT NOT NULL REFERENCES arena_matches(match_id),
            sequence_no INTEGER NOT NULL,
            round_no INTEGER NOT NULL,
            actor_key TEXT NOT NULL,
            strategy_key TEXT NOT NULL,
            skill_key TEXT NOT NULL,
            target_key TEXT NOT NULL,
            hit_roll_bp INTEGER NOT NULL,
            damage INTEGER NOT NULL,
            state_json TEXT NOT NULL,
            operation_id TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL,
            UNIQUE(match_id, sequence_no)
        );
        CREATE TABLE arena_reward_claims (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id TEXT NOT NULL UNIQUE REFERENCES arena_matches(match_id),
            player_id INTEGER NOT NULL REFERENCES players(id),
            operation_id TEXT NOT NULL UNIQUE,
            reward_json TEXT NOT NULL DEFAULT '{}',
            claimed_at TEXT NOT NULL
        );
        INSERT INTO arena_snapshots(
            snapshot_id, player_id, status, arena_mode_key, rating, matchable_at,
            expires_at, content_version, rule_version, created_at, updated_at
        ) VALUES ('s1', 1, 'published', 'arena.spar', 1000, '2026-01-01', '2026-01-08', 'c', 'r', '2026-01-01', '2026-01-01');
        INSERT INTO arena_snapshots(
            snapshot_id, player_id, status, arena_mode_key, rating, matchable_at,
            expires_at, content_version, rule_version, created_at, updated_at
        ) VALUES ('s2', 2, 'published', 'arena.spar', 1000, '2026-01-01', '2026-01-08', 'c', 'r', '2026-01-01', '2026-01-01');
        INSERT INTO arena_matches(
            match_id, challenger_id, defender_id, challenger_snapshot_id, defender_snapshot_id,
            arena_mode_key, status, outcome, rounds, score_counted, challenger_rating_delta,
            defender_rating_delta, operation_id, created_at, settled_at
        ) VALUES ('m1', 1, 2, 's1', 's2', 'arena.spar', 'settled', 'draw', 1, 1, 5, 5, 'op1', '2026-01-01', '2026-01-01');
        INSERT INTO arena_actions(
            action_id, match_id, sequence_no, round_no, actor_key, strategy_key, skill_key,
            target_key, hit_roll_bp, damage, state_json, operation_id, created_at
        ) VALUES ('a1', 'm1', 1, 1, 'challenger', 'auto', 'basic', 'defender', 1, 1, '{}', 'aop1', '2026-01-01');
        """
    )

    SQLitePlayerRepository._migrate_arena_mode_schema(connection)

    connection.execute(
        "INSERT INTO arena_snapshots(snapshot_id, player_id, status, arena_mode_key, rating, matchable_at, expires_at, content_version, rule_version, created_at, updated_at) "
        "VALUES ('s3', 2, 'revoked', 'arena.rank', 1000, '2026-01-01', '2026-01-08', 'c', 'r', '2026-01-01', '2026-01-01')"
    )
    connection.execute(
        "INSERT INTO arena_snapshots(snapshot_id, player_id, status, arena_mode_key, rating, matchable_at, expires_at, content_version, rule_version, created_at, updated_at) "
        "VALUES ('s4', 2, 'revoked', 'arena.three_realms', 1000, '2026-01-01', '2026-01-08', 'c', 'r', '2026-01-01', '2026-01-01')"
    )
    assert connection.execute("SELECT COUNT(*) FROM arena_matches").fetchone()[0] == 1
    assert connection.execute("SELECT COUNT(*) FROM arena_actions WHERE match_id = 'm1'").fetchone()[0] == 1
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    connection.close()
