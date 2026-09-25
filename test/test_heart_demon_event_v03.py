from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.progression.breakthrough.rules import breakthrough_roll_bp


def _ctx(adapter: str, user: str, request: str, operation: str = "") -> CommandContext:
    return CommandContext(adapter=adapter, user_id=user, request_id=request, operation_id=operation)


async def _setup(runtime, adapter: str, user: str) -> None:
    for index, command in enumerate(
        (
            "开始修仙",
            "寻仙问道",
            "完成引导 阅读",
            "前往近郊",
            "完成引导 采集",
            "完成引导 炼丹",
            "选择道途 体修",
        )
    ):
        result = await runtime.adapters.dispatch(adapter, _ctx(adapter, user, f"setup-{index}"), command)
        assert result.ok, (command, result.code, result.message)


def _make_nascent(runtime, user: str) -> None:
    inventory = {
        "item.pill.soul_condense": 1,
        "item.soul_crystal": 5,
        "item.beast_blood": 2,
        "item.pill.soul_restore": 1,
    }
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE players SET path_key = 'body', realm_key = 'golden_core', realm_layer = 10, cultivation = 47000, total_cultivation = 58960, foundation_quality = 5500, world_merit = 100, spirit_stones = 5000, inventory_json = ?, intro_json = ? WHERE platform_user_id = ?",
            (json.dumps(inventory), json.dumps({"flags": ["quest.prepare_nascent_soul"]}), user),
        )


def _expire_breakthrough(runtime, session_id: str, now: datetime) -> None:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE breakthrough_sessions SET ends_at = ? WHERE session_id = ?",
            ((now - timedelta(seconds=1)).isoformat(), session_id),
        )


def test_heart_demon_projection_and_resolution_are_adapter_neutral() -> None:
    async def run() -> None:
        for adapter in ("qq.official", "onebot.v11"):
            with TemporaryDirectory() as data_dir:
                now = datetime(2026, 9, 25, 12, tzinfo=timezone.utc)
                runtime = create_runtime(data_dir=data_dir, clock=lambda: now)
                user = f"heart-{adapter}"
                await _setup(runtime, adapter, user)
                _make_nascent(runtime, user)
                start_operation = next(
                    f"heart-start-{i}"
                    for i in range(1000)
                    if breakthrough_roll_bp(f"heart-start-{i}") >= 5500
                )
                started = await runtime.adapters.dispatch(
                    adapter,
                    _ctx(adapter, user, "start", start_operation),
                    "开始突破 元婴 魂元丹",
                )
                assert started.code == "BREAKTHROUGH_STARTED"
                _expire_breakthrough(runtime, started.data["session_id"], now)
                settled = await runtime.adapters.dispatch(
                    adapter,
                    _ctx(adapter, user, "settle", "heart-settle"),
                    "结算突破",
                )
                assert settled.code == "BREAKTHROUGH_FAILED"

                status = await runtime.adapters.dispatch(adapter, _ctx(adapter, user, "event"), "心魔事件")
                assert status.code == "HEART_DEMON_EVENT_STATUS"
                assert status.data["event_key"] == "event.heart_demon_trial"
                assert status.data["breakthrough_operation_id"] == "heart-settle"

                with sqlite3.connect(runtime.settings.database_path) as connection:
                    projection = connection.execute(
                        "SELECT event_key, status, breakthrough_operation_id FROM heart_demon_event_projections"
                    ).fetchone()
                    activity = connection.execute(
                        "SELECT event_key, source_operation_id FROM activity_events WHERE event_key = 'event.heart_demon_trial'"
                    ).fetchone()
                assert projection == ("event.heart_demon_trial", "pending", "heart-settle")
                assert activity == ("event.heart_demon_trial", "heart-settle")

                resolved = await runtime.adapters.dispatch(
                    adapter,
                    _ctx(adapter, user, "resolve", "heart-resolve"),
                    "化解心魔 净化",
                )
                assert resolved.code == "HEART_DEMON_RESOLVED"
                duplicate = await runtime.adapters.dispatch(
                    adapter,
                    _ctx(adapter, user, "duplicate", "heart-resolve-2"),
                    "化解心魔 面对",
                )
                assert duplicate.code == "HEART_DEMON_ALREADY_RESOLVED"
                resolved_status = await runtime.adapters.dispatch(adapter, _ctx(adapter, user, "event-2"), "心魔事件")
                assert resolved_status.data["status"] == "resolved"
                assert resolved_status.data["choice_key"] == "heart_demon.purify"
                await runtime.close()

    asyncio.run(run())


def test_expired_heart_demon_event_auto_faces_on_query() -> None:
    async def run() -> None:
        current = [datetime(2026, 9, 25, 12, tzinfo=timezone.utc)]
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=lambda: current[0])
            adapter, user = "qq.official", "heart-timeout"
            await _setup(runtime, adapter, user)
            _make_nascent(runtime, user)
            operation = next(
                f"heart-timeout-{i}" for i in range(1000) if breakthrough_roll_bp(f"heart-timeout-{i}") >= 5500
            )
            started = await runtime.adapters.dispatch(
                adapter, _ctx(adapter, user, "start", operation), "开始突破 元婴"
            )
            _expire_breakthrough(runtime, started.data["session_id"], current[0])
            settled = await runtime.adapters.dispatch(adapter, _ctx(adapter, user, "settle", "timeout-settle"), "结算突破")
            assert settled.code == "BREAKTHROUGH_FAILED"
            current[0] += timedelta(hours=25)

            status = await runtime.adapters.dispatch(adapter, _ctx(adapter, user, "event"), "心魔事件")
            assert status.code == "HEART_DEMON_EVENT_STATUS"
            assert status.data["status"] == "resolved"
            assert status.data["choice_key"] == "heart_demon.face"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                choice = connection.execute("SELECT choice_key FROM heart_demon_sessions").fetchone()[0]
            assert choice == "heart_demon.face"
            await runtime.close()

    asyncio.run(run())
