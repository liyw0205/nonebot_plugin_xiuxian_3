from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.exploration.rules import battle_roll_bp


def _context(adapter: str, user: str, request: str, operation: str = "") -> CommandContext:
    return CommandContext(
        adapter=adapter,
        user_id=user,
        request_id=request,
        operation_id=operation,
        can_write_assets=True,
    )


def _expire(runtime, table: str, key: str, value: str) -> None:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            f"UPDATE {table} SET ends_at=? WHERE {key}=?",
            ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(), value),
        )


async def _prepare_soul_player(runtime, adapter: str, user: str, location: str) -> None:
    created = await runtime.adapters.dispatch(
        adapter, _context(adapter, user, f"create-{adapter}"), "开始修仙"
    )
    assert created.ok
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            """
            UPDATE players
            SET stage='cultivator', realm_key='soul_transformation', realm_layer=1,
                location_key=?, stamina=100, stamina_max=100, energy=30, energy_max=30,
                bloodline_stability=60, max_hp=100000, max_mp=100000,
                initiative=100000, faction_reputation_json=?
            WHERE platform=? AND platform_user_id=?
            """,
            (location, json.dumps({"beast": 2999}), adapter, user),
        )


async def _prepare_nascent_player(runtime, adapter: str, user: str) -> None:
    created = await runtime.adapters.dispatch(
        adapter, _context(adapter, user, f"create-{adapter}"), "开始修仙"
    )
    assert created.ok
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            """
            UPDATE players
            SET stage='cultivator', realm_key='nascent_soul', realm_layer=1,
                cultivation=0, total_cultivation=58960, soul_power=100,
                soul_power_max=100, stamina=100, stamina_max=100, energy=100,
                energy_max=100, qualification_json=?
            WHERE platform=? AND platform_user_id=?
            """,
            (json.dumps({"insight": 30}), adapter, user),
        )


def test_soul_refinement_grows_nascent_cultivation_and_soul_once_per_day() -> None:
    async def run() -> None:
        for adapter in ("qq.official", "onebot.v11"):
            with TemporaryDirectory() as data_dir:
                runtime = create_runtime(data_dir=Path(data_dir) / adapter)
                user = f"nascent-refinement-{adapter}"
                await _prepare_nascent_player(runtime, adapter, user)

                started = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "refine-start", "refine-start"),
                    "开始修炼 神魂淬炼",
                )
                assert started.code == "CULTIVATION_STARTED"
                _expire(runtime, "cultivation_sessions", "session_id", started.data["session_id"])
                settled = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "refine-settle", "refine-settle"),
                    "结算修炼",
                )
                assert settled.code == "CULTIVATION_SETTLED"
                assert settled.data["cultivation_gain"] == 5750
                assert settled.data["soul_power_gain"] == 50
                replay = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "refine-replay", "refine-settle"),
                    "结算修炼",
                )
                assert replay.data["idempotent_replay"] is True

                second = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "refine-second", "refine-second"),
                    "开始修炼 神魂淬炼",
                )
                assert second.code == "CULTIVATION_STARTED"
                _expire(runtime, "cultivation_sessions", "session_id", second.data["session_id"])
                second_settled = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "refine-second-settle", "refine-second-settle"),
                    "结算修炼",
                )
                assert second_settled.data["soul_power_gain"] == 50
                limited = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "refine-limited", "refine-limited"),
                    "开始修炼 神魂淬炼",
                )
                assert limited.code == "CULTIVATION_DAILY_LIMIT"

                with sqlite3.connect(runtime.settings.database_path) as connection:
                    player = connection.execute(
                        "SELECT cultivation,total_cultivation,soul_power,soul_power_max FROM players WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    ).fetchone()
                assert player == (11500, 70460, 200, 300)
                await runtime.close()

    asyncio.run(run())


async def _run_exploration(runtime, adapter: str, user: str, operation: str, command: str) -> dict[str, int]:
    started = await runtime.adapters.dispatch(
        adapter, _context(adapter, user, f"{operation}-start", operation), command
    )
    assert started.code == "EXPLORATION_STARTED", started
    _expire(runtime, "exploration_sessions", "exploration_id", started.data["exploration_id"])
    settled = await runtime.adapters.dispatch(
        adapter, _context(adapter, user, f"{operation}-settle", f"{operation}-settle"), "结算探索"
    )
    assert settled.code == "EXPLORATION_SETTLED", settled
    return settled.data["result"]


def test_v04_ancestral_lake_and_soul_seed_recipe_work_on_qq_and_onebot() -> None:
    async def run() -> None:
        for adapter in ("qq.official", "onebot.v11"):
            with TemporaryDirectory() as data_dir:
                runtime = create_runtime(data_dir=Path(data_dir) / adapter)
                user = f"v04-source-{adapter}"
                await _prepare_soul_player(runtime, adapter, user, "beast.ancestral_lake")

                blocked = await runtime.adapters.dispatch(
                    adapter, _context(adapter, user, "blocked"), "开始探索 祖灵湖探索"
                )
                assert blocked.code == "EXPLORATION_LOCATION_FORBIDDEN"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE players SET faction_reputation_json=? WHERE platform=? AND platform_user_id=?",
                        (json.dumps({"beast": 3000}), adapter, user),
                    )

                # The first exploration is a normal settled run; choose stable operation
                # identities without an encounter so this test covers the source directly.
                for index in range(2):
                    operation = next(
                        f"ancestral-{index}-{candidate}"
                        for candidate in range(1000)
                        if battle_roll_bp(f"ancestral-{index}-{candidate}:battle") >= 3500
                    )
                    result = await _run_exploration(
                        runtime, adapter, user, operation, "开始探索 祖灵湖探索"
                    )
                    assert result == {
                        "item.ancestral_blood": 1,
                        "faction_reputation.beast": 30,
                    }

                with sqlite3.connect(runtime.settings.database_path) as connection:
                    row = connection.execute(
                        "SELECT inventory_json, faction_reputation_json, bloodline_stability FROM players WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    ).fetchone()
                assert json.loads(row[0])["item.ancestral_blood"] == 2
                assert json.loads(row[1])["beast"] == 3060
                assert row[2] == 50

                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE players SET location_key='xuantian.spirit_field', intro_json=? WHERE platform=? AND platform_user_id=?",
                        (json.dumps({"flags": ["guide.gather_blood_grass"]}), adapter, user),
                    )
                for index in range(5):
                    await _run_exploration(
                        runtime, adapter, user, f"spring-{index}", "开始探索 灵泉采集"
                    )

                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE players SET location_key='beast.ancestral_lake' WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    )
                preview = await runtime.adapters.dispatch(
                    adapter, _context(adapter, user, "seed-preview"), "生产预览 化神魂种"
                )
                assert preview.code == "RECIPE_PREVIEW"
                started = await runtime.adapters.dispatch(
                    adapter, _context(adapter, user, "seed-start", "seed-start"), "开始生产 化神魂种"
                )
                assert started.code == "PRODUCTION_STARTED", started
                _expire(runtime, "production_orders", "order_id", started.data["order_id"])
                settled = await runtime.adapters.dispatch(
                    adapter, _context(adapter, user, "seed-settle", "seed-settle"), "领取生产"
                )
                assert settled.code == "PRODUCTION_COMPLETED"
                assert settled.data["outputs"] == {"item.soul_seed": 1}
                cooldown = await runtime.adapters.dispatch(
                    adapter, _context(adapter, user, "seed-cooldown", "seed-cooldown"), "开始生产 化神魂种"
                )
                assert cooldown.code == "SOUL_SEED_PLOT_COOLDOWN"
                replay = await runtime.adapters.dispatch(
                    adapter, _context(adapter, user, "seed-replay", "seed-settle"), "领取生产"
                )
                assert replay.data["idempotent_replay"] is True
                await runtime.close()

    asyncio.run(run())
