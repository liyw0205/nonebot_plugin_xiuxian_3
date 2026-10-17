from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

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
        "trade.xuantian_to_beast",
        "trade.xuantian_to_demon",
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
    }
    assert cross_realm_trade_alias_map() == cross_realm_trade_rules.TRADE_ALIASES
    assert cross_realm_trade_rules.resolve_trade("三界互市") == "trade.three_realms"
    assert cross_realm_trade_rules.resolve_trade("  妖界贸易  ") == "trade.xuantian_to_beast"
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
