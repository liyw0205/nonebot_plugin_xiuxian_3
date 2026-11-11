from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory

from combat_fixtures import BALANCED_QUALIFICATION
from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.exploration.rules import (
    battle_roll_bp,
    exploration_encounter_selection,
)


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


def _prepare_player(runtime, adapter: str, user: str) -> None:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        row = connection.execute(
            "SELECT id, inventory_json FROM players WHERE platform=? AND platform_user_id=?",
            (adapter, user),
        ).fetchone()
        inventory = json.loads(row[1] or "{}")
        inventory["item.permit.cloud_mine"] = 1
        connection.execute(
            "UPDATE players SET stage='cultivator', realm_key='foundation', realm_layer=4, "
            "location_key='xuantian.cloud_city', stamina=100, stamina_max=100, energy=40, energy_max=40, "
            "qualification_json=?, inventory_json=? WHERE id=?",
            (json.dumps(BALANCED_QUALIFICATION, sort_keys=True), json.dumps(inventory, ensure_ascii=False, sort_keys=True), row[0]),
        )


def _safe_mining_operation(adapter: str, user: str) -> str:
    for index in range(10_000):
        operation = f"mine-{index}"
        enemy, _ = exploration_encounter_selection(
            "explore.cloud_mine",
            seed=f"{adapter}:{user}:{operation}",
            realm_key="foundation",
            realm_layer=4,
        )
        if enemy is None or battle_roll_bp(f"{adapter}:{user}:{operation}:battle") >= 3_000:
            return operation
    raise AssertionError("could not find a deterministic non-battle mining operation")


def test_cloud_mine_echoes_consumes_real_arrival_exploration_and_full_idle_on_both_adapters() -> None:
    async def run() -> None:
        clock = Clock(datetime(2026, 11, 12, 8, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock, adapters=ADAPTERS)
            try:
                for adapter in ADAPTERS:
                    user = f"cloud-mine-{adapter}"
                    dispatch = lambda operation, command: runtime.adapters.dispatch(
                        adapter, _context(adapter, user, operation), command
                    )
                    assert (await dispatch("create", "开始修仙")).code == "PLAYER_CREATED"
                    _prepare_player(runtime, adapter, user)

                    started = await dispatch("stage1-start", "开始云铁守望回响主线 矿口听风")
                    assert started.code == "MAINLINE_STARTED", started.message
                    early = await dispatch("stage1-early", "领取云铁守望回响主线奖励 矿口听风")
                    assert early.code == "MAINLINE_OBJECTIVES_INCOMPLETE"

                    travel = await dispatch("travel-start", "前往 云铁矿区")
                    assert travel.code == "TRAVEL_STARTED", travel.message
                    clock.advance(minutes=3)
                    assert (await dispatch("travel-settle", "结算移动")).code == "TRAVEL_COMPLETED"
                    clear_one = await dispatch("stage1-claim", "领取云铁守望回响主线奖励 矿口听风")
                    assert clear_one.code == "MAINLINE_REWARD_CLAIMED", clear_one.message

                    started_two = await dispatch("stage2-start", "开始云铁守望回响主线 云铁试掘")
                    assert started_two.code == "MAINLINE_STARTED", started_two.message
                    assert (await dispatch("stage2-early", "领取云铁守望回响主线奖励 云铁试掘")).code == "MAINLINE_OBJECTIVES_INCOMPLETE"
                    mining_operation = _safe_mining_operation(adapter, user)
                    mining = await dispatch(mining_operation, "开始探索 云铁矿区采集")
                    assert mining.code == "EXPLORATION_STARTED", mining.message
                    clock.advance(minutes=3)
                    settled = await dispatch("mine-settle", "结算探索")
                    assert settled.code == "EXPLORATION_SETTLED", settled.message
                    assert settled.data["result"].get("item.material.cloud_iron", 0) >= 1
                    clear_two = await dispatch("stage2-claim", "领取云铁守望回响主线奖励 云铁试掘")
                    assert clear_two.code == "MAINLINE_REWARD_CLAIMED", clear_two.message

                    started_three = await dispatch("stage3-start", "开始云铁守望回响主线 长夜守脉")
                    assert started_three.code == "MAINLINE_STARTED", started_three.message
                    fallback_start = await dispatch("idle-fallback-start", "开始挂机 矿区看守")
                    assert fallback_start.code == "IDLE_STARTED", fallback_start.message
                    clock.advance(hours=48)
                    fallback = await dispatch("idle-fallback-claim", "领取挂机")
                    assert fallback.code == "IDLE_CLAIMED", fallback.message
                    assert fallback.data["fallback"] is True
                    assert (await dispatch("stage3-after-fallback", "领取云铁守望回响主线奖励 长夜守脉")).code == "MAINLINE_OBJECTIVES_INCOMPLETE"

                    clock.advance(days=1)
                    full_start = await dispatch("idle-full-start", "开始挂机 矿区看守")
                    assert full_start.code == "IDLE_STARTED", full_start.message
                    clock.advance(hours=6)
                    full = await dispatch("idle-full-claim", "领取挂机")
                    assert full.code == "IDLE_CLAIMED", full.message
                    assert full.data["fallback"] is False
                    done = await dispatch("stage3-claim", "领取云铁守望回响主线奖励 长夜守脉")
                    assert done.code == "MAINLINE_REWARD_CLAIMED", done.message
                    replay = await dispatch("stage3-claim", "领取云铁守望回响主线奖励 长夜守脉")
                    assert replay.code == "MAINLINE_REWARD_CLAIMED"
                    assert replay.data["idempotent_replay"] is True

                    with sqlite3.connect(runtime.settings.database_path) as connection:
                        rows = connection.execute(
                            "SELECT event_key FROM activity_events WHERE player_id=(SELECT id FROM players WHERE platform=? AND platform_user_id=?)",
                            (adapter, user),
                        ).fetchall()
                    assert {row[0] for row in rows} >= {
                        "story.mainline.cloud_mine_echoes:cloud_mine_echoes.1",
                        "story.mainline.cloud_mine_echoes:cloud_mine_echoes.2",
                        "story.mainline.cloud_mine_echoes:cloud_mine_echoes.3",
                    }
            finally:
                await runtime.close()

    asyncio.run(run())


def test_cloud_mine_echoes_does_not_count_a_battle_failure_fallback() -> None:
    async def run() -> None:
        clock = Clock(datetime(2026, 11, 13, 8, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock, adapters=("onebot.v11",))
            try:
                adapter, user = "onebot.v11", "cloud-mine-loss"
                dispatch = lambda operation, command: runtime.adapters.dispatch(
                    adapter, _context(adapter, user, operation), command
                )
                assert (await dispatch("create", "开始修仙")).code == "PLAYER_CREATED"
                _prepare_player(runtime, adapter, user)
                assert (await dispatch("stage1-start", "开始云铁守望回响主线 矿口听风")).ok
                assert (await dispatch("travel-start", "前往 云铁矿区")).code == "TRAVEL_STARTED"
                clock.advance(minutes=3)
                assert (await dispatch("travel-settle", "结算移动")).code == "TRAVEL_COMPLETED"
                assert (await dispatch("stage1-claim", "领取云铁守望回响主线奖励 矿口听风")).ok
                assert (await dispatch("stage2-start", "开始云铁守望回响主线 云铁试掘")).ok

                loss_operation = next(
                    f"loss-{index}"
                    for index in range(10_000)
                    if battle_roll_bp(f"{adapter}:{user}:loss-{index}:battle") < 3_000
                )
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE players SET max_hp=0, initiative=0 WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    )
                started = await dispatch(loss_operation, "开始探索 云铁矿区采集")
                assert started.code == "EXPLORATION_STARTED", started.message
                clock.advance(minutes=3)
                settled = await dispatch("loss-settle", "结算探索")
                assert settled.code == "EXPLORATION_SETTLED", settled.message
                assert settled.data["battle_outcome"] == "lost"
                assert settled.data["result"].get("item.material.cloud_iron", 0) == 1
                rejected = await dispatch("stage2-claim", "领取云铁守望回响主线奖励 云铁试掘")
                assert rejected.code == "MAINLINE_OBJECTIVES_INCOMPLETE"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    status = connection.execute(
                        "SELECT status FROM mainline_runs WHERE player_id=(SELECT id FROM players WHERE platform=? AND platform_user_id=?) AND stage_key='cloud_mine_echoes.2'",
                        (adapter, user),
                    ).fetchone()[0]
                assert status == "running"
            finally:
                await runtime.close()

    asyncio.run(run())


def test_cloud_mine_echoes_status_and_help_are_registered() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, adapters=ADAPTERS)
            try:
                for adapter in ADAPTERS:
                    user = f"cloud-mine-help-{adapter}"
                    status = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, user, "status"),
                        "云铁守望回响主线",
                    )
                    assert status.code == "PLAYER_NOT_FOUND"
                    created = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, user, "create"),
                        "开始修仙",
                    )
                    assert created.code == "PLAYER_CREATED"
                    _prepare_player(runtime, adapter, user)
                    status = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, user, "status-ready"),
                        "云铁守望回响主线",
                    )
                    assert status.code == "MAINLINE_STATUS"
                    assert "矿口听风" in status.message
                    help_result = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, user, "help"),
                        "修仙帮助 生活",
                    )
                    assert help_result.code == "HELP_CATEGORY"
                    assert "云铁守望回响主线" in help_result.message
            finally:
                await runtime.close()

    asyncio.run(run())
