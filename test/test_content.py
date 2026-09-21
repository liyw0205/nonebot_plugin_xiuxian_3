from __future__ import annotations

from pathlib import Path

import pytest

from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle, ContentError


def test_runtime_content_uses_normalized_records() -> None:
    bundle = ContentBundle.load(Path(__file__).parents[1] / "data")

    sword = bundle.require("item", "item.weapon.wood_sword")
    assert sword["item_type"] == "weapon"
    assert sword["status"] == "active"
    assert bundle.require("realm", "foundation")["name"] == "筑基"
    assert bundle.get("item", "item.pill.foundation_guard", include_locked=False)


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
