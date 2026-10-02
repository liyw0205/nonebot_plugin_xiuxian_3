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
from nonebot_plugin_xiuxian_3.xiuxian.exploration.rules import (
    battle_roll_bp,
    exploration_definition,
)
from nonebot_plugin_xiuxian_3.xiuxian.rewards.rules import reward_pool_map


ADAPTERS = ("qq.official", "onebot.v11")
POOL = "reward_pool.exploration.ancestral_lake"
INITIAL_REWARDS = {
    "item.ancestral_blood": 1,
    "faction_reputation.beast": 30,
}
UPDATED_REWARDS = {
    "item.ancestral_blood": 2,
    "faction_reputation.beast": 45,
}


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


async def _prepare_player(
    runtime, adapter: str, user: str, *, strong: bool = True
) -> None:
    created = await runtime.adapters.dispatch(
        adapter, _context(adapter, user, f"{user}-create"), "开始修仙"
    )
    assert created.code == "PLAYER_CREATED"
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE players SET stage='cultivator', realm_key='soul_transformation', realm_layer=1, "
            "location_key='beast.ancestral_lake', stamina=100, stamina_max=100, "
            "energy=30, energy_max=30, bloodline_stability=60, max_hp=?, initiative=?, "
            "qualification_json=?, faction_reputation_json=? "
            "WHERE platform=? AND platform_user_id=?",
            (
                100_000 if strong else 100,
                100_000 if strong else 8,
                json.dumps({"body": 100_000, "agility": 100_000} if strong else {"body": 0, "agility": 0}),
                json.dumps({"beast": 3_000}),
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
            for table in ("players", "exploration_sessions", "operations", "battle_sessions")
        }


def _no_encounter_operation(prefix: str) -> str:
    encounter_chance_bp = exploration_definition("explore.ancestral_lake").battle_chance_bp
    return next(
        f"{prefix}-{index}"
        for index in range(10_000)
        if battle_roll_bp(f"{prefix}-{index}:battle") >= encounter_chance_bp
    )


def test_ancestral_lake_pool_freezes_across_restart_and_new_runs_read_current_content(
    tmp_path: Path,
) -> None:
    async def run() -> None:
        data_dir = _copy_data(tmp_path)
        runtime = create_runtime(data_dir=data_dir, adapters=ADAPTERS)
        pending: dict[str, tuple[str, str, str]] = {}
        try:
            for adapter in ADAPTERS:
                user = f"ancestral-freeze-{adapter}"
                await _prepare_player(runtime, adapter, user)
                start_operation = _no_encounter_operation(f"{adapter}-ancestral-first")
                started = await _send(
                    runtime, adapter, user, start_operation, "开始探索 祖灵湖探索"
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
                assert snapshot["bloodline_stability_before"] == 60
                assert snapshot["bloodline_stability_after"] == 55
                before_replay = _state(runtime)
                replay = await _send(
                    runtime, adapter, user, start_operation, "开始探索 祖灵湖探索"
                )
                assert replay.data["idempotent_replay"] is True
                assert replay.data["exploration_id"] == exploration_id
                assert _state(runtime) == before_replay
                pending[adapter] = (user, exploration_id, f"{adapter}-ancestral-settle")
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
                    inventory_text, faction_text, stability, stamina = connection.execute(
                        "SELECT inventory_json, faction_reputation_json, bloodline_stability, stamina "
                        "FROM players WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    ).fetchone()
                assert json.loads(inventory_text) == {"item.ancestral_blood": 1}
                assert json.loads(faction_text)["beast"] == 3_030
                assert (stability, stamina) == (55, 75)

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
                    "开始探索 祖灵湖探索",
                )
                assert conflict.code == "OPERATION_CONFLICT"
                assert _state(recovered) == before_replay

                next_start = _no_encounter_operation(f"{adapter}-ancestral-next")
                next_started = await _send(
                    recovered, adapter, user, next_start, "开始探索 祖灵湖探索"
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
                    f"{adapter}-ancestral-next-settle",
                    "结算探索",
                )
                assert next_settled.data["result"] == UPDATED_REWARDS
                with sqlite3.connect(recovered.settings.database_path) as connection:
                    inventory_text, faction_text, stability = connection.execute(
                        "SELECT inventory_json, faction_reputation_json, bloodline_stability "
                        "FROM players WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    ).fetchone()
                assert json.loads(inventory_text) == {"item.ancestral_blood": 3}
                assert json.loads(faction_text)["beast"] == 3_075
                assert stability == 50
        finally:
            await recovered.close()

    asyncio.run(run())


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_ancestral_lake_rejects_bad_reward_reference_atomically(
    tmp_path: Path, adapter: str
) -> None:
    async def run() -> None:
        data_dir = _copy_data(tmp_path)
        _set_pool(data_dir, {"item.missing": 1})
        runtime = create_runtime(data_dir=data_dir, adapters=(adapter,))
        try:
            user = f"ancestral-invalid-{adapter}"
            await _prepare_player(runtime, adapter, user)
            before = _state(runtime)
            rejected = await _send(
                runtime,
                adapter,
                user,
                "invalid-ancestral-reward",
                "开始探索 祖灵湖探索",
            )
            assert rejected.code == "PERSISTENCE_ERROR"
            assert _state(runtime) == before
        finally:
            await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("adapter", ADAPTERS)
@pytest.mark.parametrize("outcome", ("won", "lost"))
def test_ancestral_lake_real_encounters_settle_frozen_rewards_and_stability(
    tmp_path: Path, adapter: str, outcome: str
) -> None:
    async def run() -> None:
        data_dir = _copy_data(tmp_path)
        runtime = create_runtime(data_dir=data_dir, adapters=(adapter,))
        try:
            user = f"ancestral-{outcome}-{adapter}"
            await _prepare_player(runtime, adapter, user, strong=outcome == "won")
            operation = next(
                f"{user}-encounter-{index}"
                for index in range(10_000)
                if battle_roll_bp(f"{user}-encounter-{index}:battle")
                < exploration_definition("explore.ancestral_lake").battle_chance_bp
            )
            started = await _send(
                runtime, adapter, user, operation, "开始探索 祖灵湖探索"
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
            assert snapshot["frozen_result"] == INITIAL_REWARDS
            assert snapshot["bloodline_stability_after"] == 55
            _expire(runtime, exploration_id)

            settle_operation = f"{user}-settle"
            settled = await _send(
                runtime, adapter, user, settle_operation, "结算探索"
            )
            expected = INITIAL_REWARDS if outcome == "won" else {}
            assert settled.code == "EXPLORATION_SETTLED"
            assert settled.data["battle_outcome"] == outcome
            assert settled.data["result"] == expected
            with sqlite3.connect(runtime.settings.database_path) as connection:
                inventory_text, faction_text, stability, stamina = connection.execute(
                    "SELECT inventory_json, faction_reputation_json, bloodline_stability, stamina "
                    "FROM players WHERE platform=? AND platform_user_id=?",
                    (adapter, user),
                ).fetchone()
                battle_status, reward_status, enemy_key, battle_type = connection.execute(
                    "SELECT status, reward_status, enemy_key, battle_type FROM battle_sessions "
                    "WHERE battle_id=?",
                    (settled.data["battle_id"],),
                ).fetchone()
            assert json.loads(inventory_text) == (
                {"item.ancestral_blood": 1} if outcome == "won" else {}
            )
            assert json.loads(faction_text)["beast"] == (
                3_030 if outcome == "won" else 3_000
            )
            assert (stability, stamina) == (55, 75)
            assert (battle_status, reward_status, enemy_key, battle_type) == (
                "settled",
                "none",
                "enemy.ancestral_spirit",
                "pve.exploration",
            )

            before_replay = _state(runtime)
            replay = await _send(
                runtime, adapter, user, settle_operation, "结算探索"
            )
            assert replay.data["idempotent_replay"] is True
            assert replay.data["battle_id"] == settled.data["battle_id"]
            assert _state(runtime) == before_replay
        finally:
            await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_ancestral_lake_rejects_insufficient_bloodline_stability_atomically(
    tmp_path: Path, adapter: str
) -> None:
    async def run() -> None:
        data_dir = _copy_data(tmp_path)
        runtime = create_runtime(data_dir=data_dir, adapters=(adapter,))
        try:
            user = f"ancestral-low-stability-{adapter}"
            await _prepare_player(runtime, adapter, user)
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE players SET bloodline_stability=49 WHERE platform=? AND platform_user_id=?",
                    (adapter, user),
                )
            before = _state(runtime)
            rejected = await _send(
                runtime,
                adapter,
                user,
                "ancestral-low-stability",
                "开始探索 祖灵湖探索",
            )
            assert rejected.code == "EXPLORATION_LOCATION_FORBIDDEN"
            assert _state(runtime) == before
        finally:
            await runtime.close()

    asyncio.run(run())


def test_ancestral_lake_pool_maps_to_original_fixed_reward() -> None:
    assert reward_pool_map(POOL, "ancestral-lake-fixed-result") == INITIAL_REWARDS
