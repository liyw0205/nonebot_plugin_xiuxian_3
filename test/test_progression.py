from __future__ import annotations

import asyncio
import json
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


def test_foundation_late_milestone_is_recorded_with_the_layer_advance() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            user = "foundation-late-user"
            await _enter_cultivator(runtime, user)
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    """
                    UPDATE players
                    SET realm_key = 'foundation', realm_layer = 8, cultivation = 6300,
                        total_cultivation = 10000
                    WHERE platform_user_id = ?
                    """,
                    (user,),
                )

            first = await runtime.dispatch(
                _context(user, "foundation-late", operation_id="foundation-late-advance"),
                "晋升境界",
            )
            assert first.code == "REALM_LAYER_ADVANCED"
            assert {item["key"] for item in first.data["unlocks"]} == {"milestone.foundation_late"}
            replay = await runtime.dispatch(
                _context(user, "foundation-late-replay", operation_id="foundation-late-advance"),
                "晋升境界",
            )
            assert replay.data["idempotent_replay"] is True
            assert replay.data["unlocks"] == first.data["unlocks"]
            with sqlite3.connect(runtime.settings.database_path) as connection:
                record = connection.execute(
                    """
                    SELECT milestone_key, status, source_operation_id, snapshot_json, content_version, rule_version
                    FROM progression_milestones
                    """
                ).fetchone()
                assert record[0:3] == (
                    "milestone.foundation_late",
                    "unlocked",
                    "foundation-late-advance",
                )
                assert json.loads(record[3]) == {
                    "domain_level": 0,
                    "maximum_faction_reputation": 0,
                    "realm_key": "foundation",
                    "realm_layer": 9,
                    "required_layer": 9,
                    "required_domain_level": 0,
                    "required_max_faction_reputation": 0,
                    "required_realm": "foundation",
                    "required_total_cultivation": 10000,
                    "total_cultivation": 10000,
                    "required_void_route_count": 0,
                    "void_route_count": 0,
                }
                assert record[4:] == ("content-0.2", "progression-0.2.0")
            await runtime.close()

    asyncio.run(run())


def test_void_refining_late_milestone_requires_route_discoveries() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            user = "void-late-user"
            await _enter_cultivator(runtime, user)
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    """
                    UPDATE players
                    SET realm_key = 'void_refining', realm_layer = 8, cultivation = 1700000,
                        total_cultivation = 2500000, void_route_count = 2
                    WHERE platform_user_id = ?
                    """,
                    (user,),
                )
            below = await runtime.dispatch(_context(user, "void-late-below"), "晋升境界")
            assert below.code == "REALM_LAYER_ADVANCED"
            assert below.data["unlocks"] == []

            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    """
                    UPDATE players
                    SET cultivation = 2150000, total_cultivation = 2500000, void_route_count = 3
                    WHERE platform_user_id = ?
                    """,
                    (user,),
                )
            fulfilled = await runtime.dispatch(_context(user, "void-late-fulfilled"), "晋升境界")
            assert fulfilled.code == "REALM_LAYER_ADVANCED"
            assert {item["key"] for item in fulfilled.data["unlocks"]} == {
                "milestone.void_refining_late"
            }
            with sqlite3.connect(runtime.settings.database_path) as connection:
                snapshot = json.loads(
                    connection.execute(
                        "SELECT snapshot_json FROM progression_milestones WHERE milestone_key = 'milestone.void_refining_late'"
                    ).fetchone()[0]
                )
                assert snapshot["void_route_count"] == snapshot["required_void_route_count"] == 3
            await runtime.close()

    asyncio.run(run())


def test_soul_transformation_late_milestone_requires_domain_level() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            user = "soul-late-user"
            await _enter_cultivator(runtime, user)
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    """
                    UPDATE players
                    SET realm_key = 'soul_transformation', realm_layer = 8, cultivation = 480000,
                        total_cultivation = 720000, domain_level = 2
                    WHERE platform_user_id = ?
                    """,
                    (user,),
                )
            below = await runtime.dispatch(_context(user, "soul-late-below"), "晋升境界")
            assert below.code == "REALM_LAYER_ADVANCED"
            assert below.data["unlocks"] == []

            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    """
                    UPDATE players
                    SET cultivation = 600000, total_cultivation = 720000, domain_level = 3
                    WHERE platform_user_id = ?
                    """,
                    (user,),
                )
            fulfilled = await runtime.dispatch(_context(user, "soul-late-fulfilled"), "晋升境界")
            assert fulfilled.code == "REALM_LAYER_ADVANCED"
            assert {item["key"] for item in fulfilled.data["unlocks"]} == {
                "milestone.soul_transformation_late"
            }
            with sqlite3.connect(runtime.settings.database_path) as connection:
                snapshot = json.loads(
                    connection.execute(
                        "SELECT snapshot_json FROM progression_milestones WHERE milestone_key = 'milestone.soul_transformation_late'"
                    ).fetchone()[0]
                )
                assert snapshot["domain_level"] == snapshot["required_domain_level"] == 3
            await runtime.close()

    asyncio.run(run())


def test_nascent_soul_late_milestone_requires_reputation_and_replays() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            user = "nascent-late-user"
            await _enter_cultivator(runtime, user)
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    """
                    UPDATE players
                    SET realm_key = 'nascent_soul', realm_layer = 8, cultivation = 153000,
                        total_cultivation = 210000, faction_reputation_json = ?
                    WHERE platform_user_id = ?
                    """,
                    (json.dumps({"faction.abyss": 999}), user),
                )
            below = await runtime.dispatch(_context(user, "nascent-late-below"), "晋升境界")
            assert below.code == "REALM_LAYER_ADVANCED"
            assert below.data["unlocks"] == []

            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    """
                    UPDATE players
                    SET cultivation = 190000, total_cultivation = 210000, faction_reputation_json = ?
                    WHERE platform_user_id = ?
                    """,
                    (json.dumps({"faction.abyss": 1000, "faction.xuantian": 300}), user),
                )
            fulfilled = await runtime.dispatch(
                _context(user, "nascent-late-fulfilled", operation_id="nascent-late-advance"),
                "晋升境界",
            )
            assert fulfilled.code == "REALM_LAYER_ADVANCED"
            assert {item["key"] for item in fulfilled.data["unlocks"]} == {"milestone.nascent_soul_late"}
            replay = await runtime.dispatch(
                _context(user, "nascent-late-replay", operation_id="nascent-late-advance"),
                "晋升境界",
            )
            assert replay.data["idempotent_replay"] is True
            with sqlite3.connect(runtime.settings.database_path) as connection:
                snapshot = json.loads(
                    connection.execute(
                        "SELECT snapshot_json FROM progression_milestones WHERE milestone_key = 'milestone.nascent_soul_late'"
                    ).fetchone()[0]
                )
                assert snapshot["maximum_faction_reputation"] == 1000
                assert snapshot["required_max_faction_reputation"] == 1000
            await runtime.close()

    asyncio.run(run())


def test_foundation_late_milestone_requires_total_cultivation_threshold() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            user = "foundation-late-threshold"
            await _enter_cultivator(runtime, user)
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    """
                    UPDATE players
                    SET realm_key = 'foundation', realm_layer = 8, cultivation = 6300,
                        total_cultivation = 9999
                    WHERE platform_user_id = ?
                    """,
                    (user,),
                )
            below = await runtime.dispatch(_context(user, "foundation-late-below"), "晋升境界")
            assert below.code == "REALM_LAYER_ADVANCED"
            assert below.data["unlocks"] == []
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute("SELECT COUNT(*) FROM progression_milestones").fetchone()[0] == 0
                connection.execute(
                    "UPDATE players SET cultivation = 7700, total_cultivation = 10000 WHERE platform_user_id = ?",
                    (user,),
                )
            fulfilled = await runtime.dispatch(_context(user, "foundation-late-fulfilled"), "晋升境界")
            assert fulfilled.code == "REALM_LAYER_ADVANCED"
            assert {item["key"] for item in fulfilled.data["unlocks"]} == {"milestone.foundation_late"}
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


def test_seclusion_requires_qi_gathering_locks_resources_and_replays_once() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            user = "seclusion-user"
            await _enter_cultivator(runtime, user)

            before_gate = await runtime.dispatch(_context(user, "seclusion-gate"), "开始修炼 静修")
            assert before_gate.code == "CULTIVATION_REQUIREMENT_MISSING"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                player_id = connection.execute(
                    "SELECT id FROM players WHERE platform_user_id = ?", (user,)
                ).fetchone()[0]
                connection.execute(
                    "UPDATE players SET realm_key = 'qi_gathering', realm_layer = 1, stamina = 5, energy = 30 WHERE id = ?",
                    (player_id,),
                )

            insufficient = await runtime.dispatch(_context(user, "seclusion-insufficient"), "开始修炼 静修")
            assert insufficient.code == "RESOURCE_INSUFFICIENT"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute(
                    "SELECT stamina, energy FROM players WHERE id = ?", (player_id,)
                ).fetchone() == (5, 30)
                connection.execute("UPDATE players SET stamina = 30, energy = 30 WHERE id = ?", (player_id,))

            operation = _context(user, "seclusion-concurrent", operation_id="seclusion-start")
            first, replay = await asyncio.gather(
                runtime.dispatch(operation, "开始修炼 静修"),
                runtime.dispatch(operation, "开始修炼 静修"),
            )
            assert first.code == replay.code == "CULTIVATION_STARTED"
            assert sum(result.data["idempotent_replay"] is False for result in (first, replay)) == 1
            started = first if not first.data["idempotent_replay"] else replay
            assert started.data["mode_key"] == "cultivate.seclusion"
            assert started.data["stamina_cost"] == 6
            assert started.data["energy_cost"] == 2
            assert datetime.fromisoformat(started.data["ends_at"]) - datetime.fromisoformat(
                started.data["starts_at"]
            ) == timedelta(minutes=30)
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute(
                    "SELECT stamina, energy FROM players WHERE id = ?", (player_id,)
                ).fetchone() == (24, 28)
                assert connection.execute(
                    "SELECT COUNT(*) FROM cultivation_sessions WHERE player_id = ?", (player_id,)
                ).fetchone()[0] == 1

            _finish_session(runtime, user)
            settled = await runtime.dispatch(_context(user, "seclusion-settle"), "结算修炼")
            assert settled.code == "CULTIVATION_SETTLED"
            assert settled.data["mode_key"] == "cultivate.seclusion"
            assert settled.data["cultivation_gain"] >= 170
            assert settled.data["realm_key"] == "qi_gathering"
            assert settled.data["realm_layer"] == 1

            second = await runtime.dispatch(_context(user, "seclusion-second"), "开始修炼 静修")
            assert second.code == "CULTIVATION_STARTED"
            cancelled = await runtime.dispatch(_context(user, "seclusion-cancel"), "取消修炼")
            assert cancelled.code == "CULTIVATION_CANCELLED"
            assert cancelled.data["stamina_refund"] == 6
            assert cancelled.data["energy_refund"] == 2
            assert cancelled.data["stamina"] == 24
            assert cancelled.data["energy"] == 28
            limited = await runtime.dispatch(_context(user, "seclusion-limit"), "开始修炼 静修")
            assert limited.code == "CULTIVATION_DAILY_LIMIT"
            await runtime.close()

    asyncio.run(run())


def test_seclusion_rejects_party_combat_and_production_locks() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            user = "seclusion-lock-user"
            await _enter_cultivator(runtime, user)
            now = datetime.now(timezone.utc).isoformat()
            with sqlite3.connect(runtime.settings.database_path) as connection:
                player_id = connection.execute(
                    "SELECT id FROM players WHERE platform_user_id = ?", (user,)
                ).fetchone()[0]
                connection.execute(
                    "UPDATE players SET realm_key = 'qi_gathering', realm_layer = 1 WHERE id = ?",
                    (player_id,),
                )
                connection.execute(
                    """
                    INSERT INTO party_members(
                        party_id, player_id, role, status, confirmed_at,
                        invited_at, joined_at, left_at, created_at, updated_at
                    ) VALUES ('party-seclusion-lock', ?, 'leader', 'active', ?, ?, ?, NULL, ?, ?)
                    """,
                    (player_id, now, now, now, now, now),
                )
                resources_before_locks = connection.execute(
                    "SELECT stamina, energy FROM players WHERE id = ?", (player_id,)
                ).fetchone()
            party_locked = await runtime.dispatch(_context(user, "seclusion-party"), "开始修炼 静修")
            assert party_locked.code == "CULTIVATION_BUSY"

            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute("DELETE FROM party_members WHERE player_id = ?", (player_id,))
                connection.execute(
                    """
                    INSERT INTO exploration_sessions(
                        exploration_id, player_id, operation_id, mode_key, location_key, status,
                        starts_at, ends_at, stamina_cost, daily_limit, business_date,
                        snapshot_json, result_json, created_at, updated_at
                    ) VALUES ('explore-seclusion-lock', ?, 'explore-seclusion-lock', 'explore.outskirts',
                              'xuantian.outskirts', 'combat_pending', ?, ?, 0, 0, '2026-09-24', '{}', '{}', ?, ?)
                    """,
                    (player_id, now, now, now, now),
                )
            combat_locked = await runtime.dispatch(_context(user, "seclusion-combat"), "开始修炼 静修")
            assert combat_locked.code == "CULTIVATION_BUSY"

            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute("DELETE FROM exploration_sessions WHERE player_id = ?", (player_id,))
                connection.execute(
                    """
                    INSERT INTO production_orders(
                        order_id, player_id, operation_id, recipe_key, status, starts_at, ends_at,
                        energy_cost, currency_cost, snapshot_json, result_json, created_at, updated_at
                    ) VALUES ('production-seclusion-lock', ?, 'production-seclusion-lock',
                              'recipe.pill.healing_low', 'processing', ?, ?, 0, 0, '{}', '{}', ?, ?)
                    """,
                    (player_id, now, now, now, now),
                )
            production_locked = await runtime.dispatch(_context(user, "seclusion-production"), "开始修炼 静修")
            assert production_locked.code == "CULTIVATION_BUSY"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute(
                    "SELECT stamina, energy FROM players WHERE id = ?", (player_id,)
                ).fetchone() == resources_before_locks
            await runtime.close()

    asyncio.run(run())
