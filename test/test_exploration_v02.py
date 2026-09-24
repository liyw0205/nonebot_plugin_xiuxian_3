from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.exploration.rules import battle_roll_bp


def _context(adapter: str, user: str, operation_id: str) -> CommandContext:
    return CommandContext(adapter=adapter, user_id=user, operation_id=operation_id)


def _set_player(runtime, adapter: str, user: str, **values: object) -> None:
    assignments = ", ".join(f"{key} = ?" for key in values)
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            f"UPDATE players SET {assignments} WHERE platform = ? AND platform_user_id = ?",
            (*values.values(), adapter, user),
        )


def _expire(runtime, exploration_id: str) -> None:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE exploration_sessions SET ends_at = ? WHERE exploration_id = ?",
            ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(), exploration_id),
        )


def test_v02_cloud_mine_energy_gate_and_qq_onebot_settlement() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            for adapter, user in (("qq.official", "qq-mine"), ("onebot.v11", "ob-mine")):
                created = await runtime.adapters.dispatch(adapter, _context(adapter, user, f"{adapter}-create"), "开始修仙")
                assert created.code == "PLAYER_CREATED"
                _set_player(
                    runtime,
                    adapter,
                    user,
                    stage="cultivator",
                    realm_key="foundation",
                    realm_layer=1,
                    location_key="xuantian.cloud_mine",
                    subprofession_key="mining",
                    stamina=30,
                    energy=5,
                    energy_max=30,
                    inventory_json=json.dumps({}),
                )
                operation = next(
                    f"{adapter}-mine-{index}"
                    for index in range(1000)
                    if battle_roll_bp(f"{adapter}-mine-{index}:battle") >= 3000
                )
                started = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, operation),
                    "开始探索 云铁矿区采集",
                )
                assert started.code == "EXPLORATION_STARTED"
                assert started.data["energy_cost"] == 2
                assert started.data["content_version"] == "content-0.2"
                assert started.message.find("精力") >= 0
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    stamina, energy, snapshot_text = connection.execute(
                        "SELECT stamina, energy, snapshot_json FROM players "
                        "JOIN exploration_sessions ON exploration_sessions.player_id = players.id "
                        "WHERE players.platform = ? AND players.platform_user_id = ?",
                        (adapter, user),
                    ).fetchone()
                assert (stamina, energy) == (22, 3)
                assert json.loads(snapshot_text)["energy_cost"] == 2
                _expire(runtime, started.data["exploration_id"])
                settled = await runtime.adapters.dispatch(
                    adapter, _context(adapter, user, f"{adapter}-settle"), "结算探索"
                )
                assert settled.code == "EXPLORATION_SETTLED"
                assert settled.data["result"]["item.material.cloud_iron"] >= 1
                replay = await runtime.adapters.dispatch(
                    adapter, _context(adapter, user, f"{adapter}-settle"), "结算探索"
                )
                assert replay.data["idempotent_replay"] is True
                assert replay.data["result"] == settled.data["result"]
            await runtime.close()

    asyncio.run(run())


def test_v02_cloud_mine_rejects_missing_access_or_energy_without_spending() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            adapter, user = "onebot.v11", "mine-guards"
            await runtime.adapters.dispatch(adapter, _context(adapter, user, "create"), "开始修仙")
            _set_player(
                runtime,
                adapter,
                user,
                stage="cultivator",
                realm_key="foundation",
                realm_layer=1,
                location_key="xuantian.cloud_mine",
                subprofession_key=None,
                stamina=30,
                energy=5,
                inventory_json=json.dumps({}),
            )
            denied = await runtime.adapters.dispatch(
                adapter, _context(adapter, user, "denied"), "开始探索 云铁矿区采集"
            )
            assert denied.code == "EXPLORATION_LOCATION_FORBIDDEN"
            _set_player(runtime, adapter, user, subprofession_key="mining", energy=1)
            insufficient = await runtime.adapters.dispatch(
                adapter, _context(adapter, user, "insufficient"), "开始探索 云铁矿区采集"
            )
            assert insufficient.code == "ENERGY_INSUFFICIENT"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                stamina, energy, count = connection.execute(
                    "SELECT stamina, energy, COUNT(exploration_sessions.id) FROM players "
                    "LEFT JOIN exploration_sessions ON exploration_sessions.player_id = players.id "
                    "WHERE players.platform = ? AND players.platform_user_id = ?",
                    (adapter, user),
                ).fetchone()
            assert (stamina, energy, count) == (30, 1, 0)
            await runtime.close()

    asyncio.run(run())


def test_v02_mist_grotto_two_requires_arrived_location_and_uses_elite_snapshot() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            adapter, user = "qq.official", "mist-two"
            await runtime.adapters.dispatch(adapter, _context(adapter, user, "create"), "开始修仙")
            _set_player(
                runtime,
                adapter,
                user,
                stage="cultivator",
                realm_key="golden_core",
                realm_layer=1,
                location_key="xuantian.cloud_city",
                stamina=30,
                energy=30,
            )
            blocked = await runtime.adapters.dispatch(
                adapter, _context(adapter, user, "blocked"), "开始探索 洞天二层探索"
            )
            assert blocked.code == "EXPLORATION_LOCATION_FORBIDDEN"
            _set_player(runtime, adapter, user, location_key="cave.mist_grotto_2", max_hp=10000, initiative=100, qualification_json=json.dumps({"body": 10000, "agility": 10000}))
            operation = next(
                f"mist-two-{index}"
                for index in range(1000)
                if battle_roll_bp(f"mist-two-{index}:battle") >= 4000
            )
            started = await runtime.adapters.dispatch(
                adapter, _context(adapter, user, operation), "开始探索 洞天二层探索"
            )
            assert started.code == "EXPLORATION_STARTED"
            _expire(runtime, started.data["exploration_id"])
            settled = await runtime.adapters.dispatch(
                adapter, _context(adapter, user, "settle"), "结算探索"
            )
            assert settled.code == "EXPLORATION_SETTLED"
            assert settled.data["mode_key"] == "explore.mist_grotto_2"
            assert settled.data["result"]["cultivation"] >= 900
            await runtime.close()

    asyncio.run(run())
