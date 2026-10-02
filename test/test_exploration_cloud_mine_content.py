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
from nonebot_plugin_xiuxian_3.xiuxian.exploration.rules import battle_roll_bp


ADAPTERS = ("qq.official", "onebot.v11")
POOL = "reward_pool.exploration.cloud_mine"
MATERIAL = "item.material.cloud_iron"
FROZEN_REWARDS = {MATERIAL: 3}
CHANGED_REWARDS = {MATERIAL: 7}


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


def _set_failure_rewards(data_dir: Path, rewards: dict[str, int]) -> None:
    _update_record(
        data_dir / "奖励" / "奖励.json",
        POOL,
        battle_failure_rewards=rewards,
    )


def _set_beast_stats(data_dir: Path, *, outcome: str) -> None:
    stats = (
        {"hp": 1, "attack": 1, "initiative": 1, "agility": 1}
        if outcome == "won"
        else {"hp": 100_000, "attack": 100_000, "initiative": 1_000, "agility": 1_000}
    )
    _update_record(
        data_dir / "战斗" / "敌人.json",
        "enemy.cloud_beast",
        stats=stats,
        skills=["enemy_skill.cloud_armor"],
    )


async def _prepare_player(runtime, adapter: str, user: str, *, outcome: str = "won") -> None:
    created = await runtime.adapters.dispatch(
        adapter, _context(adapter, user, f"{user}-create"), "开始修仙"
    )
    assert created.code == "PLAYER_CREATED"
    max_hp = 20_000 if outcome == "won" else 1
    initiative = 20_000 if outcome == "won" else 1
    qualification = {"body": 10_000, "agility": 10_000} if outcome == "won" else {"body": 0, "agility": 0}
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE players SET stage='cultivator', realm_key='foundation', realm_layer=1, "
            "location_key='xuantian.cloud_mine', subprofession_key='mining', stamina=100, "
            "energy=100, max_hp=?, initiative=?, qualification_json=?, inventory_json=? "
            "WHERE platform=? AND platform_user_id=?",
            (
                max_hp,
                initiative,
                json.dumps(qualification),
                json.dumps({}),
                adapter,
                user,
            ),
        )


async def _send(runtime, adapter: str, user: str, operation_id: str, command: str):
    return await runtime.adapters.dispatch(
        adapter, _context(adapter, user, operation_id), command
    )


def _operation_for_battle(adapter: str, *, encounter: bool) -> str:
    return next(
        f"{adapter}-cloud-mine-{index}"
        for index in range(1_000)
        if (battle_roll_bp(f"{adapter}-cloud-mine-{index}:battle") < 3_000) == encounter
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


def test_cloud_mine_pool_freezes_across_restart_and_new_runs_use_current_content(
    tmp_path: Path,
) -> None:
    async def run() -> None:
        data_dir = _copy_data(tmp_path)
        _set_pool(data_dir, FROZEN_REWARDS)
        _update_record(data_dir / "道具" / "材料.json", MATERIAL, name="初开云铁")
        runtime = create_runtime(data_dir=data_dir, adapters=ADAPTERS)
        pending: dict[str, tuple[str, str, str]] = {}
        try:
            for adapter in ADAPTERS:
                user = f"cloud-mine-freeze-{adapter}"
                await _prepare_player(runtime, adapter, user)
                start_operation = _operation_for_battle(adapter, encounter=False)
                started = await _send(
                    runtime, adapter, user, start_operation, "开始探索 云铁矿区采集"
                )
                assert started.code == "EXPLORATION_STARTED"
                exploration_id = str(started.data["exploration_id"])
                _expire(runtime, exploration_id)
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    snapshot = json.loads(
                        connection.execute(
                            "SELECT snapshot_json FROM exploration_sessions WHERE exploration_id=?",
                            (exploration_id,),
                        ).fetchone()[0]
                    )
                assert snapshot["reward_pool_key"] == POOL
                assert snapshot["random_seed"] == start_operation
                assert snapshot["frozen_result"] == FROZEN_REWARDS
                assert snapshot["battle_failure_result"] == {MATERIAL: 1}
                pending[adapter] = (user, exploration_id, f"{adapter}-cloud-mine-settle")
        finally:
            await runtime.close()

        _set_pool(data_dir, CHANGED_REWARDS)
        _update_record(data_dir / "道具" / "材料.json", MATERIAL, name="新炼云铁")
        recovered = create_runtime(data_dir=data_dir, adapters=ADAPTERS)
        try:
            for adapter in ADAPTERS:
                user, exploration_id, settle_operation = pending[adapter]
                settled = await _send(recovered, adapter, user, settle_operation, "结算探索")
                assert settled.code == "EXPLORATION_SETTLED"
                assert settled.data["result"] == FROZEN_REWARDS
                assert "新炼云铁 ×3" in settled.message
                with sqlite3.connect(recovered.settings.database_path) as connection:
                    inventory_text, stamina, energy, session_status = connection.execute(
                        "SELECT players.inventory_json, players.stamina, players.energy, "
                        "exploration_sessions.status FROM players "
                        "JOIN exploration_sessions ON exploration_sessions.player_id=players.id "
                        "WHERE exploration_id=?",
                        (exploration_id,),
                    ).fetchone()
                assert json.loads(inventory_text) == {MATERIAL: 3}
                assert (stamina, energy, session_status) == (92, 98, "settled")

                before_replay = _state(recovered)
                replay = await _send(recovered, adapter, user, settle_operation, "结算探索")
                assert replay.data["idempotent_replay"] is True
                conflict = await _send(
                    recovered, adapter, user, settle_operation, "开始探索 云铁矿区采集"
                )
                assert conflict.code == "OPERATION_CONFLICT"
                assert _state(recovered) == before_replay

                next_start = _operation_for_battle(f"{adapter}-next", encounter=False)
                next_started = await _send(
                    recovered, adapter, user, next_start, "开始探索 云铁矿区采集"
                )
                assert next_started.code == "EXPLORATION_STARTED"
                _expire(recovered, str(next_started.data["exploration_id"]))
                next_settled = await _send(
                    recovered, adapter, user, f"{adapter}-next-settle", "结算探索"
                )
                assert next_settled.data["result"] == CHANGED_REWARDS
                with sqlite3.connect(recovered.settings.database_path) as connection:
                    inventory_text, stamina, energy = connection.execute(
                        "SELECT inventory_json, stamina, energy FROM players "
                        "WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    ).fetchone()
                assert json.loads(inventory_text) == {MATERIAL: 10}
                assert (stamina, energy) == (84, 96)
        finally:
            await recovered.close()

    asyncio.run(run())


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_cloud_mine_rejects_invalid_reward_content_without_cost_or_session(
    tmp_path: Path, adapter: str
) -> None:
    async def run() -> None:
        data_dir = _copy_data(tmp_path)
        _set_pool(data_dir, {"item.missing": 2})
        runtime = create_runtime(data_dir=data_dir, adapters=(adapter,))
        try:
            user = f"cloud-mine-invalid-{adapter}"
            await _prepare_player(runtime, adapter, user)
            before = _state(runtime)
            rejected = await _send(
                runtime, adapter, user, "invalid-cloud-mine", "开始探索 云铁矿区采集"
            )
            assert rejected.code == "PERSISTENCE_ERROR"
            assert _state(runtime) == before
        finally:
            await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("adapter", ADAPTERS)
@pytest.mark.parametrize("outcome", ("won", "lost"))
def test_cloud_mine_real_battles_settle_frozen_rewards_by_battle_result(
    tmp_path: Path, adapter: str, outcome: str
) -> None:
    async def run() -> None:
        data_dir = _copy_data(tmp_path)
        _set_pool(data_dir, {MATERIAL: 4})
        _set_beast_stats(data_dir, outcome=outcome)
        runtime = create_runtime(data_dir=data_dir, adapters=(adapter,))
        try:
            user = f"cloud-mine-battle-{outcome}-{adapter}"
            await _prepare_player(runtime, adapter, user, outcome=outcome)
            start_operation = _operation_for_battle(adapter, encounter=True)
            started = await _send(
                runtime, adapter, user, start_operation, "开始探索 云铁矿区采集"
            )
            assert started.code == "EXPLORATION_STARTED"
            exploration_id = str(started.data["exploration_id"])
            _expire(runtime, exploration_id)
            with sqlite3.connect(runtime.settings.database_path) as connection:
                snapshot = json.loads(
                    connection.execute(
                        "SELECT snapshot_json FROM exploration_sessions WHERE exploration_id=?",
                        (exploration_id,),
                    ).fetchone()[0]
                )
            assert snapshot["reward_pool_key"] == POOL
            assert snapshot["battle_chance_bp"] == snapshot["base_battle_chance_bp"] == 3_000
            assert snapshot["frozen_result"] == {MATERIAL: 4}
            assert snapshot["battle_failure_result"] == {MATERIAL: 1}

            settle_operation = f"{user}-settle"
            settled = await _send(runtime, adapter, user, settle_operation, "结算探索")
            assert settled.code == "EXPLORATION_SETTLED"
            assert settled.data["battle_outcome"] == outcome
            expected = {MATERIAL: 4 if outcome == "won" else 1}
            assert settled.data["result"] == expected
            with sqlite3.connect(runtime.settings.database_path) as connection:
                status, reward_status, battle_type, enemy_key, battle_json = connection.execute(
                    "SELECT status, reward_status, battle_type, enemy_key, state_json "
                    "FROM battle_sessions WHERE battle_id=?",
                    (settled.data["battle_id"],),
                ).fetchone()
                inventory_text, stamina, energy = connection.execute(
                    "SELECT inventory_json, stamina, energy FROM players "
                    "WHERE platform=? AND platform_user_id=?",
                    (adapter, user),
                ).fetchone()
            assert (status, reward_status, battle_type, enemy_key) == (
                "settled", "none", "pve.exploration", "enemy.cloud_beast"
            )
            state = json.loads(battle_json)
            assert state["enemy_hp" if outcome == "won" else "player_hp"] == 0
            assert json.loads(inventory_text) == expected
            assert (stamina, energy) == (92, 98)

            before_replay = _state(runtime)
            replay = await _send(runtime, adapter, user, settle_operation, "结算探索")
            assert replay.data["idempotent_replay"] is True
            assert replay.data["result"] == expected
            assert _state(runtime) == before_replay
        finally:
            await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_cloud_mine_failure_reward_recovers_from_snapshot_after_content_change(
    tmp_path: Path, adapter: str
) -> None:
    async def run() -> None:
        data_dir = _copy_data(tmp_path)
        _set_pool(data_dir, {MATERIAL: 4})
        _set_beast_stats(data_dir, outcome="lost")
        runtime = create_runtime(data_dir=data_dir, adapters=(adapter,))
        user = f"cloud-mine-recovery-{adapter}"
        settle_operation = f"{user}-settle"
        try:
            await _prepare_player(runtime, adapter, user, outcome="lost")
            start_operation = _operation_for_battle(adapter, encounter=True)
            started = await _send(
                runtime, adapter, user, start_operation, "开始探索 云铁矿区采集"
            )
            assert started.code == "EXPLORATION_STARTED"
            exploration_id = str(started.data["exploration_id"])
            _expire(runtime, exploration_id)

            async def interrupt_battle(*args, **kwargs):
                raise RuntimeError("injected process interruption")

            runtime.repository._run_exploration_battle = interrupt_battle
            interrupted = await _send(runtime, adapter, user, settle_operation, "结算探索")
            assert interrupted.code == "PERSISTENCE_ERROR"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                status, result_text = connection.execute(
                    "SELECT status, result_json FROM exploration_sessions WHERE exploration_id=?",
                    (exploration_id,),
                ).fetchone()
                battle_status = connection.execute(
                    "SELECT status FROM battle_sessions WHERE battle_id=?",
                    (json.loads(result_text)["battle_id"],),
                ).fetchone()[0]
            assert status == "combat_pending"
            assert battle_status == "created"
            assert json.loads(result_text)["battle_failure_result"] == {MATERIAL: 1}
        finally:
            await runtime.close()

        _set_failure_rewards(data_dir, {MATERIAL: 9})
        recovered = create_runtime(data_dir=data_dir, adapters=(adapter,))
        try:
            settled = await _send(recovered, adapter, user, settle_operation, "结算探索")
            assert settled.code == "EXPLORATION_SETTLED"
            assert settled.data["battle_outcome"] == "lost"
            assert settled.data["result"] == {MATERIAL: 1}
            with sqlite3.connect(recovered.settings.database_path) as connection:
                inventory_text, stamina, energy = connection.execute(
                    "SELECT inventory_json, stamina, energy FROM players "
                    "WHERE platform=? AND platform_user_id=?",
                    (adapter, user),
                ).fetchone()
            assert json.loads(inventory_text) == {MATERIAL: 1}
            assert (stamina, energy) == (92, 98)

            before_replay = _state(recovered)
            replay = await _send(recovered, adapter, user, settle_operation, "结算探索")
            assert replay.data["idempotent_replay"] is True
            assert replay.data["result"] == {MATERIAL: 1}
            assert _state(recovered) == before_replay
        finally:
            await recovered.close()

    asyncio.run(run())
