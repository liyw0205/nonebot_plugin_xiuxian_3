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


async def _enter_cultivator(runtime, user_id: str) -> None:
    await runtime.dispatch(_context(user_id, "create"), "开始修仙")
    await runtime.dispatch(_context(user_id, "seek"), "寻仙问道")
    await runtime.dispatch(_context(user_id, "read"), "完成引导 阅读")
    await runtime.dispatch(_context(user_id, "travel"), "前往近郊")
    await runtime.dispatch(_context(user_id, "gather"), "完成引导 采集")
    await runtime.dispatch(_context(user_id, "service"), "完成引导 炼丹")
    result = await runtime.dispatch(_context(user_id, "path"), "选择道途 体修")
    assert result.code == "CULTIVATION_ENTERED"


def _finish_session(runtime, user_id: str) -> None:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE cultivation_sessions SET ends_at = ? WHERE player_id = (SELECT id FROM players WHERE platform_user_id = ?)",
            ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(), user_id),
        )


def test_cultivation_session_settlement_and_layer_advance() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            user = "progression-user"
            await _enter_cultivator(runtime, user)

            started = await runtime.dispatch(_context(user, "start"), "开始修炼")
            assert started.code == "CULTIVATION_STARTED"
            assert started.data["stamina"] == 24
            busy = await runtime.dispatch(_context(user, "busy"), "开始修炼")
            assert busy.code == "CULTIVATION_BUSY"
            not_ready = await runtime.dispatch(_context(user, "settle-early"), "结算修炼")
            assert not_ready.code == "CULTIVATION_NOT_READY"

            _finish_session(runtime, user)
            settled = await runtime.dispatch(
                _context(user, "settle", operation_id="settle-1"),
                "结算修炼",
            )
            assert settled.code == "CULTIVATION_SETTLED"
            assert settled.data["cultivation_gain"] >= 41
            replay = await runtime.dispatch(
                _context(user, "settle-replay", operation_id="settle-1"),
                "结算修炼",
            )
            assert replay.data["idempotent_replay"] is True
            assert replay.data["cultivation"] == settled.data["cultivation"]

            # The first gain is below the L2 threshold, so a second completed
            # session is needed before the explicit layer operation.
            started_again = await runtime.dispatch(_context(user, "start-2"), "开始修炼")
            assert started_again.code == "CULTIVATION_STARTED"
            _finish_session(runtime, user)
            second = await runtime.dispatch(_context(user, "settle-2"), "结算修炼")
            assert second.code == "CULTIVATION_SETTLED"
            advanced = await runtime.dispatch(_context(user, "advance"), "晋升境界")
            assert advanced.code == "REALM_LAYER_ADVANCED"
            assert advanced.data["realm_layer"] == 2

            profile = await runtime.dispatch(_context(user, "profile"), "我的状态")
            assert "境内修为" in profile.message
            assert "总修为" in profile.message
            assert "体修" in profile.message
            await runtime.close()

    asyncio.run(run())


def test_cultivation_cancel_and_resource_recovery_are_idempotent() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            user = "recovery-user"
            await _enter_cultivator(runtime, user)
            started = await runtime.dispatch(_context(user, "start"), "开始修炼")
            assert started.data["stamina"] == 24
            cancelled = await runtime.dispatch(
                _context(user, "cancel", operation_id="cancel-1"),
                "取消修炼",
            )
            assert cancelled.code == "CULTIVATION_CANCELLED"
            assert cancelled.data["stamina"] == 26
            replay = await runtime.dispatch(
                _context(user, "cancel-replay", operation_id="cancel-1"),
                "取消修炼",
            )
            assert replay.code == "CULTIVATION_CANCELLED"
            assert replay.data["idempotent_replay"] is True

            old = datetime.now(timezone.utc) - timedelta(minutes=65)
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE players SET stamina = 10, energy = 8, updated_at = ? WHERE platform_user_id = ?",
                    (old.isoformat(), user),
                )
            recovered = await runtime.dispatch(_context(user, "recover"), "恢复状态")
            assert recovered.code == "RESOURCES_RECOVERED"
            assert recovered.data["periods"] == 2
            assert recovered.data["stamina"] == 12
            assert recovered.data["energy"] == 10
            await runtime.close()

    asyncio.run(run())
