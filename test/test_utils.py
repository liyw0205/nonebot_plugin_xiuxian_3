from __future__ import annotations

import os
import sqlite3

import pytest

from nonebot_plugin_xiuxian_3.xiuxian.utils.database import connect_sqlite
from nonebot_plugin_xiuxian_3.xiuxian.utils.assets import (
    AssetDeltaError,
    assets_grant,
    assets_spend,
    assets_with_delta,
    currency_grant,
    currency_spend,
    currency_with_delta,
    grant_player_assets,
    inventory_grant,
    inventory_json,
    inventory_missing,
    inventory_spend,
    inventory_value,
    inventory_with_delta,
    spend_player_assets,
)
from nonebot_plugin_xiuxian_3.xiuxian.utils.json import json_object
from nonebot_plugin_xiuxian_3.xiuxian.utils.json_cache import (
    DuplicateJSONKeyError,
    clear_json_cache,
    read_json_cached,
)
from nonebot_plugin_xiuxian_3.xiuxian.utils.player import (
    player_field,
    player_integer,
    player_object,
    player_inventory,
    player_qualification,
    player_intro_flags,
    player_combat_values,
    player_reputation,
    player_values,
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


def test_asset_helpers_share_inventory_and_currency_accounting() -> None:
    inventory = {"item.herb": 2, "item.sand": 1}

    assert inventory_missing(inventory, {"item.herb": 3, "item.sand": 1}) == {"item.herb": 1}
    assert inventory_spend(inventory, {"item.herb": 2}) == {"item.sand": 1}
    assert inventory_grant(inventory, {"item.herb": 3}) == {"item.herb": 5, "item.sand": 1}
    assert inventory_with_delta(inventory, {"item.sand": -1, "item.ore": 2}) == {
        "item.herb": 2,
        "item.ore": 2,
    }
    assert inventory == {"item.herb": 2, "item.sand": 1}
    assert inventory_value('{"item.herb": "2", "item.empty": 0}') == {"item.herb": 2}
    assert inventory_value('{"item.herb": "2", "item.empty": 0}', keep_zero=True) == {
        "item.herb": 2,
        "item.empty": 0,
    }
    assert inventory_json({"item.sand": 0, "item.herb": 2}) == '{"item.herb": 2}'
    assert inventory_json({"item.sand": 0, "item.herb": 2}, keep_zero=True) == '{"item.herb": 2, "item.sand": 0}'
    assert currency_grant(100, 40) == 140
    assert currency_spend(100, 40) == 60
    assert currency_with_delta(100, -40) == 60
    assert currency_with_delta(100, 40) == 140
    with pytest.raises(AssetDeltaError):
        inventory_spend(inventory, {"item.herb": 3})
    with pytest.raises(AssetDeltaError):
        currency_with_delta(0, -1)


def test_asset_state_applies_currency_and_items_together() -> None:
    inventory = {"item.herb": 2}

    granted = assets_grant(100, inventory, {"spirit_stones": 40, "item.herb": 3})
    assert granted.currency == 140
    assert granted.inventory == {"item.herb": 5}

    spent = assets_spend(granted.currency, granted.inventory, {"spirit_stones": 20, "item.herb": 2})
    assert spent.currency == 120
    assert spent.inventory == {"item.herb": 3}
    assert assets_with_delta(120, spent.inventory, {"spirit_stones": -20, "item.herb": -1}).inventory == {"item.herb": 2}
    assert inventory == {"item.herb": 2}

    with pytest.raises(AssetDeltaError):
        assets_spend(0, {}, {"spirit_stones": 1})
    with pytest.raises(AssetDeltaError):
        assets_grant(0, {}, {"spirit_stones": -1})


def test_player_asset_mutations_share_transactional_persistence() -> None:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute(
        "CREATE TABLE players (id INTEGER PRIMARY KEY, spirit_stones INTEGER NOT NULL, inventory_json TEXT NOT NULL, updated_at TEXT NOT NULL)"
    )
    connection.execute(
        "INSERT INTO players(id, spirit_stones, inventory_json, updated_at) VALUES (1, 100, ?, 'before')",
        ('{"item.herb": 2}',),
    )
    row = connection.execute("SELECT * FROM players WHERE id = 1").fetchone()

    spent = spend_player_assets(
        connection,
        row,
        {"spirit_stones": 25, "item.herb": 1},
        "spent",
    )
    assert spent.currency == 75
    assert spent.inventory == {"item.herb": 1}
    granted = grant_player_assets(
        connection,
        connection.execute("SELECT * FROM players WHERE id = 1").fetchone(),
        {"spirit_stones": 10, "item.sand": 3},
        "granted",
    )
    assert granted.currency == 85
    assert granted.inventory == {"item.herb": 1, "item.sand": 3}
    stored = connection.execute("SELECT spirit_stones, inventory_json, updated_at FROM players WHERE id = 1").fetchone()
    assert tuple(stored) == (85, '{"item.herb": 1, "item.sand": 3}', "granted")
    connection.close()


def test_player_values_normalizes_full_and_partial_rows() -> None:
    row = {
        "player_id": "p1",
        "dao_name": None,
        "qualification_json": '{"body": "12"}',
        "inventory_json": '{"item.herb": "2"}',
        "intro_json": '{"flags": ["guide.one"], "selected_service": "service.herb"}',
        "realm_key": "foundation",
        "realm_layer": "3",
        "max_hp": "240",
        "initiative": "18",
    }
    values = player_values(row)
    assert values["player_id"] == "p1"
    assert values["dao_name"] == ""
    assert values["qualification"] == {"body": 12}
    assert values["inventory"] == {"item.herb": 2}
    assert values["intro_flags"] == ("guide.one",)
    assert values["selected_service"] == "service.herb"
    assert values["realm_key"] == "foundation"
    assert values["realm_layer"] == 3
    assert values["max_hp"] == 240
    assert values["initiative"] == 18
    combat = player_combat_values(row)
    assert combat["qualification"] == values["qualification"]
    assert combat["inventory"] == values["inventory"]
    partial = player_values({"player_id": "p2", "qualification_json": "{}"})
    assert partial["realm_key"] == "mortal"
    assert partial["spirit_stones"] == 0
    assert player_field(row, "realm_key") == "foundation"
    assert player_field(row, "missing", "fallback") == "fallback"
    assert player_integer(row, "realm_layer") == 3
    with pytest.raises(ValueError):
        player_integer({"realm_layer": True}, "realm_layer")


def test_player_state_helpers_share_json_and_inventory_normalization() -> None:
    row = {
        "qualification_json": '{"body": "12", "mind": 8}',
        "inventory_json": '{"item.herb": "2", "item.empty": 0}',
        "intro_json": '{"flags": ["story.one", 2]}',
        "faction_reputation_json": '{"demon": "20", "beast": 5}',
    }
    assert player_object(row, "intro_json") == {"flags": ["story.one", 2]}
    assert player_inventory(row) == {"item.herb": 2}
    assert player_qualification(row) == {"body": 12, "mind": 8}
    assert player_intro_flags(row) == ("story.one", "2")
    assert player_reputation(row) == {"demon": 20, "beast": 5}
