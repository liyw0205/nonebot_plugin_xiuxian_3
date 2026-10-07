from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.production.rules import random_quality_bp


ADAPTERS = ("qq.official", "onebot.v11")


def _context(adapter: str, user: str, request: str, operation: str = "") -> CommandContext:
    return CommandContext(
        adapter=adapter,
        user_id=user,
        request_id=request,
        operation_id=operation,
        can_write_assets=True,
    )


async def _dispatch(runtime, adapter: str, user: str, request: str, command: str, operation: str = ""):
    return await runtime.adapters.dispatch(
        adapter,
        _context(adapter, user, request, operation),
        command,
    )


async def _enter_alchemy(runtime, adapter: str, user: str) -> None:
    for index, command in enumerate(
        (
            "开始修仙",
            "寻仙问道",
            "完成引导 阅读",
            "前往近郊",
            "完成引导 采集",
            "完成引导 炼丹",
            "选择道途 辅修 炼丹",
        )
    ):
        result = await _dispatch(runtime, adapter, user, f"setup-{index}", command)
        assert result.ok, (command, result.code, result.message)


def _finish_order(runtime, order_id: str, *, hours_ago: int = 0) -> None:
    now = datetime.now(timezone.utc) - timedelta(hours=hours_ago, seconds=1)
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE production_orders SET starts_at=?, ends_at=? WHERE order_id=?",
            (
                (now - timedelta(seconds=30)).isoformat(),
                (now - timedelta(seconds=1)).isoformat(),
                order_id,
            ),
        )


def _successful_operation_id(prefix: str) -> str:
    for index in range(1000):
        operation_id = f"{prefix}-{index}"
        if random_quality_bp(operation_id) == 1000:
            return operation_id
    raise AssertionError("could not find a successful production operation id")


def _read_settlement_state(runtime, adapter: str, user: str, order_id: str, operation_id: str):
    with sqlite3.connect(runtime.settings.database_path) as connection:
        player = connection.execute(
            "SELECT inventory_json, spirit_stones, energy, durability_json "
            "FROM players WHERE platform=? AND platform_user_id=?",
            (adapter, user),
        ).fetchone()
        order = connection.execute(
            "SELECT player_id, recipe_key, status, snapshot_json, result_json "
            "FROM production_orders WHERE order_id=?",
            (order_id,),
        ).fetchone()
        operation = connection.execute(
            "SELECT operation_name, player_id, request_hash, result_json "
            "FROM operations WHERE operation_id=?",
            (operation_id,),
        ).fetchone()
    return player, order, operation


def _read_start_state(runtime, adapter: str, user: str, operation_id: str):
    with sqlite3.connect(runtime.settings.database_path) as connection:
        player = connection.execute(
            "SELECT inventory_json, spirit_stones, energy, durability_json "
            "FROM players WHERE platform=? AND platform_user_id=?",
            (adapter, user),
        ).fetchone()
        order_count = connection.execute("SELECT COUNT(*) FROM production_orders").fetchone()[0]
        operation = connection.execute(
            "SELECT operation_name, player_id, request_hash, result_json "
            "FROM operations WHERE operation_id=?",
            (operation_id,),
        ).fetchone()
    return player, order_count, operation


def _with_duplicate_outputs(raw: str, quantity: int = 999) -> str:
    return raw[:-1] + f',"outputs":{{"item.pill.healing_low":{quantity}}}}}'


def _with_duplicate_order_id(raw: str) -> str:
    return raw[:-1] + ',"order_id":"corrupt-order"}'


def _mutate_json(raw: str, mutation: str, *, quantity: int = 999) -> str:
    if mutation == "duplicate":
        return _with_duplicate_outputs(raw, quantity)
    if mutation == "bad_json":
        return raw[:-1]
    payload = json.loads(raw)
    if mutation == "start_snapshot_outputs_mismatch":
        payload["snapshot"]["outputs"] = {"item.pill.healing_low": quantity}
    elif mutation == "snapshot_outputs_mismatch":
        payload["outputs"] = {"item.pill.healing_low": quantity}
    elif mutation == "recipe_mismatch":
        payload["recipe_key"] = "recipe.pill.focus_low"
    elif mutation == "order_mismatch":
        payload["order_id"] = "another-order"
    elif mutation == "player_mismatch":
        payload["player"]["platform_user_id"] = "another-player"
    elif mutation == "status_mismatch":
        payload["status"] = "failed" if payload["status"] == "completed" else "completed"
    elif mutation == "coherent_outputs_mismatch":
        payload["outputs"] = {"item.pill.healing_low": 999}
    else:
        raise AssertionError(f"unknown mutation: {mutation}")
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


@pytest.mark.parametrize("adapter", ADAPTERS)
@pytest.mark.parametrize("damage", ("bad_json", "duplicate"))
def test_corrupt_player_durability_rejects_production_start_without_writes_and_can_retry(
    tmp_path: Path, adapter: str, damage: str
) -> None:
    async def run() -> None:
        runtime = create_runtime(data_dir=tmp_path / adapter / damage, adapters=(adapter,))
        user = f"production-durability-{adapter}-{damage}"
        operation_id = "production-durability-start"
        try:
            await _enter_alchemy(runtime, adapter, user)
            with sqlite3.connect(runtime.settings.database_path) as connection:
                original = connection.execute(
                    "SELECT durability_json FROM players WHERE platform=? AND platform_user_id=?",
                    (adapter, user),
                ).fetchone()[0]
                if damage == "bad_json":
                    corrupted = original[:-1]
                else:
                    corrupted = '{"item.tool.basic_furnace":2000,"item.tool.basic_furnace":2000}'
                connection.execute(
                    "UPDATE players SET durability_json=? WHERE platform=? AND platform_user_id=?",
                    (corrupted, adapter, user),
                )

            before = _read_start_state(runtime, adapter, user, operation_id)
            rejected = await _dispatch(
                runtime,
                adapter,
                user,
                "start-damaged",
                "开始生产 疗伤丹",
                operation_id,
            )
            assert rejected.code == "PERSISTENCE_ERROR"
            assert _read_start_state(runtime, adapter, user, operation_id) == before
            assert before[2] is None

            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE players SET durability_json=? WHERE platform=? AND platform_user_id=?",
                    (original, adapter, user),
                )
            started = await _dispatch(
                runtime,
                adapter,
                user,
                "start-retry",
                "开始生产 疗伤丹",
                operation_id,
            )
            assert started.code == "PRODUCTION_STARTED"
            after = _read_start_state(runtime, adapter, user, operation_id)
            assert after[1] == before[1] + 1
            assert after[2] is not None
            assert after[0][0] != before[0][0]
            assert after[0][2] < before[0][2]
            assert after[0][3] != original
        finally:
            await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("adapter", ADAPTERS)
@pytest.mark.parametrize("damage", ("start_snapshot_outputs_mismatch",))
def test_corrupt_production_start_operation_result_is_rejected_and_replays_after_repair(
    tmp_path: Path, adapter: str, damage: str
) -> None:
    async def run() -> None:
        runtime = create_runtime(data_dir=tmp_path / adapter / "start-result", adapters=(adapter,))
        user = f"production-start-result-{adapter}"
        operation_id = "production-start-result"
        try:
            await _enter_alchemy(runtime, adapter, user)
            started = await _dispatch(
                runtime,
                adapter,
                user,
                "start",
                "开始生产 疗伤丹",
                operation_id,
            )
            assert started.code == "PRODUCTION_STARTED"
            before = _read_start_state(runtime, adapter, user, operation_id)
            original_result = before[2][3]
            damaged_result = _mutate_json(original_result, damage)
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE operations SET result_json=? WHERE operation_id=?",
                    (damaged_result, operation_id),
                )
            damaged = _read_start_state(runtime, adapter, user, operation_id)

            rejected = await _dispatch(
                runtime,
                adapter,
                user,
                "start-damaged-replay",
                "开始生产 疗伤丹",
                operation_id,
            )
            assert rejected.code == "PERSISTENCE_ERROR"
            assert _read_start_state(runtime, adapter, user, operation_id) == damaged

            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE operations SET result_json=? WHERE operation_id=?",
                    (original_result, operation_id),
                )
            replay = await _dispatch(
                runtime,
                adapter,
                user,
                "start-repaired-replay",
                "开始生产 疗伤丹",
                operation_id,
            )
            assert replay.code == "PRODUCTION_STARTED"
            assert replay.data["idempotent_replay"] is True
            assert replay.data["order_id"] == started.data["order_id"]
            assert _read_start_state(runtime, adapter, user, operation_id)[1:] == before[1:]
        finally:
            await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("adapter", ADAPTERS)
@pytest.mark.parametrize("recovery", (False, True))
@pytest.mark.parametrize(
    "damage",
    ("duplicate", "bad_json", "recipe_mismatch", "snapshot_outputs_mismatch"),
)
def test_corrupt_production_snapshot_is_read_only_and_original_operation_retries(
    tmp_path: Path, adapter: str, recovery: bool, damage: str
) -> None:
    async def run() -> None:
        data_dir = tmp_path / adapter / str(recovery) / damage
        runtime = create_runtime(data_dir=data_dir, adapters=(adapter,))
        user = f"production-snapshot-{adapter}-{recovery}-{damage}"
        operation_id = "production-snapshot-settle"
        start_operation_id = _successful_operation_id("production-snapshot-start")
        try:
            await _enter_alchemy(runtime, adapter, user)
            started = await _dispatch(
                runtime,
                adapter,
                user,
                "start",
                "开始生产 疗伤丹",
                start_operation_id,
            )
            assert started.code == "PRODUCTION_STARTED"
            _finish_order(runtime, started.data["order_id"], hours_ago=25 if recovery else 0)
            if recovery:
                expired = await _dispatch(runtime, adapter, user, "expire", "领取生产")
                assert expired.code == "ORDER_EXPIRED"

            with sqlite3.connect(runtime.settings.database_path) as connection:
                raw = connection.execute(
                    "SELECT snapshot_json FROM production_orders WHERE order_id=?",
                    (started.data["order_id"],),
                ).fetchone()[0]
            valid_snapshot = raw
            damaged_snapshot = _mutate_json(valid_snapshot, damage)
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE production_orders SET snapshot_json=? WHERE order_id=?",
                    (damaged_snapshot, started.data["order_id"]),
                )

            before = _read_settlement_state(
                runtime,
                adapter,
                user,
                started.data["order_id"],
                operation_id,
            )
            rejected = await _dispatch(
                runtime,
                adapter,
                user,
                "settle-damaged",
                "恢复生产" if recovery else "领取生产",
                operation_id,
            )
            assert rejected.code == "PERSISTENCE_ERROR"
            assert _read_settlement_state(
                runtime,
                adapter,
                user,
                started.data["order_id"],
                operation_id,
            ) == before
            assert before[1][2] == ("expired" if recovery else "processing")
            assert before[1][4] == "{}"
            assert before[2] is None

            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE production_orders SET snapshot_json=? WHERE order_id=?",
                    (valid_snapshot, started.data["order_id"]),
                )
            settled = await _dispatch(
                runtime,
                adapter,
                user,
                "settle-retry",
                "恢复生产" if recovery else "领取生产",
                operation_id,
            )
            assert settled.code == ("PRODUCTION_RECOVERED" if recovery else "PRODUCTION_COMPLETED")
            assert settled.data["success"] is True
            assert settled.data["outputs"] == {"item.pill.healing_low": 1}
            committed = _read_settlement_state(
                runtime,
                adapter,
                user,
                started.data["order_id"],
                operation_id,
            )
            assert committed[1][2] == "completed"
            assert committed[2] is not None

            await runtime.close()
            runtime = create_runtime(data_dir=data_dir, adapters=(adapter,))
            replay = await _dispatch(
                runtime,
                adapter,
                user,
                "settle-replay-after-restart",
                "恢复生产" if recovery else "领取生产",
                operation_id,
            )
            assert replay.code == ("PRODUCTION_RECOVERED" if recovery else "PRODUCTION_COMPLETED")
            assert replay.data["idempotent_replay"] is True
            assert _read_settlement_state(
                runtime,
                adapter,
                user,
                started.data["order_id"],
                operation_id,
            ) == committed
        finally:
            await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_corrupt_overdue_snapshot_is_rejected_before_order_expiry_projection(
    tmp_path: Path, adapter: str
) -> None:
    async def run() -> None:
        runtime = create_runtime(data_dir=tmp_path / adapter / "overdue", adapters=(adapter,))
        user = f"production-overdue-{adapter}"
        operation_id = "production-overdue-claim"
        try:
            await _enter_alchemy(runtime, adapter, user)
            started = await _dispatch(
                runtime,
                adapter,
                user,
                "start",
                "开始生产 疗伤丹",
                "production-overdue-start",
            )
            assert started.code == "PRODUCTION_STARTED"
            _finish_order(runtime, started.data["order_id"], hours_ago=25)
            with sqlite3.connect(runtime.settings.database_path) as connection:
                raw = connection.execute(
                    "SELECT snapshot_json FROM production_orders WHERE order_id=?",
                    (started.data["order_id"],),
                ).fetchone()[0]
                connection.execute(
                    "UPDATE production_orders SET snapshot_json=? WHERE order_id=?",
                    (_mutate_json(raw, "duplicate"), started.data["order_id"]),
                )

            before = _read_settlement_state(runtime, adapter, user, started.data["order_id"], operation_id)
            rejected = await _dispatch(runtime, adapter, user, "claim-overdue", "领取生产", operation_id)
            assert rejected.code == "PERSISTENCE_ERROR"
            assert _read_settlement_state(runtime, adapter, user, started.data["order_id"], operation_id) == before
            assert before[1][2] == "processing"
            assert before[2] is None
        finally:
            await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("adapter", ADAPTERS)
@pytest.mark.parametrize("recovery", (False, True))
@pytest.mark.parametrize(
    "damage",
    (
        "duplicate",
        "bad_json",
        "order_mismatch",
        "player_mismatch",
        "status_mismatch",
        "coherent_outputs_mismatch",
    ),
)
def test_corrupt_production_settlement_result_is_read_only_and_repairable(
    tmp_path: Path, adapter: str, recovery: bool, damage: str
) -> None:
    async def run() -> None:
        data_dir = tmp_path / adapter / str(recovery) / damage
        runtime = create_runtime(data_dir=data_dir, adapters=(adapter,))
        user = f"production-result-{adapter}-{recovery}-{damage}"
        start_operation_id = _successful_operation_id("production-result-start")
        try:
            await _enter_alchemy(runtime, adapter, user)
            started = await _dispatch(
                runtime,
                adapter,
                user,
                "start",
                "开始生产 疗伤丹",
                start_operation_id,
            )
            assert started.code == "PRODUCTION_STARTED"
            _finish_order(runtime, started.data["order_id"], hours_ago=25 if recovery else 0)
            if recovery:
                expired = await _dispatch(runtime, adapter, user, "expire", "领取生产")
                assert expired.code == "ORDER_EXPIRED"
            settled = await _dispatch(
                runtime,
                adapter,
                user,
                "settle",
                "恢复生产" if recovery else "领取生产",
                "production-result-settle",
            )
            assert settled.code == ("PRODUCTION_RECOVERED" if recovery else "PRODUCTION_COMPLETED")
            before = _read_settlement_state(
                runtime,
                adapter,
                user,
                started.data["order_id"],
                "production-result-settle",
            )
            original_result = before[2][3]
            damaged_result = _mutate_json(original_result, damage)
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE operations SET result_json=? WHERE operation_id=?",
                    (damaged_result, "production-result-settle"),
                )
                if damage == "coherent_outputs_mismatch":
                    operation_payload = json.loads(damaged_result)
                    order_result = {
                        key: value for key, value in operation_payload.items() if key not in {"player", "order_id"}
                    }
                    connection.execute(
                        "UPDATE production_orders SET result_json=? WHERE order_id=?",
                        (json.dumps(order_result, ensure_ascii=False, sort_keys=True), started.data["order_id"]),
                    )
            damaged_state = _read_settlement_state(
                runtime,
                adapter,
                user,
                started.data["order_id"],
                "production-result-settle",
            )

            rejected = await _dispatch(
                runtime,
                adapter,
                user,
                "settle-damaged-replay",
                "恢复生产" if recovery else "领取生产",
                "production-result-settle",
            )
            assert rejected.code == "PERSISTENCE_ERROR"
            assert _read_settlement_state(
                runtime,
                adapter,
                user,
                started.data["order_id"],
                "production-result-settle",
            ) == damaged_state

            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE operations SET result_json=? WHERE operation_id=?",
                    (original_result, "production-result-settle"),
                )
                if damage == "coherent_outputs_mismatch":
                    original_payload = json.loads(original_result)
                    original_order_result = {
                        key: value for key, value in original_payload.items() if key not in {"player", "order_id"}
                    }
                    connection.execute(
                        "UPDATE production_orders SET result_json=? WHERE order_id=?",
                        (json.dumps(original_order_result, ensure_ascii=False, sort_keys=True), started.data["order_id"]),
                    )
            repaired = _read_settlement_state(
                runtime,
                adapter,
                user,
                started.data["order_id"],
                "production-result-settle",
            )
            replay = await _dispatch(
                runtime,
                adapter,
                user,
                "settle-repaired-replay",
                "恢复生产" if recovery else "领取生产",
                "production-result-settle",
            )
            assert replay.code == ("PRODUCTION_RECOVERED" if recovery else "PRODUCTION_COMPLETED")
            assert replay.data["idempotent_replay"] is True
            assert _read_settlement_state(
                runtime,
                adapter,
                user,
                started.data["order_id"],
                "production-result-settle",
            ) == repaired
        finally:
            await runtime.close()

    asyncio.run(run())
