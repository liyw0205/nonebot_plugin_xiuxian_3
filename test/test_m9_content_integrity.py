from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from nonebot_plugin_xiuxian_3.xiuxian.combat_content import validate_combat_content
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle, ContentError
from nonebot_plugin_xiuxian_3.xiuxian.content_integrity import (
    validate_content_references,
    validate_exploration_content,
    validate_reward_content,
    validate_source_content,
)
from nonebot_plugin_xiuxian_3.xiuxian.material_content import validate_material_content
from nonebot_plugin_xiuxian_3.xiuxian.world.rules import destination_definition, resolve_destination


DATA = Path(__file__).parents[1] / "data"


def _copy(tmp_path: Path) -> Path:
    root = tmp_path / "data"
    shutil.copytree(DATA, root)
    return root


def _edit(root: Path, relative: str, key: str, **changes: object) -> None:
    path = root / relative
    document = json.loads(path.read_text(encoding="utf-8"))
    row = next(row for row in document["records"] if row["key"] == key)
    row.update(changes)
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_m9_content_references_are_closed() -> None:
    summary = validate_content_references(ContentBundle.load(DATA))
    assert summary["locations"] == 33
    assert summary["exploration_modes"] == 19
    assert summary["bounties"] == 34
    assert summary["recipes"] == 32
    assert summary["sources"] == 14
    assert summary["combat_enemies"] == 55


def test_exploration_rejects_missing_reward_pool(tmp_path: Path) -> None:
    root = _copy(tmp_path)
    _edit(root, "探索/模式.json", "explore.gather_outskirts", reward_pool_key="reward_pool.missing")
    with pytest.raises(ContentError, match="reward pool"):
        validate_exploration_content(ContentBundle.load(root))


def test_combat_rejects_empty_encounter_pool(tmp_path: Path) -> None:
    root = _copy(tmp_path)
    _edit(root, "战斗/遭遇池.json", "encounter.xuantian.outskirts", candidates=[])
    with pytest.raises(ContentError, match="requires candidates"):
        validate_combat_content(ContentBundle.load(root))


def test_rewards_reject_non_positive_quantity(tmp_path: Path) -> None:
    root = _copy(tmp_path)
    _edit(
        root,
        "奖励/奖励.json",
        "reward_pool.exploration.gather_outskirts",
        outcomes=[{"weight": 1, "rewards": {"item.mat.wood": 0}}],
    )
    with pytest.raises(ContentError, match="positive integer quantities"):
        validate_reward_content(ContentBundle.load(root))


def test_sources_reject_missing_asset_id(tmp_path: Path) -> None:
    root = _copy(tmp_path)
    _edit(root, "来源/来源.json", "source.item.herb.blood_grass", asset_keys=["item.missing"])
    with pytest.raises(ContentError, match="unavailable asset"):
        validate_source_content(ContentBundle.load(root))


def test_manifest_rejects_unregistered_json_file(tmp_path: Path) -> None:
    root = _copy(tmp_path)
    extra = root / "测试孤儿.json"
    extra.write_text(
        json.dumps({"schema": "xiuxian.content", "kind": "orphan", "records": []}),
        encoding="utf-8",
    )
    with pytest.raises(ContentError, match="manifest coverage mismatch"):
        validate_content_references(ContentBundle.load(root))


def test_material_source_validation_uses_supplied_content_bundle(tmp_path: Path) -> None:
    root = _copy(tmp_path)
    _edit(root, "探索/模式.json", "explore.gather_outskirts", location_key="location.missing")
    with pytest.raises(ContentError, match="unavailable location"):
        validate_material_content(ContentBundle.load(root))


def test_map_consumer_reads_current_location_data(tmp_path: Path) -> None:
    root = _copy(tmp_path)
    _edit(
        root,
        "地图/地点.json",
        "xuantian.outskirts",
        travel={"duration_seconds": 77, "stamina": 9, "spirit_stone": 3},
    )
    bundle = ContentBundle.load(root)
    assert resolve_destination("玄天近郊", bundle) == "xuantian.outskirts"
    definition = destination_definition("xuantian.outskirts", bundle)
    assert (definition.duration_seconds, definition.stamina_cost, definition.currency_cost) == (77, 9, 3)
    assert resolve_destination("百草坡", bundle) == "xuantian.herb_vale"
    assert destination_definition("xuantian.herb_vale", bundle).label == "百草坡"
