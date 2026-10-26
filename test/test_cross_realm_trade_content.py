from __future__ import annotations

import asyncio
import json
import shutil
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle, ContentError
from nonebot_plugin_xiuxian_3.xiuxian.economy import cross_realm_trade_rules
from nonebot_plugin_xiuxian_3.xiuxian.economy.cross_realm_trade_content import (
    DEFAULTS_KEY,
    KIND,
    cross_realm_trade_alias_map,
    cross_realm_trade_definitions,
    cross_realm_trade_defaults,
)

ROOT = Path(__file__).resolve().parents[1]
TRADE_FILE = Path("经济/跨界贸易.json")


def _context(adapter: str, user: str, request: str, operation: str = "") -> CommandContext:
    return CommandContext(
        adapter=adapter,
        user_id=user,
        request_id=request,
        operation_id=operation,
        can_write_assets=True,
    )


class MutableClock:
    def __init__(self, value: datetime):
        self.value = value

    def __call__(self) -> datetime:
        return self.value

    def advance(self, **kwargs: int) -> None:
        self.value += timedelta(**kwargs)


def _records(data_dir: Path) -> dict[str, dict]:
    document = json.loads((data_dir / TRADE_FILE).read_text(encoding="utf-8"))
    assert document["kind"] == KIND
    return {record["key"]: record for record in document["records"]}


def _write_records(data_dir: Path, records: list[dict]) -> None:
    document = json.loads((data_dir / TRADE_FILE).read_text(encoding="utf-8"))
    document["records"] = records
    (data_dir / TRADE_FILE).write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _copy_data(tmp_path: Path) -> Path:
    data_dir = tmp_path / "data"
    shutil.copytree(
        ROOT / "data", data_dir, ignore=shutil.ignore_patterns("*.sqlite3*", "*.db*")
    )
    return data_dir


def test_manifest_registers_the_trade_file() -> None:
    manifest = json.loads((ROOT / "data/内容清单.json").read_text(encoding="utf-8"))
    assert TRADE_FILE.as_posix() in manifest["files"]


def test_defaults_record_carries_the_shared_contract() -> None:
    defaults = cross_realm_trade_defaults()
    assert defaults == {
        "weekly_limit": 5,
        "binding_seconds": 86400,
        "required_reputation": 200,
    }
    assert cross_realm_trade_rules.WEEKLY_LIMIT == 5
    assert cross_realm_trade_rules.BINDING_SECONDS == 86400


def test_trade_definitions_match_the_shipped_contract() -> None:
    definitions = {record["key"]: record for record in cross_realm_trade_definitions()}
    assert tuple(sorted(definitions)) == (
        "trade.three_realms",
        "trade.three_realms.soul_crystal",
        "trade.xuantian_to_beast",
        "trade.xuantian_to_demon",
        "trade.xuantian_to_demon.array_sand",
    )
    demon = cross_realm_trade_rules.trade_definition("trade.xuantian_to_demon")
    assert demon.label == "云铁兑换魔核"
    assert demon.location_key == "demon.abyss_market" == cross_realm_trade_rules.TRADE_LOCATION
    assert demon.input_items == {"item.material.cloud_iron": 10}
    assert demon.currency_cost == 200
    assert demon.output_items == {"item.demon_core": 1}
    assert demon.weekly_limit == 5 and demon.binding_seconds == 86400
    assert demon.required_faction == "demon" and demon.required_reputation == 200
    assert demon.required_reputations is None

    beast = cross_realm_trade_rules.trade_definition("trade.xuantian_to_beast")
    assert beast.label == "灵叶兑换妖血"
    assert beast.location_key == "beast.ten_thousand_hills" == cross_realm_trade_rules.BEAST_TRADE_LOCATION
    assert beast.input_items == {"item.herb.spirit_leaf": 10}
    assert beast.currency_cost == 200
    assert beast.output_items == {"item.beast_blood": 1}
    assert beast.required_faction == "beast" and beast.required_reputation == 200
    assert beast.required_reputations is None

    three = cross_realm_trade_rules.trade_definition("trade.three_realms")
    assert three.label == "三界贸易口兑换神魂晶"
    assert three.location_key == "beast.three_realms_trade_port" == cross_realm_trade_rules.THREE_REALMS_TRADE_LOCATION
    assert three.input_items == {"item.demon_core": 2, "item.beast_blood": 2}
    assert three.currency_cost == 0
    assert three.output_items == {"item.soul_crystal": 1}
    assert three.weekly_limit == 3
    assert three.required_faction == "beast" and three.required_reputation == 200
    assert three.required_reputations == {"demon": 200, "beast": 200}

    array_sand = cross_realm_trade_rules.trade_definition(
        "trade.xuantian_to_demon.array_sand"
    )
    assert array_sand.label == "阵砂兑换魔核"
    assert array_sand.location_key == "demon.abyss_market" == cross_realm_trade_rules.TRADE_LOCATION
    assert array_sand.input_items == {"item.mat.array_sand": 10}
    assert array_sand.currency_cost == 200
    assert array_sand.output_items == {"item.demon_core": 1}
    assert array_sand.weekly_limit == 5 and array_sand.binding_seconds == 86400
    assert array_sand.required_faction == "demon" and array_sand.required_reputation == 200
    assert array_sand.required_reputations is None

    soul_return = cross_realm_trade_rules.trade_definition(
        "trade.three_realms.soul_crystal"
    )
    assert soul_return.label == "神魂晶兑换云铁"
    assert soul_return.location_key == "beast.three_realms_trade_port" == cross_realm_trade_rules.THREE_REALMS_TRADE_LOCATION
    assert soul_return.input_items == {"item.soul_crystal": 1}
    assert soul_return.currency_cost == 0
    assert soul_return.output_items == {"item.material.cloud_iron": 10}
    assert soul_return.weekly_limit == 3 and soul_return.binding_seconds == 86400
    assert soul_return.required_faction == "beast" and soul_return.required_reputation == 200
    assert soul_return.required_reputations == {"demon": 200, "beast": 200}


def test_alias_map_matches_the_shipped_vocabulary() -> None:
    assert cross_realm_trade_rules.TRADE_ALIASES == {
        "trade.xuantian_to_demon": "trade.xuantian_to_demon",
        "xuantian_to_demon": "trade.xuantian_to_demon",
        "云铁兑换魔核": "trade.xuantian_to_demon",
        "云铁换魔核": "trade.xuantian_to_demon",
        "玄天到魔界": "trade.xuantian_to_demon",
        "玄天界到魔界": "trade.xuantian_to_demon",
        "魔界贸易": "trade.xuantian_to_demon",
        "trade.xuantian_to_beast": "trade.xuantian_to_beast",
        "xuantian_to_beast": "trade.xuantian_to_beast",
        "灵叶兑换妖血": "trade.xuantian_to_beast",
        "灵叶换妖血": "trade.xuantian_to_beast",
        "玄天到妖界": "trade.xuantian_to_beast",
        "妖界贸易": "trade.xuantian_to_beast",
        "trade.three_realms": "trade.three_realms",
        "three_realms": "trade.three_realms",
        "三界贸易": "trade.three_realms",
        "三界贸易口": "trade.three_realms",
        "三界互市": "trade.three_realms",
        "魔核妖血换神魂晶": "trade.three_realms",
        "trade.xuantian_to_demon.array_sand": "trade.xuantian_to_demon.array_sand",
        "xuantian_to_demon.array_sand": "trade.xuantian_to_demon.array_sand",
        "阵砂兑换魔核": "trade.xuantian_to_demon.array_sand",
        "阵砂换魔核": "trade.xuantian_to_demon.array_sand",
        "阵砂到魔界": "trade.xuantian_to_demon.array_sand",
        "魔界阵砂贸易": "trade.xuantian_to_demon.array_sand",
        "trade.three_realms.soul_crystal": "trade.three_realms.soul_crystal",
        "three_realms.soul_crystal": "trade.three_realms.soul_crystal",
        "神魂晶兑换云铁": "trade.three_realms.soul_crystal",
        "神魂晶换云铁": "trade.three_realms.soul_crystal",
        "神魂晶到玄天": "trade.three_realms.soul_crystal",
        "神魂晶贸易": "trade.three_realms.soul_crystal",
    }
    assert cross_realm_trade_alias_map() == cross_realm_trade_rules.TRADE_ALIASES
    assert cross_realm_trade_rules.resolve_trade("三界互市") == "trade.three_realms"
    assert cross_realm_trade_rules.resolve_trade("  妖界贸易  ") == "trade.xuantian_to_beast"
    assert cross_realm_trade_rules.resolve_trade("阵砂换魔核") == "trade.xuantian_to_demon.array_sand"
    assert cross_realm_trade_rules.resolve_trade("神魂晶贸易") == "trade.three_realms.soul_crystal"
    assert cross_realm_trade_rules.resolve_trade("不存在") is None


def test_unknown_trade_still_raises_value_error() -> None:
    with pytest.raises(ValueError, match="unsupported cross-realm trade"):
        cross_realm_trade_rules.trade_definition("trade.nope")


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda records: records.pop(DEFAULTS_KEY), "missing cross_realm_trade content"),
        (
            lambda records: records["trade.xuantian_to_demon"].pop("label"),
            "requires a label",
        ),
        (
            lambda records: records["trade.xuantian_to_demon"].update({"location_key": "cave.nope"}),
            "references unknown location",
        ),
        (
            lambda records: records["trade.xuantian_to_demon"].update({"input_items": {"item.nope": 1}}),
            "references unknown item",
        ),
        (
            lambda records: records["trade.xuantian_to_demon"].update({"input_items": {}}),
            "must be a non-empty object",
        ),
        (
            lambda records: records["trade.xuantian_to_demon"].update({"input_items": {"item.material.cloud_iron": 0}}),
            "must be a positive integer",
        ),
        (
            lambda records: records["trade.xuantian_to_demon"].update({"currency_cost": -1}),
            "must be a non-negative integer",
        ),
        (
            lambda records: records["trade.xuantian_to_demon"].update({"required_faction": "god"}),
            "names unknown faction",
        ),
        (
            lambda records: records["trade.xuantian_to_demon"].update({"weekly_limit": 0}),
            "must be a positive integer",
        ),
        (
            lambda records: records["trade.three_realms"].update({"required_reputations": {"god": 1}}),
            "names unknown faction",
        ),
        (
            lambda records: records["trade.three_realms"].update({"required_reputations": {}}),
            "must be a non-empty object",
        ),
        (
            lambda records: records["trade.three_realms"].update({"required_reputations": {"demon": -1}}),
            "must be a non-negative integer",
        ),
        (
            lambda records: records["trade.xuantian_to_demon"].update({"aliases": []}),
            "aliases must be a non-empty list",
        ),
        (
            lambda records: records["trade.xuantian_to_demon"].update({"aliases": ["  "]}),
            "has an invalid alias",
        ),
        (
            lambda records: records["trade.xuantian_to_demon"].update({"aliases": ["三界互市"]}),
            "already owned by",
        ),
        (
            lambda records: records["trade.xuantian_to_demon.array_sand"].update(
                {"input_items": {"item.mat.array_sand": 0}}
            ),
            "must be a positive integer",
        ),
        (
            lambda records: records["trade.three_realms.soul_crystal"].update(
                {"required_reputations": {"god": 100}}
            ),
            "names unknown faction",
        ),
        (
            lambda records: records["trade.three_realms.soul_crystal"].update(
                {"location_key": "cave.no_such_market"}
            ),
            "references unknown location",
        ),
        (
            lambda records: records["trade.three_realms.soul_crystal"].update(
                {"output_items": {"item.not_a_real_material": 1}}
            ),
            "references unknown item",
        ),
    ],
)


def test_trade_content_rejects_invalid_contract(tmp_path: Path, mutate, message: str) -> None:
    data_dir = _copy_data(tmp_path)
    records = _records(data_dir)
    mutate(records)
    _write_records(data_dir, list(records.values()))
    bundle = ContentBundle.load(data_dir)
    with pytest.raises(ContentError, match=message):
        cross_realm_trade_definitions(bundle)


def test_locked_trade_is_excluded_not_an_error(tmp_path: Path) -> None:
    """A deliberately locked trade simply disappears from the runtime set."""

    data_dir = _copy_data(tmp_path)
    records = _records(data_dir)
    records["trade.xuantian_to_demon"]["status"] = "locked"
    _write_records(data_dir, list(records.values()))
    bundle = ContentBundle.load(data_dir)
    definitions = {record["key"] for record in cross_realm_trade_definitions(bundle)}
    assert "trade.xuantian_to_demon" not in definitions
    assert {"trade.xuantian_to_beast", "trade.three_realms"} <= definitions


def test_new_trade_contracts_only_reference_closed_items_and_locations() -> None:
    """Both new routes reuse only shipped items and existing trade locations."""

    data = json.loads((ROOT / "data" / TRADE_FILE).read_text(encoding="utf-8"))
    records = {record["key"]: record for record in data["records"]}
    array_sand = records["trade.xuantian_to_demon.array_sand"]
    soul_return = records["trade.three_realms.soul_crystal"]

    # No new item, location, permit or command keys are introduced: every key
    # the two contracts reference already exists in the shipped content.
    assert array_sand["input_items"].keys() == {"item.mat.array_sand"}
    assert array_sand["output_items"].keys() == {"item.demon_core"}
    assert soul_return["input_items"].keys() == {"item.soul_crystal"}
    assert soul_return["output_items"].keys() == {"item.material.cloud_iron"}

    bundle = ContentBundle.load(ROOT / "data")
    for key in (
        "item.mat.array_sand",
        "item.demon_core",
        "item.soul_crystal",
        "item.material.cloud_iron",
    ):
        assert bundle.require("item", key, include_locked=False)["status"] == "active"
    for location in (array_sand["location_key"], soul_return["location_key"]):
        assert bundle.require("location", location, include_locked=True)["status"] == "open"

    # Both new trades reuse the shipped reputation keys, weekly caps and the
    # shared binding window rather than inventing new gates.
    defaults = cross_realm_trade_defaults(bundle)
    assert array_sand["required_faction"] == "demon"
    assert array_sand["required_reputation"] == defaults["required_reputation"]
    assert "weekly_limit" not in array_sand
    assert soul_return["required_reputations"] == {
        faction: defaults["required_reputation"]
        for faction in ("demon", "beast")
    }
    assert soul_return["weekly_limit"] == 3
    assert soul_return["currency_cost"] == 0

    # The reward/source side of the returned material stays closed: 云铁 is a
    # registered asset of the shipped 云铁 source and is obtainable from an
    # active exploration reward pool and the 云铁矿区 battle reward pool.
    cloud_iron_sources = [
        row["key"]
        for row in bundle.list("source", include_locked=False)
        if "item.material.cloud_iron" in row.get("asset_keys", [])
    ]
    assert cloud_iron_sources == ["source.item.cloud_iron"]
    from nonebot_plugin_xiuxian_3.xiuxian.rewards.rules import reward_pool_outcomes

    for pool_key in (
        "reward_pool.exploration.cloud_mine",
        "reward_pool.enemy.cloud_mine",
    ):
        assert any(
            "item.material.cloud_iron" in rewards
            for _, rewards in reward_pool_outcomes(pool_key, bundle)
        ), pool_key


def test_new_trade_gates_reject_missing_reputation_without_mutation(tmp_path: Path) -> None:
    """A player lacking either dual-reputation key is denied the new routes."""

    async def run() -> None:
        clock = MutableClock(datetime(2026, 10, 5, 12, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=Path(data_dir), clock=clock)
            adapter = "qq.official"
            for user, command, inventory in (
                (
                    "trade-array-sand-denied",
                    "跨界贸易 阵砂换魔核",
                    {"item.mat.array_sand": 10},
                ),
                (
                    "trade-soul-denied",
                    "跨界贸易 神魂晶换云铁",
                    {"item.soul_crystal": 1},
                ),
            ):
                await runtime.adapters.dispatch(
                    adapter, _context(adapter, user, f"create-{user}"), "开始修仙"
                )
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE players SET stage='cultivator', realm_key='nascent_soul',"
                        " realm_layer=1, location_key='demon.abyss_market',"
                        " spirit_stones=500, faction_reputation_json=?, inventory_json=?"
                        " WHERE platform=? AND platform_user_id=?",
                        (json.dumps({"demon": 199, "beast": 199}), json.dumps(inventory), adapter, user),
                    )
                denied = await runtime.adapters.dispatch(
                    adapter, _context(adapter, user, f"{user}-denied", f"{user}-denied"), command
                )
                assert denied.code == "CROSS_REALM_TRADE_PERMISSION_DENIED"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    state = connection.execute(
                        "SELECT spirit_stones, inventory_json FROM players"
                        " WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    ).fetchone()
                assert state == (500, json.dumps(inventory))
            await runtime.close()

    asyncio.run(run())
