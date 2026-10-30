"""Playable chain for the Xuantian grotto volume, second part (chapter 7, stages 1-3)."""

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
from nonebot_plugin_xiuxian_3.xiuxian.exploration.rules import battle_roll_bp

DATA = Path(__file__).parents[1] / "data"
STORY = "story.mainline.xuantian"
PASS = "item.cave_pass_advanced"
PRIOR_STAGES = tuple(
    f"chapter.{chapter}.stage.{stage}"
    for chapter, stages in ((1, 3), (2, 3), (3, 3), (4, 3), (5, 3), (6, 3))
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


def _calm_operation(user: str) -> str:
    """An operation id whose exploration seed does not trigger a battle."""

    return next(
        f"{user}-gather-{index}"
        for index in range(5_000)
        if battle_roll_bp(f"{user}-gather-{index}:battle") >= 4_000
    )


def _seed_prior_volume(runtime, user: str) -> None:
    """Context fixture: the eighteen recorded stages before this volume."""

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
        # Two passes: the cloud boat consumes one, the exploration access gate needs one.
        inventory = {PASS: 3}
        connection.execute(
            "UPDATE players SET realm_key='golden_core', realm_layer=6, "
            "location_key='xuantian.new_town', stamina=200, stamina_max=200, "
            "spirit_stones=9000, inventory_json=?, intro_json=? WHERE id = ?",
            (json.dumps(inventory, ensure_ascii=False), json.dumps(intro, ensure_ascii=False), player_id),
        )


def _passes(runtime, user: str) -> int:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        raw = connection.execute(
            "SELECT inventory_json FROM players WHERE platform_user_id = ?", (user,)
        ).fetchone()[0]
    return int(json.loads(raw or "{}").get(PASS, 0))


def test_xuantian_grotto_second_layer_is_playable_end_to_end() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 26, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            root = Path(data_dir)
            shutil.copytree(DATA, root / "data")
            runtime = create_runtime(data_dir=root, clock=clock)
            user = "grotto-second"
            try:
                assert (await runtime.dispatch(_context(user, "create"), "开始修仙")).ok
                assert (await runtime.dispatch(_context(user, "seek"), "寻仙问道")).ok
                _seed_prior_volume(runtime, user)
                assert _passes(runtime, user) == 3

                # Stage 1: walk the public route to the cloud-boat dock.
                started = await runtime.dispatch(
                    _context(user, "s1-start", "s1-start"), "开始主线 chapter.7.stage.1"
                )
                assert started.code == "MAINLINE_STARTED", started
                early = await runtime.dispatch(
                    _context(user, "s1-early", "s1-early"), "领取主线奖励 chapter.7.stage.1"
                )
                assert early.code == "MAINLINE_OBJECTIVES_INCOMPLETE", early

                assert (
                    await runtime.dispatch(_context(user, "to-city"), "前往 云城")
                ).code == "TRAVEL_STARTED"
                clock.advance(seconds=200)
                assert (
                    await runtime.dispatch(_context(user, "to-city-settle"), "结算移动")
                ).code == "TRAVEL_COMPLETED"
                assert (
                    await runtime.dispatch(_context(user, "to-dock"), "前往 云舟渡口")
                ).code == "TRAVEL_STARTED"
                clock.advance(seconds=70)
                assert (
                    await runtime.dispatch(_context(user, "to-dock-settle"), "结算移动")
                ).code == "TRAVEL_COMPLETED"

                first = await runtime.dispatch(
                    _context(user, "s1-claim", "s1-claim"), "领取主线奖励 chapter.7.stage.1"
                )
                assert first.code == "MAINLINE_REWARD_CLAIMED", first
                assert first.data["next_stage_key"] == "chapter.7.stage.2"

                # Stage 2: board the cloud boat, run the second layer, come back with ore.
                second_start = await runtime.dispatch(
                    _context(user, "s2-start", "s2-start"), "开始主线 chapter.7.stage.2"
                )
                assert second_start.code == "MAINLINE_STARTED", second_start
                second_early = await runtime.dispatch(
                    _context(user, "s2-early", "s2-early"), "领取主线奖励 chapter.7.stage.2"
                )
                assert second_early.code == "MAINLINE_OBJECTIVES_INCOMPLETE", second_early

                passes_before_board = _passes(runtime, user)
                board = await runtime.dispatch(_context(user, "board"), "登上云舟 洞天二层")
                assert board.code == "CLOUD_BOAT_STARTED", board
                passes_after_board = _passes(runtime, user)
                assert passes_after_board == passes_before_board - 1, "boarding consumes exactly one pass"
                clock.advance(seconds=320)
                arrived = await runtime.dispatch(_context(user, "boat-settle"), "结算云舟")
                assert arrived.code == "CLOUD_BOAT_ARRIVED", arrived
                assert arrived.data["destination"] == "cave.mist_grotto_2"
                assert _passes(runtime, user) == passes_after_board, "settling must not consume another pass"

                # A second settle has no session to act on: it must not move the
                # player again or consume another pass.
                replay_boat = await runtime.dispatch(
                    _context(user, "boat-settle-replay", "boat-settle-replay-op"), "结算云舟"
                )
                assert replay_boat.code == "CLOUD_BOAT_NOT_FOUND", replay_boat
                assert _passes(runtime, user) == passes_after_board
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    assert connection.execute(
                        "SELECT location_key FROM players WHERE platform_user_id = ?", (user,)
                    ).fetchone()[0] == "cave.mist_grotto_2"

                gather_op = _calm_operation(user)
                gather = await runtime.dispatch(
                    _context(user, "gather", gather_op), "开始探索 洞天二层探索"
                )
                assert gather.code == "EXPLORATION_STARTED", gather
                clock.advance(seconds=620)
                settled = await runtime.dispatch(_context(user, "gather-settle"), "结算探索")
                assert settled.code == "EXPLORATION_SETTLED", settled
                assert settled.data["result"]["item.material.cloud_iron"] >= 1

                second = await runtime.dispatch(
                    _context(user, "s2-claim", "s2-claim"), "领取主线奖励 chapter.7.stage.2"
                )
                assert second.code == "MAINLINE_REWARD_CLAIMED", second
                assert second.data["next_stage_key"] == "chapter.7.stage.3"

                # Stage 3: sail back to the cloud city and walk home.
                third_start = await runtime.dispatch(
                    _context(user, "s3-start", "s3-start"), "开始主线 chapter.7.stage.3"
                )
                assert third_start.code == "MAINLINE_STARTED", third_start
                back = await runtime.dispatch(_context(user, "back-board"), "登上云舟 返回云城")
                assert back.code == "CLOUD_BOAT_STARTED", back
                clock.advance(seconds=200)
                back_arrived = await runtime.dispatch(_context(user, "back-settle"), "结算云舟")
                assert back_arrived.code == "CLOUD_BOAT_ARRIVED", back_arrived
                assert back_arrived.data["destination"] == "xuantian.cloud_city"
                assert (
                    await runtime.dispatch(_context(user, "to-town"), "前往 青石镇")
                ).code == "TRAVEL_STARTED"
                clock.advance(seconds=30)
                assert (
                    await runtime.dispatch(_context(user, "to-town-settle"), "结算移动")
                ).code == "TRAVEL_COMPLETED"

                third = await runtime.dispatch(
                    _context(user, "s3-claim", "s3-claim"), "领取主线奖励 chapter.7.stage.3"
                )
                assert third.code == "MAINLINE_REWARD_CLAIMED", third
                assert third.data.get("next_stage_key") in (None, "")

                replay = await runtime.dispatch(
                    _context(user, "s3-replay", "s3-claim"), "领取主线奖励 chapter.7.stage.3"
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
                assert f"{STORY}:chapter.7.stage.1" in events
                assert f"{STORY}:chapter.7.stage.2" in events
                assert f"{STORY}:chapter.7.stage.3" in events
            finally:
                await runtime.close()

    asyncio.run(run())


def test_grotto_second_layer_objectives_use_walkable_destinations() -> None:
    """Every arrival target must be reachable by ordinary travel, not cloud boat only."""

    from nonebot_plugin_xiuxian_3.xiuxian.adventures.mainline import mainline_definitions
    from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle

    bundle = ContentBundle.load(DATA)
    walkable: set[str] = set()
    for region in bundle.list("world_region"):
        for connection in region.get("connections", []) or []:
            walkable.add(connection["to"])
            walkable.add(connection["from"])
    cloud_destinations = {row["destination"] for row in bundle.list("world_cloud_route")}

    definitions = mainline_definitions(bundle, story_key=STORY)
    stages = [item for item in definitions if item.key.startswith("chapter.7.")]
    assert [item.key for item in stages] == [
        "chapter.7.stage.1",
        "chapter.7.stage.2",
        "chapter.7.stage.3",
    ]
    for stage in stages:
        assert stage.body and stage.objectives and stage.actions and stage.retry_message
        for objective in stage.objectives:
            if objective["type"] == "travel_arrival":
                target = objective["destination_key"]
                assert target in walkable, (stage.key, target)
                assert target not in cloud_destinations, (stage.key, target)
            if objective["type"] == "exploration_reward":
                # The mode's location may be cloud-boat only; the objective is an
                # exploration result, not an arrival, so that stays legitimate.
                assert objective["mode_key"] == "explore.mist_grotto_2"
                assert objective["location_key"] == "cave.mist_grotto_2"
                assert objective["item_key"] == "item.material.cloud_iron"
