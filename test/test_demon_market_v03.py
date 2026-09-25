from __future__ import annotations

import asyncio
import json
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


async def _prepare_player(runtime, adapter: str, user: str, reputation: int) -> None:
    await runtime.adapters.dispatch(adapter, _context(adapter, user, f"create-{adapter}"), "开始修仙")
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            """
            UPDATE players
            SET stage='cultivator', realm_key='nascent_soul', realm_layer=1,
                location_key='demon.fallen_ruins', stamina=30, stamina_max=30,
                spirit_stones=1000, faction_reputation_json=?
            WHERE platform=? AND platform_user_id=?
            """,
            (json.dumps({"demon": reputation}), adapter, user),
        )


def _expire(runtime, session_id: str) -> None:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE travel_sessions SET ends_at=? WHERE session_id=?",
            ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(), session_id),
        )


def test_demon_market_reputation_gate_and_arrival_are_idempotent_on_both_adapters() -> None:
    async def run() -> None:
        for adapter in ("qq.official", "onebot.v11"):
            with TemporaryDirectory() as data_dir:
                runtime = create_runtime(data_dir=Path(data_dir) / adapter)
                user = f"market-{adapter}"
                await _prepare_player(runtime, adapter, user, reputation=199)

                preview = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "preview-199"),
                    "移动预览 魔渊集市",
                )
                assert preview.code == "TRAVEL_PREVIEW"
                assert preview.data["ready"] is False
                assert any("魔界声望" in item and "200" in item for item in preview.data["missing"])
                rejected = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "start-199", "market-start-199"),
                    "前往 魔渊集市",
                )
                assert rejected.code == "FACTION_REPUTATION_INSUFFICIENT"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    assert connection.execute(
                        "SELECT stamina, spirit_stones FROM players WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    ).fetchone() == (30, 1000)
                    connection.execute(
                        "UPDATE players SET faction_reputation_json=? WHERE platform=? AND platform_user_id=?",
                        (json.dumps({"demon": 200}), adapter, user),
                    )

                started = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "start-200", "market-start-200"),
                    "前往 魔渊集市",
                )
                assert started.code == "TRAVEL_STARTED"
                replay = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "start-200-replay", "market-start-200"),
                    "前往 魔渊集市",
                )
                assert replay.code == "TRAVEL_STARTED"
                assert replay.data["idempotent_replay"] is True
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    assert connection.execute(
                        "SELECT stamina, spirit_stones FROM players WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    ).fetchone() == (18, 500)
                    snapshot = connection.execute(
                        "SELECT snapshot_json FROM travel_sessions WHERE session_id=?",
                        (started.data["session_id"],),
                    ).fetchone()[0]
                assert json.loads(snapshot) == {
                    "content_version": "content-0.3",
                    "currency_cost": 500,
                    "daily_start_limit": 0,
                    "destination": "demon.abyss_market",
                    "faction_reputation": 200,
                    "pass_key": None,
                    "pass_quantity": 0,
                    "required_dao_fruit_progress": 0,
                    "required_endgame_status": None,
                    "required_faction": "demon",
                    "required_faction_reputation": 200,
                    "required_intro_flag": None,
                    "rule_version": "world-0.3.0",
                    "source": "demon.fallen_ruins",
                    "stamina_cost": 12,
                    "consume_pass_on_arrival": False,
                }

                _expire(runtime, started.data["session_id"])
                arrived = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "settle-market", "market-settle"),
                    "结算移动",
                )
                assert arrived.code == "TRAVEL_COMPLETED"
                settle_replay = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "settle-market-replay", "market-settle"),
                    "结算移动",
                )
                assert settle_replay.data["idempotent_replay"] is True
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    assert connection.execute(
                        "SELECT location_key FROM players WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    ).fetchone()[0] == "demon.abyss_market"
                await runtime.close()

    asyncio.run(run())
