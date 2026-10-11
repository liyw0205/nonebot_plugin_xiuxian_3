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
from nonebot_plugin_xiuxian_3.xiuxian.adventures.mainline import MAINLINE_STORY_KEY, mainline_definitions
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle, ContentError


ROOT = Path(__file__).parents[1]


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


def test_first_two_story_stages_reject_title_only_content(tmp_path: Path) -> None:
    content_dir = _copy_content(tmp_path)
    story_path = content_dir / "剧情" / "主线.json"
    document = json.loads(story_path.read_text(encoding="utf-8"))
    first = next(row for row in document["records"] if row["key"] == "chapter.1.stage.1")
    del first["body"]
    story_path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ContentError, match="body is too short"):
        mainline_definitions(ContentBundle.load(content_dir), story_key=MAINLINE_STORY_KEY)


def test_first_two_story_stages_use_settled_player_actions_and_retry_in_place(tmp_path: Path) -> None:
    async def run() -> None:
        clock = MutableClock()
        runtime = create_runtime(data_dir=tmp_path, clock=clock, adapters=("onebot.v11",))
        user = "story-vertical-onebot"

        async def send(operation: str, command: str):
            return await runtime.adapters.dispatch("onebot.v11", _context(user, operation), command)

        try:
            assert (await send("create", "开始修仙")).ok
            assert (await send("seek", "寻仙问道")).ok
            started = await send("stage1-start", "开始主线 1")
            assert started.code == "MAINLINE_STARTED"
            assert "寻仙问道之后" in started.message
            assert "前往 近郊" in started.message

            incomplete = await send("stage1-early-claim", "领取主线奖励 1")
            assert incomplete.code == "MAINLINE_OBJECTIVES_INCOMPLETE"
            with runtime.repository._connect() as connection:
                run_row = connection.execute(
                    "SELECT status, attempt_count FROM mainline_runs WHERE stage_key='chapter.1.stage.1'"
                ).fetchone()
                assert (run_row["status"], run_row["attempt_count"]) == ("running", 1)
                assert connection.execute(
                    "SELECT 1 FROM operations WHERE operation_id='stage1-early-claim'"
                ).fetchone() is None

            travel = await send("travel-start", "前往 近郊")
            assert travel.code == "TRAVEL_STARTED", travel.message
            clock.advance(seconds=30)
            assert (await send("travel-settle", "结算移动")).code == "TRAVEL_COMPLETED"
            first_clear = await send("stage1-claim", "领取主线奖励 1")
            assert first_clear.code == "MAINLINE_REWARD_CLAIMED"
            assert first_clear.data["next_stage_key"] == "chapter.1.stage.2"

            with runtime.repository._connect() as connection:
                row = connection.execute(
                    "SELECT intro_json FROM players WHERE platform='onebot.v11' AND platform_user_id=?",
                    (user,),
                ).fetchone()
                intro = json.loads(row["intro_json"])
                intro["flags"] = list(dict.fromkeys([*intro.get("flags", []), "guide.gather_blood_grass"]))
                connection.execute(
                    "UPDATE players SET realm_key='qi_sensing', realm_layer=2, intro_json=? "
                    "WHERE platform='onebot.v11' AND platform_user_id=?",
                    (json.dumps(intro, ensure_ascii=False), user),
                )

            second_started = await send("stage2-start", "开始主线 2")
            assert second_started.code == "MAINLINE_STARTED"
            assert "开始探索 灵泉采集" in second_started.message
            second_incomplete = await send("stage2-early-claim", "领取主线奖励 2")
            assert second_incomplete.code == "MAINLINE_OBJECTIVES_INCOMPLETE"

            spirit_travel = await send("spirit-travel-start", "前往 灵泉谷")
            assert spirit_travel.code == "TRAVEL_STARTED", spirit_travel.message
            clock.advance(hours=1)
            spirit_arrival = await send("spirit-travel-settle", "结算移动")
            assert spirit_arrival.code == "TRAVEL_COMPLETED", spirit_arrival.message

            exploration = await send("spring-start", "开始探索 灵泉采集")
            assert exploration.code == "EXPLORATION_STARTED", exploration.message
            clock.advance(seconds=90)
            settlement = await send("spring-settle", "结算探索")
            assert settlement.code == "EXPLORATION_SETTLED", settlement.message
            assert settlement.data["result"]["item.herb.spirit_leaf"] >= 1

            second_clear = await send("stage2-claim", "领取主线奖励 2")
            assert second_clear.code == "MAINLINE_REWARD_CLAIMED"
            assert second_clear.data["next_stage_key"] == "chapter.1.stage.3"
            with runtime.repository._connect() as connection:
                events = {
                    row["event_key"]
                    for row in connection.execute(
                        "SELECT event_key FROM activity_events WHERE player_id=(SELECT id FROM players WHERE platform='onebot.v11' AND platform_user_id=?)",
                        (user,),
                    ).fetchall()
                }
                assert "story.mainline.xuantian:chapter.1.stage.1" in events
                assert "story.mainline.xuantian:chapter.1.stage.2" in events
        finally:
            await runtime.close()

    asyncio.run(run())


def test_idle_assignment_recovers_after_restart_and_settles_idempotently_onebot(tmp_path: Path) -> None:
    content = _copy_content(tmp_path)
    livelihood_path = content / "生活" / "生活.json"
    livelihood = json.loads(livelihood_path.read_text(encoding="utf-8"))
    route = next(row for row in livelihood["records"] if row.get("key") == "idle.town_errand")
    route["duration_seconds"] = 60
    route["daily_limit"] = 1
    livelihood_path.write_text(json.dumps(livelihood, ensure_ascii=False, indent=2), encoding="utf-8")

    reward_path = content / "奖励" / "奖励.json"
    rewards = json.loads(reward_path.read_text(encoding="utf-8"))
    pool = next(row for row in rewards["records"] if row.get("key") == "reward_pool.idle.town_errand")
    pool["outcomes"] = [{"weight": 1, "rewards": {"spirit_stones": 77, "local.xuantian.new_town": 2}}]
    reward_path.write_text(json.dumps(rewards, ensure_ascii=False, indent=2), encoding="utf-8")

    locations_path = content / "地图" / "地点.json"
    locations = json.loads(locations_path.read_text(encoding="utf-8"))
    town = next(row for row in locations["records"] if row.get("key") == "xuantian.new_town")
    town["local_reputation_maximum"] = 41
    locations_path.write_text(json.dumps(locations, ensure_ascii=False, indent=2), encoding="utf-8")

    async def run() -> None:
        clock = MutableClock()
        user = "idle-restart-onebot"
        runtime = create_runtime(data_dir=content, clock=clock, adapters=("onebot.v11",))
        assert (await runtime.dispatch(_context(user, "create"), "开始修仙")).ok
        assert (await runtime.dispatch(_context(user, "seek"), "寻仙问道")).ok
        with runtime.repository._connect() as connection:
            player_id = connection.execute(
                "SELECT id FROM players WHERE platform='onebot.v11' AND platform_user_id=?", (user,)
            ).fetchone()[0]
            connection.execute(
                "INSERT INTO player_reputations(player_id, local_json, service_reputation, updated_at) "
                "VALUES (?, ?, 0, ?) ON CONFLICT(player_id) DO UPDATE SET local_json=excluded.local_json",
                (player_id, json.dumps({"local.xuantian.new_town": 40}), clock().isoformat()),
            )
        started = await runtime.dispatch(_context(user, "start"), "开始挂机 镇中行旅")
        assert started.code == "IDLE_STARTED", started.message
        with runtime.repository._connect() as connection:
            persisted = connection.execute(
                "SELECT status, snapshot_json FROM idle_assignments WHERE assignment_id=?",
                (started.data["assignment_id"],),
            ).fetchone()
            assert persisted["status"] == "running"
            snapshot = json.loads(persisted["snapshot_json"])
            assert snapshot["full_reward"]["spirit_stones"] == 77
            assert snapshot["local_reputation_maximums"]["local.xuantian.new_town"] == 41
        await runtime.close()

        clock.advance(hours=1)
        runtime = create_runtime(data_dir=content, clock=clock, adapters=("onebot.v11",))
        claimed = await runtime.dispatch(_context(user, "claim"), "领取挂机")
        assert claimed.code == "IDLE_CLAIMED", claimed.message
        assert claimed.data["reward"] == {"spirit_stones": 77, "local.xuantian.new_town": 1}
        replay = await runtime.dispatch(_context(user, "claim"), "领取挂机")
        assert replay.code == "IDLE_CLAIMED"
        assert replay.data["idempotent_replay"] is True
        assert replay.data["reward"] == claimed.data["reward"]
        cooldown = await runtime.dispatch(_context(user, "start-again"), "开始挂机 镇中行旅")
        assert cooldown.code == "IDLE_DAILY_LIMIT"
        await runtime.close()

    asyncio.run(run())
