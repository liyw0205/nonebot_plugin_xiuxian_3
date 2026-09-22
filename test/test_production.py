from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime


def _context(user_id: str, request_id: str, *, operation_id: str = "") -> CommandContext:
    return CommandContext(
        adapter="web",
        user_id=user_id,
        request_id=request_id,
        operation_id=operation_id,
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
