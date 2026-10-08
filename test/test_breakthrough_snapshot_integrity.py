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
from nonebot_plugin_xiuxian_3.xiuxian.progression.breakthrough.rules import breakthrough_roll_bp


ADAPTERS = ("qq.official", "onebot.v11")


def _context(adapter: str, user: str, operation_id: str) -> CommandContext:
    return CommandContext(
        adapter=adapter,
        user_id=user,
        request_id=f"breakthrough-integrity:{operation_id}",
        operation_id=operation_id,
    )


async def _create_cultivator(runtime, adapter: str, user: str) -> None:
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
        result = await runtime.adapters.dispatch(adapter, _context(adapter, user, f"setup:{index}"), command)
        assert result.ok, result


def _prepare_qi_gathering(runtime, adapter: str, user: str) -> None:
    inventory = {
        "item.pill.focus_low": 1,
        "item.herb.spirit_leaf": 3,
        "item.pill.qi_guard": 1,
    }
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE players SET stage='cultivator', realm_key='qi_sensing', realm_layer=10, "
            "cultivation=1360, total_cultivation=1360, spirit_stones=1000, inventory_json=? "
            "WHERE platform=? AND platform_user_id=?",
            (json.dumps(inventory, sort_keys=True), adapter, user),
        )


def _finish(runtime, session_id: str) -> None:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE breakthrough_sessions SET ends_at=? WHERE session_id=?",
            ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(), session_id),
        )


def _copy_content(data_dir: Path) -> None:
    shutil.copytree(Path(__file__).parents[1] / "data", data_dir)


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_corrupt_breakthrough_snapshot_is_read_only_until_repaired(tmp_path: Path, adapter: str) -> None:
    async def run() -> None:
        data_dir = tmp_path / adapter.replace(".", "-") / "data"
        _copy_content(data_dir)
        runtime = create_runtime(data_dir=data_dir, adapters=(adapter,))
        user = f"breakthrough-snapshot-{adapter}"
        await _create_cultivator(runtime, adapter, user)
        _prepare_qi_gathering(runtime, adapter, user)
        start_id = f"{user}:start"
        # Keep the original roll above the frozen 80% success threshold.
        start_id = next(candidate for index in range(1000) if breakthrough_roll_bp(candidate := f"{start_id}:{index}") >= 8000)
        started = await runtime.adapters.dispatch(adapter, _context(adapter, user, start_id), "开始突破 聚气")
        assert started.code == "BREAKTHROUGH_STARTED"
        _finish(runtime, started.data["session_id"])
        settle_id = f"{user}:settle"
        with sqlite3.connect(runtime.settings.database_path) as connection:
            original = connection.execute(
                "SELECT snapshot_json FROM breakthrough_sessions WHERE session_id=?", (started.data["session_id"],)
            ).fetchone()[0]
            corrupted = original[:-1] + ',"success_bp":9999}'
            connection.execute(
                "UPDATE breakthrough_sessions SET snapshot_json=? WHERE session_id=?",
                (corrupted, started.data["session_id"]),
            )
            before = connection.execute(
                "SELECT realm_key, realm_layer, spirit_stones, inventory_json FROM players WHERE platform=? AND platform_user_id=?",
                (adapter, user),
            ).fetchone()
        rejected = await runtime.adapters.dispatch(adapter, _context(adapter, user, settle_id), "结算突破")
        assert rejected.code == "PERSISTENCE_ERROR"
        with sqlite3.connect(runtime.settings.database_path) as connection:
            after = connection.execute(
                "SELECT realm_key, realm_layer, spirit_stones, inventory_json FROM players WHERE platform=? AND platform_user_id=?",
                (adapter, user),
            ).fetchone()
            assert after == before
            assert connection.execute(
                "SELECT status FROM breakthrough_sessions WHERE session_id=?", (started.data["session_id"],)
            ).fetchone()[0] == "preparing"
            connection.execute(
                "UPDATE breakthrough_sessions SET snapshot_json=? WHERE session_id=?",
                (original, started.data["session_id"]),
            )
        repaired = await runtime.adapters.dispatch(adapter, _context(adapter, user, settle_id), "结算突破")
        assert repaired.code == "BREAKTHROUGH_FAILED"
        replay = await runtime.adapters.dispatch(adapter, _context(adapter, user, settle_id), "结算突破")
        assert replay.code == "BREAKTHROUGH_FAILED"
        assert replay.data["idempotent_replay"] is True
        await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_corrupt_breakthrough_operation_result_rejects_replay_until_repaired(tmp_path: Path, adapter: str) -> None:
    async def run() -> None:
        data_dir = tmp_path / adapter.replace(".", "-") / "data"
        _copy_content(data_dir)
        runtime = create_runtime(data_dir=data_dir, adapters=(adapter,))
        user = f"breakthrough-result-{adapter}"
        await _create_cultivator(runtime, adapter, user)
        _prepare_qi_gathering(runtime, adapter, user)
        start_id = next(
            candidate
            for index in range(1000)
            if breakthrough_roll_bp(candidate := f"{user}:start:{index}") < 8000
        )
        started = await runtime.adapters.dispatch(adapter, _context(adapter, user, start_id), "开始突破 聚气")
        assert started.code == "BREAKTHROUGH_STARTED"
        _finish(runtime, started.data["session_id"])
        settle_id = f"{user}:settle"
        settled = await runtime.adapters.dispatch(adapter, _context(adapter, user, settle_id), "结算突破")
        assert settled.code == "BREAKTHROUGH_SUCCEEDED"
        with sqlite3.connect(runtime.settings.database_path) as connection:
            original = connection.execute(
                "SELECT result_json FROM operations WHERE operation_id=?", (settle_id,)
            ).fetchone()[0]
            connection.execute(
                "UPDATE operations SET result_json=? WHERE operation_id=?",
                (original[:-1] + ',"success_bp":1}', settle_id),
            )
            before = connection.execute(
                "SELECT realm_key, realm_layer, spirit_stones, inventory_json FROM players WHERE platform=? AND platform_user_id=?",
                (adapter, user),
            ).fetchone()
        rejected = await runtime.adapters.dispatch(adapter, _context(adapter, user, settle_id), "结算突破")
        assert rejected.code == "PERSISTENCE_ERROR"
        with sqlite3.connect(runtime.settings.database_path) as connection:
            assert connection.execute(
                "SELECT realm_key, realm_layer, spirit_stones, inventory_json FROM players WHERE platform=? AND platform_user_id=?",
                (adapter, user),
            ).fetchone() == before
            connection.execute("UPDATE operations SET result_json=? WHERE operation_id=?", (original, settle_id))
        await runtime.close()
        restarted = create_runtime(data_dir=data_dir, adapters=(adapter,))
        replay = await restarted.adapters.dispatch(adapter, _context(adapter, user, settle_id), "结算突破")
        assert replay.code == "BREAKTHROUGH_SUCCEEDED"
        assert replay.data["idempotent_replay"] is True
        await restarted.close()

    asyncio.run(run())


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_breakthrough_operation_write_failure_rolls_back_and_retries(tmp_path: Path, adapter: str) -> None:
    async def run() -> None:
        data_dir = tmp_path / adapter.replace(".", "-") / "data"
        _copy_content(data_dir)
        runtime = create_runtime(data_dir=data_dir, adapters=(adapter,))
        user = f"breakthrough-write-failure-{adapter}"
        await _create_cultivator(runtime, adapter, user)
        _prepare_qi_gathering(runtime, adapter, user)
        start_id = next(
            candidate
            for index in range(1000)
            if breakthrough_roll_bp(candidate := f"{user}:start:{index}") < 8000
        )
        started = await runtime.adapters.dispatch(adapter, _context(adapter, user, start_id), "开始突破 聚气")
        assert started.code == "BREAKTHROUGH_STARTED"
        _finish(runtime, started.data["session_id"])
        settle_id = f"{user}:settle"
        with sqlite3.connect(runtime.settings.database_path) as connection:
            operation_literal = json.dumps(settle_id)
            connection.execute(
                "CREATE TRIGGER injected_breakthrough_settlement_failure "
                f"BEFORE INSERT ON operations WHEN NEW.operation_id={operation_literal} "
                "BEGIN SELECT RAISE(ABORT, 'injected breakthrough operation failure'); END"
            )
            before = connection.execute(
                "SELECT realm_key, realm_layer, spirit_stones, inventory_json FROM players WHERE platform=? AND platform_user_id=?",
                (adapter, user),
            ).fetchone()
        failed = await runtime.adapters.dispatch(adapter, _context(adapter, user, settle_id), "结算突破")
        assert failed.code == "PERSISTENCE_ERROR"
        with sqlite3.connect(runtime.settings.database_path) as connection:
            assert connection.execute(
                "SELECT realm_key, realm_layer, spirit_stones, inventory_json FROM players WHERE platform=? AND platform_user_id=?",
                (adapter, user),
            ).fetchone() == before
            assert connection.execute(
                "SELECT status FROM breakthrough_sessions WHERE session_id=?", (started.data["session_id"],)
            ).fetchone()[0] == "preparing"
            connection.execute("DROP TRIGGER injected_breakthrough_settlement_failure")
        retried = await runtime.adapters.dispatch(adapter, _context(adapter, user, settle_id), "结算突破")
        assert retried.code == "BREAKTHROUGH_SUCCEEDED"
        replay = await runtime.adapters.dispatch(adapter, _context(adapter, user, settle_id), "结算突破")
        assert replay.code == "BREAKTHROUGH_SUCCEEDED"
        assert replay.data["idempotent_replay"] is True
        await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_corrupt_breakthrough_start_operation_player_rejects_replay(tmp_path: Path, adapter: str) -> None:
    async def run() -> None:
        data_dir = tmp_path / adapter.replace(".", "-") / "data"
        _copy_content(data_dir)
        runtime = create_runtime(data_dir=data_dir, adapters=(adapter,))
        user = f"breakthrough-start-result-{adapter}"
        await _create_cultivator(runtime, adapter, user)
        _prepare_qi_gathering(runtime, adapter, user)
        operation_id = next(
            candidate
            for index in range(1000)
            if breakthrough_roll_bp(candidate := f"{user}:start:{index}") >= 8000
        )
        started = await runtime.adapters.dispatch(
            adapter,
            _context(adapter, user, operation_id),
            "开始突破 聚气",
        )
        assert started.code == "BREAKTHROUGH_STARTED"
        with sqlite3.connect(runtime.settings.database_path) as connection:
            original = connection.execute(
                "SELECT result_json FROM operations WHERE operation_id=?", (operation_id,)
            ).fetchone()[0]
            payload = json.loads(original)
            payload["player"]["player_id"] = "foreign-player"
            connection.execute(
                "UPDATE operations SET result_json=? WHERE operation_id=?",
                (json.dumps(payload, sort_keys=True), operation_id),
            )
        replay = await runtime.adapters.dispatch(
            adapter,
            _context(adapter, user, operation_id),
            "开始突破 聚气",
        )
        assert replay.code == "PERSISTENCE_ERROR"
        await runtime.close()

    asyncio.run(run())
