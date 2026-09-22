from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.exploration.rules import battle_roll_bp


def _context(user_id: str, request_id: str, *, operation_id: str = "") -> CommandContext:
    return CommandContext(
        adapter="web",
        user_id=user_id,
        request_id=request_id,
        operation_id=operation_id,
    )


async def _enter_cultivator(runtime, user_id: str) -> None:
    await runtime.dispatch(_context(user_id, "create"), "开始修仙")
    await runtime.dispatch(_context(user_id, "seek"), "寻仙问道")
    await runtime.dispatch(_context(user_id, "read"), "完成引导 阅读")
    await runtime.dispatch(_context(user_id, "travel"), "前往近郊")
    await runtime.dispatch(_context(user_id, "gather"), "完成引导 采集")
    await runtime.dispatch(_context(user_id, "service"), "完成引导 炼丹")
    result = await runtime.dispatch(_context(user_id, "path"), "选择道途 体修")
    assert result.code == "CULTIVATION_ENTERED"


def _expire_exploration(runtime, user_id: str, exploration_id: str) -> None:
    old = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE exploration_sessions SET ends_at = ? WHERE exploration_id = ? AND player_id = (SELECT id FROM players WHERE platform_user_id = ?)",
            (old, exploration_id, user_id),
        )


def _set_player(runtime, user_id: str, **values: object) -> None:
    if not values:
        return
    assignments = ", ".join(f"{key} = ?" for key in values)
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            f"UPDATE players SET {assignments} WHERE platform_user_id = ?",
            (*values.values(), user_id),
        )


def test_exploration_modes_settle_rewards_and_replay_once() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            user = "exploration-rewards"
            await _enter_cultivator(runtime, user)

            gather_operation = next(
                f"gather-start-{index}"
                for index in range(1000)
                if battle_roll_bp(f"gather-start-{index}:battle") >= 1000
            )
            gather = await runtime.dispatch(
                _context(user, "gather-start", operation_id=gather_operation),
                "开始探索 近郊采集",
            )
            assert gather.code == "EXPLORATION_STARTED"
            assert "xuantian.outskirts" not in gather.message
            assert "玄天界·近郊" in gather.message
            _expire_exploration(runtime, user, gather.data["exploration_id"])
            settled = await runtime.dispatch(
                _context(user, "gather-settle", operation_id="gather-settle"),
                "结算探索",
            )
            assert settled.code == "EXPLORATION_SETTLED"
            assert settled.data["result"]["item.herb.blood_grass"] >= 1
            replay = await runtime.dispatch(
                _context(user, "gather-replay", operation_id="gather-settle"),
                "结算探索",
            )
            assert replay.data["idempotent_replay"] is True
            assert replay.data["result"] == settled.data["result"]

            _set_player(runtime, user, realm_layer=2, stamina=30)
            trial = await runtime.dispatch(_context(user, "trial-start"), "开始探索 短历练")
            assert trial.code == "EXPLORATION_STARTED"
            _expire_exploration(runtime, user, trial.data["exploration_id"])
            trial_result = await runtime.dispatch(_context(user, "trial-settle"), "结算探索")
            assert trial_result.code == "EXPLORATION_SETTLED"
            assert 40 <= trial_result.data["result"]["cultivation"] <= 80
            assert 10 <= trial_result.data["result"]["spirit_stones"] <= 30

            _set_player(runtime, user, location_key="xuantian.spirit_field", stamina=30)
            spring = await runtime.dispatch(_context(user, "spring-start"), "开始探索 灵泉采集")
            assert spring.code == "EXPLORATION_STARTED"
            _expire_exploration(runtime, user, spring.data["exploration_id"])
            spring_result = await runtime.dispatch(_context(user, "spring-settle"), "结算探索")
            assert spring_result.code == "EXPLORATION_SETTLED"
            assert spring_result.data["result"]["item.herb.spirit_leaf"] >= 1

            _set_player(
                runtime,
                user,
                realm_key="qi_gathering",
                realm_layer=4,
                location_key="cave.mist_grotto",
                stamina=30,
                inventory_json=json.dumps({"item.cave_pass_basic": 1}),
            )
            mist_operation = next(
                f"mist-start-{index}"
                for index in range(1000)
                if battle_roll_bp(f"mist-start-{index}:battle") >= 2500
            )
            mist = await runtime.dispatch(
                _context(user, "mist-start", operation_id=mist_operation),
                "开始探索 雾隐洞天探索",
            )
            assert mist.code == "EXPLORATION_STARTED"
            _expire_exploration(runtime, user, mist.data["exploration_id"])
            mist_result = await runtime.dispatch(_context(user, "mist-settle"), "结算探索")
            assert mist_result.code == "EXPLORATION_SETTLED"
            assert 300 <= mist_result.data["result"]["cultivation"] <= 500
            assert any(key.startswith("item.") for key in mist_result.data["result"])
            await runtime.close()

    asyncio.run(run())


def test_exploration_ready_cancel_quota_and_resource_guards() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            user = "exploration-guards"
            await _enter_cultivator(runtime, user)
            started = await runtime.dispatch(_context(user, "start"), "开始探索 近郊采集")
            assert started.code == "EXPLORATION_STARTED"
            early = await runtime.dispatch(_context(user, "early"), "结算探索")
            assert early.code == "EXPLORATION_NOT_READY"
            cancelled = await runtime.dispatch(
                _context(user, "cancel", operation_id="cancel-exploration"),
                "取消探索",
            )
            assert cancelled.code == "EXPLORATION_CANCELLED"
            assert cancelled.data["stamina_refund"] == 3
            replay = await runtime.dispatch(
                _context(user, "cancel-replay", operation_id="cancel-exploration"),
                "取消探索",
            )
            assert replay.data["idempotent_replay"] is True
            conflict = await runtime.dispatch(
                _context(user, "start-conflict", operation_id="cancel-exploration"),
                "开始探索 近郊采集",
            )
            assert conflict.code == "OPERATION_CONFLICT"

            _set_player(runtime, user, stamina=0)
            before = await runtime.dispatch(_context(user, "before"), "我的状态")
            insufficient = await runtime.dispatch(_context(user, "insufficient"), "开始探索 近郊采集")
            after = await runtime.dispatch(_context(user, "after"), "我的状态")
            assert insufficient.code == "RESOURCE_INSUFFICIENT"
            assert after.data["stamina"] == before.data["stamina"] == 0

            _set_player(runtime, user, stamina=30)
            # The cancelled start still consumes today's start quota.
            for index in range(11):
                quota_operation = next(
                    f"quota-start-{index}-{candidate}"
                    for candidate in range(1000)
                    if battle_roll_bp(f"quota-start-{index}-{candidate}:battle") >= 1000
                )
                started = await runtime.dispatch(
                    _context(user, f"quota-start-{index}", operation_id=quota_operation),
                    "开始探索 近郊采集",
                )
                assert started.code == "EXPLORATION_STARTED"
                _expire_exploration(runtime, user, started.data["exploration_id"])
                settled = await runtime.dispatch(_context(user, f"quota-settle-{index}"), "结算探索")
                assert settled.code == "EXPLORATION_SETTLED"
                _set_player(runtime, user, stamina=30)
            limited = await runtime.dispatch(_context(user, "quota-limit"), "开始探索 近郊采集")
            assert limited.code == "EXPLORATION_QUOTA_EXHAUSTED"
            await runtime.close()

    asyncio.run(run())


def test_exploration_conflicts_and_combat_pending_are_stable() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            user = "exploration-conflicts"
            await _enter_cultivator(runtime, user)
            started = await runtime.dispatch(_context(user, "start"), "开始探索 近郊采集")
            assert started.code == "EXPLORATION_STARTED"
            assert (await runtime.dispatch(_context(user, "cultivate"), "开始修炼")).code == "CULTIVATION_BUSY"
            _set_player(runtime, user, realm_layer=2)
            assert (await runtime.dispatch(_context(user, "travel-conflict"), "前往 灵泉谷")).code == "TRAVEL_BUSY"
            assert (await runtime.dispatch(_context(user, "production"), "开始生产 炼丹")).code == "PRODUCTION_BUSY"

            _set_player(runtime, user, stamina=30, realm_key="qi_sensing", realm_layer=2, location_key="xuantian.outskirts")
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE exploration_sessions SET status = 'settled', result_json = ? WHERE exploration_id = ?",
                    (json.dumps({"status": "settled", "result": {}}), started.data["exploration_id"]),
                )
            battle_operation = next(
                f"battle-start-{index}"
                for index in range(1000)
                if battle_roll_bp(f"battle-start-{index}:battle") < 1000
            )
            battle = await runtime.dispatch(
                _context(user, "battle-start", operation_id=battle_operation),
                "开始探索 近郊采集",
            )
            assert battle.code == "EXPLORATION_STARTED"
            _expire_exploration(runtime, user, battle.data["exploration_id"])
            pending = await runtime.dispatch(_context(user, "battle-settle"), "结算探索")
            assert pending.code == "EXPLORATION_COMBAT_PENDING"
            pending_again = await runtime.dispatch(_context(user, "battle-settle-again"), "结算探索")
            assert pending_again.code == "EXPLORATION_COMBAT_PENDING"
            assert pending_again.data["idempotent_replay"] is False
            replay = await runtime.dispatch(
                _context(user, "battle-replay", operation_id=pending.operation_id or ""),
                "结算探索",
            )
            assert replay.code == "EXPLORATION_COMBAT_PENDING"
            assert replay.data["idempotent_replay"] is True
            await runtime.close()

    asyncio.run(run())
