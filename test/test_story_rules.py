from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle
from nonebot_plugin_xiuxian_3.xiuxian.rewards.rules import reward_definition
from nonebot_plugin_xiuxian_3.xiuxian.specials.story_rules import (
    CLAIM_OPERATION,
    StoryContentError,
    story_definition,
)


def _edit_record(data_dir: Path, relative_path: str, key: str, update) -> None:
    path = data_dir / relative_path
    document = json.loads(path.read_text(encoding="utf-8"))
    record = next(row for row in document["records"] if row["key"] == key)
    update(record)
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_story_rules_consume_content_and_reject_bad_references(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    shutil.copytree(Path(__file__).resolve().parents[1] / "data", data_dir)
    _edit_record(
        data_dir,
        "剧情/故事.json",
        "story.xuantian.road",
        lambda row: row["branches"][0].update(
            required_source_count=4,
            completed_nodes=["node.merchant.1", "node.merchant.2", "node.merchant.3", "node.merchant.4"],
        ),
    )
    _edit_record(
        data_dir,
        "奖励/奖励.json",
        "reward.story.xuantian_road.ending",
        lambda row: row["entries"][0].update(quantity=13),
    )
    content = ContentBundle.load(data_dir)
    definition = story_definition(content)
    merchant = definition.branches[0]
    reward = reward_definition(definition.reward_key, content, operation=CLAIM_OPERATION)
    assert merchant.required_source_count == 4
    assert len(merchant.completed_nodes) == 4
    assert reward.local_reputation == {"local.xuantian.new_town": 13}

    _edit_record(
        data_dir,
        "剧情/故事.json",
        "story.xuantian.road",
        lambda row: row["branches"][0].update(codex_entry_key="codex.story.missing"),
    )
    with pytest.raises(StoryContentError, match="codex entry"):
        story_definition(ContentBundle.load(data_dir))
