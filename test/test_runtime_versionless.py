from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

import nonebot_plugin_xiuxian_3.xiuxian as xiuxian
from nonebot_plugin_xiuxian_3.xiuxian.config import XiuxianSettings
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle
from nonebot_plugin_xiuxian_3.xiuxian.persistence.sqlite_repository import SQLitePlayerRepository
from nonebot_plugin_xiuxian_3.contracts import strip_runtime_metadata


def test_runtime_does_not_select_rules_by_release_label() -> None:
    data_root = Path(__file__).parents[1] / "data"
    bundle = ContentBundle.load(data_root)

    assert set(bundle.manifest) == {"schema", "status", "files"}
    assert not (data_root / "内容版本.json").exists()
    assert not (Path(__file__).parents[1] / "nonebot_plugin_xiuxian_3" / "xiuxian" / "versions.py").exists()
    assert not hasattr(xiuxian, "active_content_version")
    assert not hasattr(xiuxian, "active_rule_version")
    assert strip_runtime_metadata({"result": {"content_version": "", "value": 1}}) == {
        "result": {"value": 1}
    }


def test_new_player_schema_has_no_release_marker(tmp_path: Path) -> None:
    async def run() -> None:
        settings = XiuxianSettings(data_dir=tmp_path)
        repository = SQLitePlayerRepository(settings)
        await repository.initialize()
        with sqlite3.connect(settings.database_path) as connection:
            for table in ("players", "fate_pools", "fate_rolls"):
                columns = {
                    row[1]
                    for row in connection.execute(f"PRAGMA table_info({table})")
                }
                assert "content_version" not in columns
                assert "rule_version" not in columns

    asyncio.run(run())
