from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from nonebot_plugin_xiuxian_3.xiuxian.combat_content import validate_combat_content
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle, ContentError


DATA = Path(__file__).parents[1] / "data"


def _copy_data(tmp_path: Path, *, include_source_fixture: bool = False) -> Path:
    root = tmp_path / "data"
    shutil.copytree(DATA, root)
    if include_source_fixture:
        manifest_path = root / "内容清单.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["files"].append("来源/来源.json")
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        source_path = root / "来源/来源.json"
        source_path.parent.mkdir(parents=True)
        source_path.write_text(
            json.dumps(
                {
                    "schema": "xiuxian.content",
                    "kind": "source",
                    "records": [
                        {
                            "key": "source.item.mist_core",
                            "name": "雾隐核心来源",
                            "desc": "战斗来源测试夹具。",
                            "asset_keys": ["item.material.mist_core"],
                            "channels": [
                                {
                                    "operation": "battle.claim",
                                    "reference": "reward_pool.enemy.mist",
                                }
                            ],
                            "status": "active",
                        }
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    return root


def _edit(root: Path, relative: str, key: str, **changes: object) -> None:
    path = root / relative
    document = json.loads(path.read_text(encoding="utf-8"))
    row = next(row for row in document["records"] if row["key"] == key)
    row.update(changes)
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_combat_content_closes_current_enemy_and_encounter_data() -> None:
    summary = validate_combat_content(ContentBundle.load(DATA))

    assert summary == {
        "enemies": 55,
        "enemy_profiles": 33,
        "encounters": 14,
        "candidates": 27,
        "drop_pools": 6,
        "consumed_encounters": 0,
        "enemy_skills": 11,
    }


@pytest.mark.parametrize(
    ("relative", "key", "changes", "message"),
    [
        (
            "战斗/遭遇池.json",
            "encounter.xuantian.outskirts",
            {"desc": ""},
            "requires non-empty desc",
        ),
        (
            "战斗/遭遇池.json",
            "encounter.xuantian.outskirts",
            {"candidates": [{"enemy_key": "enemy.missing", "weight": 1}]},
            "unavailable enemy",
        ),
        (
            "战斗/敌人.json",
            "enemy.ironwood_weasel",
            {"skills": ["enemy_skill.missing"]},
            "unavailable enemy skill",
        ),
        (
            "战斗/敌人.json",
            "enemy.ironwood_weasel",
            {"combat_profile": {"random_pool_key": "battle.enemy.ironwood_weasel", "drop_pool_key": "reward_pool.missing", "reward": {}}},
            "unavailable drop pool",
        ),
        (
            "来源/来源.json",
            "source.item.mist_core",
            {"channels": [{"operation": "battle.claim", "reference": "reward_pool.missing"}]},
            "unavailable battle reward",
        ),
    ],
)
def test_combat_content_rejects_dangling_or_malformed_references(
    tmp_path: Path,
    relative: str,
    key: str,
    changes: dict[str, object],
    message: str,
) -> None:
    root = _copy_data(tmp_path, include_source_fixture=relative.startswith("来源/"))
    _edit(root, relative, key, **changes)

    with pytest.raises(ContentError, match=message):
        validate_combat_content(ContentBundle.load(root))


def test_combat_content_rejects_invalid_drop_pool_reward(tmp_path: Path) -> None:
    root = _copy_data(tmp_path)
    _edit(
        root,
        "奖励/奖励.json",
        "reward_pool.enemy.early",
        outcomes=[{"weight": 1, "rewards": {"item.missing": 1}}],
    )

    with pytest.raises(ContentError, match="inactive item"):
        validate_combat_content(ContentBundle.load(root))


def test_combat_content_rejects_invalid_enemy_profile_stats(tmp_path: Path) -> None:
    root = _copy_data(tmp_path)
    _edit(
        root,
        "战斗/敌人.json",
        "enemy.ironwood_weasel",
        stats={"hp": 0, "attack": 11, "initiative": 13, "agility": True},
    )

    with pytest.raises(ContentError, match="stats.agility"):
        validate_combat_content(ContentBundle.load(root))
