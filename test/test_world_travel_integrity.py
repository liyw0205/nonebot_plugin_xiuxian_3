from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path

import pytest

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from travel_fixtures import set_travel_end_at


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
    created = await _dispatch(runtime, adapter, user, "create", "开始修仙")
    assert created.code == "PLAYER_CREATED"
    sought = await _dispatch(runtime, adapter, user, "seek", "寻仙问道")
    assert sought.ok
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE players SET stage='cultivator', realm_key='foundation', realm_layer=1, "
            "location_key='xuantian.new_town', stamina=30, stamina_max=30, spirit_stones=100, "
            "inventory_json=? WHERE platform=? AND platform_user_id=?",
            (json.dumps({"item.cave_pass_basic": 1}), adapter, user),
        )


def _duplicate(raw: str, key: str, value: object) -> str:
    return raw[:-1] + f',"{key}":{json.dumps(value, ensure_ascii=False)}}}'


def _mutate_operation(raw: str, damage: str) -> str:
    if damage == "duplicate":
        return _duplicate(raw, "destination", "xuantian.new_town")
    if damage == "truncated":
        return raw[:-1]
    if damage == "semantic":
        payload = json.loads(raw)
        payload["destination"] = "xuantian.new_town"
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)
    if damage == "end_time":
        payload = json.loads(raw)
        payload["ends_at"] = "2099-01-01T00:00:00+00:00"
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)
    raise AssertionError(f"unknown operation damage: {damage}")


def _mutate_snapshot(raw: str, damage: str) -> str:
    if damage == "duplicate":
        return _duplicate(raw, "consume_pass_on_arrival", True)
    if damage == "semantic_timing":
        payload = json.loads(raw)
        payload["consume_pass_on_arrival"] = True
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)
    if damage == "truncated":
        return raw[:-1]
    if damage == "semantic":
        payload = json.loads(raw)
        payload["destination"] = "xuantian.new_town"
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)
    raise AssertionError(f"unknown snapshot damage: {damage}")


def _start_state(runtime, adapter: str, user: str, operation: str):
    with sqlite3.connect(runtime.settings.database_path) as connection:
        player = connection.execute(
            "SELECT stamina, spirit_stones, inventory_json, location_key FROM players "
            "WHERE platform=? AND platform_user_id=?",
            (adapter, user),
        ).fetchone()
        session = connection.execute(
            "SELECT session_id, status, snapshot_json, result_json FROM travel_sessions "
            "WHERE player_id=(SELECT id FROM players WHERE platform=? AND platform_user_id=?) "
            "ORDER BY id DESC LIMIT 1",
            (adapter, user),
        ).fetchone()
        ledger = connection.execute(
            "SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id=?",
            (operation,),
        ).fetchone()
    return player, session, ledger


def _settlement_state(runtime, adapter: str, user: str, operation: str):
    with sqlite3.connect(runtime.settings.database_path) as connection:
        player = connection.execute(
            "SELECT stamina, spirit_stones, inventory_json, location_key FROM players "
            "WHERE platform=? AND platform_user_id=?",
            (adapter, user),
        ).fetchone()
        session = connection.execute(
            "SELECT session_id, status, result_json FROM travel_sessions "
            "WHERE player_id=(SELECT id FROM players WHERE platform=? AND platform_user_id=?) "
            "ORDER BY id DESC LIMIT 1",
            (adapter, user),
        ).fetchone()
        ledger = connection.execute(
            "SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id=?",
            (operation,),
        ).fetchone()
    return player, session, ledger


def _expire_travel(runtime, session_id: str, *, snapshot_json: str | None = None) -> None:
    expired_at = "2000-01-01T00:00:00+00:00"
    with sqlite3.connect(runtime.settings.database_path) as connection:
        set_travel_end_at(connection, session_id, expired_at)
        if snapshot_json is None:
            return
        else:
            connection.execute(
                "UPDATE travel_sessions SET snapshot_json=? WHERE session_id=?",
                (snapshot_json, session_id),
            )


async def _prepare_beast_intro_player(runtime, adapter: str, user: str) -> None:
    await _prepare(runtime, adapter, user)
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE players SET realm_key='nascent_soul', realm_layer=1, "
            "location_key='xuantian.floating_boat', stamina=60, stamina_max=60, "
            "faction_reputation_json=?, intro_json=? WHERE platform=? AND platform_user_id=?",
            (
                json.dumps({"beast": 0}),
                json.dumps({"flags": ["access.beast_ten_thousand_hills"]}),
                adapter,
                user,
            ),
        )


@pytest.mark.parametrize("adapter", ADAPTERS)
@pytest.mark.parametrize("damage", ("duplicate", "truncated", "semantic", "end_time"))
def test_travel_start_operation_replay_rejects_corruption_without_writes(
    tmp_path: Path, adapter: str, damage: str
) -> None:
    async def run() -> None:
        runtime = create_runtime(data_dir=tmp_path / adapter / "start" / damage, adapters=(adapter,))
        user = f"travel-start-integrity-{adapter}-{damage}"
        operation = "travel-start-operation"
        try:
            await _prepare(runtime, adapter, user)
            started = await _dispatch(runtime, adapter, user, "start", "前往 雾隐洞天", operation)
            assert started.code == "TRAVEL_STARTED"
            before = _start_state(runtime, adapter, user, operation)
            original_result = before[2][2]
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE operations SET result_json=? WHERE operation_id=?",
                    (_mutate_operation(original_result, damage), operation),
                )
            damaged = _start_state(runtime, adapter, user, operation)

            rejected = await _dispatch(runtime, adapter, user, "damaged-replay", "前往 雾隐洞天", operation)
            assert rejected.code == "PERSISTENCE_ERROR"
            assert _start_state(runtime, adapter, user, operation) == damaged

            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE operations SET result_json=? WHERE operation_id=?",
                    (original_result, operation),
                )
            replay = await _dispatch(runtime, adapter, user, "repaired-replay", "前往 雾隐洞天", operation)
            assert replay.code == "TRAVEL_STARTED"
            assert replay.data["idempotent_replay"] is True
            assert _start_state(runtime, adapter, user, operation)[:2] == before[:2]
        finally:
            await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("adapter", ADAPTERS)
@pytest.mark.parametrize(
    "damage", ("duplicate", "semantic_timing", "truncated", "semantic")
)
def test_travel_snapshot_recovery_is_read_only_retryable_and_replayable(
    tmp_path: Path, adapter: str, damage: str
) -> None:
    async def run() -> None:
        data_dir = tmp_path / adapter / "settle" / damage
        runtime = create_runtime(data_dir=data_dir, adapters=(adapter,))
        user = f"travel-settle-integrity-{adapter}-{damage}"
        start_operation = "travel-start-operation"
        settle_operation = "travel-settle-operation"
        try:
            await _prepare(runtime, adapter, user)
            started = await _dispatch(runtime, adapter, user, "start", "前往 雾隐洞天", start_operation)
            assert started.code == "TRAVEL_STARTED"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                valid_snapshot = connection.execute(
                    "SELECT snapshot_json FROM travel_sessions WHERE session_id=?",
                    (started.data["session_id"],),
                ).fetchone()[0]
            _expire_travel(
                runtime,
                started.data["session_id"],
                snapshot_json=_mutate_snapshot(valid_snapshot, damage),
            )

            before = _settlement_state(runtime, adapter, user, settle_operation)
            rejected = await _dispatch(runtime, adapter, user, "damaged-settle", "结算移动", settle_operation)
            assert rejected.code == "PERSISTENCE_ERROR"
            assert _settlement_state(runtime, adapter, user, settle_operation) == before
            assert before[1][1] == "running"
            assert before[2] is None

            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE travel_sessions SET snapshot_json=? WHERE session_id=?",
                    (valid_snapshot, started.data["session_id"]),
                )
            settled = await _dispatch(runtime, adapter, user, "repaired-settle", "结算移动", settle_operation)
            assert settled.code == "TRAVEL_COMPLETED"
            assert settled.data["idempotent_replay"] is False
            committed = _settlement_state(runtime, adapter, user, settle_operation)
            assert committed[1][1] == "arrived"
            assert committed[0][3] == "cave.mist_grotto"
            assert committed[2] is not None

            await runtime.close()
            runtime = create_runtime(data_dir=data_dir, adapters=(adapter,))
            replay = await _dispatch(runtime, adapter, user, "restart-replay", "结算移动", settle_operation)
            assert replay.code == "TRAVEL_COMPLETED"
            assert replay.data["idempotent_replay"] is True
            assert _settlement_state(runtime, adapter, user, settle_operation) == committed
        finally:
            await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("adapter", ADAPTERS)
@pytest.mark.parametrize("damage", ("duplicate", "truncated", "semantic", "end_time"))
def test_travel_settlement_operation_replay_rejects_corruption_without_writes(
    tmp_path: Path, adapter: str, damage: str
) -> None:
    async def run() -> None:
        data_dir = tmp_path / adapter / "settlement-operation" / damage
        runtime = create_runtime(data_dir=data_dir, adapters=(adapter,))
        user = f"travel-settlement-operation-{adapter}-{damage}"
        operation = "travel-settlement-operation"
        try:
            await _prepare(runtime, adapter, user)
            started = await _dispatch(runtime, adapter, user, "start", "前往 雾隐洞天", "travel-start-operation")
            assert started.code == "TRAVEL_STARTED"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                _expire_travel(runtime, started.data["session_id"])
            settled = await _dispatch(runtime, adapter, user, "settle", "结算移动", operation)
            assert settled.code == "TRAVEL_COMPLETED"
            before = _settlement_state(runtime, adapter, user, operation)
            original_result = before[2][2]
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE operations SET result_json=? WHERE operation_id=?",
                    (_mutate_operation(original_result, damage), operation),
                )
            damaged = _settlement_state(runtime, adapter, user, operation)
            rejected = await _dispatch(runtime, adapter, user, "damaged-replay", "结算移动", operation)
            assert rejected.code == "PERSISTENCE_ERROR"
            assert _settlement_state(runtime, adapter, user, operation) == damaged

            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE operations SET result_json=? WHERE operation_id=?",
                    (original_result, operation),
                )
            replay = await _dispatch(runtime, adapter, user, "repaired-replay", "结算移动", operation)
            assert replay.code == "TRAVEL_COMPLETED"
            assert replay.data["idempotent_replay"] is True
            assert _settlement_state(runtime, adapter, user, operation) == before
        finally:
            await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("adapter", ADAPTERS)
@pytest.mark.parametrize("settled_at", ("not-a-time", "2026-10-08T12:00:00"))
def test_arrived_travel_replay_rejects_invalid_settled_at_without_writes(
    tmp_path: Path, adapter: str, settled_at: str
) -> None:
    async def run() -> None:
        runtime = create_runtime(data_dir=tmp_path / adapter / "settled-at", adapters=(adapter,))
        user = f"travel-settled-at-{adapter}"
        operation = "travel-settle-operation"
        try:
            await _prepare(runtime, adapter, user)
            started = await _dispatch(runtime, adapter, user, "start", "前往 雾隐洞天", "travel-start-operation")
            assert started.code == "TRAVEL_STARTED"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                _expire_travel(runtime, started.data["session_id"])
            settled = await _dispatch(runtime, adapter, user, "settle", "结算移动", operation)
            assert settled.code == "TRAVEL_COMPLETED"
            before = _settlement_state(runtime, adapter, user, operation)
            original_result = before[1][2]
            payload = json.loads(original_result)
            payload["settled_at"] = settled_at
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE travel_sessions SET result_json=? WHERE session_id=?",
                    (json.dumps(payload, ensure_ascii=False, sort_keys=True), started.data["session_id"]),
                )
            damaged = _settlement_state(runtime, adapter, user, operation)

            rejected = await _dispatch(runtime, adapter, user, "damaged-replay", "结算移动", operation)
            assert rejected.code == "PERSISTENCE_ERROR"
            assert _settlement_state(runtime, adapter, user, operation) == damaged

            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE travel_sessions SET result_json=? WHERE session_id=?",
                    (original_result, started.data["session_id"]),
                )
            replay = await _dispatch(runtime, adapter, user, "repaired-replay", "结算移动", operation)
            assert replay.code == "TRAVEL_COMPLETED"
            assert replay.data["idempotent_replay"] is True
            assert _settlement_state(runtime, adapter, user, operation) == before
        finally:
            await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_beast_hills_intro_flag_allows_low_reputation_travel_settlement(
    tmp_path: Path, adapter: str
) -> None:
    async def run() -> None:
        runtime = create_runtime(data_dir=tmp_path / adapter / "beast-intro", adapters=(adapter,))
        user = f"travel-beast-intro-{adapter}"
        try:
            await _prepare_beast_intro_player(runtime, adapter, user)
            started = await _dispatch(runtime, adapter, user, "start", "前往 万兽山", "beast-travel-start")
            assert started.code == "TRAVEL_STARTED"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                snapshot = json.loads(
                    connection.execute(
                        "SELECT snapshot_json FROM travel_sessions WHERE session_id=?",
                        (started.data["session_id"],),
                    ).fetchone()[0]
                )
                _expire_travel(runtime, started.data["session_id"])
            assert snapshot["beast_hills_permission"] == "intro_flag"
            assert snapshot["faction_reputation"] == 0

            settled = await _dispatch(runtime, adapter, user, "settle", "结算移动", "beast-travel-settle")
            assert settled.code == "TRAVEL_COMPLETED"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute(
                    "SELECT location_key FROM players WHERE platform=? AND platform_user_id=?",
                    (adapter, user),
                ).fetchone()[0] == "beast.ten_thousand_hills"
        finally:
            await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("adapter", ADAPTERS)
@pytest.mark.parametrize("permission", ("unknown", "reputation"))
def test_beast_hills_snapshot_permission_tampering_is_read_only(
    tmp_path: Path, adapter: str, permission: str
) -> None:
    async def run() -> None:
        runtime = create_runtime(data_dir=tmp_path / adapter / "beast-permission" / permission, adapters=(adapter,))
        user = f"travel-beast-permission-{adapter}-{permission}"
        operation = "beast-travel-settle"
        try:
            await _prepare_beast_intro_player(runtime, adapter, user)
            started = await _dispatch(runtime, adapter, user, "start", "前往 万兽山", "beast-travel-start")
            assert started.code == "TRAVEL_STARTED"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                raw_snapshot = connection.execute(
                    "SELECT snapshot_json FROM travel_sessions WHERE session_id=?",
                    (started.data["session_id"],),
                ).fetchone()[0]
                payload = json.loads(raw_snapshot)
                payload["beast_hills_permission"] = permission
            _expire_travel(
                runtime,
                started.data["session_id"],
                snapshot_json=json.dumps(payload, ensure_ascii=False, sort_keys=True),
            )
            before = _settlement_state(runtime, adapter, user, operation)

            rejected = await _dispatch(runtime, adapter, user, "damaged-settle", "结算移动", operation)
            assert rejected.code == "PERSISTENCE_ERROR"
            assert _settlement_state(runtime, adapter, user, operation) == before
            assert before[1][1] == "running"
            assert before[2] is None
        finally:
            await runtime.close()

    asyncio.run(run())
