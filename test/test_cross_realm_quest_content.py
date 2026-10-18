from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle, ContentError
from nonebot_plugin_xiuxian_3.xiuxian.quests import cross_realm_rules
from nonebot_plugin_xiuxian_3.xiuxian.quests.cross_realm_quest_content import (
    quest_defaults,
    quest_record,
    quest_records,
)

ROOT = Path(__file__).resolve().parents[1]
QUEST_FILE = Path("任务/跨界任务.json")


def _copy_data(tmp_path: Path) -> Path:
    data_dir = tmp_path / "data"
    shutil.copytree(
        ROOT / "data", data_dir, ignore=shutil.ignore_patterns("*.sqlite3*", "*.db*")
    )
    return data_dir


def _mutate(data_dir: Path, key: str, mutate) -> None:
    document = json.loads((data_dir / QUEST_FILE).read_text(encoding="utf-8"))
    for record in document["records"]:
        if record["key"] == key:
            mutate(record)
            break
    else:
        raise AssertionError(f"record {key} not found")
    (data_dir / QUEST_FILE).write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def test_manifest_registers_the_quest_file() -> None:
    manifest = json.loads((ROOT / "data/内容清单.json").read_text(encoding="utf-8"))
    assert QUEST_FILE.as_posix() in manifest["files"]


def test_quest_record_matches_the_shipped_contract() -> None:
    record = quest_record(cross_realm_rules.DEMON_MAINLINE)
    assert record["label"] == "魔界主线"
    assert record["exploration_mode"] == cross_realm_rules.DEMON_MAINLINE_EXPLORATION == "explore.demon_abyss"
    assert record["exploration_target"] == cross_realm_rules.DEMON_MAINLINE_EXPLORATION_TARGET == 2
    assert record["faction"] == "demon"
    assert record["required_reputation"] == cross_realm_rules.DEMON_MAINLINE_REQUIRED_REPUTATION == 200
    assert record["required_realm"] == cross_realm_rules.DEMON_MAINLINE_REQUIRED_REALM == "nascent_soul"
    assert record["required_layer"] == cross_realm_rules.DEMON_MAINLINE_REQUIRED_LAYER == 1
    assert record["access_flag"] == cross_realm_rules.DEMON_MAINLINE_ACCESS_FLAG == "access.demon.fallen_ruins"
    assert record["aliases"] == ("魔界主线",)


def test_realm_gate_reads_realm_content_not_a_table() -> None:
    assert cross_realm_rules.demon_mainline_realm_ready("nascent_soul", 1) is True
    assert cross_realm_rules.demon_mainline_realm_ready("nascent_soul", 0) is False
    assert cross_realm_rules.demon_mainline_realm_ready("foundation", 10) is False
    assert cross_realm_rules.demon_mainline_realm_ready("tribulation", 10) is True
    # An unknown realm resolves to rank -1 through the realm content lookup.
    assert cross_realm_rules.demon_mainline_realm_ready("not_a_realm", 5) is False


@pytest.mark.parametrize(
    "key, mutate, message",
    [
        ("cross_realm_quest.defaults", lambda r: r.update({"status": "locked"}), "missing cross_realm_quest content"),
        ("cross_realm_quest.defaults", lambda r: r.pop("desc"), "requires a desc"),
        ("cross_realm_quest.defaults", lambda r: r.update({"factions": []}), "non-empty list"),
        ("cross_realm_quest.defaults", lambda r: r.update({"factions": ["abyss"]}), "unsupported faction"),
        ("quest.demon_main_1", lambda r: r.update({"faction": "abyss"}), "unsupported faction"),
        ("quest.demon_main_1", lambda r: r.update({"exploration_mode": "explore.not_a_mode"}), "unknown exploration mode"),
        ("quest.demon_main_1", lambda r: r.update({"exploration_mode": "explore.dao_origin"}), "non-open exploration mode"),
        ("quest.demon_main_1", lambda r: r.update({"exploration_target": 0}), "positive integer"),
        ("quest.demon_main_1", lambda r: r.update({"required_reputation": -1}), "positive integer"),
        ("quest.demon_main_1", lambda r: r.update({"required_realm": "not_a_realm"}), "unknown realm"),
        ("quest.demon_main_1", lambda r: r.update({"required_layer": 0}), "positive integer"),
        ("quest.demon_main_1", lambda r: r.update({"access_flag": "flags.demon"}), "access_flag must live under access."),
        ("quest.demon_main_1", lambda r: r.update({"access_flag": ""}), "access_flag is invalid"),
        ("quest.demon_main_1", lambda r: r.update({"aliases": []}), "non-empty list"),
        ("quest.demon_main_1", lambda r: r.pop("desc"), "desc is invalid"),
        ("quest.demon_main_1", lambda r: r.update({"status": "locked"}), "no cross-realm quests are active"),
    ],
)
def test_content_rejects_invalid_contracts(tmp_path: Path, key: str, mutate, message: str) -> None:
    data_dir = _copy_data(tmp_path)
    _mutate(data_dir, key, mutate)
    bundle = ContentBundle.load(data_dir)
    if key == "cross_realm_quest.defaults":
        with pytest.raises(ContentError, match=message):
            quest_defaults(bundle)
    else:
        with pytest.raises(ContentError, match=message):
            quest_records(bundle)


def test_content_rejects_unknown_quest(tmp_path: Path) -> None:
    bundle = ContentBundle.load(_copy_data(tmp_path))
    with pytest.raises(ContentError, match="not active"):
        quest_record("quest.not_a_quest", bundle)
