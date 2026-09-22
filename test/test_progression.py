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
            assert "入门" in profile.message
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


def test_expired_cultivation_requires_recovery_and_replays_once() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            user = "expired-user"
            await _enter_cultivator(runtime, user)
            started = await runtime.dispatch(_context(user, "start"), "开始修炼")
            assert started.code == "CULTIVATION_STARTED"
            old = datetime.now(timezone.utc) - timedelta(hours=25)
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE cultivation_sessions SET ends_at = ? WHERE session_id = ?",
                    ((old - timedelta(minutes=1)).isoformat(), started.data["session_id"]),
                )

            expired = await runtime.dispatch(_context(user, "settle"), "结算修炼")
            assert expired.code == "CULTIVATION_EXPIRED"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                status = connection.execute(
                    "SELECT status FROM cultivation_sessions WHERE session_id = ?",
                    (started.data["session_id"],),
                ).fetchone()[0]
            assert status == "expired"
            blocked = await runtime.dispatch(_context(user, "start-again"), "开始修炼")
            assert blocked.code == "CULTIVATION_RECOVERY_REQUIRED"

            recovered = await runtime.dispatch(
                _context(user, "recover", operation_id="recover-1"),
                "恢复修炼",
            )
            assert recovered.code == "CULTIVATION_RECOVERED"
            assert recovered.data["cultivation_gain"] >= 41
            replay = await runtime.dispatch(
                _context(user, "recover-replay", operation_id="recover-1"),
                "恢复修炼",
            )
            assert replay.code == "CULTIVATION_RECOVERED"
            assert replay.data["idempotent_replay"] is True
            assert replay.data["cultivation"] == recovered.data["cultivation"]
            duplicate = await runtime.dispatch(_context(user, "recover-2"), "恢复修炼")
            assert duplicate.code == "CULTIVATION_ALREADY_RECOVERED"
            await runtime.close()

    asyncio.run(run())


def test_qi_sensing_milestone_unlocks_are_boundary_stable() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            user = "milestone-user"
            await _enter_cultivator(runtime, user)
            thresholds = (170, 560, 1130, 1360)
            expected = (
                {"guidance.path", "livelihood.service.second.preview"},
                {"cultivate.seclusion.preview", "sect.regular_task"},
                {"progression.breakthrough.preview", "exploration.elite.preview"},
                {"progression.cross_realm.preview"},
            )
            for index, (target_layer, cultivation) in enumerate(zip((3, 6, 9, 10), thresholds, strict=True)):
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE players SET realm_layer = ?, cultivation = ? WHERE platform_user_id = ?",
                        (target_layer - 1, cultivation, user),
                    )
                result = await runtime.dispatch(
                    _context(user, f"advance-{index}", operation_id=f"advance-{index}"),
                    "晋升境界",
                )
                assert result.code == "REALM_LAYER_ADVANCED"
                assert {item["key"] for item in result.data["unlocks"]} == expected[index]
                assert all(item["status"] in {"open", "preview"} for item in result.data["unlocks"])
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE players SET realm_layer = 9, cultivation = 1360 WHERE platform_user_id = ?",
                    (user,),
                )
            replay = await runtime.dispatch(
                _context(user, "advance-replay", operation_id="advance-3"),
                "晋升境界",
            )
            assert replay.data["idempotent_replay"] is True
            assert {item["key"] for item in replay.data["unlocks"]} == {"progression.cross_realm.preview"}
            await runtime.close()

    asyncio.run(run())


def test_spirit_spring_requires_access_and_enforces_daily_quota() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            user = "spirit-spring-user"
            await _enter_cultivator(runtime, user)
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE players SET realm_layer = 2, cultivation = 80 WHERE platform_user_id = ?",
                    (user,),
                )

            not_at_spring = await runtime.dispatch(_context(user, "spring-before"), "开始修炼 灵泉")
            assert not_at_spring.code == "LOCATION_REQUIRED"
            travel = await runtime.dispatch(_context(user, "spring-travel"), "前往灵泉谷")
            assert travel.code == "TRAVEL_COMPLETED"
            assert travel.data["stamina"] == 22

            gains: list[int] = []
            for index in range(4):
                started = await runtime.dispatch(
                    _context(user, f"spring-start-{index}"),
                    "开始修炼 灵泉",
                )
                assert started.code == "CULTIVATION_STARTED"
                assert started.data["mode_key"] == "cultivate.spirit_spring"
                assert started.data["stamina_cost"] == 3
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE cultivation_sessions SET ends_at = ? WHERE session_id = ?",
                        ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(), started.data["session_id"]),
                    )
                settled = await runtime.dispatch(_context(user, f"spring-settle-{index}"), "结算修炼")
                assert settled.code == "CULTIVATION_SETTLED"
                assert settled.data["mode_key"] == "cultivate.spirit_spring"
                assert settled.data["cultivation_gain"] >= 80
                gains.append(settled.data["cultivation_gain"])
            limited = await runtime.dispatch(_context(user, "spring-limit"), "开始修炼 灵泉")
            assert limited.code == "CULTIVATION_DAILY_LIMIT"
            assert len(set(gains)) == 1
            profile = await runtime.dispatch(_context(user, "spring-profile"), "我的状态")
            assert "灵泉谷" in profile.message
            await runtime.close()

    asyncio.run(run())
