from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.progression.breakthrough.rules import breakthrough_roll_bp


def _ctx(user: str, request: str, operation: str = "") -> CommandContext:
    return CommandContext(adapter="web", user_id=user, request_id=request, operation_id=operation)


async def _setup(runtime, user: str) -> None:
    for index, command in enumerate((
        "开始修仙",
        "寻仙问道",
        "完成引导 阅读",
        "前往近郊",
        "完成引导 采集",
        "完成引导 炼丹",
        "选择道途 体修",
    )):
        assert (await runtime.dispatch(_ctx(user, f"setup-{index}"), command)).ok


def _make_nascent(runtime, user: str, *, soul_restore: int = 1, path: str = "body") -> None:
    inventory = {
        "item.pill.soul_condense": 1,
        "item.soul_crystal": 5,
        "item.beast_blood": 2,
        "item.pill.soul_restore": soul_restore,
    }
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE players SET path_key = ?, realm_key = 'golden_core', realm_layer = 10, cultivation = 47000, total_cultivation = 58960, foundation_quality = 5500, world_merit = 100, spirit_stones = 5000, inventory_json = ?, intro_json = ? WHERE platform_user_id = ?",
            (path, json.dumps(inventory), json.dumps({"flags": ["quest.prepare_nascent_soul"]}), user),
        )


def _finish(runtime, session_id: str) -> None:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE breakthrough_sessions SET ends_at = ? WHERE session_id = ?",
            ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(), session_id),
        )


def test_nascent_soul_success_grants_soul_resources_and_stats() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            user = "nascent-success"
            await _setup(runtime, user)
            _make_nascent(runtime, user)
            operation = next(f"nascent-success-{i}" for i in range(1000) if breakthrough_roll_bp(f"nascent-success-{i}") < 6000)
            started = await runtime.dispatch(_ctx(user, "start", operation), "开始突破 元婴")
            assert started.code == "BREAKTHROUGH_STARTED"
            _finish(runtime, started.data["session_id"])
            settled = await runtime.dispatch(_ctx(user, "settle", "nascent-settle"), "结算突破")
            assert settled.code == "BREAKTHROUGH_SUCCEEDED"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                row = connection.execute(
                    "SELECT realm_key, realm_layer, cultivation, total_cultivation, world_merit, soul_power, domain_charge, max_hp, max_mp, carry_capacity, exploration_efficiency_bp FROM players WHERE platform_user_id = ?",
                    (user,),
                ).fetchone()
            assert row == ("nascent_soul", 1, 0, 58960, 200, 100, 100, 600, 480, 50, 1500)
            await runtime.close()

    asyncio.run(run())


def test_nascent_soul_failure_creates_heart_demon_and_purify_is_idempotent() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            user = "nascent-failure"
            await _setup(runtime, user)
            _make_nascent(runtime, user)
            operation = next(f"nascent-failure-{i}" for i in range(1000) if breakthrough_roll_bp(f"nascent-failure-{i}") >= 5500)
            started = await runtime.dispatch(_ctx(user, "start", operation), "开始突破 元婴 魂元丹")
            assert started.code == "BREAKTHROUGH_STARTED"
            _finish(runtime, started.data["session_id"])
            settled = await runtime.dispatch(_ctx(user, "settle", "nascent-failure-settle"), "结算突破")
            assert settled.code == "BREAKTHROUGH_FAILED"
            assert settled.data["heart_demon_pending"] is True
            pending = await runtime.dispatch(_ctx(user, "retry", "nascent-retry"), "开始突破 元婴")
            assert pending.code == "HEART_DEMON_PENDING"
            resolved = await runtime.dispatch(_ctx(user, "heart", "heart-choice"), "化解心魔 净化")
            assert resolved.code == "HEART_DEMON_RESOLVED"
            replay = await runtime.dispatch(_ctx(user, "heart-replay", "heart-choice"), "化解心魔 净化")
            assert replay.data["idempotent_replay"] is True
            with sqlite3.connect(runtime.settings.database_path) as connection:
                inventory = connection.execute("SELECT inventory_json FROM players WHERE platform_user_id = ?", (user,)).fetchone()[0]
                demons = connection.execute("SELECT status, choice_key FROM heart_demon_sessions").fetchone()
            assert json.loads(inventory)["item.pill.soul_restore"] == 0
            assert demons == ("resolved", "heart_demon.purify")
            await runtime.close()

    asyncio.run(run())
