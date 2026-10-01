import sqlite3

from nonebot_plugin_xiuxian_3.xiuxian.persistence.schema import SCHEMA


def test_current_party_schema_has_no_release_markers() -> None:
    connection = sqlite3.connect(":memory:", isolation_level=None)
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript(SCHEMA)

    party_columns = {row[1] for row in connection.execute("PRAGMA table_info(parties)")}
    battle_columns = {
        row[1] for row in connection.execute("PRAGMA table_info(party_battle_sessions)")
    }
    connection.close()
