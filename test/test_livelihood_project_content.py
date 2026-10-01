from __future__ import annotations

import asyncio
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pytest

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle, ContentError
from nonebot_plugin_xiuxian_3.xiuxian.livelihood.rules import public_project_definitions


def _copy_content(tmp_path: Path) -> Path:
    target = tmp_path / "content"
    shutil.copytree(Path(__file__).parents[1] / "data", target)
    return target


def _project_record(path: Path, project_key: str) -> dict:
    source = path / "生活" / "生活.json"
    document = json.loads(source.read_text(encoding="utf-8"))
    return next(row for row in document["records"] if row.get("key") == project_key)


def test_public_project_rules_are_loaded_from_content(tmp_path: Path) -> None:
    content_dir = _copy_content(tmp_path)
    source = content_dir / "生活" / "生活.json"
    document = json.loads(source.read_text(encoding="utf-8"))
    project = next(row for row in document["records"] if row["key"] == "project.town_well")
    project["reward"]["spirit_stones"] = 77
    project["requirements"]["item.mat.wood"] = 90
    source.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")

    async def run() -> None:
        runtime = create_runtime(data_dir=content_dir)
        context = CommandContext(adapter="onebot.v11", user_id="content-project", operation_id="create")
        assert (await runtime.dispatch(context, "开始修仙")).ok
        assert (
            await runtime.dispatch(
                CommandContext(adapter="onebot.v11", user_id="content-project", operation_id="seek"),
                "寻仙问道",
            )
        ).ok
        with runtime.repository._connect() as connection:
            player_id = connection.execute(
                "SELECT id FROM players WHERE platform=? AND platform_user_id=?",
                ("onebot.v11", "content-project"),
            ).fetchone()[0]
            connection.execute(
                "UPDATE players SET inventory_json=? WHERE id=?",
                (json.dumps({"item.mat.wood": 90}), player_id),
            )
        for index in range(9):
            result = await runtime.dispatch(
                CommandContext(
                    adapter="onebot.v11",
                    user_id="content-project",
                    operation_id=f"wood-{index}",
                ),
                "贡献公共项目 project.town_well 木材 10",
            )
            assert result.ok
        settled = await runtime.dispatch(
            CommandContext(adapter="onebot.v11", user_id="content-project", operation_id="settle"),
            "结算公共项目",
        )
        assert settled.ok
        assert settled.data["reward"]["spirit_stones"] == 77
        await runtime.close()

    asyncio.run(run())


def test_public_project_content_rejects_unknown_asset_reference(tmp_path: Path) -> None:
    content_dir = _copy_content(tmp_path)
    source = content_dir / "生活" / "生活.json"
    document = json.loads(source.read_text(encoding="utf-8"))
    project = next(row for row in document["records"] if row["key"] == "project.market_road")
    project["requirements"]["item.missing_material"] = 1
    source.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")

    bundle = ContentBundle.load(content_dir)
    with pytest.raises(ContentError, match="unknown item item.missing_material"):
        public_project_definitions(bundle)


def test_public_project_service_source_values_are_content_driven(tmp_path: Path) -> None:
    content_dir = _copy_content(tmp_path)
    source = content_dir / "生活" / "生活.json"
    document = json.loads(source.read_text(encoding="utf-8"))
    project = next(row for row in document["records"] if row["key"] == "project.domain_refuge")
    project["service_sources"][0]["contribution_points"] = 23
    source.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")

    bundle = ContentBundle.load(content_dir)
    definition = public_project_definitions(bundle)["project.domain_refuge"]
    assert definition.service_sources[0].contribution_points == 23
