import sqlite3

from nonebot_plugin_xiuxian_3.xiuxian.persistence.sqlite_repository import SQLitePlayerRepository


def test_party_type_migration_preserves_existing_party_members() -> None:
    connection = sqlite3.connect(":memory:", isolation_level=None)
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript(
        """
        CREATE TABLE players (id INTEGER PRIMARY KEY, player_id TEXT NOT NULL);
        INSERT INTO players(id, player_id) VALUES (1, 'p1'), (2, 'p2');
        CREATE TABLE parties (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            party_id TEXT NOT NULL UNIQUE,
            party_type TEXT NOT NULL CHECK (party_type IN ('exploration_pair')),
            status TEXT NOT NULL CHECK (status IN ('forming', 'ready', 'disbanded', 'expired')),
            leader_id INTEGER NOT NULL REFERENCES players(id),
            location_key TEXT NOT NULL,
            confirmation_deadline TEXT NOT NULL,
            current_session_id TEXT,
            distribution_key TEXT NOT NULL DEFAULT 'contribution',
            content_version TEXT NOT NULL,
            rule_version TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE party_members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            party_id TEXT NOT NULL REFERENCES parties(party_id),
            player_id INTEGER NOT NULL REFERENCES players(id),
            role TEXT NOT NULL,
            status TEXT NOT NULL,
            confirmed_at TEXT,
            invited_at TEXT NOT NULL,
            joined_at TEXT,
            left_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE party_battle_sessions (battle_id TEXT PRIMARY KEY, party_id TEXT NOT NULL REFERENCES parties(party_id));
        INSERT INTO parties(party_id, party_type, status, leader_id, location_key, confirmation_deadline, content_version, rule_version, created_at, updated_at)
        VALUES ('party-old', 'exploration_pair', 'forming', 1, 'xuantian.new_town', '2026-01-01', 'c', 'r', '2026-01-01', '2026-01-01');
        INSERT INTO party_members(party_id, player_id, role, status, invited_at, created_at, updated_at)
        VALUES ('party-old', 1, 'leader', 'active', '2026-01-01', '2026-01-01', '2026-01-01');
        INSERT INTO party_battle_sessions(battle_id, party_id) VALUES ('battle-old', 'party-old');
        """
    )

    SQLitePlayerRepository._migrate_party_type_schema(connection)

    connection.execute(
        "INSERT INTO parties(party_id, party_type, status, leader_id, location_key, confirmation_deadline, content_version, rule_version, created_at, updated_at) VALUES ('party-trio', 'arena_trio', 'forming', 2, 'xuantian.new_town', '2026-01-01', 'c', 'r', '2026-01-01', '2026-01-01')"
    )
    connection.execute(
        "INSERT INTO parties(party_id, party_type, status, leader_id, location_key, confirmation_deadline, content_version, rule_version, created_at, updated_at) VALUES ('party-standard', 'standard_pve', 'forming', 2, 'xuantian.outskirts', '2026-01-01', 'content-0.3', 'social-0.3.2', '2026-01-01', '2026-01-01')"
    )
    assert connection.execute("SELECT party_type FROM parties WHERE party_id = 'party-old'").fetchone()[0] == "exploration_pair"
    assert connection.execute("SELECT party_type FROM parties WHERE party_id = 'party-standard'").fetchone()[0] == "standard_pve"
    assert connection.execute("SELECT party_id FROM party_members WHERE party_id = 'party-old'").fetchone()[0] == "party-old"
    assert connection.execute("SELECT party_id FROM party_battle_sessions WHERE battle_id = 'battle-old'").fetchone()[0] == "party-old"
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    connection.close()
