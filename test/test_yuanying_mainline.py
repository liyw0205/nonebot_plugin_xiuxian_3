"""The 元婴 arc must be a real, gated, playable chain.

`chapter.9.stage.3` (金丹三层) used to end the mainline and the next reachable stage was
化神.  These tests pin the nine 元婴 stages as a complete chain under the same vertical-slice
gate as every other realm, and prove one of them end to end through public commands.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.adventures.mainline import (
    MAINLINE_STAGES,
    MAINLINE_STORY_KEY,
    mainline_definitions,
)
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle, ContentError

ROOT = Path(__file__).parents[1]
ARC = tuple(f"chapter.{chapter}.stage.{stage}" for chapter in (10, 11, 12) for stage in (1, 2, 3))


class MutableClock:
    def __init__(self) -> None:
        self.value = datetime(2026, 10, 11, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.value

    def advance(self, **kwargs: int) -> None:
        self.value += timedelta(**kwargs)


def _context(user: str, operation_id: str) -> CommandContext:
    return CommandContext(adapter="onebot.v11", user_id=user, operation_id=operation_id)


def _copy_content(path: Path) -> Path:
    target = path / "data"
    shutil.copytree(
        ROOT / "data",
        target,
        ignore=shutil.ignore_patterns("*.sqlite3", "*.sqlite3-*", "*.db", "*.db-*"),
    )
    return target


def _stages_by_key() -> dict[str, object]:
    return {stage.key: stage for stage in MAINLINE_STAGES}


def test_the_yuanying_arc_is_a_complete_gated_chain() -> None:
    stages = _stages_by_key()
    assert len(MAINLINE_STAGES) == 40
    assert stages["chapter.9.stage.3"].next_stage_key == "chapter.10.stage.1"

    previous = "chapter.9.stage.3"
    for index, key in enumerate(ARC):
        stage = stages[key]
        assert stage.required_realm == "nascent_soul"
        assert stage.required_layer == index + 1
        assert len(stage.body.strip()) >= 80
        assert stage.objectives, f"{key} needs a real objective"
        assert stage.state_events, f"{key} needs an activity event"
        assert stage.actions, f"{key} needs a public action"
        assert stages[previous].next_stage_key == key
        previous = key
    # chapter.13 (元婴 L10 万兽山) continues the same chain and closes the realm.
    assert stages[ARC[-1]].next_stage_key == "chapter.13.stage.1"
    assert stages["chapter.13.stage.3"].next_stage_key is None


def test_every_yuanying_action_is_a_command_a_player_can_send(tmp_path: Path) -> None:
    async def run() -> None:
        runtime = create_runtime(data_dir=tmp_path, adapters=("onebot.v11",))
        try:
            handlers = runtime.adapters.router._handlers
            for stage in MAINLINE_STAGES:
                if stage.key not in ARC:
                    continue
                for action in stage.actions:
                    command = str(action["command"]).strip().lower()
                    assert command in handlers, f"{stage.key} tells the player to send {command!r}, which is not registered"
        finally:
            await runtime.close()

    asyncio.run(run())


def test_the_gate_still_rejects_a_short_body_or_a_broken_chain(tmp_path: Path) -> None:
    content_dir = _copy_content(tmp_path)
    story_path = content_dir / "剧情" / "主线.json"
    document = json.loads(story_path.read_text(encoding="utf-8"))
    target = next(row for row in document["records"] if row["key"] == "chapter.10.stage.1")
    target["body"] = "太短。"
    story_path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ContentError, match="body is too short"):
        mainline_definitions(ContentBundle.load(content_dir), story_key=MAINLINE_STORY_KEY)

    content_dir2 = _copy_content(tmp_path / "chain")
    story_path2 = content_dir2 / "剧情" / "主线.json"
    document2 = json.loads(story_path2.read_text(encoding="utf-8"))
    target2 = next(row for row in document2["records"] if row["key"] == "chapter.10.stage.1")
    target2["next_stage_key"] = "chapter.9.stage.3"
    story_path2.write_text(json.dumps(document2, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ContentError):
        mainline_definitions(ContentBundle.load(content_dir2), story_key=MAINLINE_STORY_KEY)


def test_a_nascent_soul_player_clears_the_first_yuanying_stage(tmp_path: Path) -> None:
    async def run() -> None:
        clock = MutableClock()
        runtime = create_runtime(data_dir=tmp_path, clock=clock, adapters=("onebot.v11",))
        user = "yuanying-onebot"

        async def send(operation: str, command: str):
            return await runtime.adapters.dispatch("onebot.v11", _context(user, operation), command)

        try:
            assert (await send("create", "开始修仙")).ok
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE players SET stage='cultivator', realm_key='nascent_soul', realm_layer=1, stamina=120, stamina_max=120, "
                    "spirit_stones=5000 WHERE platform='onebot.v11' AND platform_user_id=?",
                    (user,),
                )
                connection.commit()
            with sqlite3.connect(runtime.settings.database_path) as connection:
                player_id = connection.execute(
                    "SELECT id FROM players WHERE platform='onebot.v11' AND platform_user_id=?",
                    (user,),
                ).fetchone()[0]
                connection.execute(
                    "INSERT OR REPLACE INTO mainline_runs(player_id, story_key, chapter, stage, stage_key, status, "
                    "attempt_count, first_clear_claimed, first_clear_key, created_at, updated_at) "
                    "VALUES (?, 'story.mainline.xuantian', 9, 3, 'chapter.9.stage.3', 'claimed', 1, 1, ?, ?, ?)",
                    (player_id, f"chapter.9.stage.3:{player_id}", "2026-10-11T00:00:00+00:00", "2026-10-11T00:00:00+00:00"),
                )
                connection.commit()

            started = await send("stage10-start", "开始主线 云城问舟")
            assert started.code == "MAINLINE_STARTED", started.message
            assert "云城" in started.message

            travel = await send("stage10-travel", "前往 云城")
            assert travel.code == "TRAVEL_STARTED", travel.message
            clock.advance(seconds=180)
            assert (await send("stage10-settle", "结算移动")).code == "TRAVEL_COMPLETED"

            claimed = await send("stage10-claim", "领取主线奖励 云城问舟")
            assert claimed.code == "MAINLINE_REWARD_CLAIMED", claimed.message
            assert claimed.data["next_stage_key"] == "chapter.10.stage.2"

            replay = await send("stage10-claim", "领取主线奖励 云城问舟")
            assert replay.code == "MAINLINE_REWARD_CLAIMED", replay.message
            assert replay.data.get("idempotent_replay") is True
        finally:
            await runtime.close()

    asyncio.run(run())


def test_a_golden_core_player_cannot_start_the_yuanying_arc(tmp_path: Path) -> None:
    async def run() -> None:
        clock = MutableClock()
        runtime = create_runtime(data_dir=tmp_path, clock=clock, adapters=("onebot.v11",))
        user = "golden-core-onebot"

        async def send(operation: str, command: str):
            return await runtime.adapters.dispatch("onebot.v11", _context(user, operation), command)

        try:
            assert (await send("create", "开始修仙")).ok
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE players SET stage='cultivator', realm_key='golden_core', realm_layer=3, stamina=120, stamina_max=120 "
                    "WHERE platform='onebot.v11' AND platform_user_id=?",
                    (user,),
                )
                connection.commit()
            refused = await send("stage10-refused", "开始主线 云城问舟")
            assert refused.code == "MAINLINE_REQUIREMENT_MISSING", refused.message
        finally:
            await runtime.close()

    asyncio.run(run())
