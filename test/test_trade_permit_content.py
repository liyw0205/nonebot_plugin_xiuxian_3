from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle, ContentError
from nonebot_plugin_xiuxian_3.xiuxian.livelihood import trade_permit_rules
from nonebot_plugin_xiuxian_3.xiuxian.livelihood.trade_permit_content import (
    permit_defaults,
    permit_records,
)

ROOT = Path(__file__).resolve().parents[1]
PERMIT_FILE = Path("经济/贸易许可.json")


def _copy_data(tmp_path: Path) -> Path:
    data_dir = tmp_path / "data"
    shutil.copytree(
        ROOT / "data", data_dir, ignore=shutil.ignore_patterns("*.sqlite3*", "*.db*")
    )
    return data_dir


def _mutate(data_dir: Path, key: str, mutate) -> None:
    document = json.loads((data_dir / PERMIT_FILE).read_text(encoding="utf-8"))
    for record in document["records"]:
        if record["key"] == key:
            mutate(record)
            break
    else:
        raise AssertionError(f"record {key} not found")
    (data_dir / PERMIT_FILE).write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def test_manifest_registers_the_permit_file() -> None:
    manifest = json.loads((ROOT / "data/内容清单.json").read_text(encoding="utf-8"))
    assert PERMIT_FILE.as_posix() in manifest["files"]


def test_permit_records_match_the_shipped_contract() -> None:
    records = permit_records()
    assert [record["key"] for record in records] == [
        "permit.beast_trade",
        "permit.demon_trade",
    ]
    demon = trade_permit_rules.TRADE_PERMITS["permit.demon_trade"]
    assert demon.label == "魔界贸易许可"
    assert demon.faction_key == "demon"
    assert demon.required_quest == "quest.demon_intro"
    assert demon.reputation_required == 80
    assert demon.cost == 500
    assert demon.duration_seconds == 604800
    beast = trade_permit_rules.TRADE_PERMITS["permit.beast_trade"]
    assert beast.label == "妖界贸易许可"
    assert beast.faction_key == "beast"
    assert beast.required_quest == "quest.beast_intro"
    assert beast.reputation_required == 80
    assert beast.cost == 500
    assert beast.duration_seconds == 604800
    assert trade_permit_rules.PERMIT_COST == 500
    assert trade_permit_rules.PERMIT_DURATION_SECONDS == 604800


def test_aliases_match_the_shipped_contract() -> None:
    assert trade_permit_rules.ALIASES == {
        "魔界": "permit.demon_trade",
        "魔界贸易": "permit.demon_trade",
        "魔界贸易许可": "permit.demon_trade",
        "妖界": "permit.beast_trade",
        "妖界贸易": "permit.beast_trade",
        "妖界贸易许可": "permit.beast_trade",
        "permit.demon_trade": "permit.demon_trade",
        "permit.beast_trade": "permit.beast_trade",
    }
    assert trade_permit_rules.resolve_trade_permit("魔界").key == "permit.demon_trade"
    assert trade_permit_rules.resolve_trade_permit("妖界贸易").key == "permit.beast_trade"
    assert trade_permit_rules.resolve_trade_permit("permit.beast_trade").key == "permit.beast_trade"
    with pytest.raises(ValueError, match="unsupported trade permit"):
        trade_permit_rules.resolve_trade_permit("不存在的许可")


@pytest.mark.parametrize(
    "key, mutate, message",
    [
        ("trade_permit.defaults", lambda r: r.update({"status": "locked"}), "missing trade_permit content"),
        ("trade_permit.defaults", lambda r: r.pop("desc"), "requires a desc"),
        ("trade_permit.defaults", lambda r: r.update({"factions": []}), "non-empty list"),
        ("trade_permit.defaults", lambda r: r.update({"factions": ["abyss"]}), "unsupported faction"),
        ("permit.demon_trade", lambda r: r.update({"faction": "abyss"}), "unsupported faction"),
        ("permit.demon_trade", lambda r: r.update({"required_quest_flag": "flags.demon"}), "must live under quest."),
        ("permit.demon_trade", lambda r: r.update({"required_quest_flag": ""}), "required_quest_flag is invalid"),
        ("permit.demon_trade", lambda r: r.update({"required_reputation": 0}), "positive integer"),
        ("permit.demon_trade", lambda r: r.update({"cost": -1}), "positive integer"),
        ("permit.demon_trade", lambda r: r.update({"duration_seconds": 0}), "positive integer"),
        ("permit.demon_trade", lambda r: r.update({"aliases": []}), "non-empty list"),
        ("permit.beast_trade", lambda r: r.update({"aliases": ["魔界"]}), "conflicts"),
        ("permit.demon_trade", lambda r: r.pop("desc"), "desc is invalid"),
        ("permit.demon_trade", lambda r: r.update({"label": ""}), "label is invalid"),
    ],
)
def test_content_rejects_invalid_contracts(tmp_path: Path, key: str, mutate, message: str) -> None:
    data_dir = _copy_data(tmp_path)
    _mutate(data_dir, key, mutate)
    bundle = ContentBundle.load(data_dir)
    if key == "trade_permit.defaults":
        with pytest.raises(ContentError, match=message):
            permit_defaults(bundle)
    else:
        with pytest.raises(ContentError, match=message):
            permit_records(bundle)


def test_content_rejects_duplicate_permit_keys_at_load(tmp_path: Path) -> None:
    data_dir = _copy_data(tmp_path)
    document = json.loads((data_dir / PERMIT_FILE).read_text(encoding="utf-8"))
    document["records"][1]["key"] = document["records"][2]["key"]
    (data_dir / PERMIT_FILE).write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    with pytest.raises(ContentError, match="duplicate content key trade_permit"):
        ContentBundle.load(data_dir)
