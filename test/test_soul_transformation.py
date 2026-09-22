from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.progression.breakthrough.rules import breakthrough_roll_bp


def _context(adapter: str, user: str, request: str, operation: str = "") -> CommandContext:
    return CommandContext(adapter=adapter, user_id=user, request_id=request, operation_id=operation)


async def _player(runtime, user: str) -> None:
    created = await runtime.dispatch(_context("web", user, "create"), "开始修仙")
    assert created.ok
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE players SET stage = 'cultivator', realm_key = 'nascent_soul', realm_layer = 10, cultivation = 100000, total_cultivation = 248960, soul_power = 250, world_merit = 500, spirit_stones = 20000, domain_level = 5, path_key = 'body', inventory_json = ?, intro_json = ?, faction_reputation_json = ? WHERE platform_user_id = ?",
            (
                json.dumps({"item.soul_seed": 1, "item.domain_core": 1, "item.ancient_fruit": 3, "item.pill.domain_restore": 1}),
                json.dumps({"flags": ["quest.soul_transformation"]}),
                json.dumps({"xuantian": 2500}),
                user,
            ),
        )


def _finish(runtime, session_id: str) -> None:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE breakthrough_sessions SET ends_at = ? WHERE session_id = ?",
            ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(), session_id),
        )


def test_soul_transformation_gate_does_not_charge_and_success_initializes_domain() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            user = "v04-success"
            await _player(runtime, user)
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute("UPDATE players SET soul_power = 199 WHERE platform_user_id = ?", (user,))
            blocked = await runtime.dispatch(_context("web", user, "blocked", "v04-blocked"), "开始突破 化神")
            assert blocked.code == "SOUL_POWER_INSUFFICIENT"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute("SELECT spirit_stones, world_merit FROM players WHERE platform_user_id = ?", (user,)).fetchone() == (20000, 500)
                connection.execute("UPDATE players SET soul_power = 250 WHERE platform_user_id = ?", (user,))
            operation = next(f"v04-success-{i}" for i in range(1000) if breakthrough_roll_bp(f"v04-success-{i}") < 9000)
            started = await runtime.dispatch(_context("web", user, "start", operation), "开始突破 化神")
            assert started.code == "BREAKTHROUGH_STARTED"
            _finish(runtime, started.data["session_id"])
            settled = await runtime.dispatch(_context("web", user, "settle", "v04-settle"), "结算突破")
            assert settled.code == "BREAKTHROUGH_SUCCEEDED"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                row = connection.execute("SELECT realm_key, realm_layer, domain_power, domain_charge, realm_resistance_bp, max_hp, max_mp, initiative, world_merit FROM players WHERE platform_user_id = ?", (user,)).fetchone()
            assert row == ("soul_transformation", 1, 100, 150, 1000, 1000, 800, 20, 300)
            await runtime.close()

    asyncio.run(run())


def test_soul_transformation_failure_creates_crack_and_domain_confirmation_is_idempotent() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            user = "v04-failure"
            await _player(runtime, user)
            operation = next(f"v04-failure-{i}" for i in range(1000) if breakthrough_roll_bp(f"v04-failure-{i}") >= 7550)
            started = await runtime.dispatch(_context("web", user, "start", operation), "开始突破 化神")
            _finish(runtime, started.data["session_id"])
            settled = await runtime.dispatch(_context("web", user, "settle", "v04-settle"), "结算突破")
            assert settled.code == "BREAKTHROUGH_FAILED"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                row = connection.execute("SELECT cultivation, domain_crack_until FROM players WHERE platform_user_id = ?", (user,)).fetchone()
            assert row[0] == 70000 and row[1]
            blocked = await runtime.dispatch(_context("web", user, "choose-blocked", "v04-choose-blocked"), "选择领域 体修")
            assert blocked.code == "DOMAIN_CRACK_ACTIVE"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                inventory = json.loads(connection.execute("SELECT inventory_json FROM players WHERE platform_user_id = ?", (user,)).fetchone()[0])
                inventory["item.domain_core"] = 1
                connection.execute("UPDATE players SET domain_crack_until = ?, realm_key = 'soul_transformation', realm_layer = 3, spirit_stones = 12000, inventory_json = ? WHERE platform_user_id = ?", ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(), json.dumps(inventory), user))
            selected = await runtime.dispatch(_context("web", user, "choose", "v04-choose"), "选择领域 体修")
            assert selected.code == "DOMAIN_SELECTION_PENDING"
            confirmed = await runtime.dispatch(_context("web", user, "confirm", "v04-confirm"), "确认领域")
            replay = await runtime.dispatch(_context("web", user, "confirm-replay", "v04-confirm"), "确认领域")
            assert confirmed.code == "DOMAIN_SELECTED"
            assert replay.data["idempotent_replay"] is True
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute("SELECT domain_key, spirit_stones FROM players WHERE platform_user_id = ?", (user,)).fetchone() == ("domain.mountain_body", 2000)
            await runtime.close()

    asyncio.run(run())
