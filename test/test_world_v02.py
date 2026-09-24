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


def _prepare_player(runtime, adapter: str, user: str, *, realm: str, location: str, inventory: dict[str, int] | None = None) -> None:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            """
            UPDATE players
            SET stage='cultivator', realm_key=?, realm_layer=1, location_key=?,
                stamina=30, stamina_max=30, spirit_stones=1000, inventory_json=?, intro_json='{}'
            WHERE platform=? AND platform_user_id=?
            """,
            (realm, location, json.dumps(inventory or {}, ensure_ascii=False), adapter, user),
        )


def _expire_boat(runtime, session_id: str) -> None:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE cloud_boat_sessions SET ends_at=? WHERE session_id=?",
            ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(), session_id),
        )


def test_cloud_boat_route_is_idempotent_and_qq_onebot_compatible() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            for adapter, user in (("qq.official", "qq-cloud"), ("onebot.v11", "ob-cloud")):
                await runtime.adapters.dispatch(adapter, _context(adapter, user, f"create-{adapter}"), "开始修仙")
                await runtime.adapters.dispatch(adapter, _context(adapter, user, f"seek-{adapter}"), "寻仙问道")
                _prepare_player(
                    runtime,
                    adapter,
                    user,
                    realm="golden_core",
                    location="xuantian.cloud_city",
                    inventory={"item.cave_pass_advanced": 1},
                )

                started = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, f"board-{adapter}", f"board-{adapter}"),
                    "登上云舟 洞天二层",
                )
                assert started.code == "CLOUD_BOAT_STARTED"
                replay = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, f"board-replay-{adapter}", f"board-{adapter}"),
                    "登上云舟 洞天二层",
                )
                assert replay.data["idempotent_replay"] is True
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    state = connection.execute(
                        "SELECT spirit_stones, stamina, inventory_json, location_key FROM players WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    ).fetchone()
                assert state[0:2] == (500, 22)
                assert json.loads(state[2]) == {}
                assert state[3] == "xuantian.cloud_city"

                _expire_boat(runtime, started.data["session_id"])
                settled = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, f"settle-{adapter}", f"settle-{adapter}"),
                    "结算云舟",
                )
                assert settled.code == "CLOUD_BOAT_ARRIVED"
                settle_replay = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, f"settle-replay-{adapter}", f"settle-{adapter}"),
                    "结算云舟",
                )
                assert settle_replay.data["idempotent_replay"] is True
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    state = connection.execute(
                        "SELECT location_key FROM players WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    ).fetchone()
                    snapshot = connection.execute(
                        "SELECT status, snapshot_json FROM cloud_boat_sessions WHERE session_id=?",
                        (started.data["session_id"],),
                    ).fetchone()
                assert state[0] == "cave.mist_grotto_2"
                assert snapshot[0] == "arrived"
                assert json.loads(snapshot[1])["rule_version"] == "world-0.2.0"
                bypass = await runtime.dispatch(
                    _context(adapter, user, f"bypass-{adapter}", f"bypass-{adapter}"),
                    "前往 雾隐洞天二层",
                )
                assert bypass.code == "LOCATION_REQUIREMENT_MISSING"
            await runtime.close()

    asyncio.run(run())


def test_demon_intro_requires_arrival_and_is_once_only() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            adapter, user = "onebot.v11", "ob-demon"
            await runtime.dispatch(_context(adapter, user, "create"), "开始修仙")
            await runtime.dispatch(_context(adapter, user, "seek"), "寻仙问道")
            _prepare_player(runtime, adapter, user, realm="foundation", location="xuantian.cloud_city")
            started = await runtime.dispatch(_context(adapter, user, "board", "board"), "登上云舟 魔界引导")
            assert started.code == "CLOUD_BOAT_STARTED"
            _expire_boat(runtime, started.data["session_id"])
            assert (await runtime.dispatch(_context(adapter, user, "settle", "settle"), "结算云舟")).code == "CLOUD_BOAT_ARRIVED"

            accepted = await runtime.dispatch(
                _context(adapter, user, "intro", "intro"), "接受魔界引导 确认风险"
            )
            assert accepted.code == "DEMON_INTRO_ACCEPTED"
            replay = await runtime.dispatch(
                _context(adapter, user, "intro-replay", "intro"), "接受魔界引导"
            )
            assert replay.data["idempotent_replay"] is True
            duplicate = await runtime.dispatch(_context(adapter, user, "intro-duplicate", "intro-2"), "接受魔界引导")
            assert duplicate.code == "DEMON_INTRO_ALREADY_COMPLETED"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                player = connection.execute(
                    "SELECT spirit_stones, faction_reputation_json, intro_json FROM players WHERE platform=? AND platform_user_id=?",
                    (adapter, user),
                ).fetchone()
                events = connection.execute(
                    "SELECT COUNT(*) FROM quest_events WHERE player_id=(SELECT id FROM players WHERE platform=? AND platform_user_id=?) AND quest_key='quest.demon_intro'",
                    (adapter, user),
                ).fetchone()[0]
            assert player[0] == 400
            assert json.loads(player[1]) == {"demon": 20}
            assert set(json.loads(player[2])["flags"]) == {"quest.demon_intro", "access.demon_abyss_gate"}
            assert events == 1
            await runtime.close()

    asyncio.run(run())


def test_cloud_boat_recovery_uses_frozen_route_after_24_hours() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            adapter, user = "qq.official", "qq-cloud-recovery"
            await runtime.dispatch(_context(adapter, user, "create"), "开始修仙")
            await runtime.dispatch(_context(adapter, user, "seek"), "寻仙问道")
            _prepare_player(runtime, adapter, user, realm="foundation", location="xuantian.cloud_city")
            started = await runtime.dispatch(_context(adapter, user, "board", "board"), "登上云舟 魔界引导")
            assert started.code == "CLOUD_BOAT_STARTED"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE cloud_boat_sessions SET ends_at=? WHERE session_id=?",
                    ((datetime.now(timezone.utc) - timedelta(hours=25)).isoformat(), started.data["session_id"]),
                )
            recovered = await runtime.dispatch(_context(adapter, user, "recover", "recover"), "恢复云舟")
            assert recovered.code == "CLOUD_BOAT_RECOVERED"
            replay = await runtime.dispatch(_context(adapter, user, "recover-replay", "recover"), "恢复云舟")
            assert replay.data["idempotent_replay"] is True
            with sqlite3.connect(runtime.settings.database_path) as connection:
                state = connection.execute(
                    "SELECT location_key, spirit_stones, stamina FROM players WHERE platform=? AND platform_user_id=?",
                    (adapter, user),
                ).fetchone()
                session = connection.execute(
                    "SELECT status, result_json FROM cloud_boat_sessions WHERE session_id=?",
                    (started.data["session_id"],),
                ).fetchone()
            assert state == ("demon.abyss_gate", 500, 20)
            assert session[0] == "arrived"
            assert json.loads(session[1])["recovered"] is True
            await runtime.close()

    asyncio.run(run())


def test_array_hall_permission_does_not_leak_production_and_replays() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            adapter, user = "qq.official", "qq-array"
            await runtime.dispatch(_context(adapter, user, "create"), "开始修仙")
            await runtime.dispatch(_context(adapter, user, "seek"), "寻仙问道")
            _prepare_player(runtime, adapter, user, realm="qi_gathering", location="xuantian.array_hall")
            denied = await runtime.dispatch(_context(adapter, user, "denied", "denied"), "使用阵堂")
            assert denied.code == "ARRAY_HALL_PERMISSION_DENIED"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute(
                    "SELECT stamina FROM players WHERE platform=? AND platform_user_id=?", (adapter, user)
                ).fetchone()[0] == 30
                connection.execute(
                    "UPDATE players SET intro_json=? WHERE platform=? AND platform_user_id=?",
                    (json.dumps({"flags": ["array_hall.invite"]}), adapter, user),
                )
            authorized = await runtime.dispatch(_context(adapter, user, "use", "use"), "使用阵堂")
            assert authorized.code == "ARRAY_HALL_AUTHORIZED"
            replay = await runtime.dispatch(_context(adapter, user, "use-replay", "use"), "使用阵堂")
            assert replay.data["idempotent_replay"] is True
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute(
                    "SELECT stamina FROM players WHERE platform=? AND platform_user_id=?", (adapter, user)
                ).fetchone()[0] == 27
            await runtime.close()

    asyncio.run(run())
