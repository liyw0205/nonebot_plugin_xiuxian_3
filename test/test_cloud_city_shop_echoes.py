from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from combat_fixtures import BALANCED_QUALIFICATION
from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.adventures.mainline import (
    CLOUD_CITY_ECHOES_STORY_KEY,
    mainline_definitions,
)
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle, ContentError
from nonebot_plugin_xiuxian_3.xiuxian.exploration.rules import (
    battle_roll_bp,
    exploration_encounter_selection,
)


ADAPTERS = ("qq.official", "onebot.v11")
MODE = "explore.cloud_city_patrol"
LOCATION = "xuantian.cloud_city"
BATTLE_BP = 3_500
DATA = Path(__file__).parents[1] / "data"


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


def _prepare_player(runtime, adapter: str, user: str) -> None:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE players SET stage='cultivator', realm_key='golden_core', realm_layer=1, "
            "location_key='xuantian.new_town', stamina=200, stamina_max=200, spirit_stones=3000, "
            "max_hp=100000, initiative=100000, qualification_json=? "
            "WHERE platform=? AND platform_user_id=?",
            (json.dumps(BALANCED_QUALIFICATION), adapter, user),
        )


def _battle_operation(adapter: str, user: str) -> str:
    for index in range(10_000):
        operation = f"patrol-{index}"
        enemy, _ = exploration_encounter_selection(
            MODE,
            seed=f"{adapter}:{user}:{operation}",
            realm_key="golden_core",
            realm_layer=1,
        )
        if enemy == "enemy.bandit_apprentice" and battle_roll_bp(f"{adapter}:{user}:{operation}:battle") < BATTLE_BP:
            return operation
    raise AssertionError("could not find a deterministic patrol battle seed")


def test_cloud_city_echoes_contract_and_live_sources() -> None:
    bundle = ContentBundle.load(DATA)
    definitions = {item.key: item for item in mainline_definitions(bundle, story_key=CLOUD_CITY_ECHOES_STORY_KEY)}
    stages = [definitions[f"cloud_city_echoes.{index}"] for index in (1, 2, 3)]
    assert [item.next_stage_key for item in stages] == [
        "cloud_city_echoes.2", "cloud_city_echoes.3", None
    ]
    assert stages[0].objectives[0] == {
        "key": "reach_cloud_city",
        "type": "travel_arrival",
        "label": "本关开始后结算行程抵达云城",
        "destination_key": LOCATION,
    }
    assert stages[1].objectives[0] == {
        "key": "win_cloud_city_patrol",
        "type": "exploration_battle_victory",
        "label": "本关开始后在云城巡夜中赢得一场遭遇战",
        "mode_key": MODE,
        "location_key": LOCATION,
    }
    assert stages[2].objectives[0]["route_key"] == "idle.cloud_city_shop"
    route = bundle.require("livelihood", "idle.cloud_city_shop")
    assert route["requirements"]["local_reputation"]["local.xuantian.cloud_city"] == 200
    assert route["duration_seconds"] == 8 * 60 * 60


def test_cloud_city_echoes_rejects_inactive_sources(tmp_path) -> None:
    import shutil

    data = tmp_path / "content"
    shutil.copytree("data", data)
    story_path = data / "剧情" / "主线.json"
    document = json.loads(story_path.read_text(encoding="utf-8"))
    stage = next(row for row in document["records"] if row["key"] == "cloud_city_echoes.2")
    stage["objectives"][0]["mode_key"] = "explore.cloud_city_locked"
    story_path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    try:
        mainline_definitions(ContentBundle.load(data), story_key=CLOUD_CITY_ECHOES_STORY_KEY)
    except ContentError:
        pass
    else:
        raise AssertionError("inactive patrol source must fail content loading")


def test_cloud_city_echoes_runs_on_both_adapters_and_requires_full_idle() -> None:
    async def run() -> None:
        clock = Clock(datetime(2026, 11, 15, 8, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock, adapters=ADAPTERS)
            try:
                for adapter in ADAPTERS:
                    user = f"cloud-city-{adapter}"
                    dispatch = lambda operation, command: runtime.adapters.dispatch(
                        adapter, _context(adapter, user, operation), command
                    )
                    assert (await dispatch("create", "开始修仙")).code == "PLAYER_CREATED"
                    _prepare_player(runtime, adapter, user)

                    status = await dispatch("status", "云城店铺回响主线")
                    assert status.code == "MAINLINE_STATUS" and "云城听更" in status.message
                    started = await dispatch("stage1-start", "开始云城店铺回响主线 云城听更")
                    assert started.code == "MAINLINE_STARTED", started.message
                    assert (await dispatch("stage1-early", "领取云城店铺回响主线奖励 云城听更")).code == "MAINLINE_OBJECTIVES_INCOMPLETE"

                    travel = await dispatch("travel-start", "前往 云城")
                    assert travel.code == "TRAVEL_STARTED", travel.message
                    clock.advance(minutes=3)
                    assert (await dispatch("travel-settle", "结算移动")).code == "TRAVEL_COMPLETED"
                    assert (await dispatch("stage1-claim", "领取云城店铺回响主线奖励 云城听更")).code == "MAINLINE_REWARD_CLAIMED"

                    assert (await dispatch("stage2-start", "开始云城店铺回响主线 巡夜见锋")).code == "MAINLINE_STARTED"
                    assert (await dispatch("stage2-early", "领取云城店铺回响主线奖励 巡夜见锋")).code == "MAINLINE_OBJECTIVES_INCOMPLETE"
                    patrol_operation = _battle_operation(adapter, user)
                    patrol = await dispatch(patrol_operation, "开始探索 云城巡夜")
                    assert patrol.code == "EXPLORATION_STARTED", patrol.message
                    clock.advance(seconds=200)
                    settled = await dispatch("patrol-settle", "结算探索")
                    assert settled.code == "EXPLORATION_SETTLED", settled.message
                    assert settled.data["battle_outcome"] == "won", settled.data
                    assert (await dispatch("stage2-claim", "领取云城店铺回响主线奖励 巡夜见锋")).code == "MAINLINE_REWARD_CLAIMED"
                    blocked = await dispatch("shop-blocked", "开始挂机 云城店铺")
                    assert blocked.code in {"IDLE_REQUIREMENT_MISSING", "IDLE_CONTENT_CLOSED"}, blocked
                    with sqlite3.connect(runtime.settings.database_path) as connection:
                        player_id = connection.execute(
                            "SELECT id FROM players WHERE platform=? AND platform_user_id=?", (adapter, user)
                        ).fetchone()[0]
                        connection.execute(
                            "INSERT INTO player_reputations(player_id, local_json, service_reputation, updated_at) "
                            "VALUES (?, ?, 0, ?) ON CONFLICT(player_id) DO UPDATE SET local_json=excluded.local_json",
                            (player_id, json.dumps({"local.xuantian.cloud_city": 200}, sort_keys=True), clock().isoformat()),
                        )
                    old_start = await dispatch("shop-old-start", "开始挂机 云城店铺")
                    assert old_start.code == "IDLE_STARTED", old_start.message
                    clock.advance(hours=8)
                    old_claim = await dispatch("shop-old-claim", "领取挂机")
                    assert old_claim.code == "IDLE_CLAIMED" and old_claim.data["fallback"] is False
                    clock.advance(days=1)
                    assert (await dispatch("stage3-start", "开始云城店铺回响主线 店铺交班")).code == "MAINLINE_STARTED"
                    stale = await dispatch("stage3-stale", "领取云城店铺回响主线奖励 店铺交班")
                    assert stale.code == "MAINLINE_OBJECTIVES_INCOMPLETE"
                    expired_start = await dispatch("shop-expired-start", "开始挂机 云城店铺")
                    assert expired_start.code == "IDLE_STARTED", expired_start.message
                    clock.advance(hours=48)
                    expired = await dispatch("shop-expired-claim", "领取挂机")
                    assert expired.code == "IDLE_CLAIMED" and expired.data["fallback"] is True
                    assert (await dispatch("stage3-expired", "领取云城店铺回响主线奖励 店铺交班")).code == "MAINLINE_OBJECTIVES_INCOMPLETE"

                    clock.advance(days=1)
                    full_start = await dispatch("shop-full-start", "开始挂机 云城店铺")
                    assert full_start.code == "IDLE_STARTED", full_start.message
                    clock.advance(hours=8)
                    full = await dispatch("shop-full-claim", "领取挂机")
                    assert full.code == "IDLE_CLAIMED" and full.data["fallback"] is False
                    done = await dispatch("stage3-claim", "领取云城店铺回响主线奖励 店铺交班")
                    assert done.code == "MAINLINE_REWARD_CLAIMED", done.message
                    replay = await dispatch("stage3-claim", "领取云城店铺回响主线奖励 店铺交班")
                    assert replay.code == "MAINLINE_REWARD_CLAIMED" and replay.data["idempotent_replay"] is True
            finally:
                await runtime.close()

    asyncio.run(run())


def test_cloud_city_echoes_does_not_count_a_patrol_battle_loss() -> None:
    async def run() -> None:
        clock = Clock(datetime(2026, 11, 18, 8, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock, adapters=("onebot.v11",))
            adapter, user = "onebot.v11", "cloud-city-loss"
            dispatch = lambda operation, command: runtime.adapters.dispatch(
                adapter, _context(adapter, user, operation), command
            )
            try:
                assert (await dispatch("create", "开始修仙")).code == "PLAYER_CREATED"
                _prepare_player(runtime, adapter, user)
                assert (await dispatch("stage1-start", "开始云城店铺回响主线 云城听更")).ok
                assert (await dispatch("travel-start", "前往 云城")).code == "TRAVEL_STARTED"
                clock.advance(minutes=3)
                assert (await dispatch("travel-settle", "结算移动")).code == "TRAVEL_COMPLETED"
                assert (await dispatch("stage1-claim", "领取云城店铺回响主线奖励 云城听更")).ok
                assert (await dispatch("stage2-start", "开始云城店铺回响主线 巡夜见锋")).ok
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE players SET max_hp=10, initiative=1 WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    )
                patrol_operation = _battle_operation(adapter, user)
                assert (await dispatch(patrol_operation, "开始探索 云城巡夜")).code == "EXPLORATION_STARTED"
                clock.advance(seconds=200)
                settled = await dispatch("patrol-loss-settle", "结算探索")
                assert settled.code == "EXPLORATION_SETTLED" and settled.data["battle_outcome"] == "lost"
                rejected = await dispatch("stage2-claim", "领取云城店铺回响主线奖励 巡夜见锋")
                assert rejected.code == "MAINLINE_OBJECTIVES_INCOMPLETE"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    status = connection.execute(
                        "SELECT status FROM mainline_runs WHERE player_id=(SELECT id FROM players WHERE platform=? AND platform_user_id=?) AND stage_key='cloud_city_echoes.2'",
                        (adapter, user),
                    ).fetchone()[0]
                assert status == "running"
            finally:
                await runtime.close()

    asyncio.run(run())
