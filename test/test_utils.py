from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone

import pytest

from nonebot_plugin_xiuxian_3.xiuxian.utils.database import connect_sqlite
from nonebot_plugin_xiuxian_3.xiuxian.utils.assets import (
    AssetState,
    AssetTransition,
    AssetDeltaError,
    apply_player_asset_transition,
    grant_player_currency,
    apply_player_assets,
    change_player_currency,
    change_player_items,
    assets_grant,
    assets_spend,
    assets_with_delta,
    asset_transition,
    currency_grant,
    currency_spend,
    currency_with_delta,
    grant_player_assets,
    grant_player_items,
    inventory_grant,
    inventory_json,
    inventory_missing,
    inventory_spend,
    inventory_value,
    inventory_with_delta,
    player_asset_state,
    player_asset_amount,
    player_asset_amounts,
    player_assets_missing,
    player_has_assets,
    player_currency,
    player_item_amount,
    spend_player_assets,
    spend_player_currency,
    spend_player_items,
    write_player_values,
)
from nonebot_plugin_xiuxian_3.contracts import PlayerView
from nonebot_plugin_xiuxian_3.xiuxian.combat.repository import CombatRepositoryMixin
from nonebot_plugin_xiuxian_3.xiuxian.utils.json import json_list, json_object
from nonebot_plugin_xiuxian_3.xiuxian.utils.json_cache import (
    DuplicateJSONKeyError,
    clear_json_cache,
    read_json_cached,
)
from nonebot_plugin_xiuxian_3.xiuxian.utils.player import (
    PLAYER_NUMERIC_FIELDS,
    PLAYER_VIEW_FIELDS,
    player_field,
    player_integer,
    player_numeric_delta,
    change_player_state,
    change_player_values,
    grant_player_state,
    spend_player_state,
    player_object,
    player_inventory,
    player_qualification,
    player_intro_flags,
    player_combat_values,
    player_reputation,
    player_reputation_with_delta,
    player_values,
    player_numeric_values,
    player_has_values,
    player_requirements_missing,
    player_has_requirements,
    player_values_missing,
    player_realm_values,
    player_profile_values,
    player_resource_bars,
    player_state_values,
    player_status_values,
    player_projection,
    player_view_values,
    split_player_rewards,
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


def test_json_list_normalizes_stored_values_without_sharing_defaults() -> None:
    default = [{"key": "value"}]

    assert json_list('[{"key": "stored"}]') == [{"key": "stored"}]
    decoded = json_list('[{"key": "stored"}]')
    decoded.append({"key": "extra"})
    assert json_list('[{"key": "stored"}]') == [{"key": "stored"}]
    assert json_list("invalid json", default) == default
    assert json_list(None, default) == default
    assert default == [{"key": "value"}]


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


def test_player_asset_reads_share_row_and_projection_shapes() -> None:
    player = PlayerView(
        player_id="p1",
        platform="qq.official",
        platform_user_id="u1",
        scene_id="s1",
        nickname="道友",
        dao_name="玄尘",
        stage="cultivator",
        spirit_stones=80,
        qualification={"body": 10},
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        inventory={"item.herb": 2},
        realm_key="qi_sensing",
        realm_layer=1,
    )
    assert player_asset_amount(player, "spirit_stones") == 80
    assert player_asset_amount(player, "item.herb") == 2
    assert player_asset_amounts(player, ["spirit_stones", "item.herb"]) == {
        "spirit_stones": 80,
        "item.herb": 2,
    }
    assert player_assets_missing(player, {"spirit_stones": 100, "item.herb": 3}) == {
        "spirit_stones": 20,
        "item.herb": 1,
    }


def test_player_asset_reads_allow_partial_currency_rows_and_preserve_zero_items() -> None:
    assert player_asset_amount({"spirit_stones": "42"}, "currency.spirit_stone") == 42
    assert player_currency({"spirit_stones": "42"}) == 42
    assert player_inventory({"inventory_json": '{"item.herb": 2, "item.empty": 0}'}, keep_zero=True) == {
        "item.herb": 2,
        "item.empty": 0,
    }
    assert player_item_amount({"spirit_stones": 42, "inventory_json": '{"item.herb": 2}'}, "item.herb") == 2
    with pytest.raises(AssetDeltaError, match="item key cannot address currency"):
        player_item_amount({"spirit_stones": 42, "inventory_json": "{}"}, "spirit_stones")


def test_player_requirement_helpers_share_asset_and_numeric_reading() -> None:
    row = {
        "spirit_stones": 80,
        "inventory_json": '{"item.herb": 2}',
        "stamina": 4,
    }
    assert player_has_assets(row, {"spirit_stones": 80, "item.herb": 2})
    assert not player_has_assets(row, {"spirit_stones": 81})
    assert player_values_missing(row, {"stamina": 6, "energy": 1}) == {
        "stamina": 2,
        "energy": 1,
    }
    assert player_has_values(row, {"stamina": 4})
    with pytest.raises(ValueError, match="must be non-negative"):
        player_values_missing(row, {"stamina": -1})


def test_player_requirements_combine_assets_and_numeric_resources() -> None:
    row = {
        "spirit_stones": 80,
        "inventory_json": '{"item.herb": 2}',
        "stamina": 4,
        "energy": 9,
    }
    assert player_requirements_missing(
        row,
        assets={"spirit_stones": 100, "item.herb": 3},
        values={"stamina": 6, "energy": 8},
    ) == {"spirit_stones": 20, "item.herb": 1, "stamina": 2}
    assert player_has_requirements(
        row,
        assets={"spirit_stones": 80, "item.herb": 2},
        values={"stamina": 4},
    )
    with pytest.raises(ValueError, match="duplicated"):
        player_requirements_missing(row, assets={"energy": 1}, values={"energy": 1})
    with pytest.raises(ValueError, match="at least one"):
        player_requirements_missing(row)


def test_player_state_kernel_persists_assets_and_shared_views_atomically() -> None:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute(
        "CREATE TABLE players("
        "id INTEGER PRIMARY KEY, spirit_stones INTEGER NOT NULL, "
        "inventory_json TEXT NOT NULL, energy INTEGER NOT NULL, "
        "energy_max INTEGER NOT NULL, updated_at TEXT NOT NULL)"
    )
    connection.execute(
        "INSERT INTO players(id, spirit_stones, inventory_json, energy, energy_max, updated_at) "
        "VALUES (1, 80, ?, 4, 10, '')",
        ('{"item.herb": 2}',),
    )
    row = connection.execute("SELECT * FROM players WHERE id = 1").fetchone()
    assert row is not None

    grant_player_state(
        connection,
        row,
        {"spirit_stones": 40, "item.herb": 3},
        "now",
        value_delta={"energy": 20},
        maximums={"energy": row["energy_max"]},
    )
    connection.commit()
    updated = connection.execute("SELECT * FROM players WHERE id = 1").fetchone()
    assert updated is not None
    assert player_currency(updated) == 120
    assert player_inventory(updated) == {"item.herb": 5}
    assert player_integer(updated, "energy") == 10

    profile = player_profile_values(updated)
    status = player_status_values(updated)
    combat = player_combat_values(updated)
    assert profile["spirit_stones"] == status["spirit_stones"] == 120
    assert profile["energy"] == status["energy"] == 10
    assert combat["energy"] == 10
    assert player_state_values(updated)["inventory"] == {"item.herb": 5}

    with pytest.raises(AssetDeltaError, match="missing items"):
        spend_player_state(
            connection,
            updated,
            {"item.herb": 99},
            "later",
            value_delta={"energy": -3},
        )
    unchanged = connection.execute("SELECT * FROM players WHERE id = 1").fetchone()
    assert unchanged is not None
    assert player_currency(unchanged) == 120
    assert player_inventory(unchanged) == {"item.herb": 5}
    assert player_integer(unchanged, "energy") == 10


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


def test_asset_transition_exposes_one_validated_before_after_pair() -> None:
    transition = asset_transition(
        "100",
        {"item.herb": "2"},
        {"spirit_stones": -25, "item.herb": -1, "item.sand": 3},
    )
    assert transition == AssetTransition(
        before=AssetState(100, {"item.herb": 2}),
        after=AssetState(75, {"item.herb": 1, "item.sand": 3}),
        mode="delta",
    )
    with pytest.raises(AssetDeltaError):
        asset_transition(0, {}, {"spirit_stones": -1}, mode="delta")


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


def test_player_asset_operation_dispatch_keeps_one_transaction_kernel() -> None:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute(
        "CREATE TABLE players (id INTEGER PRIMARY KEY, spirit_stones INTEGER NOT NULL, inventory_json TEXT NOT NULL, updated_at TEXT NOT NULL)"
    )
    connection.execute(
        "INSERT INTO players(id, spirit_stones, inventory_json, updated_at) VALUES (1, 10, ?, 'before')",
        ('{"item.herb": 1}',),
    )
    row = connection.execute("SELECT * FROM players WHERE id = 1").fetchone()
    assert apply_player_assets(connection, row, {"spirit_stones": 5}, "after-grant", mode="grant").currency == 15
    row = connection.execute("SELECT * FROM players WHERE id = 1").fetchone()
    assert apply_player_assets(connection, row, {"item.herb": 1}, "after-spend", mode="spend").inventory == {}
    row = connection.execute("SELECT * FROM players WHERE id = 1").fetchone()
    assert apply_player_assets(connection, row, {"spirit_stones": -3}, "after-delta", mode="delta").currency == 12
    with pytest.raises(ValueError, match="unsupported asset operation"):
        apply_player_assets(connection, row, {}, "after-invalid", mode="unknown")
    connection.close()


def test_player_asset_transition_persists_and_returns_the_same_states() -> None:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute(
        "CREATE TABLE players (id INTEGER PRIMARY KEY, spirit_stones INTEGER NOT NULL, inventory_json TEXT NOT NULL, updated_at TEXT NOT NULL)"
    )
    connection.execute(
        "INSERT INTO players(id, spirit_stones, inventory_json, updated_at) VALUES (1, 40, ?, 'before')",
        ('{"item.herb": 2}',),
    )
    row = connection.execute("SELECT * FROM players WHERE id = 1").fetchone()
    transition = apply_player_asset_transition(
        connection,
        row,
        {"spirit_stones": 10, "item.herb": -1, "item.sand": 2},
        "after",
    )
    assert transition.before == AssetState(40, {"item.herb": 2})
    assert transition.after == AssetState(50, {"item.herb": 1, "item.sand": 2})
    stored = connection.execute("SELECT spirit_stones, inventory_json, updated_at FROM players WHERE id = 1").fetchone()
    assert tuple(stored) == (50, '{"item.herb": 1, "item.sand": 2}', "after")
    connection.close()


def test_asset_shortcuts_share_the_same_player_transaction_kernel() -> None:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute(
        "CREATE TABLE players (id INTEGER PRIMARY KEY, spirit_stones INTEGER NOT NULL, inventory_json TEXT NOT NULL, energy INTEGER NOT NULL, updated_at TEXT NOT NULL)"
    )
    connection.execute(
        "INSERT INTO players(id, spirit_stones, inventory_json, energy, updated_at) VALUES (1, 10, ?, 8, 'before')",
        ('{"item.herb": 1}',),
    )
    row = connection.execute("SELECT * FROM players WHERE id = 1").fetchone()
    grant_player_items(connection, row, {"item.sand": 2}, "items-granted")
    row = connection.execute("SELECT * FROM players WHERE id = 1").fetchone()
    spend_player_items(connection, row, {"item.herb": 1}, "items-spent")
    row = connection.execute("SELECT * FROM players WHERE id = 1").fetchone()
    grant_player_currency(connection, row, 5, "currency-added", player_values={"energy": 9})
    row = connection.execute("SELECT * FROM players WHERE id = 1").fetchone()
    spend_player_currency(connection, row, 3, "currency-spent")
    stored = connection.execute("SELECT spirit_stones, inventory_json, energy, updated_at FROM players WHERE id = 1").fetchone()
    assert tuple(stored) == (12, '{"item.sand": 2}', 9, "currency-spent")
    connection.close()


def test_signed_currency_and_item_changes_share_the_same_kernel() -> None:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute(
        "CREATE TABLE players (id INTEGER PRIMARY KEY, spirit_stones INTEGER NOT NULL, inventory_json TEXT NOT NULL, updated_at TEXT NOT NULL)"
    )
    connection.execute(
        "INSERT INTO players(id, spirit_stones, inventory_json, updated_at) VALUES (1, 30, ?, 'before')",
        ('{"item.herb": 3}',),
    )
    row = connection.execute("SELECT * FROM players WHERE id = 1").fetchone()
    change_player_currency(connection, row, -10, "currency-changed")
    row = connection.execute("SELECT * FROM players WHERE id = 1").fetchone()
    change_player_items(connection, row, {"item.herb": -2, "item.sand": 1}, "items-changed")
    stored = connection.execute("SELECT spirit_stones, inventory_json, updated_at FROM players WHERE id = 1").fetchone()
    assert tuple(stored) == (20, '{"item.herb": 1, "item.sand": 1}', "items-changed")
    with pytest.raises(AssetDeltaError):
        change_player_currency(
            connection,
            connection.execute("SELECT * FROM players WHERE id = 1").fetchone(),
            -21,
            "rejected",
        )
    assert connection.execute("SELECT spirit_stones FROM players WHERE id = 1").fetchone()[0] == 20
    connection.close()


def test_player_asset_mutation_can_commit_other_player_values_atomically() -> None:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute(
        "CREATE TABLE players (id INTEGER PRIMARY KEY, spirit_stones INTEGER NOT NULL, inventory_json TEXT NOT NULL, energy INTEGER NOT NULL, updated_at TEXT NOT NULL)"
    )
    connection.execute(
        "INSERT INTO players(id, spirit_stones, inventory_json, energy, updated_at) VALUES (1, 100, ?, 8, 'before')",
        ('{"item.herb": 2}',),
    )
    row = connection.execute("SELECT * FROM players WHERE id = 1").fetchone()

    changed = spend_player_assets(
        connection,
        row,
        {"spirit_stones": 25, "item.herb": 1},
        "spent",
        player_values={"energy": 3},
    )
    assert changed == player_asset_state(
        connection.execute("SELECT * FROM players WHERE id = 1").fetchone()
    )
    stored = connection.execute(
        "SELECT spirit_stones, inventory_json, energy, updated_at FROM players WHERE id = 1"
    ).fetchone()
    assert tuple(stored) == (75, '{"item.herb": 1}', 3, "spent")

    with pytest.raises(ValueError, match="invalid player column"):
        write_player_values(connection, 1, {"energy; DROP TABLE players": 1}, "bad")
    connection.close()


def test_asset_mutations_accept_the_content_currency_key() -> None:
    current = assets_spend(
        500,
        {"item.herb": 2},
        {"currency.spirit_stone": 125, "item.herb": 1},
    )
    assert current == AssetState(currency=375, inventory={"item.herb": 1})


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
    assert combat["max_hp"] == values["max_hp"]
    assert combat["initiative"] == values["initiative"]
    assert combat["pollution"] == values["pollution"]
    combat["inventory"]["item.herb"] = 99
    assert values["inventory"] == {"item.herb": 2}
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


def test_player_reputation_delta_uses_stable_faction_keys_and_validation() -> None:
    row = {"faction_reputation_json": '{"xuantian": "4"}'}
    assert player_reputation_with_delta(
        row,
        {"faction_reputation.xuantian": 6, "faction_reputation.beast": 2},
    ) == {"xuantian": 10, "beast": 2}
    with pytest.raises(ValueError, match="unsupported reputation key"):
        player_reputation_with_delta(row, {"xuantian": 1})
    with pytest.raises(ValueError, match="must be an integer"):
        player_reputation_with_delta(row, {"faction_reputation.xuantian": True})
    with pytest.raises(ValueError, match="cannot be negative"):
        player_reputation_with_delta(row, {"faction_reputation.xuantian": -5})


def test_split_player_rewards_reuses_one_state_partition_for_settlement() -> None:
    parts = split_player_rewards(
        {
            "item.herb.blood_grass": 2,
            "currency.spirit_stone": 5,
            "cultivation": 40,
            "faction_reputation.beast": 3,
        }
    )
    assert parts.assets == {
        "item.herb.blood_grass": 2,
        "spirit_stones": 5,
    }
    assert parts.value_delta == {"cultivation": 40, "total_cultivation": 40}
    assert parts.reputation == {"faction_reputation.beast": 3}

    with pytest.raises(ValueError, match="unsupported player reward key"):
        split_player_rewards({"reward.unknown": 1})
    with pytest.raises(ValueError, match="cannot be negative"):
        split_player_rewards({"item.herb.blood_grass": -1})


@pytest.mark.parametrize("amount", [True, False, 1.5, 1.0, "1", None])
def test_split_player_rewards_requires_integer_quantities(amount) -> None:
    with pytest.raises(ValueError, match="must be an integer"):
        split_player_rewards({"item.herb.blood_grass": amount})


@pytest.mark.parametrize("key", [None, 1, True, ""])
def test_split_player_rewards_requires_nonempty_string_keys(key) -> None:
    with pytest.raises(ValueError, match="must be a non-empty string"):
        split_player_rewards({key: 1})


@pytest.mark.parametrize("key", ["stamina_max", "energy_max", "soul_power_max"])
def test_split_player_rewards_rejects_resource_maximums(key: str) -> None:
    with pytest.raises(ValueError, match="unsupported player reward key"):
        split_player_rewards({key: 1})


@pytest.mark.parametrize("key", ["item.", "faction_reputation."])
def test_split_player_rewards_requires_named_assets_and_factions(key: str) -> None:
    with pytest.raises(ValueError, match="must name"):
        split_player_rewards({key: 1})


def test_split_player_rewards_preserves_zero_and_explicit_cumulative_values() -> None:
    parts = split_player_rewards(
        {"item.herb.blood_grass": 0, "cultivation": 4, "total_cultivation": 7}
    )
    assert parts.assets == {"item.herb.blood_grass": 0}
    assert parts.value_delta == {"cultivation": 4, "total_cultivation": 7}


def test_player_integer_projection_is_shared_by_profile_and_combat_reads() -> None:
    row = {"spirit_stones": "12", "stamina": "8", "energy": 4, "world_merit": "2"}
    resources = player_numeric_values(row)
    assert resources["spirit_stones"] == 12
    assert resources["stamina"] == 8
    assert player_numeric_values(row, ("energy", "world_merit")) == {"energy": 4, "world_merit": 2}
    assert player_values(row)["spirit_stones"] == resources["spirit_stones"]


def test_player_projection_uses_one_numeric_field_table() -> None:
    row = {
        "spirit_stones": "12",
        "stamina": "8",
        "arena_rating": None,
        "domain_power": "17",
        "dao_fruit_progress": "4",
    }
    values = player_values(row)

    assert "domain_power" in PLAYER_NUMERIC_FIELDS
    assert "dao_fruit_progress" in PLAYER_NUMERIC_FIELDS
    assert values["spirit_stones"] == 12
    assert values["arena_rating"] == 1000
    assert values["domain_power"] == 17
    assert values["dao_fruit_progress"] == 4


def test_player_view_field_definitions_are_unique() -> None:
    for fields in PLAYER_VIEW_FIELDS.values():
        assert len(fields) == len(set(fields))

    combat = player_combat_values({"faction_reputation_json": '{"demon": 3}'})
    assert combat["faction_reputation"] == {"demon": 3}


def test_player_profile_and_status_projections_are_detached_and_consistent() -> None:
    row = {
        "player_id": "p1",
        "dao_name": "玄尘",
        "stage": "cultivator",
        "realm_key": "foundation",
        "realm_layer": 3,
        "spirit_stones": 12,
        "stamina": 8,
        "stamina_max": 10,
        "energy": 4,
        "energy_max": 6,
        "inventory_json": '{"item.herb": 2}',
        "qualification_json": '{"body": 12}',
    }
    profile = player_profile_values(row)
    status = player_status_values(row)
    profile_view = player_view_values(row, "profile")
    status_view = player_view_values(row, "status")
    assert profile["realm_key"] == status["realm_key"] == "foundation"
    assert profile["inventory"] == status["inventory"] == {"item.herb": 2}
    assert profile_view == profile
    assert status_view == status
    profile["inventory"]["item.herb"] = 99
    assert status["inventory"] == {"item.herb": 2}
    assert player_projection(row, ("spirit_stones", "energy")) == {"spirit_stones": 12, "energy": 4}
    assert player_view_values(row, "combat")["inventory"] == {"item.herb": 2}
    with pytest.raises(ValueError, match="unsupported player view"):
        player_view_values(row, "unknown")  # type: ignore[arg-type]


def test_combat_projection_reuses_normalized_flags_and_reputation() -> None:
    row = {
        "player_id": "p1",
        "qualification_json": '{"cross_realm_alliance": "alliance.demon", "body": 12}',
        "intro_json": '{"flags": ["access.demon.fallen_ruins", "alliance.beast"]}',
        "faction_reputation_json": '{"demon": "240", "beast": 80}',
        "inventory_json": "{}",
    }

    combat = player_combat_values(row)

    assert combat["qualification"] == {"body": 12}
    assert combat["intro_flags"] == ("access.demon.fallen_ruins", "alliance.beast")
    assert combat["faction_reputation"] == {"demon": 240, "beast": 80}


def test_player_state_reader_and_resource_bars_share_one_normalized_source() -> None:
    row = {
        "player_id": "p1",
        "spirit_stones": "12",
        "stamina": "8",
        "stamina_max": "10",
        "energy": 4,
        "energy_max": 6,
        "soul_power": "3",
        "soul_power_max": "9",
        "inventory_json": '{"item.herb": "2"}',
    }
    full = player_state_values(row)
    assert full == player_values(row)
    assert player_state_values(row, "profile")["spirit_stones"] == 12
    assert player_state_values(row, "status")["stamina"] == 8
    assert player_state_values(row, "combat")["inventory"] == {"item.herb": 2}
    assert player_resource_bars(row) == {
        "stamina": {"current": 8, "maximum": 10},
        "energy": {"current": 4, "maximum": 6},
        "soul_power": {"current": 3, "maximum": 9},
        "domain_charge": {"current": 0, "maximum": 0},
        "void_power": {"current": 0, "maximum": 0},
    }


def test_player_numeric_projection_and_delta_share_resource_validation() -> None:
    row = {
        "realm_key": "foundation",
        "realm_layer": "4",
        "stamina": 8,
        "stamina_max": 10,
        "pollution": 3,
    }
    assert player_integer(row, "stamina") == 8
    assert player_realm_values(row) == {
        "stage": "new_user",
        "status": "active",
        "location_key": "xuantian.new_town",
        "realm_key": "foundation",
        "realm_layer": 4,
        "path_key": None,
        "subprofession_key": None,
    }
    assert player_numeric_delta(row, {"stamina": 3}, maximums={"stamina": 10}) == {"stamina": 10}
    assert player_numeric_delta({"stamina": 100}, {"stamina": -20}, maximums={"stamina": 0}) == {
        "stamina": 80
    }
    assert player_numeric_delta(row, {"pollution": -3}) == {"pollution": 0}
    assert player_numeric_delta(row, {"stamina": -9}, clamp_minimum=True) == {"stamina": 0}
    with pytest.raises(ValueError, match="cannot be below"):
        player_numeric_delta(row, {"stamina": -9})


def test_combat_realm_gate_uses_shared_realm_projection() -> None:
    assert CombatRepositoryMixin._meets_enemy_requirement(
        {"realm_key": "foundation", "realm_layer": "3"}, "foundation", 2
    )
    # Partial rows use the same neutral realm defaults as all other player views.
    assert CombatRepositoryMixin._meets_enemy_requirement({}, "mortal", 0)


def test_change_player_values_persists_the_same_validated_delta() -> None:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute(
        "CREATE TABLE players (id INTEGER PRIMARY KEY, stamina INTEGER NOT NULL, stamina_max INTEGER NOT NULL, world_merit INTEGER NOT NULL, updated_at TEXT NOT NULL)"
    )
    connection.execute("INSERT INTO players VALUES (1, 8, 10, 20, 'before')")
    row = connection.execute("SELECT * FROM players WHERE id=1").fetchone()
    assert change_player_values(connection, row, {"stamina": 5, "world_merit": 3}, "after", maximums={"stamina": row["stamina_max"]}) == {"stamina": 10, "world_merit": 23}
    stored = connection.execute("SELECT stamina, world_merit, updated_at FROM players WHERE id=1").fetchone()
    assert tuple(stored) == (10, 23, "after")
    connection.close()


def test_change_player_state_commits_assets_and_numeric_values_together() -> None:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute(
        "CREATE TABLE players (id INTEGER PRIMARY KEY, spirit_stones INTEGER NOT NULL, inventory_json TEXT NOT NULL, stamina INTEGER NOT NULL, stamina_max INTEGER NOT NULL, world_merit INTEGER NOT NULL, updated_at TEXT NOT NULL)"
    )
    connection.execute(
        "INSERT INTO players VALUES (1, 100, ?, 8, 10, 20, 'before')",
        ('{"item.herb": 2}',),
    )
    row = connection.execute("SELECT * FROM players WHERE id=1").fetchone()

    result = change_player_state(
        connection,
        row,
        updated_at="after",
        asset_values={"spirit_stones": 25, "item.herb": 1, "item.sand": 2},
        asset_mode="delta",
        value_delta={"stamina": 5, "world_merit": -3},
        maximums={"stamina": row["stamina_max"]},
    )

    assert result.values == {"stamina": 10, "world_merit": 17}
    assert result.assets == AssetState(125, {"item.herb": 3, "item.sand": 2})
    stored = connection.execute(
        "SELECT spirit_stones, inventory_json, stamina, world_merit, updated_at FROM players WHERE id=1"
    ).fetchone()
    assert tuple(stored) == (125, '{"item.herb": 3, "item.sand": 2}', 10, 17, "after")
    connection.close()


def test_grant_and_spend_player_state_use_the_same_asset_numeric_kernel() -> None:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute(
        "CREATE TABLE players (id INTEGER PRIMARY KEY, spirit_stones INTEGER NOT NULL, inventory_json TEXT NOT NULL, energy INTEGER NOT NULL, updated_at TEXT NOT NULL)"
    )
    connection.execute(
        "INSERT INTO players(id, spirit_stones, inventory_json, energy, updated_at) VALUES (1, 20, ?, 4, 'before')",
        ('{"item.herb": 1}',),
    )

    row = connection.execute("SELECT * FROM players WHERE id=1").fetchone()
    granted = grant_player_state(
        connection,
        row,
        {"spirit_stones": 10, "item.sand": 2},
        "grant",
        value_delta={"energy": 3},
    )
    assert granted.assets == AssetState(30, {"item.herb": 1, "item.sand": 2})
    assert granted.values == {"energy": 7}

    row = connection.execute("SELECT * FROM players WHERE id=1").fetchone()
    spent = spend_player_state(
        connection,
        row,
        {"spirit_stones": 5, "item.herb": 1},
        "spend",
        value_delta={"energy": -2},
    )
    assert spent.assets == AssetState(25, {"item.sand": 2})
    assert spent.values == {"energy": 5}
    stored = connection.execute(
        "SELECT spirit_stones, inventory_json, energy, updated_at FROM players WHERE id=1"
    ).fetchone()
    assert tuple(stored) == (25, '{"item.sand": 2}', 5, "spend")
    connection.close()


def test_change_player_state_rejects_duplicate_numeric_values_before_writing() -> None:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute(
        "CREATE TABLE players (id INTEGER PRIMARY KEY, spirit_stones INTEGER NOT NULL, inventory_json TEXT NOT NULL, energy INTEGER NOT NULL, updated_at TEXT NOT NULL)"
    )
    connection.execute(
        "INSERT INTO players VALUES (1, 10, '{}', 8, 'before')"
    )
    row = connection.execute("SELECT * FROM players WHERE id=1").fetchone()

    with pytest.raises(ValueError, match="supplied more than once"):
        change_player_state(
            connection,
            row,
            updated_at="after",
            asset_values={"spirit_stones": 1},
            value_delta={"energy": 1},
            player_values={"energy": 9},
        )

    assert tuple(connection.execute("SELECT spirit_stones, energy, updated_at FROM players").fetchone()) == (10, 8, "before")
    connection.close()


def test_change_player_state_commits_json_player_fields_with_assets() -> None:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute(
        "CREATE TABLE players (id INTEGER PRIMARY KEY, spirit_stones INTEGER NOT NULL, inventory_json TEXT NOT NULL, intro_json TEXT NOT NULL, updated_at TEXT NOT NULL)"
    )
    connection.execute(
        "INSERT INTO players VALUES (1, 10, '{}', '{}', 'before')"
    )
    row = connection.execute("SELECT * FROM players WHERE id=1").fetchone()

    change_player_state(
        connection,
        row,
        updated_at="after",
        asset_values={"spirit_stones": 5, "item.sand": 1},
        asset_mode="grant",
        player_values={"intro_json": '{"flags":["guide.one"]}'},
    )

    stored = connection.execute(
        "SELECT spirit_stones, inventory_json, intro_json, updated_at FROM players WHERE id=1"
    ).fetchone()
    assert tuple(stored) == (15, '{"item.sand": 1}', '{"flags":["guide.one"]}', "after")
    connection.close()
