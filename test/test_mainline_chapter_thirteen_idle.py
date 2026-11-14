from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.adventures.mainline import (
    MAINLINE_STORY_KEY,
    mainline_definitions,
)


ADAPTERS = ("qq.official", "onebot.v11")


class Clock:
    def __init__(self) -> None:
        self.value = datetime(2026, 11, 25, 8, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.value

    def advance(self, **kwargs: int) -> None:
        self.value += timedelta(**kwargs)


def _context(adapter: str, user: str, operation: str) -> CommandContext:
    return CommandContext(
        adapter=adapter,
        user_id=user,
        request_id=f"{adapter}:{user}:{operation}",
        operation_id=f"{adapter}:{user}:{operation}",
        can_write_assets=True,
    )


def _prepare_player(runtime, adapter: str, user: str) -> int:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE players SET stage='cultivator', realm_key='nascent_soul', realm_layer=10, "
            "location_key='xuantian.floating_boat', stamina=100, stamina_max=100, energy=100, "
            "energy_max=100, spirit_stones=5000, max_hp=100000, initiative=100000, "
            "faction_reputation_json=?, intro_json=? "
            "WHERE platform=? AND platform_user_id=?",
            (
                json.dumps({"beast": 200}),
                json.dumps({"flags": ["access.beast_ten_thousand_hills"]}),
                adapter,
                user,
            ),
        )
        player_id = connection.execute(
            "SELECT id FROM players WHERE platform=? AND platform_user_id=?",
            (adapter, user),
        ).fetchone()[0]
        connection.execute(
            "INSERT OR REPLACE INTO mainline_runs("
            "player_id, story_key, chapter, stage, stage_key, status, attempt_count, "
            "first_clear_claimed, first_clear_key, created_at, updated_at"
            ") VALUES (?, ?, 13, 3, 'chapter.13.stage.3', 'claimed', 1, 1, ?, ?, ?)",
            (
                player_id,
                MAINLINE_STORY_KEY,
                f"{MAINLINE_STORY_KEY}:13:3:{user}",
                "2026-11-24T08:00:00+00:00",
                "2026-11-24T08:00:00+00:00",
            ),
        )
        return int(player_id)


def test_chapter_thirteen_stage_four_is_optional_and_keeps_stage_three_terminal() -> None:
    definitions = {
        item.key: item
        for item in mainline_definitions(None, story_key=MAINLINE_STORY_KEY)
    }
    assert definitions["chapter.13.stage.3"].next_stage_key is None
    stage = definitions["chapter.13.stage.4"]
    assert stage.prerequisites == ("chapter.13.stage.3",)
    assert stage.required_realm == "nascent_soul"
    assert stage.required_layer == 10
    assert stage.objectives[0]["type"] == "idle_claim"
    assert stage.objectives[0]["route_key"] == "idle.beast_hills_watch"
    assert {action["command"] for action in stage.actions} == {
        "前往",
        "挂机预览",
        "开始挂机",
    }


def test_beast_covenant_watch_runs_end_to_end_on_qq_and_onebot() -> None:
    async def run() -> None:
        for adapter in ADAPTERS:
            clock = Clock()
            with TemporaryDirectory() as data_dir:
                runtime = create_runtime(
                    data_dir=data_dir, clock=clock, adapters=ADAPTERS
                )
                user = f"chapter-thirteen-watch-{adapter}"

                async def send(operation: str, command: str):
                    return await runtime.adapters.dispatch(
                        adapter, _context(adapter, user, operation), command
                    )

                try:
                    assert (await send("create", "开始修仙")).code == "PLAYER_CREATED"
                    player_id = _prepare_player(runtime, adapter, user)

                    for category in ("探索", "生活"):
                        help_result = await send(
                            f"help-{category}", f"修仙帮助 {category}"
                        )
                        assert help_result.code == "HELP_CATEGORY"
                        assert "守契夜巡" in help_result.message
                        assert "挂机预览 万兽山守契" in help_result.message

                    status = await send("status", "主线道途")
                    assert status.code == "MAINLINE_STATUS"
                    assert "守契夜巡" in status.message

                    started = await send(
                        "stage-start", "开始主线 守契夜巡"
                    )
                    assert started.code == "MAINLINE_STARTED", started.message
                    early = await send(
                        "early-claim", "领取主线奖励 守契夜巡"
                    )
                    assert early.code == "MAINLINE_OBJECTIVES_INCOMPLETE"

                    preview = await send("idle-preview", "挂机预览 万兽山守契")
                    assert preview.code == "IDLE_PREVIEW", preview.message
                    route = next(
                        item
                        for item in preview.data["routes"]
                        if item["route_key"] == "idle.beast_hills_watch"
                    )
                    assert route["ready"] is False
                    assert any("所在地点不符" in value for value in route["missing"])
                    blocked = await send("idle-blocked", "开始挂机 万兽山守契")
                    assert blocked.code == "IDLE_REQUIREMENT_MISSING"

                    travel = await send("travel-start", "前往 万兽山入口")
                    assert travel.code == "TRAVEL_STARTED", travel.message
                    clock.advance(seconds=300)
                    assert (
                        await send("travel-settle", "结算移动")
                    ).code == "TRAVEL_COMPLETED"

                    cancelled_start = await send(
                        "idle-cancel-start", "开始挂机 万兽山守契"
                    )
                    assert cancelled_start.code == "IDLE_STARTED", cancelled_start.message
                    cancelled = await send("idle-cancel", "取消挂机")
                    assert cancelled.code == "IDLE_CANCELLED", cancelled.message
                    assert (
                        await send("cancelled-story", "领取主线奖励 守契夜巡")
                    ).code == "MAINLINE_OBJECTIVES_INCOMPLETE"

                    clock.advance(days=1)
                    expired_start = await send(
                        "idle-expired-start", "开始挂机 万兽山守契"
                    )
                    assert expired_start.code == "IDLE_STARTED", expired_start.message
                    clock.advance(hours=48)
                    expired_claim = await send("idle-expired-claim", "领取挂机")
                    assert expired_claim.code == "IDLE_CLAIMED", expired_claim.message
                    assert expired_claim.data["fallback"] is True
                    assert (
                        await send("expired-story", "领取主线奖励 守契夜巡")
                    ).code == "MAINLINE_OBJECTIVES_INCOMPLETE"

                    clock.advance(days=1)
                    idle_started = await send(
                        "idle-start", "开始挂机 万兽山守契"
                    )
                    assert idle_started.code == "IDLE_STARTED", idle_started.message
                    assignment_id = idle_started.data["assignment_id"]
                    with sqlite3.connect(runtime.settings.database_path) as connection:
                        snapshot = json.loads(
                            connection.execute(
                                "SELECT snapshot_json FROM idle_assignments "
                                "WHERE assignment_id=?",
                                (assignment_id,),
                            ).fetchone()[0]
                        )
                    assert snapshot["route_key"] == "idle.beast_hills_watch"
                    assert snapshot["location_key"] == "beast.ten_thousand_hills"

                    await runtime.close()
                    runtime = create_runtime(
                        data_dir=data_dir, clock=clock, adapters=ADAPTERS
                    )
                    restored = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, user, "restored-status"),
                        "挂机状态",
                    )
                    assert restored.code == "IDLE_STATUS"
                    assert (
                        restored.data["assignment"]["assignment_id"] == assignment_id
                    )

                    clock.advance(hours=10)
                    idle_claim = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, user, "idle-claim"),
                        "领取挂机",
                    )
                    assert idle_claim.code == "IDLE_CLAIMED", idle_claim.message
                    assert idle_claim.data["fallback"] is False
                    assert idle_claim.data["reward"]["item.clue.beast_bloodline"] == 1

                    story_claim = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, user, "story-claim"),
                        "领取主线奖励 守契夜巡",
                    )
                    assert story_claim.code == "MAINLINE_REWARD_CLAIMED", story_claim.message
                    assert story_claim.data["next_stage_key"] is None
                    replay = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, user, "story-claim"),
                        "领取主线奖励 守契夜巡",
                    )
                    assert replay.code == "MAINLINE_REWARD_CLAIMED"
                    assert replay.data["idempotent_replay"] is True

                    with sqlite3.connect(runtime.settings.database_path) as connection:
                        events = {
                            row[0]
                            for row in connection.execute(
                                "SELECT event_key FROM activity_events WHERE player_id=?",
                                (player_id,),
                            ).fetchall()
                        }
                    assert (
                        "story.mainline.xuantian:chapter.13.stage.4" in events
                    )
                finally:
                    await runtime.close()

    asyncio.run(run())
