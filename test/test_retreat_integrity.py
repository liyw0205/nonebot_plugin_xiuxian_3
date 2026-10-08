from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime


ADAPTERS = ("qq.official", "onebot.v11")


def _context(adapter: str, user: str, request: str, operation: str = "") -> CommandContext:
    return CommandContext(
        adapter=adapter,
        user_id=user,
        request_id=request,
        operation_id=operation,
    )


async def _dispatch(runtime, adapter: str, user: str, request: str, command: str, operation: str = ""):
    return await runtime.adapters.dispatch(
        adapter,
        _context(adapter, user, request, operation),
        command,
    )


async def _prepare(runtime, adapter: str, user: str) -> None:
    for index, command in enumerate(
        (
            "开始修仙",
            "寻仙问道",
            "完成引导 阅读",
            "前往近郊",
            "完成引导 采集",
            "完成引导 炼丹",
            "选择道途 体修",
        )
    ):
        result = await _dispatch(runtime, adapter, user, f"setup-{index}", command)
        assert result.ok, (command, result.code, result.message)


def _replace_object_member(raw: str, key: str, value: object) -> str:
    return raw[:-1] + f',"{key}":{json.dumps(value, ensure_ascii=False)}}}'


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_retreat_start_replay_rejects_duplicate_json_then_recovers(tmp_path, adapter: str) -> None:
    async def run() -> None:
        runtime = create_runtime(data_dir=tmp_path / adapter, adapters=(adapter,))
        user = f"retreat-start-{adapter}"
        operation = "retreat-start-operation"
        try:
            await _prepare(runtime, adapter, user)
            started = await _dispatch(runtime, adapter, user, "start", "开始闭关", operation)
            assert started.code == "RETREAT_STARTED"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                before = connection.execute(
                    "SELECT energy, inventory_json FROM players WHERE platform=? AND platform_user_id=?",
                    (adapter, user),
                ).fetchone()
                original = connection.execute(
                    "SELECT result_json FROM operations WHERE operation_id=?", (operation,)
                ).fetchone()[0]
                connection.execute(
                    "UPDATE operations SET result_json=? WHERE operation_id=?",
                    (_replace_object_member(original, "status", "running"), operation),
                )
            rejected = await _dispatch(runtime, adapter, user, "replay-bad", "开始闭关", operation)
            assert rejected.code == "PERSISTENCE_ERROR"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute(
                    "SELECT energy, inventory_json FROM players WHERE platform=? AND platform_user_id=?",
                    (adapter, user),
                ).fetchone() == before
                connection.execute(
                    "UPDATE operations SET result_json=? WHERE operation_id=?", (original, operation)
                )
            repaired = await _dispatch(runtime, adapter, user, "replay-good", "开始闭关", operation)
            assert repaired.code == "RETREAT_STARTED"
            assert repaired.data["idempotent_replay"] is True
        finally:
            await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_retreat_snapshot_recovery_is_zero_write_and_retryable(tmp_path, adapter: str) -> None:
    async def run() -> None:
        clock = [datetime(2026, 9, 22, tzinfo=timezone.utc)]
        runtime = create_runtime(data_dir=tmp_path / adapter, adapters=(adapter,), clock=lambda: clock[0])
        user = f"retreat-settle-{adapter}"
        operation = "retreat-settle-operation"
        try:
            await _prepare(runtime, adapter, user)
            started = await _dispatch(runtime, adapter, user, "start", "开始闭关", "retreat-start")
            assert started.code == "RETREAT_STARTED"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                valid_snapshot = connection.execute(
                    "SELECT snapshot_json FROM retreat_sessions WHERE session_id=?",
                    (started.data["session_id"],),
                ).fetchone()[0]
                before = connection.execute(
                    "SELECT cultivation, energy, inventory_json FROM players WHERE platform=? AND platform_user_id=?",
                    (adapter, user),
                ).fetchone()
                connection.execute(
                    "UPDATE retreat_sessions SET snapshot_json=? WHERE session_id=?",
                    (_replace_object_member(valid_snapshot, "energy_cost", 999), started.data["session_id"]),
                )
            clock[0] = datetime.fromisoformat(started.data["ends_at"]) + timedelta(seconds=1)
            rejected = await _dispatch(runtime, adapter, user, "settle-bad", "结算闭关", operation)
            assert rejected.code == "PERSISTENCE_ERROR"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute(
                    "SELECT cultivation, energy, inventory_json FROM players WHERE platform=? AND platform_user_id=?",
                    (adapter, user),
                ).fetchone() == before
                assert connection.execute(
                    "SELECT status FROM retreat_sessions WHERE session_id=?", (started.data["session_id"],)
                ).fetchone()[0] == "running"
                assert connection.execute(
                    "SELECT COUNT(*) FROM operations WHERE operation_id=?", (operation,)
                ).fetchone()[0] == 0
                connection.execute(
                    "UPDATE retreat_sessions SET snapshot_json=? WHERE session_id=?",
                    (valid_snapshot, started.data["session_id"]),
                )
            settled = await _dispatch(runtime, adapter, user, "settle-good", "结算闭关", operation)
            assert settled.code == "RETREAT_SETTLED"
            replay = await _dispatch(runtime, adapter, user, "settle-replay", "结算闭关", operation)
            assert replay.code == "RETREAT_SETTLED"
            assert replay.data["idempotent_replay"] is True
        finally:
            await runtime.close()

    asyncio.run(run())
