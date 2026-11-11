from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.adventures.mainline import (
    SEEKER_ECHOES_STORY_KEY,
    mainline_definitions,
)
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle, ContentError


DATA = Path(__file__).parents[1] / "data"
ADAPTERS = ("qq.official", "onebot.v11")


class Clock:
    def __init__(self, value: datetime) -> None:
        self.value = value

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


def _prepare_seeker(runtime, clock: Clock, adapter: str, user: str) -> int:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        player_id = connection.execute(
            "SELECT id FROM players WHERE platform=? AND platform_user_id=?",
            (adapter, user),
        ).fetchone()[0]
        now = clock().isoformat()
        connection.execute(
            "UPDATE players SET stage='seeker', location_key='xuantian.new_town', "
            "stamina=100, stamina_max=100, energy=40, energy_max=40 WHERE id=?",
            (player_id,),
        )
        connection.execute(
            "INSERT INTO player_reputations(player_id, local_json, service_reputation, updated_at) "
            "VALUES (?, ?, 0, ?) ON CONFLICT(player_id) DO UPDATE SET local_json=excluded.local_json",
            (player_id, json.dumps({"local.xuantian.new_town": 10}, sort_keys=True), now),
        )
        connection.execute(
            "INSERT INTO residences(residence_id, player_id, operation_id, residence_key, status, "
            "starts_at, ends_at, rent_cost, created_at, updated_at) "
            "VALUES (?, ?, ?, 'residence.herb_court', 'active', ?, ?, 0, ?, ?)",
            (
                f"{adapter}:{user}:residence",
                player_id,
                f"{adapter}:{user}:residence-operation",
                now,
                (clock.value + timedelta(days=7)).isoformat(),
                now,
                now,
            ),
        )
        return int(player_id)


def test_seeker_echoes_content_closes_only_open_sources() -> None:
    bundle = ContentBundle.load(DATA)
    definitions = {
        item.key: item
        for item in mainline_definitions(bundle, story_key=SEEKER_ECHOES_STORY_KEY)
    }
    stages = [definitions[f"seeker_echoes.{index}"] for index in (1, 2, 3)]
    assert [item.next_stage_key for item in stages] == [
        "seeker_echoes.2",
        "seeker_echoes.3",
        None,
    ]
    assert stages[0].objectives[0] == {
        "key": "return_new_town",
        "type": "travel_arrival",
        "label": "本关开始后结算行程抵达青石镇",
        "destination_key": "xuantian.new_town",
    }
    assert stages[1].objectives[0]["route_key"] == "idle.seeker_town_inquiry"
    assert stages[2].objectives[0]["route_key"] == "idle.seeker_herb_tending"
    for route_key in ("idle.seeker_town_inquiry", "idle.seeker_herb_tending"):
        route = bundle.require("livelihood", route_key)
        assert route["status"] == "active"
        assert bundle.require("reward", route["reward_pool_key"])["status"] == "active"
        assert bundle.require("reward", route["fallback_reward_pool_key"])["status"] == "active"


def test_seeker_echoes_rejects_inactive_idle_source(tmp_path) -> None:
    import shutil

    data_dir = tmp_path / "content"
    shutil.copytree(DATA, data_dir)
    path = data_dir / "生活" / "生活.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    route = next(row for row in document["records"] if row["key"] == "idle.seeker_town_inquiry")
    route["status"] = "locked"
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    try:
        mainline_definitions(ContentBundle.load(data_dir), story_key=SEEKER_ECHOES_STORY_KEY)
    except ContentError:
        pass
    else:
        raise AssertionError("locked idle source must fail content loading")


def test_seeker_echoes_help_points_to_real_commands() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, adapters=("qq.official",))
            try:
                result = await runtime.dispatch(
                    _context("qq.official", "seeker-help", "help"),
                    "修仙帮助 生活",
                )
                assert result.code == "HELP_CATEGORY"
                for token in (
                    "寻道闲居回响主线",
                    "挂机预览 镇中问询",
                    "挂机预览 灵田照看",
                    "完整领取",
                    "逾时保底不替代主线交班",
                ):
                    assert token in result.message, token
            finally:
                await runtime.close()

    asyncio.run(run())


def test_seeker_echoes_runs_on_both_adapters_and_counts_only_full_idle_claims() -> None:
    async def run() -> None:
        clock = Clock(datetime(2026, 11, 20, 8, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock, adapters=ADAPTERS)
            try:
                for adapter in ADAPTERS:
                    user = f"seeker-echoes-{adapter}"
                    dispatch = lambda operation, command: runtime.adapters.dispatch(
                        adapter, _context(adapter, user, operation), command
                    )
                    assert (await dispatch("create", "开始修仙")).code == "PLAYER_CREATED"
                    assert (await dispatch("seek", "寻仙问道")).ok
                    player_id = _prepare_seeker(runtime, clock, adapter, user)

                    assert (await dispatch("status", "寻道闲居回响主线")).code == "MAINLINE_STATUS"
                    started = await dispatch(
                        "stage1-start", "开始寻道闲居回响主线 回镇听雨"
                    )
                    assert started.code == "MAINLINE_STARTED", started.message
                    early = await dispatch(
                        "stage1-early", "领取寻道闲居回响主线奖励 回镇听雨"
                    )
                    assert early.code == "MAINLINE_OBJECTIVES_INCOMPLETE"

                    assert (await dispatch("to-outskirts", "前往 近郊")).code == "TRAVEL_STARTED"
                    clock.advance(seconds=31)
                    assert (await dispatch("to-outskirts-settle", "结算移动")).code == "TRAVEL_COMPLETED"
                    assert (await dispatch("back-town", "前往 青石镇")).code == "TRAVEL_STARTED"
                    assert (await dispatch("back-town-settle", "结算移动")).code == "TRAVEL_COMPLETED"
                    first = await dispatch(
                        "stage1-claim", "领取寻道闲居回响主线奖励 回镇听雨"
                    )
                    assert first.code == "MAINLINE_REWARD_CLAIMED", first.message

                    assert (await dispatch("stage2-start", "开始寻道闲居回响主线 镇中问询")).code == "MAINLINE_STARTED"
                    assert (await dispatch("inquiry-early", "领取寻道闲居回响主线奖励 镇中问询")).code == "MAINLINE_OBJECTIVES_INCOMPLETE"
                    assert (await dispatch("inquiry-start", "开始挂机 镇中问询")).code == "IDLE_STARTED"
                    clock.advance(hours=27, seconds=1)
                    expired = await dispatch("inquiry-expired", "领取挂机")
                    assert expired.code == "IDLE_CLAIMED" and expired.data["fallback"] is True
                    assert (await dispatch("stage2-expired", "领取寻道闲居回响主线奖励 镇中问询")).code == "MAINLINE_OBJECTIVES_INCOMPLETE"
                    clock.advance(days=1)
                    assert (await dispatch("inquiry-retry-start", "开始挂机 镇中问询")).code == "IDLE_STARTED"
                    clock.advance(hours=3)
                    inquiry = await dispatch("inquiry-claim", "领取挂机")
                    assert inquiry.code == "IDLE_CLAIMED" and inquiry.data["fallback"] is False
                    second = await dispatch(
                        "stage2-claim", "领取寻道闲居回响主线奖励 镇中问询"
                    )
                    assert second.code == "MAINLINE_REWARD_CLAIMED", second.message
                    assert (await dispatch("stage2-claim", "领取寻道闲居回响主线奖励 镇中问询")).data["idempotent_replay"] is True

                    assert (await dispatch("stage3-start", "开始寻道闲居回响主线 灵田照看")).code == "MAINLINE_STARTED"
                    assert (await dispatch("herb-early", "领取寻道闲居回响主线奖励 灵田照看")).code == "MAINLINE_OBJECTIVES_INCOMPLETE"
                    assert (await dispatch("herb-start", "开始挂机 灵田照看")).code == "IDLE_STARTED"
                    clock.advance(hours=4)
                    herb = await dispatch("herb-claim", "领取挂机")
                    assert herb.code == "IDLE_CLAIMED" and herb.data["fallback"] is False
                    third = await dispatch(
                        "stage3-claim", "领取寻道闲居回响主线奖励 灵田照看"
                    )
                    assert third.code == "MAINLINE_REWARD_CLAIMED", third.message
                    replay = await dispatch(
                        "stage3-claim", "领取寻道闲居回响主线奖励 灵田照看"
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
                        assert "story.mainline.seeker_echoes:seeker_echoes.3" in events
                        assert connection.execute(
                            "SELECT COUNT(*) FROM operations WHERE operation_id LIKE ?",
                            (f"{adapter}:{user}:stage%-claim",),
                        ).fetchone()[0] == 3
            finally:
                await runtime.close()

    asyncio.run(run())
