from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime


def _context(adapter: str, user: str, request: str, operation: str = "") -> CommandContext:
    return CommandContext(
        adapter=adapter,
        user_id=user,
        request_id=request,
        operation_id=operation,
        can_write_assets=True,
    )


def _prepare_player(runtime, adapter: str, user: str) -> None:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            """
            UPDATE players
            SET stage='cultivator', realm_key='foundation', realm_layer=1,
                location_key='xuantian.cloud_city', stamina=30, stamina_max=30,
                spirit_stones=1000, intro_json='{}'
            WHERE platform=? AND platform_user_id=?
            """,
            (adapter, user),
        )


def _expire(runtime, session_id: str, *, age: timedelta = timedelta(seconds=1)) -> None:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        ends_at = datetime.fromisoformat(
            connection.execute(
                "SELECT ends_at FROM cloud_boat_sessions WHERE session_id=?", (session_id,)
            ).fetchone()[0]
        )
    advance = age + timedelta(seconds=1)
    runtime.repository._clock = lambda ends_at=ends_at, advance=advance: ends_at + advance


def _duplicate_json_key(raw: str, key: str, value: object) -> str:
    return raw[:-1] + f',"{key}":{json.dumps(value, ensure_ascii=False)}}}'


def _session_state(runtime, adapter: str, user: str, session_id: str) -> tuple[object, ...]:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        player = connection.execute(
            "SELECT location_key, spirit_stones, stamina FROM players WHERE platform=? AND platform_user_id=?",
            (adapter, user),
        ).fetchone()
        session = connection.execute(
            "SELECT status, destination, snapshot_json FROM cloud_boat_sessions WHERE session_id=?",
            (session_id,),
        ).fetchone()
        settlement_count = connection.execute(
            "SELECT COUNT(*) FROM operations WHERE operation_name IN ('world.settle_cloud_boat', 'world.recover_cloud_boat') AND player_id=(SELECT id FROM players WHERE platform=? AND platform_user_id=?)",
            (adapter, user),
        ).fetchone()[0]
    return (*player, *session[:2], settlement_count)


def test_cloud_boat_rejects_snapshot_and_session_column_tampering() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            for adapter in ("qq.official", "onebot.v11"):
                user = f"cloud-integrity-{adapter}"
                await runtime.dispatch(_context(adapter, user, f"create-{adapter}"), "开始修仙")
                await runtime.dispatch(_context(adapter, user, f"seek-{adapter}"), "寻仙问道")
                _prepare_player(runtime, adapter, user)
                started = await runtime.dispatch(
                    _context(adapter, user, f"board-{adapter}", f"board-{adapter}"),
                    "登上云舟 魔界引导",
                )
                assert started.code == "CLOUD_BOAT_STARTED"
                session_id = started.data["session_id"]
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    original_ends_at = connection.execute(
                        "SELECT ends_at FROM cloud_boat_sessions WHERE session_id=?", (session_id,)
                    ).fetchone()[0]
                    tampered_ends_at = (
                        datetime.fromisoformat(original_ends_at) + timedelta(minutes=1)
                    ).isoformat()
                    connection.execute(
                        "UPDATE cloud_boat_sessions SET ends_at=? WHERE session_id=?",
                        (tampered_ends_at, session_id),
                    )
                rejected_time = await runtime.dispatch(
                    _context(adapter, user, f"ends-at-reject-{adapter}", f"ends-at-reject-{adapter}"),
                    "结算云舟",
                )
                assert rejected_time.code == "PERSISTENCE_ERROR"
                assert _session_state(runtime, adapter, user, session_id)[0:2] == (
                    "xuantian.cloud_city",
                    500,
                )
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE cloud_boat_sessions SET ends_at=? WHERE session_id=?",
                        (original_ends_at, session_id),
                    )
                _expire(runtime, session_id)

                with sqlite3.connect(runtime.settings.database_path) as connection:
                    snapshot = json.loads(
                        connection.execute(
                            "SELECT snapshot_json FROM cloud_boat_sessions WHERE session_id=?", (session_id,)
                        ).fetchone()[0]
                    )
                    snapshot["destination"] = "tampered.destination"
                    connection.execute(
                        "UPDATE cloud_boat_sessions SET snapshot_json=? WHERE session_id=?",
                        (json.dumps(snapshot, ensure_ascii=False), session_id),
                    )
                rejected_snapshot = await runtime.dispatch(
                    _context(adapter, user, f"snapshot-reject-{adapter}", f"settle-{adapter}"),
                    "结算云舟",
                )
                assert rejected_snapshot.code == "PERSISTENCE_ERROR"
                assert _session_state(runtime, adapter, user, session_id)[0:2] == (
                    "xuantian.cloud_city",
                    500,
                )

                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE cloud_boat_sessions SET snapshot_json=? WHERE session_id=?",
                        (
                            json.dumps(
                                {
                                    "route_key": "route.cloud_to_abyss_intro",
                                    "source": "xuantian.cloud_city",
                                    "destination": "demon.abyss_gate",
                                    "stamina_cost": 10,
                                    "currency_cost": 500,
                                    "pass_key": None,
                                    "pass_quantity": 0,
                                    "required_realm": "foundation",
                                    "required_layer": 1,
                                    "required_quest": None,
                                },
                                ensure_ascii=False,
                                sort_keys=True,
                            ),
                            session_id,
                        ),
                    )
                    connection.execute(
                        "UPDATE cloud_boat_sessions SET destination=? WHERE session_id=?",
                        ("tampered.destination", session_id),
                    )
                rejected_column = await runtime.dispatch(
                    _context(adapter, user, f"column-reject-{adapter}", f"settle-{adapter}"),
                    "结算云舟",
                )
                assert rejected_column.code == "PERSISTENCE_ERROR"
                assert _session_state(runtime, adapter, user, session_id)[0:2] == (
                    "xuantian.cloud_city",
                    500,
                )

                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE cloud_boat_sessions SET destination=? WHERE session_id=?",
                        ("demon.abyss_gate", session_id),
                    )
                settled = await runtime.dispatch(
                    _context(adapter, user, f"settle-{adapter}", f"settle-{adapter}"),
                    "结算云舟",
                )
                assert settled.code == "CLOUD_BOAT_ARRIVED"
                board_after_arrival = await runtime.dispatch(
                    _context(adapter, user, f"board-after-{adapter}", f"board-{adapter}"),
                    "登上云舟 魔界引导",
                )
                assert board_after_arrival.code == "CLOUD_BOAT_STARTED"
                assert board_after_arrival.data["idempotent_replay"] is True
                assert _session_state(runtime, adapter, user, session_id)[0:2] == (
                    "demon.abyss_gate",
                    500,
                )
            await runtime.close()

    asyncio.run(run())


def test_cloud_boat_rejects_tampered_start_and_settlement_replays() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            for adapter in ("qq.official", "onebot.v11"):
                user = f"cloud-replay-{adapter}"
                await runtime.dispatch(_context(adapter, user, f"create-{adapter}"), "开始修仙")
                await runtime.dispatch(_context(adapter, user, f"seek-{adapter}"), "寻仙问道")
                _prepare_player(runtime, adapter, user)
                started = await runtime.dispatch(
                    _context(adapter, user, f"board-{adapter}", f"board-{adapter}"),
                    "登上云舟 魔界引导",
                )
                session_id = started.data["session_id"]
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    original = connection.execute(
                        "SELECT result_json FROM operations WHERE operation_id=?", (f"board-{adapter}",)
                    ).fetchone()[0]
                    payload = json.loads(original)
                    payload["destination"] = "tampered.destination"
                    connection.execute(
                        "UPDATE operations SET result_json=? WHERE operation_id=?",
                        (json.dumps(payload, ensure_ascii=False), f"board-{adapter}"),
                    )
                board_rejected = await runtime.dispatch(
                    _context(adapter, user, f"board-reject-{adapter}", f"board-{adapter}"),
                    "登上云舟 魔界引导",
                )
                assert board_rejected.code == "PERSISTENCE_ERROR"
                assert _session_state(runtime, adapter, user, session_id)[0:2] == (
                    "xuantian.cloud_city",
                    500,
                )
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE operations SET result_json=? WHERE operation_id=?",
                        (original, f"board-{adapter}"),
                    )
                _expire(runtime, session_id)
                settled = await runtime.dispatch(
                    _context(adapter, user, f"settle-{adapter}", f"settle-{adapter}"),
                    "结算云舟",
                )
                assert settled.code == "CLOUD_BOAT_ARRIVED"
                board_replay = await runtime.dispatch(
                    _context(adapter, user, f"board-after-settle-{adapter}", f"board-{adapter}"),
                    "登上云舟 魔界引导",
                )
                assert board_replay.code == "CLOUD_BOAT_STARTED"
                assert board_replay.data["idempotent_replay"] is True
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    original_settle = connection.execute(
                        "SELECT result_json FROM operations WHERE operation_id=?", (f"settle-{adapter}",)
                    ).fetchone()[0]
                    payload = json.loads(original_settle)
                    payload["destination"] = "tampered.destination"
                    connection.execute(
                        "UPDATE operations SET result_json=? WHERE operation_id=?",
                        (json.dumps(payload, ensure_ascii=False), f"settle-{adapter}"),
                    )
                replay_rejected = await runtime.dispatch(
                    _context(adapter, user, f"settle-reject-{adapter}", f"settle-{adapter}"),
                    "结算云舟",
                )
                assert replay_rejected.code == "PERSISTENCE_ERROR"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE operations SET result_json=? WHERE operation_id=?",
                        (original_settle, f"settle-{adapter}"),
                    )
                replay = await runtime.dispatch(
                    _context(adapter, user, f"settle-replay-{adapter}", f"settle-{adapter}"),
                    "结算云舟",
                )
                assert replay.code == "CLOUD_BOAT_ARRIVED"
                assert replay.data["idempotent_replay"] is True
            await runtime.close()

    asyncio.run(run())


def test_cloud_boat_rejects_duplicate_snapshot_json_without_writes() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            for adapter in ("qq.official", "onebot.v11"):
                user = f"cloud-duplicate-{adapter}"
                await runtime.dispatch(_context(adapter, user, f"create-{adapter}"), "开始修仙")
                await runtime.dispatch(_context(adapter, user, f"seek-{adapter}"), "寻仙问道")
                _prepare_player(runtime, adapter, user)
                started = await runtime.dispatch(
                    _context(adapter, user, f"board-{adapter}", f"board-{adapter}"),
                    "登上云舟 魔界引导",
                )
                assert started.code == "CLOUD_BOAT_STARTED"
                session_id = started.data["session_id"]
                _expire(runtime, session_id)
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    raw_snapshot = connection.execute(
                        "SELECT snapshot_json FROM cloud_boat_sessions WHERE session_id=?", (session_id,)
                    ).fetchone()[0]
                    connection.execute(
                        "UPDATE cloud_boat_sessions SET snapshot_json=? WHERE session_id=?",
                        (_duplicate_json_key(raw_snapshot, "destination", "demon.abyss_gate"), session_id),
                    )
                rejected = await runtime.dispatch(
                    _context(adapter, user, f"duplicate-reject-{adapter}", f"settle-{adapter}"),
                    "结算云舟",
                )
                assert rejected.code == "PERSISTENCE_ERROR"
                assert _session_state(runtime, adapter, user, session_id)[0:2] == (
                    "xuantian.cloud_city",
                    500,
                )
            await runtime.close()

    asyncio.run(run())


def test_cloud_boat_settlement_operation_failure_rolls_back_and_retries() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            for adapter in ("qq.official", "onebot.v11"):
                user = f"cloud-failure-{adapter}"
                await runtime.dispatch(_context(adapter, user, f"create-{adapter}"), "开始修仙")
                await runtime.dispatch(_context(adapter, user, f"seek-{adapter}"), "寻仙问道")
                _prepare_player(runtime, adapter, user)
                started = await runtime.dispatch(
                    _context(adapter, user, f"board-{adapter}", f"board-{adapter}"),
                    "登上云舟 魔界引导",
                )
                session_id = started.data["session_id"]
                _expire(runtime, session_id)
                operation_id = f"settle-failure-{adapter}"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        f"CREATE TRIGGER reject_cloud_operation_{adapter.replace('.', '_')} "
                        f"BEFORE INSERT ON operations WHEN NEW.operation_id='{operation_id}' "
                        "BEGIN SELECT RAISE(ABORT, 'injected cloud operation failure'); END"
                    )
                failed = await runtime.dispatch(
                    _context(adapter, user, f"settle-failure-{adapter}", operation_id),
                    "结算云舟",
                )
                assert failed.code == "PERSISTENCE_ERROR"
                assert _session_state(runtime, adapter, user, session_id)[0:2] == (
                    "xuantian.cloud_city",
                    500,
                )
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(f"DROP TRIGGER reject_cloud_operation_{adapter.replace('.', '_')}")
                retried = await runtime.dispatch(
                    _context(adapter, user, f"settle-retry-{adapter}", operation_id),
                    "结算云舟",
                )
                assert retried.code == "CLOUD_BOAT_ARRIVED"
                assert _session_state(runtime, adapter, user, session_id)[0:2] == (
                    "demon.abyss_gate",
                    500,
                )
            await runtime.close()

    asyncio.run(run())


def test_cloud_boat_recovery_rejects_snapshot_and_result_tampering() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            for adapter in ("qq.official", "onebot.v11"):
                user = f"cloud-recovery-integrity-{adapter}"
                await runtime.dispatch(_context(adapter, user, f"create-{adapter}"), "开始修仙")
                await runtime.dispatch(_context(adapter, user, f"seek-{adapter}"), "寻仙问道")
                _prepare_player(runtime, adapter, user)
                started = await runtime.dispatch(
                    _context(adapter, user, f"board-{adapter}", f"board-{adapter}"),
                    "登上云舟 魔界引导",
                )
                assert started.code == "CLOUD_BOAT_STARTED"
                session_id = started.data["session_id"]
                _expire(runtime, session_id, age=timedelta(hours=25))
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    snapshot = json.loads(
                        connection.execute(
                            "SELECT snapshot_json FROM cloud_boat_sessions WHERE session_id=?", (session_id,)
                        ).fetchone()[0]
                    )
                    snapshot["destination"] = "tampered.destination"
                    connection.execute(
                        "UPDATE cloud_boat_sessions SET snapshot_json=? WHERE session_id=?",
                        (json.dumps(snapshot, ensure_ascii=False), session_id),
                    )
                rejected = await runtime.dispatch(
                    _context(adapter, user, f"recover-reject-{adapter}", f"recover-{adapter}"),
                    "恢复云舟",
                )
                assert rejected.code == "PERSISTENCE_ERROR"
                assert _session_state(runtime, adapter, user, session_id)[0:2] == (
                    "xuantian.cloud_city",
                    500,
                )
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE cloud_boat_sessions SET snapshot_json=? WHERE session_id=?",
                        (
                            json.dumps(
                                {
                                    "route_key": "route.cloud_to_abyss_intro",
                                    "source": "xuantian.cloud_city",
                                    "destination": "demon.abyss_gate",
                                    "stamina_cost": 10,
                                    "currency_cost": 500,
                                    "pass_key": None,
                                    "pass_quantity": 0,
                                    "required_realm": "foundation",
                                    "required_layer": 1,
                                    "required_quest": None,
                                },
                                ensure_ascii=False,
                                sort_keys=True,
                            ),
                            session_id,
                        ),
                    )
                recovered = await runtime.dispatch(
                    _context(adapter, user, f"recover-{adapter}", f"recover-{adapter}"),
                    "恢复云舟",
                )
                assert recovered.code == "CLOUD_BOAT_RECOVERED"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    original = connection.execute(
                        "SELECT result_json FROM operations WHERE operation_id=?", (f"recover-{adapter}",)
                    ).fetchone()[0]
                    payload = json.loads(original)
                    payload["destination"] = "tampered.destination"
                    connection.execute(
                        "UPDATE operations SET result_json=? WHERE operation_id=?",
                        (json.dumps(payload, ensure_ascii=False), f"recover-{adapter}"),
                    )
                replay_rejected = await runtime.dispatch(
                    _context(adapter, user, f"recover-replay-reject-{adapter}", f"recover-{adapter}"),
                    "恢复云舟",
                )
                assert replay_rejected.code == "PERSISTENCE_ERROR"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE operations SET result_json=? WHERE operation_id=?",
                        (original, f"recover-{adapter}"),
                    )
                replay = await runtime.dispatch(
                    _context(adapter, user, f"recover-replay-{adapter}", f"recover-{adapter}"),
                    "恢复云舟",
                )
                assert replay.code == "CLOUD_BOAT_RECOVERED"
                assert replay.data["idempotent_replay"] is True
            await runtime.close()

    asyncio.run(run())
