from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.exploration.rules import cloud_boat_storm_roll_bp


def _context(adapter: str, user: str, request_id: str, operation_id: str = "") -> CommandContext:
    return CommandContext(adapter=adapter, user_id=user, request_id=request_id, operation_id=operation_id)


def _set_player(runtime, adapter: str, user: str, **values: object) -> None:
    assignments = ", ".join(f"{key} = ?" for key in values)
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            f"UPDATE players SET {assignments} WHERE platform = ? AND platform_user_id = ?",
            (*values.values(), adapter, user),
        )


def _expire(runtime, exploration_id: str) -> None:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE exploration_sessions SET ends_at = ? WHERE exploration_id = ?",
            ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(), exploration_id),
        )


def _storm_operation(prefix: str) -> str:
    return next(
        f"{prefix}-{index}"
        for index in range(1000)
        if cloud_boat_storm_roll_bp(f"{prefix}-{index}") < 2500
    )


def _clear_operation(prefix: str) -> str:
    return next(
        f"{prefix}-{index}"
        for index in range(1000)
        if cloud_boat_storm_roll_bp(f"{prefix}-{index}") >= 2500
    )


def test_cloud_boat_trial_pay_and_clear_are_idempotent_for_qq_and_onebot() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            cases = (
                ("qq.official", "cloud-trial-qq", _storm_operation("qq-trial"), "支付"),
                ("onebot.v11", "cloud-trial-ob", _clear_operation("ob-trial"), "clear"),
            )
            for adapter, user, operation, mode in cases:
                created = await runtime.adapters.dispatch(adapter, _context(adapter, user, "create"), "开始修仙")
                assert created.code == "PLAYER_CREATED"
                _set_player(
                    runtime,
                    adapter,
                    user,
                    stage="cultivator",
                    realm_key="golden_core",
                    realm_layer=1,
                    location_key="xuantian.floating_boat",
                    stamina=30,
                    stamina_max=30,
                    spirit_stones=300,
                    inventory_json=json.dumps({}),
                )
                started = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "start", operation),
                    "开始探索 云舟试炼",
                )
                assert started.code == "EXPLORATION_STARTED"
                assert started.data["mode_key"] == "explore.cloud_boat_trial"
                assert started.data["stamina_cost"] == 12
                _expire(runtime, started.data["exploration_id"])
                settle_operation = f"{adapter}:settle"
                settled = await runtime.adapters.dispatch(adapter, _context(adapter, user, "settle", settle_operation), "结算探索")
                if mode == "支付":
                    assert settled.code == "EXPLORATION_STORM_PENDING"
                    chosen = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, user, "storm", operation_id=f"{adapter}:storm-pay"),
                        "选择云舟风暴 支付",
                    )
                    assert chosen.code == "EXPLORATION_STORM_SETTLED"
                    assert chosen.data["result"]["cultivation"] >= 800
                    replay = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, user, "storm-replay", operation_id=f"{adapter}:storm-pay"),
                        "选择云舟风暴 支付",
                    )
                    assert replay.data["idempotent_replay"] is True
                    with sqlite3.connect(runtime.settings.database_path) as connection:
                        state = connection.execute(
                            "SELECT stamina, spirit_stones, cultivation FROM players WHERE platform = ? AND platform_user_id = ?",
                            (adapter, user),
                        ).fetchone()
                    assert state[0:2] == (18, 200)
                else:
                    assert settled.code == "EXPLORATION_SETTLED"
                    assert 600 <= settled.data["result"]["cultivation"] <= 900
                    assert 1 <= settled.data["result"]["item.ticket.cloud_boat_fragment"] <= 2
                    replay = await runtime.adapters.dispatch(
                        adapter,
                            _context(adapter, user, "settle-replay", operation_id=settle_operation),
                        "结算探索",
                    )
                    assert replay.data["idempotent_replay"] is True
            await runtime.close()

    asyncio.run(run())


def test_cloud_boat_trial_wait_timeout_and_turn_back_paths() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            adapter = "onebot.v11"
            for index, choice in enumerate(("等待", "返航")):
                user = f"cloud-trial-choice-{index}"
                await runtime.adapters.dispatch(adapter, _context(adapter, user, "create"), "开始修仙")
                _set_player(
                    runtime,
                    adapter,
                    user,
                    stage="cultivator",
                    realm_key="golden_core",
                    realm_layer=1,
                    location_key="xuantian.floating_boat",
                    stamina=30,
                    stamina_max=30,
                    spirit_stones=300,
                    inventory_json=json.dumps({}),
                )
                operation = _storm_operation(f"choice-{index}")
                started = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "start", operation),
                    "开始探索 云舟试炼",
                )
                _expire(runtime, started.data["exploration_id"])
                pending = await runtime.adapters.dispatch(adapter, _context(adapter, user, "settle"), "结算探索")
                assert pending.code == "EXPLORATION_STORM_PENDING"
                if choice == "等待":
                    waited = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, user, "wait", operation_id=f"wait-{index}"),
                        "选择云舟风暴 等待",
                    )
                    assert waited.code == "EXPLORATION_STORM_WAITING"
                    with sqlite3.connect(runtime.settings.database_path) as connection:
                        connection.execute(
                            "UPDATE exploration_sessions SET ends_at = ? WHERE exploration_id = ?",
                            ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(), started.data["exploration_id"]),
                        )
                    settled = await runtime.adapters.dispatch(adapter, _context(adapter, user, "settle-after-wait"), "结算探索")
                    assert settled.code == "EXPLORATION_SETTLED"
                    assert settled.data["result"]["item.ticket.cloud_boat_fragment"] >= 1
                else:
                    returned = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, user, "turn-back", operation_id=f"turn-back-{index}"),
                        "选择云舟风暴 返航",
                    )
                    assert returned.code == "EXPLORATION_STORM_SETTLED"
                    assert returned.data["result"] == {"stamina_refund": 6}
                    with sqlite3.connect(runtime.settings.database_path) as connection:
                        state = connection.execute(
                            "SELECT stamina, spirit_stones, cultivation, inventory_json FROM players WHERE platform = ? AND platform_user_id = ?",
                            (adapter, user),
                        ).fetchone()
                    assert state[0:3] == (24, 300, 0)
                    assert json.loads(state[3]) == {}
            await runtime.close()

    asyncio.run(run())
