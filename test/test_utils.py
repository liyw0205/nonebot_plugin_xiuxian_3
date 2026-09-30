from __future__ import annotations

import os
import sqlite3

import pytest

from nonebot_plugin_xiuxian_3.xiuxian.utils.database import connect_sqlite
from nonebot_plugin_xiuxian_3.xiuxian.utils.json import json_object
from nonebot_plugin_xiuxian_3.xiuxian.utils.json_cache import (
    DuplicateJSONKeyError,
    clear_json_cache,
    read_json_cached,
)


def test_json_cache_returns_copies_and_invalidates_changed_files(tmp_path) -> None:
    path = tmp_path / "content.json"
    path.write_text('{"value": [1]}', encoding="utf-8")
    clear_json_cache()

    first = read_json_cached(path)
    first["value"].append(2)
    assert read_json_cached(path) == {"value": [1]}

    before = path.stat().st_mtime_ns
    path.write_text('{"value": [3]}', encoding="utf-8")
    os.utime(path, ns=(before + 1_000_000, before + 1_000_000))
    assert read_json_cached(path) == {"value": [3]}


def test_json_cache_invalidates_replaced_files_and_rejects_duplicate_keys(tmp_path) -> None:
    path = tmp_path / "content.json"
    replacement = tmp_path / "replacement.json"
    path.write_text('{"value": 1}', encoding="utf-8")
    clear_json_cache()
    assert read_json_cached(path) == {"value": 1}

    replacement.write_text('{"value": 2}', encoding="utf-8")
    replacement.replace(path)
    assert read_json_cached(path) == {"value": 2}

    path.write_text('{"value": 1, "value": 2}', encoding="utf-8")
    with pytest.raises(DuplicateJSONKeyError, match="duplicate JSON object key"):
        read_json_cached(path)


def test_sqlite_connection_uses_shared_pragmas(tmp_path) -> None:
    database_path = tmp_path / "store" / "test.sqlite3"
    connection = connect_sqlite(database_path, busy_timeout_ms=1200)
    try:
        assert isinstance(connection, sqlite3.Connection)
        assert connection.row_factory is sqlite3.Row
        assert connection.execute("PRAGMA busy_timeout").fetchone()[0] == 1200
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert connection.execute("PRAGMA synchronous").fetchone()[0] == 1
    finally:
        connection.close()


def test_json_object_normalizes_stored_values_without_sharing_defaults() -> None:
    default = {"spirit_stones": 3}

    assert json_object('{"spirit_stones": 5}') == {"spirit_stones": 5}
    assert json_object({"spirit_stones": 7}) == {"spirit_stones": 7}
    assert json_object("invalid json", default) == default
    assert json_object([], default) == default

    decoded = json_object(None, default)
    decoded["spirit_stones"] = 0
    assert default == {"spirit_stones": 3}
