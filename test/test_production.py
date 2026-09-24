from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.production.rules import random_quality_bp


def _context(user_id: str, request_id: str, *, operation_id: str = "") -> CommandContext:
    return CommandContext(
        adapter="web",
        user_id=user_id,
        request_id=request_id,
        operation_id=operation_id,
    )


def _adapter_context(adapter: str, user_id: str, request_id: str, operation_id: str = "") -> CommandContext:
    return CommandContext(
        adapter=adapter,
        user_id=user_id,
        request_id=request_id,
        operation_id=operation_id,
        can_write_assets=True,
    )


async def _enter_alchemy(runtime, user_id: str) -> None:
    commands = (
        "开始修仙",
        "寻仙问道",
        "完成引导 阅读",
        "前往近郊",
        "完成引导 采集",
        "完成引导 炼丹",
        "选择道途 辅修 炼丹",
    )
    for index, command in enumerate(commands):
        result = await runtime.dispatch(_context(user_id, f"setup-{index}"), command)
        assert result.ok, (command, result.code, result.message)


def _finish_order(runtime, order_id: str, *, hours_ago: int = 0) -> None:
    now = datetime.now(timezone.utc) - timedelta(hours=hours_ago, seconds=1)
    ends_at = now - timedelta(seconds=1)
    starts_at = now - timedelta(seconds=30)
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE production_orders SET starts_at = ?, ends_at = ? WHERE order_id = ?",
            (starts_at.isoformat(), ends_at.isoformat(), order_id),
        )


def test_production_preview_start_complete_and_replay() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            user = "production-success"
            await _enter_alchemy(runtime, user)

            preview = await runtime.dispatch(_context(user, "preview"), "生产预览 疗伤丹")
            assert preview.code == "RECIPE_PREVIEW"
            assert "止血草" in preview.message
            assert "item.herb" not in preview.message

            started = await runtime.dispatch(
                _context(user, "start", operation_id="production-start-1"),
                "开始生产 疗伤丹",
            )
            assert started.code == "PRODUCTION_STARTED"
            assert started.data["energy"] == 24
            replay_start = await runtime.dispatch(
                _context(user, "start-replay", operation_id="production-start-1"),
                "开始生产 低阶疗伤丹",
            )
            assert replay_start.data["idempotent_replay"] is True
            assert replay_start.data["order_id"] == started.data["order_id"]
            _finish_order(runtime, started.data["order_id"])

            completed = await runtime.dispatch(
                _context(user, "complete", operation_id="production-complete-1"),
                "领取生产",
            )
            assert completed.code == "PRODUCTION_COMPLETED"
            assert completed.data["success"] is True
            assert completed.data["outputs"] == {"item.pill.healing_low": 1}
            assert completed.data["tool_durability_bp"] == 1900
            replay = await runtime.dispatch(
                _context(user, "complete-replay", operation_id="production-complete-1"),
                "领取生产",
            )
            assert replay.data["idempotent_replay"] is True
            assert replay.data["outputs"] == completed.data["outputs"]
            await runtime.close()

    asyncio.run(run())


def test_production_failure_refunds_inputs_and_expired_recovery() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            user = "production-failure"
            await _enter_alchemy(runtime, user)
            started = await runtime.dispatch(
                _context(user, "start-fail", operation_id="fail-0"),
                "开始生产 疗伤丹",
            )
            assert started.code == "PRODUCTION_STARTED"
            _finish_order(runtime, started.data["order_id"])
            failed = await runtime.dispatch(_context(user, "finish-fail"), "领取生产")
            assert failed.code == "PRODUCTION_COMPLETED"
            assert failed.data["success"] is False
            assert failed.data["refunds"] == {"item.herb.blood_grass": 1}

            second = await runtime.dispatch(
                _context(user, "start-expired", operation_id="production-start-expired"),
                "开始生产 疗伤丹",
            )
            assert second.code == "PRODUCTION_STARTED"
            _finish_order(runtime, second.data["order_id"], hours_ago=25)
            expired = await runtime.dispatch(_context(user, "expired"), "领取生产")
            assert expired.code == "ORDER_EXPIRED"
            recovered = await runtime.dispatch(
                _context(user, "recover", operation_id="production-recover-1"),
                "恢复生产",
            )
            assert recovered.code == "PRODUCTION_RECOVERED"
            assert recovered.data["idempotent_replay"] is False
            replay = await runtime.dispatch(
                _context(user, "recover-replay", operation_id="production-recover-1"),
                "恢复生产",
            )
            assert replay.data["idempotent_replay"] is True
            await runtime.close()

    asyncio.run(run())


def test_v02_mist_barrier_production_uses_array_hall_permission_for_qq_and_onebot() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            for adapter, user in (("qq.official", "qq-mist-barrier"), ("onebot.v11", "ob-mist-barrier")):
                await runtime.adapters.dispatch(adapter, _adapter_context(adapter, user, f"create-{adapter}"), "开始修仙")
                await runtime.adapters.dispatch(adapter, _adapter_context(adapter, user, f"seek-{adapter}"), "寻仙问道")
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        """
                        UPDATE players SET stage='cultivator', realm_key='golden_core', realm_layer=1,
                            location_key='xuantian.array_hall', subprofession_key='formation',
                            energy=30, energy_max=30, spirit_stones=500, intro_json=?, inventory_json=?
                        WHERE platform=? AND platform_user_id=?
                        """,
                        (json.dumps({"flags": []}), json.dumps({
                            "item.mat.array_sand": 5,
                            "item.herb.spirit_leaf": 2,
                        }), adapter, user),
                    )

                denied = await runtime.adapters.dispatch(
                    adapter,
                    _adapter_context(adapter, user, f"preview-denied-{adapter}"),
                    "生产预览 迷雾屏障",
                )
                assert denied.code == "RECIPE_REQUIREMENT_MISSING"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE players SET intro_json=? WHERE platform=? AND platform_user_id=?",
                        (json.dumps({"flags": ["array_hall.invite"]}), adapter, user),
                    )

                preview = await runtime.adapters.dispatch(
                    adapter,
                    _adapter_context(adapter, user, f"preview-{adapter}"),
                    "生产预览 迷雾屏障",
                )
                assert preview.code == "RECIPE_PREVIEW"
                assert preview.data["recipe_key"] == "recipe.array.mist_barrier"
                assert preview.data["energy_cost"] == 12
                assert preview.data["currency_cost"] == 100
                assert "阵砂" in preview.message and "灵叶" in preview.message

                start_operation = next(
                    f"{adapter}-mist-start-{index}"
                    for index in range(256)
                    if random_quality_bp(f"{adapter}-mist-start-{index}") >= 1000
                )
                started = await runtime.adapters.dispatch(
                    adapter,
                    _adapter_context(adapter, user, f"start-{adapter}", start_operation),
                    "开始生产 迷雾屏障",
                )
                assert started.code == "PRODUCTION_STARTED"
                assert (started.data["energy"], started.data["spirit_stones"]) == (18, 400)
                replay_start = await runtime.adapters.dispatch(
                    adapter,
                    _adapter_context(adapter, user, f"start-replay-{adapter}", start_operation),
                    "开始生产 recipe.array.mist_barrier",
                )
                assert replay_start.data["idempotent_replay"] is True
                assert replay_start.data["order_id"] == started.data["order_id"]

                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE production_orders SET ends_at=? WHERE order_id=?",
                        ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(), started.data["order_id"]),
                    )
                settled = await runtime.adapters.dispatch(
                    adapter,
                    _adapter_context(adapter, user, f"settle-{adapter}", f"settle-{adapter}"),
                    "领取生产",
                )
                assert settled.code == "PRODUCTION_COMPLETED"
                assert settled.data["success"] is True
                assert settled.data["outputs"] == {"item.array.mist_barrier": 1}
                assert settled.data["refunds"] == {}
                replay_settlement = await runtime.adapters.dispatch(
                    adapter,
                    _adapter_context(adapter, user, f"settle-replay-{adapter}", f"settle-{adapter}"),
                    "领取生产",
                )
                assert replay_settlement.data["idempotent_replay"] is True
                assert replay_settlement.data["outputs"] == settled.data["outputs"]
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    inventory = json.loads(
                        connection.execute(
                            "SELECT inventory_json FROM players WHERE platform=? AND platform_user_id=?",
                            (adapter, user),
                        ).fetchone()[0]
                    )
                assert inventory["item.array.mist_barrier"] == 1

                failure_operation = next(
                    f"{adapter}-mist-failure-{index}"
                    for index in range(256)
                    if random_quality_bp(f"{adapter}-mist-failure-{index}") == 0
                )
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE players SET energy=30, spirit_stones=500, inventory_json=? "
                        "WHERE platform=? AND platform_user_id=?",
                        (json.dumps({
                            "item.mat.array_sand": 5,
                            "item.herb.spirit_leaf": 2,
                            "item.array.mist_barrier": 1,
                        }), adapter, user),
                    )
                failed_start = await runtime.adapters.dispatch(
                    adapter,
                    _adapter_context(adapter, user, f"failure-start-{adapter}", failure_operation),
                    "开始生产 迷雾屏障",
                )
                assert failed_start.code == "PRODUCTION_STARTED"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE production_orders SET ends_at=? WHERE order_id=?",
                        ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(), failed_start.data["order_id"]),
                    )
                failed = await runtime.adapters.dispatch(
                    adapter,
                    _adapter_context(adapter, user, f"failure-settle-{adapter}"),
                    "领取生产",
                )
                assert failed.code == "PRODUCTION_COMPLETED"
                assert failed.data["success"] is False
                assert failed.data["refunds"] == {
                    "item.mat.array_sand": 3,
                    "item.herb.spirit_leaf": 1,
                }
            await runtime.close()

    asyncio.run(run())
