from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle, ContentError
from nonebot_plugin_xiuxian_3.xiuxian.exploration.rules import exploration_definition

ROOT = Path(__file__).resolve().parents[1]
MODE_FILE = Path("探索/模式.json")
ITEM_FILE = Path("道具/材料.json")


def _copy_data(tmp_path: Path) -> Path:
    data_dir = tmp_path / "data"
    shutil.copytree(
        ROOT / "data", data_dir, ignore=shutil.ignore_patterns("*.sqlite3*", "*.db*")
    )
    return data_dir


def test_manifest_does_not_need_a_new_file() -> None:
    manifest = json.loads((ROOT / "data/内容清单.json").read_text(encoding="utf-8"))
    # All five touched files are already registered; the manifest itself changes
    # only via its own seed-migration rule.
    for entry in (
        "探索/模式.json",
        "道具/材料.json",
        "奖励/奖励.json",
        "战斗/遭遇池.json",
        "来源/来源.json",
    ):
        assert entry in manifest["files"]


def test_time_garden_mode_matches_the_shipped_contract() -> None:
    definition = exploration_definition("explore.time_garden")
    assert definition.label == "时序福地采撷"
    assert definition.location_key == "cave.time_garden"
    assert definition.required_realm == "void_refining"
    assert definition.required_layer == 1
    assert definition.duration_seconds == 900
    assert definition.stamina_cost == 25
    assert definition.energy_cost == 3
    assert definition.daily_limit == 2
    assert definition.battle_chance_bp == 5000


def test_time_garden_location_promises_the_mode() -> None:
    locations = json.loads((ROOT / "data/地图/地点.json").read_text(encoding="utf-8"))
    garden = next(row for row in locations["records"] if row["key"] == "cave.time_garden")
    assert garden["status"] == "open"
    assert "explore.time_garden" in garden["actions"], (
        "the location must not promise a dangling action"
    )


def test_time_trace_item_matches_the_shipped_contract() -> None:
    bundle = ContentBundle.load(ROOT / "data")
    item = bundle.require("item", "item.herb.time_trace", include_locked=False)
    assert item["name"] == "时痕草"
    assert item["item_type"] == "herb"
    assert item["quality"] == "rare"
    source = item["gathering_sources"][0]
    assert source["mode_key"] == "explore.time_garden"
    assert source["reward_pool_key"] == "reward_pool.exploration.time_garden"


def test_reward_pool_and_encounter_pool_contracts() -> None:
    bundle = ContentBundle.load(ROOT / "data")
    pool = bundle.require("reward", "reward_pool.exploration.time_garden", include_locked=False)
    outcomes = pool["outcomes"]
    assert sum(entry["weight"] for entry in outcomes) == 10
    assert outcomes[0]["rewards"] == {"item.herb.time_trace": 1, "spirit_stones": 260}
    assert outcomes[1]["rewards"] == {"item.herb.time_trace": 2, "spirit_stones": 220}
    assert outcomes[2]["rewards"] == {"item.void_crystal": 1, "spirit_stones": 300}
    encounter = bundle.require(
        "encounter_pool", "encounter.void.time_garden", include_locked=False
    )
    assert [(c["enemy_key"], c["weight"]) for c in encounter["candidates"]] == [
        ("enemy.time_garden_echo", 60),
        ("enemy.time_garden_keeper", 40),
    ]
    for candidate in encounter["candidates"]:
        assert bundle.require("enemy", candidate["enemy_key"], include_locked=False)


def test_source_registry_closes_the_material_provenance() -> None:
    bundle = ContentBundle.load(ROOT / "data")
    source = bundle.require("source", "source.item.void_materials", include_locked=False)
    assert "item.herb.time_trace" in source["asset_keys"]
    references = [
        (channel["operation"], channel["reference"]) for channel in source["channels"]
    ]
    assert ("exploration.settle", "reward_pool.exploration.time_garden") in references


def test_time_garden_mode_rejects_broken_variants(tmp_path: Path) -> None:
    data_dir = _copy_data(tmp_path)
    document = json.loads((data_dir / MODE_FILE).read_text(encoding="utf-8"))
    record = next(row for row in document["records"] if row["key"] == "explore.time_garden")
    record["location_key"] = "cave.not_a_location"
    (data_dir / MODE_FILE).write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    bundle = ContentBundle.load(data_dir)
    with pytest.raises(ContentError, match="unavailable location"):
        exploration_definition("explore.time_garden", bundle)


def test_time_trace_item_rejects_broken_source(tmp_path: Path) -> None:
    data_dir = _copy_data(tmp_path)
    document = json.loads((data_dir / ITEM_FILE).read_text(encoding="utf-8"))
    item = next(row for row in document["records"] if row["key"] == "item.herb.time_trace")
    item["gathering_sources"][0]["mode_key"] = "explore.not_a_mode"
    (data_dir / ITEM_FILE).write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    bundle = ContentBundle.load(data_dir)
    from nonebot_plugin_xiuxian_3.xiuxian.material_content import validate_material_content

    with pytest.raises(ContentError):
        validate_material_content(bundle)
