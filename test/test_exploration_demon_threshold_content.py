from __future__ import annotations

import asyncio
import json
import shutil
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.rewards.rules import reward_pool_map


ADAPTERS = ("qq.official", "onebot.v11")
POOL = "reward_pool.exploration.demon_threshold"
INITIAL_REWARDS = {"item.soul_crystal": 1, "item.demon_core": 1}
UPDATED_REWARDS = {"item.soul_crystal": 2, "item.demon_core": 3}


def _context(adapter: str, user: str, operation_id: str) -> CommandContext:
    return CommandContext(adapter=adapter, user_id=user, operation_id=operation_id)


def _copy_data(tmp_path: Path) -> Path:
    target = tmp_path / "data"
    shutil.copytree(Path(__file__).parents[1] / "data", target)
    return target


def _update_record(path: Path, key: str, **changes: object) -> None:
    document = json.loads(path.read_text(encoding="utf-8"))
    next(record for record in document["records"] if record["key"] == key).update(changes)
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _set_pool(data_dir: Path, rewards: dict[str, int]) -> None:
    _update_record(
        data_dir / "奖励" / "奖励.json",
        POOL,
        outcomes=[{"weight": 1, "rewards": rewards}],
    )


async def _prepare_player(runtime, adapter: str, user: str) -> None:
    created = await runtime.adapters.dispatch(
        adapter, _context(adapter, user, f"{user}-create"), "开始修仙"
    )
    assert created.code == "PLAYER_CREATED"
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE players SET stage='cultivator', realm_key='golden_core', realm_layer=10, "
            "location_key='demon.abyss_gate', stamina=100, stamina_max=100, "
            "energy=100, energy_max=100, intro_json=? "
            "WHERE platform=? AND platform_user_id=?",
            (
                json.dumps({"flags": ["access.demon_abyss_gate"]}),
                adapter,
                user,
            ),
        )


async def _send(runtime, adapter: str, user: str, operation_id: str, command: str):
    return await runtime.adapters.dispatch(
        adapter, _context(adapter, user, operation_id), command
    )


def _expire(runtime, exploration_id: str) -> None:
    old = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE exploration_sessions SET ends_at=? WHERE exploration_id=?",
            (old, exploration_id),
        )


def _state(runtime) -> dict[str, list[tuple]]:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        return {
            table: connection.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
            for table in (
                "players",
                "exploration_sessions",
                "exploration_item_bindings",
                "operations",
                "battle_sessions",
            )
        }


def test_demon_threshold_pool_freezes_across_restart_and_new_runs_read_current_content(
    tmp_path: Path,
) -> None:
    async def run() -> None:
        data_dir = _copy_data(tmp_path)
        runtime = create_runtime(data_dir=data_dir, adapters=ADAPTERS)
        pending: dict[str, tuple[str, str, str]] = {}
        try:
            for adapter in ADAPTERS:
                user = f"demon-threshold-{adapter}"
                await _prepare_player(runtime, adapter, user)
                start_operation = f"{adapter}-demon-threshold-first"
                started = await _send(
                    runtime, adapter, user, start_operation, "开始探索 深渊门备材"
                )
                assert started.code == "EXPLORATION_STARTED"
                exploration_id = str(started.data["exploration_id"])
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    snapshot = json.loads(
                        connection.execute(
                            "SELECT snapshot_json FROM exploration_sessions WHERE exploration_id=?",
                            (exploration_id,),
                        ).fetchone()[0]
                    )
                assert snapshot["reward_pool_key"] == POOL
                assert snapshot["random_seed"] == start_operation
                assert snapshot["frozen_result"] == INITIAL_REWARDS
                before_replay = _state(runtime)
                replay = await _send(
                    runtime, adapter, user, start_operation, "开始探索 深渊门备材"
                )
                assert replay.data["idempotent_replay"] is True
                assert replay.data["exploration_id"] == exploration_id
                assert _state(runtime) == before_replay
                pending[adapter] = (user, exploration_id, f"{adapter}-demon-settle")
        finally:
            await runtime.close()

        _set_pool(data_dir, UPDATED_REWARDS)
        recovered = create_runtime(data_dir=data_dir, adapters=ADAPTERS)
        try:
            for adapter in ADAPTERS:
                user, exploration_id, settle_operation = pending[adapter]
                _expire(recovered, exploration_id)
                settled = await _send(
                    recovered, adapter, user, settle_operation, "结算探索"
                )
                assert settled.code == "EXPLORATION_SETTLED"
                assert settled.data["result"] == INITIAL_REWARDS
                assert settled.data["battle_id"] is None
                with sqlite3.connect(recovered.settings.database_path) as connection:
                    inventory_text, stamina, energy = connection.execute(
                        "SELECT inventory_json, stamina, energy FROM players "
                        "WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    ).fetchone()
                    binding = connection.execute(
                        "SELECT item_key, quantity FROM exploration_item_bindings "
                        "WHERE source_operation_id=?",
                        (settle_operation,),
                    ).fetchone()
                assert json.loads(inventory_text) == INITIAL_REWARDS
                assert (stamina, energy) == (92, 98)
                assert binding == ("item.demon_core", 1)

                before_replay = _state(recovered)
                replay = await _send(
                    recovered, adapter, user, settle_operation, "结算探索"
                )
                assert replay.data["idempotent_replay"] is True
                conflict = await _send(
                    recovered,
                    adapter,
                    user,
                    settle_operation,
                    "开始探索 深渊门备材",
                )
                assert conflict.code == "OPERATION_CONFLICT"
                assert _state(recovered) == before_replay

                next_start = f"{adapter}-demon-threshold-next"
                next_started = await _send(
                    recovered, adapter, user, next_start, "开始探索 深渊门备材"
                )
                assert next_started.code == "EXPLORATION_STARTED"
                next_id = str(next_started.data["exploration_id"])
                with sqlite3.connect(recovered.settings.database_path) as connection:
                    next_snapshot = json.loads(
                        connection.execute(
                            "SELECT snapshot_json FROM exploration_sessions WHERE exploration_id=?",
                            (next_id,),
                        ).fetchone()[0]
                    )
                assert next_snapshot["frozen_result"] == UPDATED_REWARDS
                _expire(recovered, next_id)
                next_settled = await _send(
                    recovered,
                    adapter,
                    user,
                    f"{adapter}-demon-threshold-next-settle",
                    "结算探索",
                )
                assert next_settled.data["result"] == UPDATED_REWARDS
                with sqlite3.connect(recovered.settings.database_path) as connection:
                    inventory_text, stamina, energy = connection.execute(
                        "SELECT inventory_json, stamina, energy FROM players "
                        "WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    ).fetchone()
                    binding_total = connection.execute(
                        "SELECT SUM(quantity) FROM exploration_item_bindings "
                        "WHERE player_id=(SELECT id FROM players WHERE platform=? AND platform_user_id=?)",
                        (adapter, user),
                    ).fetchone()[0]
                assert json.loads(inventory_text) == {
                    key: INITIAL_REWARDS.get(key, 0) + UPDATED_REWARDS.get(key, 0)
                    for key in INITIAL_REWARDS.keys() | UPDATED_REWARDS.keys()
                }
                assert (stamina, energy) == (84, 96)
                assert binding_total == 4
        finally:
            await recovered.close()

    asyncio.run(run())


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_demon_threshold_rejects_bad_reward_reference_atomically(
    tmp_path: Path, adapter: str
) -> None:
    async def run() -> None:
        data_dir = _copy_data(tmp_path)
        _set_pool(data_dir, {"item.missing": 1})
        runtime = create_runtime(data_dir=data_dir, adapters=(adapter,))
        try:
            user = f"demon-threshold-invalid-{adapter}"
            await _prepare_player(runtime, adapter, user)
            before = _state(runtime)
            rejected = await _send(
                runtime,
                adapter,
                user,
                "invalid-demon-threshold",
                "开始探索 深渊门备材",
            )
            assert rejected.code == "PERSISTENCE_ERROR"
            assert _state(runtime) == before
        finally:
            await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("adapter", ADAPTERS)
@pytest.mark.parametrize(
    ("field", "value", "expected_code"),
    (
        ("stamina", 7, "RESOURCE_INSUFFICIENT"),
        ("energy", 1, "ENERGY_INSUFFICIENT"),
    ),
)
def test_demon_threshold_rejects_insufficient_cost_without_partial_changes(
    tmp_path: Path,
    adapter: str,
    field: str,
    value: int,
    expected_code: str,
) -> None:
    async def run() -> None:
        data_dir = _copy_data(tmp_path)
        runtime = create_runtime(data_dir=data_dir, adapters=(adapter,))
        try:
            user = f"demon-threshold-{field}-{adapter}"
            await _prepare_player(runtime, adapter, user)
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    f"UPDATE players SET {field}=? WHERE platform=? AND platform_user_id=?",
                    (value, adapter, user),
                )
            before = _state(runtime)
            rejected = await _send(
                runtime,
                adapter,
                user,
                f"demon-threshold-low-{field}",
                "开始探索 深渊门备材",
            )
            assert rejected.code == expected_code
            assert _state(runtime) == before
        finally:
            await runtime.close()

    asyncio.run(run())


def test_demon_threshold_pool_maps_to_original_fixed_reward() -> None:
    assert reward_pool_map(POOL, "demon-threshold-fixed-result") == INITIAL_REWARDS
