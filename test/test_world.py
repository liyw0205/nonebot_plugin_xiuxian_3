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
