from __future__ import annotations

import asyncio
import json
import shutil
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
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
                    original_operation = connection.execute(
                        "SELECT result_json FROM operations WHERE operation_id=?",
                        (f"board-{adapter}",),
                    ).fetchone()[0]
                    connection.execute(
                        "UPDATE operations SET result_json='{' WHERE operation_id=?",
                        (f"board-{adapter}",),
                    )
                malformed = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, f"board-malformed-{adapter}", f"board-{adapter}"),
                    "登上云舟 洞天二层",
                )
                assert malformed.code == "PERSISTENCE_ERROR"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE operations SET result_json=? WHERE operation_id=?",
                        (original_operation, f"board-{adapter}"),
                    )
                restored = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, f"board-restored-{adapter}", f"board-{adapter}"),
                    "登上云舟 洞天二层",
                )
                assert restored.data["idempotent_replay"] is True
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
            for adapter in ("qq.official", "onebot.v11"):
                user = f"{adapter}-cloud-recovery"
                await runtime.dispatch(_context(adapter, user, "create"), "开始修仙")
                await runtime.dispatch(_context(adapter, user, "seek"), "寻仙问道")
                _prepare_player(runtime, adapter, user, realm="foundation", location="xuantian.cloud_city")
                started = await runtime.dispatch(
                    _context(adapter, user, f"board-{adapter}", f"board-{adapter}"),
                    "登上云舟 魔界引导",
                )
                assert started.code == "CLOUD_BOAT_STARTED"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE cloud_boat_sessions SET ends_at=? WHERE session_id=?",
                        ((datetime.now(timezone.utc) - timedelta(hours=25)).isoformat(), started.data["session_id"]),
                    )
                recovered = await runtime.dispatch(
                    _context(adapter, user, f"recover-{adapter}", f"recover-{adapter}"), "恢复云舟"
                )
                assert recovered.code == "CLOUD_BOAT_RECOVERED"
                replay = await runtime.dispatch(
                    _context(adapter, user, f"recover-replay-{adapter}", f"recover-{adapter}"), "恢复云舟"
                )
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


def test_demon_intro_recovery_rejects_malformed_operation_on_both_adapters() -> None:
    async def run() -> None:
        for adapter in ("qq.official", "onebot.v11"):
            with TemporaryDirectory() as data_dir:
                runtime = create_runtime(data_dir=data_dir, adapters=(adapter,))
                user = f"demon-intro-malformed-{adapter}"
                await runtime.dispatch(_context(adapter, user, "create"), "开始修仙")
                await runtime.dispatch(_context(adapter, user, "seek"), "寻仙问道")
                _prepare_player(runtime, adapter, user, realm="foundation", location="xuantian.cloud_city")
                started = await runtime.dispatch(
                    _context(adapter, user, "board", "board"), "登上云舟 魔界引导"
                )
                assert started.code == "CLOUD_BOAT_STARTED"
                _expire_boat(runtime, started.data["session_id"])
                settled = await runtime.dispatch(
                    _context(adapter, user, "settle", "settle"), "结算云舟"
                )
                assert settled.code == "CLOUD_BOAT_ARRIVED"
                accepted = await runtime.dispatch(
                    _context(adapter, user, "intro", "intro"), "接受魔界引导"
                )
                assert accepted.code == "DEMON_INTRO_ACCEPTED"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    original_operation = connection.execute(
                        "SELECT result_json FROM operations WHERE operation_id=?", ("intro",)
                    ).fetchone()[0]
                    connection.execute(
                        "UPDATE operations SET result_json='{' WHERE operation_id=?", ("intro",)
                    )
                await runtime.close()
                restarted = create_runtime(data_dir=data_dir, adapters=(adapter,))
                malformed = await restarted.dispatch(
                    _context(adapter, user, "intro-malformed", "intro"), "接受魔界引导"
                )
                assert malformed.code == "PERSISTENCE_ERROR"
                with sqlite3.connect(restarted.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE operations SET result_json=? WHERE operation_id=?",
                        (original_operation, "intro"),
                    )
                replay = await restarted.dispatch(
                    _context(adapter, user, "intro-replay", "intro"), "接受魔界引导"
                )
                assert replay.code == "DEMON_INTRO_ACCEPTED"
                assert replay.data["idempotent_replay"] is True
                with sqlite3.connect(restarted.settings.database_path) as connection:
                    state = connection.execute(
                        "SELECT spirit_stones, faction_reputation_json FROM players "
                        "WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    ).fetchone()
                assert state == (400, '{"demon": 20}')
                await restarted.close()

    asyncio.run(run())


def test_cloud_boat_recovery_rejects_malformed_operation_after_restart() -> None:
    async def run() -> None:
        for adapter in ("qq.official", "onebot.v11"):
            with TemporaryDirectory() as data_dir:
                runtime = create_runtime(data_dir=data_dir, adapters=(adapter,))
                user = f"cloud-recovery-malformed-{adapter}"
                await runtime.dispatch(_context(adapter, user, "create"), "开始修仙")
                await runtime.dispatch(_context(adapter, user, "seek"), "寻仙问道")
                _prepare_player(runtime, adapter, user, realm="foundation", location="xuantian.cloud_city")
                started = await runtime.dispatch(
                    _context(adapter, user, "board", "board"), "登上云舟 魔界引导"
                )
                assert started.code == "CLOUD_BOAT_STARTED"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE cloud_boat_sessions SET ends_at=? WHERE session_id=?",
                        ((datetime.now(timezone.utc) - timedelta(hours=25)).isoformat(), started.data["session_id"]),
                    )
                recovered = await runtime.dispatch(
                    _context(adapter, user, "recover", "recover"), "恢复云舟"
                )
                assert recovered.code == "CLOUD_BOAT_RECOVERED"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    original_operation = connection.execute(
                        "SELECT result_json FROM operations WHERE operation_id=?", ("recover",)
                    ).fetchone()[0]
                    connection.execute(
                        "UPDATE operations SET result_json='{' WHERE operation_id=?", ("recover",)
                    )
                await runtime.close()
                restarted = create_runtime(data_dir=data_dir, adapters=(adapter,))
                malformed = await restarted.dispatch(
                    _context(adapter, user, "recover-malformed", "recover"), "恢复云舟"
                )
                assert malformed.code == "PERSISTENCE_ERROR"
                with sqlite3.connect(restarted.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE operations SET result_json=? WHERE operation_id=?",
                        (original_operation, "recover"),
                    )
                replay = await restarted.dispatch(
                    _context(adapter, user, "recover-replay", "recover"), "恢复云舟"
                )
                assert replay.code == "CLOUD_BOAT_RECOVERED"
                assert replay.data["idempotent_replay"] is True
                with sqlite3.connect(restarted.settings.database_path) as connection:
                    state = connection.execute(
                        "SELECT location_key, spirit_stones, stamina FROM players WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    ).fetchone()
                assert state == ("demon.abyss_gate", 500, 20)
                await restarted.close()

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


def test_locked_locations_reject_travel_without_writes_on_both_adapters() -> None:
    async def run() -> None:
        with TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            shutil.copytree(Path(__file__).parents[1] / "data", data_dir)
            runtime = create_runtime(data_dir=data_dir)
            destinations = (
                ("array", "阵堂", "qi_gathering", "xuantian.cloud_city"),
                ("void", "虚空门户", "soul_transformation", "cave.boundary_realm"),
            )
            for adapter in ("qq.official", "onebot.v11"):
                for suffix, label, realm, location in destinations:
                    user = f"locked-{suffix}-{adapter}"
                    await runtime.dispatch(_context(adapter, user, f"create-{user}"), "开始修仙")
                    await runtime.dispatch(_context(adapter, user, f"seek-{user}"), "寻仙问道")
                    _prepare_player(runtime, adapter, user, realm=realm, location=location)

                    preview = await runtime.dispatch(
                        _context(adapter, user, f"preview-{user}"), f"移动预览 {label}"
                    )
                    assert preview.code == "TRAVEL_PREVIEW"
                    assert preview.data["ready"] is False
                    assert "此地尚未开放" in preview.data["missing"]

                    operation_id = f"travel-{user}"
                    rejected = await runtime.dispatch(
                        _context(adapter, user, f"start-{user}", operation_id), f"前往 {label}"
                    )
                    assert rejected.code == "LOCATION_LOCKED"
                    with sqlite3.connect(runtime.settings.database_path) as connection:
                        player = connection.execute(
                            "SELECT location_key, stamina, spirit_stones, inventory_json FROM players "
                            "WHERE platform=? AND platform_user_id=?",
                            (adapter, user),
                        ).fetchone()
                        assert player == (location, 30, 1000, "{}")
                        assert connection.execute(
                            "SELECT COUNT(*) FROM travel_sessions WHERE player_id=(SELECT id FROM players "
                            "WHERE platform=? AND platform_user_id=?)",
                            (adapter, user),
                        ).fetchone()[0] == 0
                        assert connection.execute(
                            "SELECT COUNT(*) FROM operations WHERE operation_id=?", (operation_id,)
                        ).fetchone()[0] == 0
            await runtime.close()

    asyncio.run(run())


def test_travel_operation_replays_before_current_location_status_check() -> None:
    async def run() -> None:
        with TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            shutil.copytree(Path(__file__).parents[1] / "data", data_dir)
            locations_path = data_dir / "地图" / "地点.json"
            locations = json.loads(locations_path.read_text(encoding="utf-8"))
            for location in locations["records"]:
                if location["key"] in {"xuantian.array_hall", "void.portal"}:
                    location["status"] = "open"
            locations_path.write_text(json.dumps(locations, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            runtime = create_runtime(data_dir=data_dir)
            destinations = (
                ("array", "阵堂", "qi_gathering", "xuantian.cloud_city"),
                ("void", "虚空门户", "soul_transformation", "cave.boundary_realm"),
            )
            operations: list[tuple[str, str, str]] = []
            for adapter in ("qq.official", "onebot.v11"):
                for suffix, label, realm, location in destinations:
                    user = f"replay-{suffix}-{adapter}"
                    operation_id = f"travel-{user}"
                    await runtime.dispatch(_context(adapter, user, f"create-{user}"), "开始修仙")
                    await runtime.dispatch(_context(adapter, user, f"seek-{user}"), "寻仙问道")
                    _prepare_player(runtime, adapter, user, realm=realm, location=location)
                    started = await runtime.dispatch(
                        _context(adapter, user, f"start-{user}", operation_id), f"前往 {label}"
                    )
                    assert started.code == "TRAVEL_STARTED"
                    operations.append((adapter, user, operation_id))
            await runtime.close()

            locations = json.loads(locations_path.read_text(encoding="utf-8"))
            for location in locations["records"]:
                if location["key"] in {"xuantian.array_hall", "void.portal"}:
                    location["status"] = "locked"
            locations_path.write_text(json.dumps(locations, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            restarted = create_runtime(data_dir=data_dir)
            for adapter, user, operation_id in operations:
                replay = await restarted.dispatch(
                    _context(adapter, user, f"replay-{user}", operation_id),
                    "前往 阵堂" if "array" in user else "前往 虚空门户",
                )
                assert replay.code == "TRAVEL_STARTED"
                assert replay.data["idempotent_replay"] is True
            await restarted.close()

    asyncio.run(run())
