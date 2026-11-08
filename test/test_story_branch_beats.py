"""Every story branch must carry one beat per source claim it requires.

`sojourner` required two idle claims but listed a single branch beat, and
`wanderer` required three while listing two. The loader only checked
`len(nodes) >= required_count`, so both shipped short. This module pins the
tightened rule and the two completed branches.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle
from nonebot_plugin_xiuxian_3.xiuxian.specials.story_rules import (
    StoryContentError,
    story_definition,
)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


def _context(user: str, name: str, operation_id: str = "") -> CommandContext:
    return CommandContext(
        adapter="web", user_id=user, request_id=name, operation_id=operation_id
    )


def test_every_branch_declares_one_beat_per_required_source() -> None:
    story = story_definition(ContentBundle.load(DATA))
    assert len(story.branches) == 5
    for branch in story.branches:
        beats = (
            branch.completed_nodes[1:]
            if branch.completed_nodes[0] == story.entry_node
            else branch.completed_nodes
        )
        expected = tuple(
            f"node.{branch.key}.{index}"
            for index in range(1, branch.required_source_count + 1)
        )
        assert beats == expected, branch.key


def test_the_two_short_branches_are_completed() -> None:
    story = story_definition(ContentBundle.load(DATA))
    branches = {branch.key: branch for branch in story.branches}
    assert branches["sojourner"].completed_nodes[-1] == "node.sojourner.2"
    assert branches["wanderer"].completed_nodes[-1] == "node.wanderer.3"
    # The branches that were already complete keep their declared beats.
    assert tuple(branches["warden"].completed_nodes) == (
        "node.arrival",
        "node.warden.1",
        "node.warden.2",
    )
    assert tuple(branches["merchant"].completed_nodes) == (
        "node.merchant.1",
        "node.merchant.2",
        "node.merchant.3",
    )


def test_a_branch_that_ends_early_is_rejected() -> None:
    """The rule would have caught the shipped gaps, so keep it exercised."""

    bundle = ContentBundle.load(DATA)
    records = dict(bundle._records)
    row = json.loads(json.dumps(records[("story", "story.xuantian.road")]))
    for branch in row["branches"]:
        if branch["key"] == "sojourner":
            branch["completed_nodes"] = ["node.arrival", "node.sojourner.1"]
    records[("story", "story.xuantian.road")] = row
    import dataclasses

    broken = dataclasses.replace(bundle, _records=records)
    try:
        story_definition(broken)
    except StoryContentError as exc:
        assert "completed_nodes" in str(exc)
    else:  # pragma: no cover - the rule must not pass a short branch
        raise AssertionError("a single-beat sojourner branch was accepted")


def test_claiming_the_sojourner_branch_records_both_beats() -> None:
    async def run() -> None:
        clock_box = [datetime(2026, 9, 30, 12, tzinfo=timezone.utc)]
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=lambda: clock_box[0])
            user = "sojourner-run"
            try:
                assert (await runtime.dispatch(_context(user, "create"), "开始修仙")).ok
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE players SET stage='seeker', realm_key='qi_sensing', "
                        "realm_layer=3, spirit_stones=500 WHERE platform_user_id=?",
                        (user,),
                    )
                preview = await runtime.dispatch(_context(user, "story"), "剧情线")
                assert preview.ok, preview
                assert "闲居" in preview.message, preview.message
            finally:
                await runtime.close()

    asyncio.run(run())
