from __future__ import annotations

import asyncio
import sqlite3
import tomllib
from pathlib import Path

import nonebot_plugin_xiuxian_3.xiuxian as xiuxian
from nonebot_plugin_xiuxian_3.xiuxian.config import XiuxianSettings
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle
from nonebot_plugin_xiuxian_3.xiuxian.persistence.sqlite_repository import SQLitePlayerRepository


def test_runtime_does_not_select_rules_by_release_label() -> None:
    data_root = Path(__file__).parents[1] / "data"
    bundle = ContentBundle.load(data_root)

    assert set(bundle.manifest) == {"schema", "status", "files"}
    assert not (data_root / "内容版本.json").exists()
    assert not (Path(__file__).parents[1] / "nonebot_plugin_xiuxian_3" / "xiuxian" / "versions.py").exists()


def test_project_metadata_keeps_build_versions_out_of_runtime_rules() -> None:
    root = Path(__file__).parents[1]
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    version = project.get("version")
    assert isinstance(version, str) and version
    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    assert f"## {version}" in changelog

    for relative_path in ("examples/nonebot/pyproject.toml", "docker/pyproject.toml"):
        project = tomllib.loads((root / relative_path).read_text(encoding="utf-8"))["project"]
        assert isinstance(project.get("name"), str) and project["name"]
        has_static_version = isinstance(project.get("version"), str) and bool(project["version"])
        has_dynamic_version = "version" in project.get("dynamic", [])
        assert has_static_version != has_dynamic_version


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
                assert not {
                    column
                    for column in columns
                    if "version" in str(column).lower() or "release" in str(column).lower()
                }

    asyncio.run(run())
