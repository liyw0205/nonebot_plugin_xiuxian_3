from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from combat_fixtures import BALANCED_QUALIFICATION

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.adventures.mainline import (
    CLOUD_CITY_ECHOES_STORY_KEY,
    mainline_definitions,
)
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle
from nonebot_plugin_xiuxian_3.xiuxian.exploration.rules import (
    battle_roll_bp,
    exploration_encounter_selection,
)
from nonebot_plugin_xiuxian_3.xiuxian.specials.dispatch_rules import (
    DISPATCHES,
    choose_outcome,
)


DATA = Path(__file__).parents[1] / "data"
ADAPTERS = ("qq.official", "onebot.v11")
LOCATION = "xuantian.cloud_city"
ROUTE = "idle.cloud_city_shop"
DISPATCH = "dispatch.golden_core.vein_survey"
PATROL = "explore.cloud_city_patrol"
BATTLE_BP = 3_500


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


def _dispatch_seed(salt: str) -> str:
    definition = DISPATCHES[DISPATCH]
    return next(
        seed
        for index in range(10_000)
        if (seed := f"cloud-city-shop-{salt}-{index}")
        and choose_outcome(definition, seed) == "success"
    )


def _dispatch_uuid(seed: str):
    return patch(
        "nonebot_plugin_xiuxian_3.xiuxian.specials.dispatch_repository.uuid4",
        side_effect=[SimpleNamespace(hex=seed), SimpleNamespace(hex=f"assignment-{seed}")],
    )


def _patrol_operation(adapter: str, user: str) -> str:
    for index in range(10_000):
        operation = f"patrol-{index}"
        seed = f"{adapter}:{user}:{operation}"
        enemy, _ = exploration_encounter_selection(
            PATROL, seed=seed, realm_key="golden_core", realm_layer=1
        )
        if enemy == "enemy.bandit_apprentice" and battle_roll_bp(f"{seed}:battle") < BATTLE_BP:
            return operation
    raise AssertionError("could not find a deterministic patrol battle seed")


def _prepare_player(runtime, adapter: str, user: str, clock: Clock) -> int:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        row = connection.execute(
            "SELECT id FROM players WHERE platform=? AND platform_user_id=?",
            (adapter, user),
        ).fetchone()
        assert row is not None
        player_id = int(row[0])
        connection.execute(
            "UPDATE players SET stage='cultivator', realm_key='golden_core', realm_layer=1, "
            "location_key='xuantian.new_town', stamina=200, stamina_max=200, energy=100, "
            "energy_max=100, spirit_stones=5000, max_hp=100000, initiative=100000, "
            "qualification_json=? WHERE id=?",
            (json.dumps(BALANCED_QUALIFICATION), player_id),
        )
        connection.execute(
            "INSERT INTO player_reputations(player_id, local_json, service_reputation, updated_at) "
            "VALUES (?, ?, 0, ?) ON CONFLICT(player_id) DO UPDATE SET local_json=excluded.local_json",
            (player_id, json.dumps({"local.xuantian.cloud_city": 195}), clock().isoformat()),
        )
        return player_id


def _local_reputation(runtime, player_id: int) -> int:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        row = connection.execute(
            "SELECT local_json FROM player_reputations WHERE player_id=?", (player_id,)
        ).fetchone()
    return int(json.loads(row[0])["local.xuantian.cloud_city"])


def test_shop_route_contract_points_to_a_live_source_and_requires_city_presence() -> None:
    bundle = ContentBundle.load(DATA)
    route = bundle.require("livelihood", ROUTE, include_locked=False)
    assert route["requirements"]["location_key"] == LOCATION
    assert route["requirements"]["local_reputation"]["local.xuantian.cloud_city"] == 200

    dispatch = bundle.require("livelihood", DISPATCH, include_locked=False)
    assert dispatch["rewards"]["success"]["local.xuantian.cloud_city"] == 5
    assert dispatch["rewards"]["partial"]["local.xuantian.cloud_city"] == 2

    stages = {
        stage.key: stage
        for stage in mainline_definitions(bundle, story_key=CLOUD_CITY_ECHOES_STORY_KEY)
    }
    handoff = stages["cloud_city_echoes.3"]
    assert handoff.objectives[0]["route_key"] == ROUTE
    assert any(action["command"] == "挂机预览" and action["argument"] == "云城店铺" for action in handoff.actions)
    assert any(action["command"] == "接受派遣" and action["argument"] == "云铁矿区勘测" for action in handoff.actions)


def test_public_city_source_unlocks_shop_story_after_restart_and_qq_gate() -> None:
    async def run() -> None:
        clock = Clock(datetime(2026, 11, 13, 8, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            for adapter in ADAPTERS:
                user = f"city-shop-location-{adapter}"
                runtime = create_runtime(data_dir=data_dir, clock=clock, adapters=ADAPTERS)

                async def send(operation: str, command: str):
                    return await runtime.adapters.dispatch(
                        adapter, _context(adapter, user, operation), command
                    )

                try:
                    assert (await send("create", "开始修仙")).ok
                    assert (await send("seek", "寻仙问道")).ok
                    player_id = _prepare_player(runtime, adapter, user, clock)

                    help_result = await send("help-life", "修仙帮助 生活")
                    assert "身在云城" in help_result.message
                    assert "名望达到 200" in help_result.message
                    assert "云铁矿区勘测" in help_result.message

                    status = await send("story-status", "云城店铺回响主线")
                    assert status.code == "MAINLINE_STATUS", status.message
                    assert "云城听更" in status.message

                    blocked = await send("shop-before-travel", "挂机预览 云城店铺")
                    shop = next(item for item in blocked.data["routes"] if item["route_key"] == ROUTE)
                    assert shop["ready"] is False
                    assert any("所在地点不符" in value for value in shop["missing"])
                    blocked_start = await send("shop-start-before-travel", "开始挂机 云城店铺")
                    assert blocked_start.code == "IDLE_REQUIREMENT_MISSING", blocked_start.message

                    story_start = await send("story-start", "开始云城店铺回响主线 云城听更")
                    assert story_start.code == "MAINLINE_STARTED", story_start.message
                    early_story_claim = await send(
                        "story-early-claim", "领取云城店铺回响主线奖励 云城听更"
                    )
                    assert early_story_claim.code == "MAINLINE_OBJECTIVES_INCOMPLETE"

                    travel = await send("travel-start", "前往 云城")
                    assert travel.code == "TRAVEL_STARTED", travel.message
                    clock.advance(minutes=3)
                    arrived = await send("travel-settle", "结算移动")
                    assert arrived.code == "TRAVEL_COMPLETED", arrived.message
                    stage1 = await send(
                        "story-claim-arrival", "领取云城店铺回响主线奖励 云城听更"
                    )
                    assert stage1.code == "MAINLINE_REWARD_CLAIMED", stage1.message
                    assert _local_reputation(runtime, player_id) == 198

                    stage2_start = await send(
                        "story-start-patrol", "开始云城店铺回响主线 巡夜见锋"
                    )
                    assert stage2_start.code == "MAINLINE_STARTED", stage2_start.message
                    patrol = await send(
                        _patrol_operation(adapter, user), "开始探索 云城巡夜"
                    )
                    assert patrol.code == "EXPLORATION_STARTED", patrol.message
                    clock.advance(seconds=200)
                    patrol_settled = await send("patrol-settle", "结算探索")
                    assert patrol_settled.code == "EXPLORATION_SETTLED", patrol_settled.message
                    assert patrol_settled.data["battle_outcome"] == "won"
                    stage2 = await send(
                        "story-claim-patrol", "领取云城店铺回响主线奖励 巡夜见锋"
                    )
                    assert stage2.code == "MAINLINE_REWARD_CLAIMED", stage2.message
                    stage3_start = await send(
                        "story-start-handoff", "开始云城店铺回响主线 店铺交班"
                    )
                    assert stage3_start.code == "MAINLINE_STARTED", stage3_start.message

                    still_blocked = await send("shop-before-source", "挂机预览 云城店铺")
                    shop = next(item for item in still_blocked.data["routes"] if item["route_key"] == ROUTE)
                    assert any("地方名望不足（需要 200）" in value for value in shop["missing"])

                    seed = _dispatch_seed(adapter)
                    with _dispatch_uuid(seed):
                        accepted = await send("survey-accept", "接受派遣 云铁矿区勘测")
                    assert accepted.code == "DISPATCH_ACCEPTED", accepted.message
                    assert _local_reputation(runtime, player_id) == 198
                    clock.value = datetime.fromisoformat(accepted.data["ends_at"])
                    survey = await send("survey-settle", "结算派遣")
                    assert survey.code == "DISPATCH_SETTLED", survey.message
                    assert survey.data["outcome"] == "success"
                    assert survey.data["reward"]["local.xuantian.cloud_city"] == 5
                    assert _local_reputation(runtime, player_id) == 203

                    ready = await send("shop-ready", "挂机预览 云城店铺")
                    shop = next(item for item in ready.data["routes"] if item["route_key"] == ROUTE)
                    assert shop["ready"] is True, shop["missing"]

                    started = await send("shop-start", "开始挂机 云城店铺")
                    assert started.code == "IDLE_STARTED", started.message
                    with sqlite3.connect(runtime.settings.database_path) as connection:
                        snapshot_row = connection.execute(
                            "SELECT status, snapshot_json FROM idle_assignments WHERE assignment_id=?",
                            (started.data["assignment_id"],),
                        ).fetchone()
                    assert snapshot_row is not None and snapshot_row[0] == "running"
                    snapshot = json.loads(snapshot_row[1])
                    assert snapshot["location_key"] == LOCATION
                    assert snapshot["route_key"] == ROUTE
                    await runtime.close()

                    runtime = create_runtime(data_dir=data_dir, clock=clock, adapters=ADAPTERS)
                    restored = await runtime.adapters.dispatch(
                        adapter, _context(adapter, user, "shop-status-restored"), "挂机状态"
                    )
                    assert restored.code == "IDLE_STATUS", restored.message
                    assert restored.data["assignment"]["assignment_id"] == started.data["assignment_id"]
                    clock.advance(hours=8)

                    claimed = await runtime.adapters.dispatch(
                        adapter, _context(adapter, user, "shop-claim"), "领取挂机"
                    )
                    assert claimed.code == "IDLE_CLAIMED", claimed.message
                    assert claimed.data["fallback"] is False
                    assert claimed.data["reward"]["local.xuantian.cloud_city"] == 2
                    assert "云城店铺" in claimed.message and "所得" in claimed.message
                    reputation_after = _local_reputation(runtime, player_id)
                    assert reputation_after == 205

                    replay = await runtime.adapters.dispatch(
                        adapter, _context(adapter, user, "shop-claim"), "领取挂机"
                    )
                    assert replay.code == "IDLE_CLAIMED"
                    assert replay.data["idempotent_replay"] is True
                    assert replay.data["reward"] == claimed.data["reward"]
                    assert _local_reputation(runtime, player_id) == reputation_after
                    story_claim = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, user, "story-complete"),
                        "领取云城店铺回响主线奖励 店铺交班",
                    )
                    assert story_claim.code == "MAINLINE_REWARD_CLAIMED", story_claim.message
                    assert story_claim.data["next_stage_key"] is None
                finally:
                    await runtime.close()

    asyncio.run(run())
