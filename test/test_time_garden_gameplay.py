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
from nonebot_plugin_xiuxian_3.xiuxian.rewards.rules import reward_pool_map
from combat_fixtures import BALANCED_QUALIFICATION, equip_damage_weapon


def _context(user_id: str, request_id: str, *, operation_id: str = "") -> CommandContext:
    return CommandContext(
        adapter="web",
        user_id=user_id,
        request_id=request_id,
        operation_id=operation_id,
    )


def _set_player(runtime, user_id: str, **values: object) -> None:
    assignments = ", ".join(f"{key} = ?" for key in values)
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            f"UPDATE players SET {assignments} WHERE platform_user_id = ?",
            (*values.values(), user_id),
        )


def _expire_exploration(runtime, user_id: str, exploration_id: str) -> None:
    old = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE exploration_sessions SET ends_at = ? WHERE exploration_id = ? AND player_id = (SELECT id FROM players WHERE platform_user_id = ?)",
            (old, exploration_id, user_id),
        )


def _arm(runtime, user_id: str) -> None:
    """Give the player a real combat build: the garden enemies are
    void_refining-tier (1600-1720 hp, 120-128 attack)."""
    _set_player(
        runtime,
        user_id,
        max_hp=20000,
        initiative=20000,
        qualification_json=json.dumps(BALANCED_QUALIFICATION),
    )
    equip_damage_weapon(runtime, "web", user_id, 50_000)


def _garden_operation(prefix: str) -> str:
    # Exploration battles are deterministic per operation id: the start
    # operation id becomes the snapshot random_seed and the settle rolls
    # battle_roll_bp(seed + ":battle"). Derive an id whose roll lands
    # below the 5000bp battle chance using the production helper.
    return next(
        f"{prefix}-{index}"
        for index in range(10_000)
        if battle_roll_bp(f"{prefix}-{index}:battle") < 5_000
    )


def test_time_garden_full_chain_rewards_daily_limit_and_replay() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=Path(data_dir))
            user = "time-garden"
            assert (await runtime.dispatch(_context(user, "create"), "开始修仙")).ok
            assert (await runtime.dispatch(_context(user, "seek"), "寻仙问道")).ok
            # Context fixture: void_refining L1 at the garden. The objective
            # itself (travel-free exploration) runs through real commands.
            _set_player(
                runtime,
                user,
                stage="cultivator",
                realm_key="void_refining",
                realm_layer=1,
                location_key="cave.time_garden",
                stamina=100,
                stamina_max=100,
                energy=30,
                energy_max=30,
                qualification_json=json.dumps(
                    {"body": 10, "spirit": 10, "insight": 10, "root": 10, "agility": 10, "fortune": 10}
                ),
            )
            _arm(runtime, user)

            # Realm gate: a foundation cultivator is refused.
            low = "time-garden-low"
            assert (await runtime.dispatch(_context(low, "create-low"), "开始修仙")).ok
            assert (await runtime.dispatch(_context(low, "seek-low"), "寻仙问道")).ok
            _set_player(
                runtime,
                low,
                stage="cultivator",
                realm_key="foundation",
                realm_layer=10,
                location_key="cave.time_garden",
                stamina=100,
                stamina_max=100,
                energy=30,
                energy_max=30,
            )
            refused = await runtime.dispatch(
                _context(low, "low-start"), "开始探索 时序福地采撷"
            )
            assert refused.code == "EXPLORATION_LOCATION_FORBIDDEN"

            # Wrong location is refused.
            _set_player(runtime, user, location_key="void.archive_ruins")
            wrong_place = await runtime.dispatch(
                _context(user, "wrong-start"), "开始探索 时序福地采撷"
            )
            assert wrong_place.code == "EXPLORATION_LOCATION_FORBIDDEN"
            _set_player(runtime, user, location_key="cave.time_garden")

            # Two battles (roll < 5000bp): both must be won and settled.
            for index in range(2):
                operation_id = _garden_operation(f"garden-win-{index}")
                started = await runtime.dispatch(
                    _context(user, f"start-{index}", operation_id=operation_id),
                    "开始探索 时序福地采撷",
                )
                assert started.code == "EXPLORATION_STARTED", started.message
                exploration_id = started.data["exploration_id"]
                _expire_exploration(runtime, user, exploration_id)
                settled = await runtime.dispatch(
                    _context(user, f"settle-{index}", operation_id=f"{operation_id}:settle"),
                    "结算探索",
                )
                assert settled.code == "EXPLORATION_SETTLED", settled.message
                assert settled.data["battle_outcome"] == "won"
                result = settled.data["result"]
                assert result, "a won battle must yield a frozen reward"
                assert any("item.herb.time_trace" in key or "item.void_crystal" in key for key in result)

            # Daily limit 2: the third attempt the same UTC day is refused.
            third = await runtime.dispatch(
                _context(user, "start-3", operation_id="garden-third"),
                "开始探索 时序福地采撷",
            )
            assert third.code == "EXPLORATION_QUOTA_EXHAUSTED"

            # Reward outcomes are deterministic per operation id.
            seed_a = "garden-determinism-a"
            seed_b = "garden-determinism-b"
            assert reward_pool_map(
                "reward_pool.exploration.time_garden", seed_a
            ) == reward_pool_map("reward_pool.exploration.time_garden", seed_a)
            assert reward_pool_map(
                "reward_pool.exploration.time_garden", seed_a
            ) is not None and reward_pool_map(
                "reward_pool.exploration.time_garden", seed_b
            ) is not None

            await runtime.close()

    asyncio.run(run())


def test_time_garden_no_battle_path_still_settles() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=Path(data_dir))
            user = "time-garden-peace"
            assert (await runtime.dispatch(_context(user, "create"), "开始修仙")).ok
            assert (await runtime.dispatch(_context(user, "seek"), "寻仙问道")).ok
            _set_player(
                runtime,
                user,
                stage="cultivator",
                realm_key="void_refining",
                realm_layer=1,
                location_key="cave.time_garden",
                stamina=100,
                stamina_max=100,
                energy=30,
                energy_max=30,
                qualification_json=json.dumps(
                    {"body": 10, "spirit": 10, "insight": 10, "root": 10, "agility": 10, "fortune": 10}
                ),
            )
            _arm(runtime, user)
            # Derive an operation id whose roll lands at/above 5000bp: no battle.
            index = next(
                index
                for index in range(10_000)
                if battle_roll_bp(f"peace-{index}:battle") >= 5_000
            )
            operation_id = f"peace-{index}"
            started = await runtime.dispatch(
                _context(user, "start", operation_id=operation_id),
                "开始探索 时序福地采撷",
            )
            assert started.code == "EXPLORATION_STARTED"
            _expire_exploration(runtime, user, started.data["exploration_id"])
            settled = await runtime.dispatch(
                _context(user, "settle", operation_id=f"{operation_id}:settle"),
                "结算探索",
            )
            assert settled.code == "EXPLORATION_SETTLED"
            assert settled.data["battle_outcome"] in (None, "none")
            result = settled.data["result"]
            assert result, "a peaceful settle still freezes a weighted reward"
            assert set(result) <= {"item.herb.time_trace", "item.void_crystal", "spirit_stones"}
            # Replay with the same settle operation id returns the frozen result.
            replay = await runtime.dispatch(
                _context(user, "settle-replay", operation_id=f"{operation_id}:settle"),
                "结算探索",
            )
            assert replay.data["idempotent_replay"] is True
            await runtime.close()

    asyncio.run(run())
