from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timezone
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime


TEST_NOW = datetime(2026, 9, 22, 12, tzinfo=timezone.utc)


def _context(user_id: str, request_id: str, *, operation_id: str = "") -> CommandContext:
    return CommandContext(
        adapter="web",
        user_id=user_id,
        request_id=request_id,
        operation_id=operation_id,
    )


def _insert_source_operations(runtime, user_id: str, names: list[str]) -> None:
    now = TEST_NOW.isoformat()
    with sqlite3.connect(runtime.settings.database_path) as connection:
        player_id = connection.execute(
            "SELECT id FROM players WHERE platform_user_id = ?", (user_id,)
        ).fetchone()[0]
        for index, name in enumerate(names):
            operation_id = f"source-{index}-{name}"
            connection.execute(
                """
                INSERT INTO operations(
                    operation_id, operation_name, player_id, request_hash, result_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (operation_id, name, player_id, f"hash-{index}", json.dumps({}), now),
            )


def test_wayfaring_start_status_caps_and_free_claim_are_idempotent() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=lambda: TEST_NOW)
            user = "wayfaring-user"
            assert (await runtime.dispatch(_context(user, "create"), "开始修仙")).ok
            started = await runtime.dispatch(_context(user, "start"), "开始行卷")
            assert started.code == "WAYFARING_STARTED"
            replay = await runtime.dispatch(
                _context(user, "start-replay", operation_id=started.operation_id or ""),
                "开始行卷",
            )
            assert replay.code == "WAYFARING_STARTED"
            assert replay.data["idempotent_replay"] is True

            _insert_source_operations(
                runtime,
                user,
                ["routine.checkin.daily"] * 6 + ["production.complete"] * 4,
            )
            status = await runtime.dispatch(_context(user, "status"), "问道行卷")
            assert status.code == "WAYFARING_STATUS"
            assert status.data["daily_points"] == 100
            assert status.data["total_points"] == 100
            assert status.data["current_level"] == 1

            claimed = await runtime.dispatch(
                _context(user, "claim", operation_id="claim-free-1"),
                "领取行卷 1",
            )
            assert claimed.code == "WAYFARING_LEVEL_CLAIMED"
            duplicate = await runtime.dispatch(
                _context(user, "claim-duplicate"),
                "领取行卷 1",
            )
            assert duplicate.code == "WAYFARING_ALREADY_CLAIMED"
            replay_claim = await runtime.dispatch(
                _context(user, "claim-replay", operation_id="claim-free-1"),
                "领取行卷 1",
            )
            assert replay_claim.code == "WAYFARING_LEVEL_CLAIMED"
            assert replay_claim.data["idempotent_replay"] is True
            await runtime.close()

    asyncio.run(run())


def test_wayfaring_paid_track_requires_monthly_contract_without_asset_change() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=lambda: TEST_NOW)
            user = "wayfaring-paid-user"
            assert (await runtime.dispatch(_context(user, "create"), "开始修仙")).ok
            assert (await runtime.dispatch(_context(user, "start"), "开始行卷")).ok
            _insert_source_operations(runtime, user, ["production.complete"] * 4)
            assert (await runtime.dispatch(_context(user, "status"), "问道行卷")).data["current_level"] == 1
            before = sqlite3.connect(runtime.settings.database_path).execute(
                "SELECT spirit_stones, inventory_json FROM players WHERE platform_user_id = ?", (user,)
            ).fetchone()
            result = await runtime.dispatch(_context(user, "paid"), "领取行卷 1 付费")
            assert result.code == "WAYFARING_PAID_LOCKED"
            after = sqlite3.connect(runtime.settings.database_path).execute(
                "SELECT spirit_stones, inventory_json FROM players WHERE platform_user_id = ?", (user,)
            ).fetchone()
            assert before == after
            await runtime.close()

    asyncio.run(run())
