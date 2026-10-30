"""Playable chain for the Xuantian grotto volume (chapter 6, stages 1-3)."""

from __future__ import annotations

import asyncio
import json
import shutil
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime

DATA = Path(__file__).parents[1] / "data"
STORY = "story.mainline.xuantian"
PRIOR_STAGES = tuple(
    f"chapter.{chapter}.stage.{stage}"
    for chapter, stages in ((1, 3), (2, 3), (3, 3), (4, 3), (5, 3))
    for stage in range(1, stages + 1)
)


class MutableClock:
    def __init__(self, value: datetime):
        self.value = value

    def __call__(self) -> datetime:
        return self.value

    def advance(self, **kwargs: int) -> None:
        self.value += timedelta(**kwargs)


def _context(user: str, name: str, operation_id: str = "") -> CommandContext:
    return CommandContext(adapter="web", user_id=user, request_id=name, operation_id=operation_id)


def _seed_prior_volume(runtime, user: str) -> None:
    """Context fixture: the fifteen recorded stages before this volume."""

    now = datetime(2026, 9, 20, tzinfo=timezone.utc).isoformat()
    with sqlite3.connect(runtime.settings.database_path) as connection:
        player_id = connection.execute(
            "SELECT id FROM players WHERE platform_user_id = ?", (user,)
        ).fetchone()[0]
        for key in PRIOR_STAGES:
            chapter, stage = (int(part) for part in key.split(".")[1::2])
            connection.execute(
                "INSERT INTO mainline_runs(player_id, story_key, chapter, stage, stage_key, status, "
                "first_clear_claimed, first_clear_key, snapshot_json, result_json, created_at, updated_at) "
                "VALUES(?, ?, ?, ?, ?, 'claimed', 1, ?, '{}', '{}', ?, ?)",
                (player_id, STORY, chapter, stage, key, f"{STORY}:{key}", now, now),
            )
        row = connection.execute(
            "SELECT intro_json FROM players WHERE id = ?", (player_id,)
        ).fetchone()
        intro = json.loads(row[0] or "{}")
        intro["flags"] = list(dict.fromkeys([*intro.get("flags", []), "guide.gather_blood_grass"]))
        connection.execute(
            "UPDATE players SET realm_key='golden_core', realm_layer=6, "
            "location_key='xuantian.outskirts', stamina=200, stamina_max=200, "
            "spirit_stones=9000, intro_json=? WHERE id = ?",
            (json.dumps(intro, ensure_ascii=False), player_id),
        )


def test_xuantian_grotto_volume_is_playable_end_to_end() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 24, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            root = Path(data_dir)
            shutil.copytree(DATA, root / "data")
            runtime = create_runtime(data_dir=root, clock=clock)
            user = "grotto-volume"
            try:
                assert (await runtime.dispatch(_context(user, "create"), "开始修仙")).ok
                assert (await runtime.dispatch(_context(user, "seek"), "寻仙问道")).ok
                _seed_prior_volume(runtime, user)

                # Stage 1: come back to the town and take up the old ledger.
                started = await runtime.dispatch(
                    _context(user, "s1-start", "s1-start"), "开始主线 chapter.6.stage.1"
                )
                assert started.code == "MAINLINE_STARTED", started
                early = await runtime.dispatch(
                    _context(user, "s1-early", "s1-early"), "领取主线奖励 chapter.6.stage.1"
                )
                assert early.code == "MAINLINE_OBJECTIVES_INCOMPLETE", early

                assert (
                    await runtime.dispatch(_context(user, "to-town"), "前往 青石镇")
                ).code == "TRAVEL_STARTED"
                clock.advance(seconds=60)
                assert (
                    await runtime.dispatch(_context(user, "to-town-settle"), "结算移动")
                ).code == "TRAVEL_COMPLETED"

                first = await runtime.dispatch(
                    _context(user, "s1-claim", "s1-claim"), "领取主线奖励 chapter.6.stage.1"
                )
                assert first.code == "MAINLINE_REWARD_CLAIMED", first
                assert first.data["next_stage_key"] == "chapter.6.stage.2"

                # Stage 2: gather spirit leaves in the valley.
                second_start = await runtime.dispatch(
                    _context(user, "s2-start", "s2-start"), "开始主线 chapter.6.stage.2"
                )
                assert second_start.code == "MAINLINE_STARTED", second_start
                second_early = await runtime.dispatch(
                    _context(user, "s2-early", "s2-early"), "领取主线奖励 chapter.6.stage.2"
                )
                assert second_early.code == "MAINLINE_OBJECTIVES_INCOMPLETE", second_early

                assert (
                    await runtime.dispatch(_context(user, "to-valley"), "前往 灵泉谷")
                ).code == "TRAVEL_STARTED"
                clock.advance(seconds=120)
                assert (
                    await runtime.dispatch(_context(user, "to-valley-settle"), "结算移动")
                ).code == "TRAVEL_COMPLETED"

                gather = await runtime.dispatch(_context(user, "gather"), "开始探索 灵泉采集")
                assert gather.code == "EXPLORATION_STARTED", gather
                clock.advance(seconds=90)
                settled = await runtime.dispatch(_context(user, "gather-settle"), "结算探索")
                assert settled.code == "EXPLORATION_SETTLED", settled
                assert settled.data["result"]["item.herb.spirit_leaf"] >= 1

                second = await runtime.dispatch(
                    _context(user, "s2-claim", "s2-claim"), "领取主线奖励 chapter.6.stage.2"
                )
                assert second.code == "MAINLINE_REWARD_CLAIMED", second
                assert second.data["next_stage_key"] == "chapter.6.stage.3"

                # Stage 3: carry the leaves home and close the volume.
                third_start = await runtime.dispatch(
                    _context(user, "s3-start", "s3-start"), "开始主线 chapter.6.stage.3"
                )
                assert third_start.code == "MAINLINE_STARTED", third_start
                assert (
                    await runtime.dispatch(_context(user, "back-town"), "前往 青石镇")
                ).code == "TRAVEL_STARTED"
                clock.advance(seconds=60)
                assert (
                    await runtime.dispatch(_context(user, "back-town-settle"), "结算移动")
                ).code == "TRAVEL_COMPLETED"

                third = await runtime.dispatch(
                    _context(user, "s3-claim", "s3-claim"), "领取主线奖励 chapter.6.stage.3"
                )
                assert third.code == "MAINLINE_REWARD_CLAIMED", third
                assert third.data["next_stage_key"] == "chapter.7.stage.1"

                replay = await runtime.dispatch(
                    _context(user, "s3-replay", "s3-claim"), "领取主线奖励 chapter.6.stage.3"
                )
                assert replay.code == "MAINLINE_REWARD_CLAIMED", replay
                assert replay.data["idempotent_replay"] is True

                with sqlite3.connect(runtime.settings.database_path) as connection:
                    events = {
                        row[0]
                        for row in connection.execute(
                            "SELECT event_key FROM activity_events WHERE player_id="
                            "(SELECT id FROM players WHERE platform_user_id = ?)",
                            (user,),
                        ).fetchall()
                    }
                assert f"{STORY}:chapter.6.stage.1" in events
                assert f"{STORY}:chapter.6.stage.2" in events
                assert f"{STORY}:chapter.6.stage.3" in events
            finally:
                await runtime.close()

    asyncio.run(run())


def test_grotto_volume_objectives_use_walkable_destinations() -> None:
    """Every arrival target must be reachable by ordinary travel, not cloud boat only."""

    from nonebot_plugin_xiuxian_3.xiuxian.adventures.mainline import mainline_definitions
    from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle

    bundle = ContentBundle.load(DATA)
    regions = bundle.list("world_region")
    walkable: set[str] = set()
    for region in regions:
        for connection in region.get("connections", []) or []:
            walkable.add(connection["to"])
            walkable.add(connection["from"])
    cloud_destinations = {row["destination"] for row in bundle.list("world_cloud_route")}

    definitions = mainline_definitions(bundle, story_key=STORY)
    grotto = [item for item in definitions if item.key.startswith("chapter.6.")]
    assert [item.key for item in grotto] == [
        "chapter.6.stage.1",
        "chapter.6.stage.2",
        "chapter.6.stage.3",
    ]
    for stage in grotto:
        for objective in stage.objectives:
            if objective["type"] == "travel_arrival":
                target = objective["destination_key"]
                assert target in walkable, (stage.key, target)
                assert target not in cloud_destinations, (stage.key, target)
