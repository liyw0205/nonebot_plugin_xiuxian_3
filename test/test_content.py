from __future__ import annotations

from pathlib import Path

import pytest

from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle, ContentError
from nonebot_plugin_xiuxian_3.xiuxian.advancement.talent_rules import TALENT_NODE_DEFINITIONS


def test_runtime_content_uses_normalized_records() -> None:
    bundle = ContentBundle.load(Path(__file__).parents[1] / "data")

    sword = bundle.require("item", "item.weapon.wood_sword")
    assert sword["item_type"] == "weapon"
    assert sword["status"] == "active"
    assert bundle.require("realm", "foundation")["name"] == "筑基"
    assert bundle.get("item", "item.pill.foundation_guard", include_locked=False)
    constitution = bundle.require("constitution", "constitution.iron_bone")
    assert constitution["effect"] == {"type": "max_hp_bp", "value": 300}
    assert len(bundle.list("constitution", include_locked=False)) == 6
    talents = bundle.list("talent", include_locked=False)
    assert len(talents) == 30
    assert [row["cost_points"] for row in talents if row["tree_key"] == "body"] == [0, 1, 2, 3, 5]
    assert {row["key"] for row in talents} == set(TALENT_NODE_DEFINITIONS)
    assert all(row["effect"]["value"] in {100, 150, 200, 250, 300} for row in talents)


def test_runtime_content_is_optional_for_isolated_data_dirs(tmp_path: Path) -> None:
    assert ContentBundle.load_optional(tmp_path) is None


def test_runtime_content_rejects_path_escape(tmp_path: Path) -> None:
    (tmp_path / "内容清单.json").write_text(
        '{"schema":"xiuxian.content","schema_version":1,"content_version":"x",'
        '"rule_version":"x","files":["../outside.json"]}',
        encoding="utf-8",
    )
    with pytest.raises(ContentError, match="escapes data directory"):
        ContentBundle.load(tmp_path)
