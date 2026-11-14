from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.specials.dispatch_rules import DISPATCHES, choose_outcome


ADAPTERS = ("qq.official", "onebot.v11")
STORY = "story.mainline.xuantian"


class Clock:
    def __init__(self) -> None:
        self.value = datetime(2026, 11, 20, 8, tzinfo=timezone.utc)

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
            "UPDATE players SET stage='cultivator', realm_key='golden_core', realm_layer=3, "
            "location_key='xuantian.new_town', stamina=200, stamina_max=200, energy=100, "
            "energy_max=100, spirit_stones=5000, max_hp=100000, initiative=100000 "
            "WHERE platform=? AND platform_user_id=?",
            (adapter, user),
        )
        player_id = connection.execute(
            "SELECT id FROM players WHERE platform=? AND platform_user_id=?",
            (adapter, user),
        ).fetchone()[0]
        connection.execute(
            "INSERT INTO player_reputations(player_id, local_json, service_reputation, updated_at) "
            "VALUES (?, ?, 0, ?) ON CONFLICT(player_id) DO UPDATE SET local_json=excluded.local_json",
            (player_id, json.dumps({"local.xuantian.cloud_city": 195}, sort_keys=True), "2026-11-20T08:00:00+00:00"),
        )
        connection.execute(
            "INSERT OR REPLACE INTO mainline_runs("
            "player_id, story_key, chapter, stage, stage_key, status, attempt_count, "
            "first_clear_claimed, first_clear_key, created_at, updated_at"
            ") VALUES (?, ?, 9, 3, 'chapter.9.stage.3', 'claimed', 1, 1, ?, ?, ?)",
            (
                player_id,
                STORY,
                f"{STORY}:9:3:{user}",
                "2026-11-20T07:00:00+00:00",
                "2026-11-20T07:00:00+00:00",
            ),
        )
        return int(player_id)


def _success_seed(adapter: str, user: str) -> str:
    # The dispatch repository freezes this UUID as the deterministic risk seed.
    for index in range(10_000):
        seed = f"chapter-nine-ledger-{adapter}-{user}-{index}"
        if choose_outcome(DISPATCHES["dispatch.golden_core.vein_survey"], seed) == "success":
            return seed
    raise AssertionError("could not find a deterministic successful dispatch seed")


def test_chapter_nine_idle_epilogue_runs_on_qq_and_onebot_with_restart() -> None:
    async def run() -> None:
        clock = Clock()
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock, adapters=ADAPTERS)
            try:
                for adapter in ADAPTERS:
                    user = f"chapter-nine-ledger-{adapter}"

                    async def send(operation: str, command: str):
                        return await runtime.adapters.dispatch(
                            adapter, _context(adapter, user, operation), command
                        )

                    assert (await send("create", "开始修仙")).code == "PLAYER_CREATED"
                    player_id = _prepare_player(runtime, adapter, user)

                    status = await send("status", "主线道途")
                    assert status.code == "MAINLINE_STATUS"
                    assert "账房夜值" in status.message
                    for category in ("探索", "生活"):
                        help_result = await send(f"help-{category}", f"修仙帮助 {category}")
                        assert help_result.code == "HELP_CATEGORY"
                        assert "账房夜值" in help_result.message

                    started = await send("stage-start", "开始主线 账房夜值")
                    assert started.code == "MAINLINE_STARTED", started.message
                    assert "挂机预览 云城店铺" in started.message
                    assert "command:" in started.message
                    early = await send("early", "领取主线奖励 账房夜值")
                    assert early.code == "MAINLINE_OBJECTIVES_INCOMPLETE"

                    travel = await send("travel-start", "前往 云城")
                    assert travel.code == "TRAVEL_STARTED", travel.message
                    clock.advance(minutes=3)
                    assert (await send("travel-settle", "结算移动")).code == "TRAVEL_COMPLETED"

                    blocked = await send("idle-blocked", "开始挂机 云城店铺")
                    assert blocked.code == "IDLE_REQUIREMENT_MISSING", blocked.message

                    seed = _success_seed(adapter, user)
                    with patch(
                        "nonebot_plugin_xiuxian_3.xiuxian.specials.dispatch_repository.uuid4",
                        side_effect=[
                            SimpleNamespace(hex=seed),
                            SimpleNamespace(hex=f"assignment-{seed}"),
                        ],
                    ):
                        accepted = await send("survey-accept", "接受派遣 云铁矿区勘测")
                    assert accepted.code == "DISPATCH_ACCEPTED", accepted.message
                    clock.value = datetime.fromisoformat(accepted.data["ends_at"])
                    settled = await send("survey-settle", "结算派遣")
                    assert settled.code == "DISPATCH_SETTLED", settled.message
                    assert settled.data["outcome"] == "success"
                    assert settled.data["reward"]["local.xuantian.cloud_city"] == 5

                    ready = await send("idle-preview", "挂机预览 云城店铺")
                    shop = next(item for item in ready.data["routes"] if item["route_key"] == "idle.cloud_city_shop")
                    assert shop["ready"] is True, shop["missing"]
                    cancelled_start = await send("idle-cancel-start", "开始挂机 云城店铺")
                    assert cancelled_start.code == "IDLE_STARTED", cancelled_start.message
                    cancelled = await send("idle-cancel", "取消挂机")
                    assert cancelled.code == "IDLE_CANCELLED", cancelled.message
                    assert (await send("cancelled-story-claim", "领取主线奖励 账房夜值")).code == "MAINLINE_OBJECTIVES_INCOMPLETE"

                    clock.advance(days=1)
                    expired_start = await send("idle-expired-start", "开始挂机 云城店铺")
                    assert expired_start.code == "IDLE_STARTED", expired_start.message
                    clock.advance(hours=48)
                    expired_claim = await send("idle-expired-claim", "领取挂机")
                    assert expired_claim.code == "IDLE_CLAIMED", expired_claim.message
                    assert expired_claim.data["fallback"] is True
                    assert (await send("expired-story-claim", "领取主线奖励 账房夜值")).code == "MAINLINE_OBJECTIVES_INCOMPLETE"

                    clock.advance(days=1)
                    idle_started = await send("idle-start", "开始挂机 云城店铺")
                    assert idle_started.code == "IDLE_STARTED", idle_started.message
                    assignment_id = idle_started.data["assignment_id"]
                    with sqlite3.connect(runtime.settings.database_path) as connection:
                        snapshot = json.loads(
                            connection.execute(
                                "SELECT snapshot_json FROM idle_assignments WHERE assignment_id=?",
                                (assignment_id,),
                            ).fetchone()[0]
                        )
                    assert snapshot["route_key"] == "idle.cloud_city_shop"
                    assert snapshot["location_key"] == "xuantian.cloud_city"

                    await runtime.close()
                    runtime = create_runtime(data_dir=data_dir, clock=clock, adapters=ADAPTERS)
                    restored = await runtime.adapters.dispatch(
                        adapter, _context(adapter, user, "restored-status"), "挂机状态"
                    )
                    assert restored.code == "IDLE_STATUS"
                    assert restored.data["assignment"]["assignment_id"] == assignment_id

                    clock.advance(hours=8)
                    idle_claim = await runtime.adapters.dispatch(
                        adapter, _context(adapter, user, "idle-claim"), "领取挂机"
                    )
                    assert idle_claim.code == "IDLE_CLAIMED", idle_claim.message
                    assert idle_claim.data["fallback"] is False

                    story_claim = await runtime.adapters.dispatch(
                        adapter, _context(adapter, user, "story-claim"), "领取主线奖励 账房夜值"
                    )
                    assert story_claim.code == "MAINLINE_REWARD_CLAIMED", story_claim.message
                    assert story_claim.data["next_stage_key"] is None
                    replay = await runtime.adapters.dispatch(
                        adapter, _context(adapter, user, "story-claim"), "领取主线奖励 账房夜值"
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
                    assert "story.mainline.xuantian:chapter.9.stage.4" in events
            finally:
                await runtime.close()

    asyncio.run(run())


def test_old_chapter_nine_clear_still_unlocks_chapter_ten() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=Path(data_dir), adapters=("onebot.v11",))
            user = "chapter-nine-legacy"
            try:
                assert (await runtime.dispatch(_context("onebot.v11", user, "create"), "开始修仙")).ok
                _prepare_player(runtime, "onebot.v11", user)
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE players SET realm_key='nascent_soul', realm_layer=1 "
                        "WHERE platform='onebot.v11' AND platform_user_id=?",
                        (user,),
                    )
                result = await runtime.dispatch(
                    _context("onebot.v11", user, "chapter-ten"),
                    "开始主线 云城问舟",
                )
                # The optional epilogue never becomes a prerequisite for the old chain.
                assert result.code == "MAINLINE_STARTED", result.message
            finally:
                await runtime.close()

    asyncio.run(run())
