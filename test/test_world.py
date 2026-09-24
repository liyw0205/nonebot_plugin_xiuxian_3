from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime


def _context(user_id: str, request_id: str, *, operation_id: str = "") -> CommandContext:
    return CommandContext(adapter="web", user_id=user_id, request_id=request_id, operation_id=operation_id)


def _foundation_player(runtime, user_id: str) -> None:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            """
            UPDATE players
            SET stage = 'cultivator', realm_key = 'foundation', realm_layer = 1,
                location_key = 'xuantian.new_town', stamina = 30, stamina_max = 30,
                spirit_stones = 100, inventory_json = ?
            WHERE platform_user_id = ?
            """,
            (json.dumps({"item.cave_pass_basic": 1}, ensure_ascii=False), user_id),
        )


def test_cave_travel_locks_costs_and_settles_idempotently() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            user = "cave-traveller"
            await runtime.dispatch(_context(user, "create"), "开始修仙")
            await runtime.dispatch(_context(user, "seek"), "寻仙问道")
            _foundation_player(runtime, user)

            preview = await runtime.dispatch(_context(user, "preview"), "移动预览 雾隐洞天")
            assert preview.code == "TRAVEL_PREVIEW"
            assert preview.data["ready"] is True

            started = await runtime.dispatch(
                _context(user, "start", operation_id="travel-start"), "前往 雾隐洞天"
            )
            assert started.code == "TRAVEL_STARTED"
            replay = await runtime.dispatch(
                _context(user, "start-replay", operation_id="travel-start"), "前往 雾隐洞天"
            )
            assert replay.data["idempotent_replay"] is True
            with sqlite3.connect(runtime.settings.database_path) as connection:
                row = connection.execute(
                    "SELECT stamina, spirit_stones, inventory_json, location_key FROM players WHERE platform_user_id = ?",
                    (user,),
                ).fetchone()
                assert row[0:2] == (25, 90)
                assert json.loads(row[2]) == {}
                assert row[3] == "xuantian.new_town"
                connection.execute(
                    "UPDATE travel_sessions SET ends_at = ? WHERE session_id = ?",
                    ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(), started.data["session_id"]),
                )

            settled = await runtime.dispatch(
                _context(user, "settle", operation_id="travel-settle"), "结算移动"
            )
            assert settled.code == "TRAVEL_COMPLETED"
            again = await runtime.dispatch(
                _context(user, "settle-replay", operation_id="travel-settle"), "结算移动"
            )
            assert again.data["idempotent_replay"] is True
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute(
                    "SELECT location_key FROM players WHERE platform_user_id = ?", (user,)
                ).fetchone()[0] == "cave.mist_grotto"
            await runtime.close()

    asyncio.run(run())


def test_cave_travel_is_mutually_exclusive_with_cultivation() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            user = "cave-busy"
            await runtime.dispatch(_context(user, "create"), "开始修仙")
            await runtime.dispatch(_context(user, "seek"), "寻仙问道")
            _foundation_player(runtime, user)
            with sqlite3.connect(runtime.settings.database_path) as connection:
                player_id = connection.execute(
                    "SELECT id FROM players WHERE platform_user_id = ?", (user,)
                ).fetchone()[0]
                now = datetime.now(timezone.utc).isoformat()
                connection.execute(
                    """
                    INSERT INTO production_orders(
                        order_id, player_id, operation_id, recipe_key, status,
                        starts_at, ends_at, snapshot_json, result_json, created_at, updated_at
                    ) VALUES ('busy-order', ?, 'busy-operation', 'recipe.test', 'processing', ?, ?, '{}', '{}', ?, ?)
                    """,
                    (player_id, now, (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(), now, now),
                )
            blocked = await runtime.dispatch(_context(user, "travel"), "前往 雾隐洞天")
            assert blocked.code == "TRAVEL_BUSY"
            await runtime.close()

    asyncio.run(run())


def test_qq_and_onebot_sky_terrace_travel_and_trial_location_gate() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            for adapter, user in (("qq.official", "qq-sky-terrace"), ("onebot.v11", "onebot-sky-terrace")):
                await runtime.dispatch(
                    CommandContext(adapter=adapter, user_id=user, request_id=f"create-{adapter}"), "开始修仙"
                )
                await runtime.dispatch(
                    CommandContext(adapter=adapter, user_id=user, request_id=f"seek-{adapter}"), "寻仙问道"
                )
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE players SET stage='cultivator', realm_key='tribulation', realm_layer=3, "
                        "endgame_status='tribulation', location_key='xuantian.new_town', stamina=30, "
                        "inventory_json=? WHERE platform=? AND platform_user_id=?",
                        (json.dumps({"item.tribulation_token": 2}), adapter, user),
                    )

                context = lambda request, operation="": CommandContext(
                    adapter=adapter, user_id=user, request_id=request, operation_id=operation
                )
                wrong_location = await runtime.dispatch(
                    context(f"wrong-location-{adapter}", f"wrong-location-{adapter}"),
                    "开始天劫试炼 身心劫",
                )
                assert wrong_location.code == "TRIBULATION_LOCATION_REQUIRED"
                blocked_route = await runtime.dispatch(
                    context(f"blocked-route-{adapter}", f"blocked-route-{adapter}"), "前往 天劫台"
                )
                assert blocked_route.code == "TRIBULATION_TERRACE_REQUIREMENT_MISSING"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    player = connection.execute(
                        "SELECT inventory_json, location_key FROM players WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    ).fetchone()
                assert json.loads(player[0]) == {"item.tribulation_token": 2}
                assert player[1] == "xuantian.new_town"

                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE players SET location_key='dao.origin_gate' WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    )
                    connection.execute(
                        "UPDATE players SET inventory_json='{}' WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    )
                missing_pass = await runtime.dispatch(context(f"missing-pass-preview-{adapter}"), "移动预览 天劫台")
                assert missing_pass.data["ready"] is False
                assert "通行物品" in missing_pass.data["missing"]
                missing_pass_start = await runtime.dispatch(
                    context(f"missing-pass-{adapter}", f"missing-pass-{adapter}"), "前往 天劫台"
                )
                assert missing_pass_start.code == "TRIBULATION_TERRACE_REQUIREMENT_MISSING"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE players SET inventory_json=? WHERE platform=? AND platform_user_id=?",
                        (json.dumps({"item.tribulation_token": 2}), adapter, user),
                    )
                preview = await runtime.dispatch(context(f"preview-{adapter}"), "移动预览 天劫台")
                assert preview.code == "TRAVEL_PREVIEW"
                assert preview.data["ready"] is True
                started = await runtime.dispatch(
                    context(f"travel-{adapter}", f"travel-{adapter}"), "前往 天劫台"
                )
                assert started.code == "TRAVEL_STARTED"
                replay = await runtime.dispatch(
                    context(f"travel-replay-{adapter}", f"travel-{adapter}"), "前往 天劫台"
                )
                assert replay.data["idempotent_replay"] is True
                during_travel = await runtime.dispatch(
                    context(f"trial-during-travel-{adapter}", f"trial-during-travel-{adapter}"),
                    "开始天劫试炼 身心劫",
                )
                assert during_travel.code == "TRIBULATION_TRIAL_BUSY"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE travel_sessions SET ends_at=? WHERE session_id=?",
                        ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(), started.data["session_id"]),
                    )
                    player = connection.execute(
                        "SELECT inventory_json, location_key FROM players WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    ).fetchone()
                assert json.loads(player[0]) == {"item.tribulation_token": 1}
                assert player[1] == "dao.origin_gate"
                arrived = await runtime.dispatch(
                    context(f"settle-travel-{adapter}", f"settle-travel-{adapter}"), "结算移动"
                )
                assert arrived.code == "TRAVEL_COMPLETED"
                arrival_replay = await runtime.dispatch(
                    context(f"settle-travel-replay-{adapter}", f"settle-travel-{adapter}"), "结算移动"
                )
                assert arrival_replay.data["idempotent_replay"] is True
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    player = connection.execute(
                        "SELECT inventory_json, location_key FROM players WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    ).fetchone()
                assert json.loads(player[0]) == {"item.tribulation_token": 1}
                assert player[1] == "tribulation.sky_terrace"

                trial = await runtime.dispatch(
                    context(f"trial-{adapter}", f"trial-{adapter}"), "开始天劫试炼 身心劫"
                )
                assert trial.code == "TRIAL_STARTED"
                trial_replay = await runtime.dispatch(
                    context(f"trial-replay-{adapter}", f"trial-{adapter}"), "开始天劫试炼 身心劫"
                )
                assert trial_replay.data["idempotent_replay"] is True
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    player = connection.execute(
                        "SELECT inventory_json FROM players WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    ).fetchone()[0]
                    assert json.loads(player) == {}
                    assert connection.execute(
                        "SELECT COUNT(*) FROM tribulation_trial_sessions WHERE player_id=("
                        "SELECT id FROM players WHERE platform=? AND platform_user_id=?)",
                        (adapter, user),
                    ).fetchone()[0] == 1
            await runtime.close()

    asyncio.run(run())


def test_ascension_path_is_reached_by_final_battle_without_a_second_certificate() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            for adapter, user in (("qq.official", "qq-ending-travel"), ("onebot.v11", "ob-ending-travel")):
                context = lambda request, operation="": CommandContext(
                    adapter=adapter, user_id=user, request_id=request, operation_id=operation
                )
                await runtime.dispatch(context(f"create-{adapter}"), "开始修仙")
                await runtime.dispatch(context(f"seek-{adapter}"), "寻仙问道")
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE players SET stage='cultivator', realm_key='tribulation', realm_layer=10, "
                        "endgame_status='ascension_ready', location_key='tribulation.sky_terrace', stamina=30, "
                        "stamina_max=30, inventory_json=? WHERE platform=? AND platform_user_id=?",
                        (json.dumps({"item.ascension_certificate": 1}), adapter, user),
                    )

                preview = await runtime.dispatch(context(f"preview-{adapter}"), "移动预览 飞升路")
                assert preview.code == "TRAVEL_PREVIEW"
                assert preview.data["ready"] is True
                started = await runtime.dispatch(
                    context(f"start-{adapter}", f"start-{adapter}"), "前往 飞升路"
                )
                assert started.code == "TRAVEL_STARTED"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    row = connection.execute(
                        "SELECT inventory_json, location_key FROM players WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    ).fetchone()
                    assert json.loads(row[0]) == {"item.ascension_certificate": 1}
                    assert row[1] == "tribulation.sky_terrace"
                    connection.execute(
                        "UPDATE travel_sessions SET ends_at=? WHERE session_id=?",
                        ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(), started.data["session_id"]),
                    )
                settled = await runtime.dispatch(
                    context(f"settle-{adapter}", f"settle-{adapter}"), "结算移动"
                )
                assert settled.code == "TRAVEL_COMPLETED"
                assert settled.data["pass_consumed"] is False
                replay = await runtime.dispatch(
                    context(f"settle-replay-{adapter}", f"settle-{adapter}"), "结算移动"
                )
                assert replay.data["idempotent_replay"] is True
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    state = connection.execute(
                        "SELECT inventory_json, location_key FROM players WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    ).fetchone()
                    assert json.loads(state[0]) == {"item.ascension_certificate": 1}
                    assert state[1] == "ascension.heaven_path"

                    connection.execute(
                        "UPDATE players SET endgame_status='remained_in_world', location_key='ascension.heaven_path', stamina=30 "
                        "WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    )
                left_preview = await runtime.dispatch(context(f"left-preview-{adapter}"), "移动预览 留界殿")
                assert left_preview.data["ready"] is True
                left_started = await runtime.dispatch(
                    context(f"left-start-{adapter}", f"left-start-{adapter}"), "前往 留界殿"
                )
                assert left_started.code == "TRAVEL_STARTED"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE travel_sessions SET ends_at=? WHERE session_id=?",
                        ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(), left_started.data["session_id"]),
                    )
                left_settled = await runtime.dispatch(
                    context(f"left-settle-{adapter}", f"left-settle-{adapter}"), "结算移动"
                )
                assert left_settled.code == "TRAVEL_COMPLETED"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    state = connection.execute(
                        "SELECT stamina, location_key FROM players WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    ).fetchone()
                    assert state == (20, "ascension.left_world_hall")

                    connection.execute(
                        "UPDATE players SET endgame_status='ascended', location_key='xuantian.new_town' "
                        "WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    )
                frozen_preview = await runtime.dispatch(context(f"frozen-preview-{adapter}"), "移动预览 近郊")
                assert frozen_preview.data["ready"] is False
                assert "当前状态" in frozen_preview.data["missing"]
                frozen_start = await runtime.dispatch(context(f"frozen-start-{adapter}"), "前往 近郊")
                assert frozen_start.code == "LOCATION_LOCKED"
            await runtime.close()

    asyncio.run(run())
