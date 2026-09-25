from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.economy.rules import resolve_market_item
from nonebot_plugin_xiuxian_3.xiuxian.production.rules import random_quality_bp


def _context(adapter: str, user: str, request: str, operation: str = "") -> CommandContext:
    return CommandContext(
        adapter=adapter,
        user_id=user,
        request_id=request,
        operation_id=operation,
        can_write_assets=True,
    )


async def _player(runtime, adapter: str, user: str, *, realm: str, location: str, inventory: dict[str, int], subprofession: str | None = None) -> None:
    await runtime.adapters.dispatch(adapter, _context(adapter, user, f"create-{adapter}"), "开始修仙")
    await runtime.adapters.dispatch(adapter, _context(adapter, user, f"seek-{adapter}"), "寻仙问道")
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            """
            UPDATE players SET stage='cultivator', realm_key=?, realm_layer=1,
                location_key=?, subprofession_key=?, selected_service=?,
                stamina=30, stamina_max=30, energy=30, energy_max=30,
                spirit_stones=1000, inventory_json=?, durability_json='{}', intro_json='{}'
            WHERE platform=? AND platform_user_id=?
            """,
            (realm, location, subprofession, subprofession, json.dumps(inventory), adapter, user),
        )


def test_cloud_tea_is_consumed_once_and_frozen_into_qq_onebot_cultivation() -> None:
    async def run() -> None:
        for adapter in ("qq.official", "onebot.v11"):
            with TemporaryDirectory() as data_dir:
                runtime = create_runtime(data_dir=Path(data_dir) / adapter)
                user = f"tea-{adapter}"
                await _player(
                    runtime,
                    adapter,
                    user,
                    realm="qi_gathering",
                    location="xuantian.spirit_field",
                    inventory={"item.food.cloud_tea": 2},
                )
                used = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "tea-use", "tea-use-op"),
                    "使用 云灵茶",
                )
                assert used.code == "ITEM_USED"
                replay = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "tea-replay", "tea-use-op"),
                    "使用 item.food.cloud_tea",
                )
                assert replay.data["idempotent_replay"] is True
                duplicate = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "tea-duplicate", "tea-duplicate-op"),
                    "使用 云茶",
                )
                assert duplicate.code == "ITEM_EFFECT_ALREADY_PENDING"
                started = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "cultivation-start", "cultivation-tea-op"),
                    "开始修炼",
                )
                assert started.code == "CULTIVATION_STARTED"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    snapshot_text, effects_text = connection.execute(
                        "SELECT snapshot_json, item_effects_json FROM cultivation_sessions JOIN players ON players.id=cultivation_sessions.player_id"
                    ).fetchone()
                snapshot = json.loads(snapshot_text)
                assert snapshot["cloud_tea_effect_bp"] == 500
                assert snapshot["state_bp"] == 10500
                assert json.loads(effects_text) == {}
                await runtime.close()

    asyncio.run(run())


def test_mist_barrier_reduces_risk_once_and_expires_for_qq_onebot() -> None:
    async def run() -> None:
        for adapter in ("qq.official", "onebot.v11"):
            with TemporaryDirectory() as data_dir:
                runtime = create_runtime(data_dir=Path(data_dir) / adapter)
                user = f"barrier-{adapter}"
                await _player(
                    runtime,
                    adapter,
                    user,
                    realm="golden_core",
                    location="cave.mist_grotto_2",
                    inventory={"item.array.mist_barrier": 1},
                )
                used = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "barrier-use", "barrier-op"),
                    "使用 迷雾屏障阵 雾隐洞天二层",
                )
                assert used.code == "ITEM_USED"
                replay = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "barrier-replay", "barrier-op"),
                    "使用 迷雾屏障阵 雾隐洞天二层",
                )
                assert replay.data["idempotent_replay"] is True
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    barrier_id, expires_at = connection.execute(
                        "SELECT barrier_id, expires_at FROM mist_barrier_instances"
                    ).fetchone()
                    connection.execute(
                        "UPDATE players SET inventory_json=? WHERE platform=? AND platform_user_id=?",
                        (json.dumps({"item.array.mist_barrier": 1}), adapter, user),
                    )
                started = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "explore-start", "explore-barrier-op"),
                    "开始探索 洞天二层探索",
                )
                assert started.code == "EXPLORATION_STARTED"
                assert started.data["risk_reduction_bp"] == 500
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    snapshot = json.loads(connection.execute("SELECT snapshot_json FROM exploration_sessions").fetchone()[0])
                    assert snapshot["barrier_id"] == barrier_id
                    assert snapshot["battle_chance_bp"] == 3500
                    connection.execute(
                        "UPDATE mist_barrier_instances SET expires_at=? WHERE barrier_id=?",
                        ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(), barrier_id),
                    )
                assert await runtime.repository.expire_mist_barriers() == 1
                assert await runtime.repository.expire_mist_barriers() == 0
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    assert connection.execute(
                        "SELECT status FROM mist_barrier_instances WHERE barrier_id=?", (barrier_id,)
                    ).fetchone()[0] == "expired"
                await runtime.close()

    asyncio.run(run())


def test_cloud_sword_production_materializes_equipment_instance() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            adapter, user = "onebot.v11", "cloud-sword-instance"
            await _player(
                runtime,
                adapter,
                user,
                realm="golden_core",
                location="cave.mist_grotto_2",
                subprofession="artifice",
                inventory={
                    "item.material.cloud_iron": 4,
                    "item.mat.array_sand": 1,
                    "item.mat.wood": 2,
                    "item.tool.basic_hammer": 1,
                },
            )
            claimed = await runtime.adapters.dispatch(
                adapter,
                _context(adapter, user, "facility-claim"),
                "认领设施槽位 炼器台",
            )
            assert claimed.code == "FACILITY_SLOT_CLAIMED"
            await runtime.repository.maintain_facilities()
            operation = next(
                f"cloud-sword-{index}"
                for index in range(256)
                if random_quality_bp(f"cloud-sword-{index}") >= 1000
            )
            started = await runtime.adapters.dispatch(
                adapter,
                _context(adapter, user, "production-start", operation),
                "开始生产 云纹剑",
            )
            assert started.code == "PRODUCTION_STARTED"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE production_orders SET ends_at=? WHERE order_id=?",
                    ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(), started.data["order_id"]),
                )
            settled = await runtime.adapters.dispatch(
                adapter,
                _context(adapter, user, "production-settle"),
                "领取生产",
            )
            assert settled.data["outputs"] == {"item.weapon.cloud_sword": 1}
            with sqlite3.connect(runtime.settings.database_path) as connection:
                instance = connection.execute(
                    "SELECT item_key, status, durability_bp FROM equipment_instances WHERE player_id=(SELECT id FROM players WHERE platform=? AND platform_user_id=?)",
                    (adapter, user),
                ).fetchone()
                inventory = json.loads(connection.execute("SELECT inventory_json FROM players WHERE platform=? AND platform_user_id=?", (adapter, user)).fetchone()[0])
            assert instance[0:2] == ("item.weapon.cloud_sword", "active")
            assert 8500 <= instance[2] <= 10000
            assert inventory.get("item.weapon.cloud_sword", 0) == 0
            await runtime.close()

    asyncio.run(run())


def test_v02_bound_production_items_are_not_market_tradeable() -> None:
    for item in ("item.pill.core_condense", "item.pill.golden_core_guard", "item.array.mist_barrier"):
        try:
            resolve_market_item(item)
        except ValueError:
            continue
        raise AssertionError(f"{item} unexpectedly became tradeable")
