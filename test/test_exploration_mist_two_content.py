from __future__ import annotations

import asyncio
import json
import shutil
import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.combat.rules import ENEMIES
from nonebot_plugin_xiuxian_3.xiuxian.exploration.rules import battle_roll_bp


ADAPTERS = ("qq.official", "onebot.v11")
POOL = "reward_pool.exploration.mist_grotto_2"
MATERIAL = "item.material.cloud_iron"
FROZEN_REWARDS = {"cultivation": 777, MATERIAL: 3}
CHANGED_REWARDS = {"cultivation": 999, MATERIAL: 6}


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


async def _prepare_player(runtime, adapter: str, user: str, *, outcome: str = "won") -> None:
    created = await runtime.adapters.dispatch(
        adapter, _context(adapter, user, f"{user}-create"), "开始修仙"
    )
    assert created.code == "PLAYER_CREATED"
    strong = outcome == "won"
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE players SET stage='cultivator', realm_key='golden_core', realm_layer=1, "
            "location_key='cave.mist_grotto_2', stamina=100, max_hp=?, initiative=?, "
            "qualification_json=?, inventory_json='{}' WHERE platform=? AND platform_user_id=?",
            (
                20_000 if strong else 1,
                20_000 if strong else 1,
                json.dumps({"body": 10_000, "agility": 10_000} if strong else {"body": 0, "agility": 0}),
                adapter,
                user,
            ),
        )


async def _send(runtime, adapter: str, user: str, operation: str, command: str):
    return await runtime.adapters.dispatch(adapter, _context(adapter, user, operation), command)


def _operation_for_encounter(adapter: str, *, encounter: bool) -> str:
    return next(
        f"{adapter}-mist-two-{index}"
        for index in range(1_000)
        if (battle_roll_bp(f"{adapter}-mist-two-{index}:battle") < 4_000) == encounter
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
                "players", "exploration_sessions", "operations", "codex_entries", "battle_sessions"
            )
        }


def test_mist_grotto_two_rewards_freeze_across_restart_for_both_adapters(tmp_path: Path) -> None:
    async def run() -> None:
        data_dir = _copy_data(tmp_path)
        _set_pool(data_dir, FROZEN_REWARDS)
        _update_record(data_dir / "道具" / "材料.json", MATERIAL, name="初开云铁")
        runtime = create_runtime(data_dir=data_dir, adapters=ADAPTERS)
        pending: dict[str, tuple[str, str, str]] = {}
        try:
            for adapter in ADAPTERS:
                user = f"mist-two-freeze-{adapter}"
                await _prepare_player(runtime, adapter, user)
                start_operation = _operation_for_encounter(adapter, encounter=False)
                started = await _send(
                    runtime, adapter, user, start_operation, "开始探索 洞天二层探索"
                )
                assert started.code == "EXPLORATION_STARTED"
                exploration_id = str(started.data["exploration_id"])
                _expire(runtime, exploration_id)
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    snapshot_text = connection.execute(
                        "SELECT snapshot_json FROM exploration_sessions WHERE exploration_id=?",
                        (exploration_id,),
                    ).fetchone()[0]
                snapshot = json.loads(snapshot_text)
                assert snapshot["reward_pool_key"] == POOL
                assert snapshot["random_seed"] == start_operation
                assert snapshot["frozen_result"] == FROZEN_REWARDS
                assert snapshot["stamina_cost"] == 15
                assert snapshot["battle_chance_bp"] == 4_000
                pending[adapter] = (user, exploration_id, f"{adapter}-mist-two-settle")
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
                assert "境内修为 +777" in settled.message
                assert "新炼云铁 ×3" in settled.message
                with sqlite3.connect(recovered.settings.database_path) as connection:
                    inventory_text, cultivation, total_cultivation, stamina = connection.execute(
                        "SELECT inventory_json, cultivation, total_cultivation, stamina FROM players "
                        "WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    ).fetchone()
                    status = connection.execute(
                        "SELECT status FROM exploration_sessions WHERE exploration_id=?",
                        (exploration_id,),
                    ).fetchone()[0]
                assert json.loads(inventory_text) == {MATERIAL: 3}
                assert (cultivation, total_cultivation, stamina, status) == (777, 777, 85, "settled")

                before_replay = _state(recovered)
                replay = await _send(recovered, adapter, user, settle_operation, "结算探索")
                assert replay.data["idempotent_replay"] is True
                conflict = await _send(
                    recovered, adapter, user, settle_operation, "开始探索 洞天二层探索"
                )
                assert conflict.code == "OPERATION_CONFLICT"
                assert _state(recovered) == before_replay

                next_operation = _operation_for_encounter(f"{adapter}-next", encounter=False)
                next_started = await _send(
                    recovered, adapter, user, next_operation, "开始探索 洞天二层探索"
                )
                assert next_started.code == "EXPLORATION_STARTED"
                _expire(recovered, str(next_started.data["exploration_id"]))
                next_settled = await _send(
                    recovered, adapter, user, f"{adapter}-next-settle", "结算探索"
                )
                assert next_settled.data["result"] == CHANGED_REWARDS
                assert "境内修为 +999" in next_settled.message
                with sqlite3.connect(recovered.settings.database_path) as connection:
                    inventory_text, cultivation, total_cultivation, stamina = connection.execute(
                        "SELECT inventory_json, cultivation, total_cultivation, stamina FROM players "
                        "WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    ).fetchone()
                assert json.loads(inventory_text) == {MATERIAL: 9}
                assert (cultivation, total_cultivation, stamina) == (1_776, 1_776, 70)
        finally:
            await recovered.close()

    asyncio.run(run())


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_mist_grotto_two_rejects_invalid_pool_without_cost_or_session(
    tmp_path: Path, adapter: str,
) -> None:
    async def run() -> None:
        data_dir = _copy_data(tmp_path)
        _set_pool(data_dir, {"item.missing": 1})
        runtime = create_runtime(data_dir=data_dir, adapters=(adapter,))
        try:
            user = f"mist-two-invalid-{adapter}"
            await _prepare_player(runtime, adapter, user)
            before = _state(runtime)
            rejected = await _send(
                runtime, adapter, user, "invalid-start", "开始探索 洞天二层探索"
            )
            assert rejected.code == "PERSISTENCE_ERROR"
            assert _state(runtime) == before
        finally:
            await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("outcome", ("won", "lost"))
def test_mist_grotto_two_real_encounters_settle_frozen_rewards_by_outcome(
    tmp_path: Path, outcome: str,
) -> None:
    async def run() -> None:
        data_dir = _copy_data(tmp_path)
        _set_pool(data_dir, FROZEN_REWARDS)
        runtime = create_runtime(data_dir=data_dir, adapters=ADAPTERS)
        base_enemy = ENEMIES["enemy.mist_elite"]
        test_enemy = replace(
            base_enemy,
            max_hp=1 if outcome == "won" else 100_000,
            attack=1 if outcome == "won" else 100_000,
            initiative=1 if outcome == "won" else 1_000,
            agility=1 if outcome == "won" else 1_000,
        )
        try:
            with patch.dict(ENEMIES, {"enemy.mist_elite": test_enemy}):
                for adapter in ADAPTERS:
                    user = f"mist-two-battle-{outcome}-{adapter}"
                    await _prepare_player(runtime, adapter, user, outcome=outcome)
                    start_operation = _operation_for_encounter(adapter, encounter=True)
                    started = await _send(
                        runtime, adapter, user, start_operation, "开始探索 洞天二层探索"
                    )
                    assert started.code == "EXPLORATION_STARTED"
                    exploration_id = str(started.data["exploration_id"])
                    _expire(runtime, exploration_id)
                    settled = await _send(
                        runtime, adapter, user, f"{user}-settle", "结算探索"
                    )
                    assert settled.code == "EXPLORATION_SETTLED"
                    assert settled.data["battle_outcome"] == outcome
                    expected = FROZEN_REWARDS if outcome == "won" else {}
                    assert settled.data["result"] == expected
                    with sqlite3.connect(runtime.settings.database_path) as connection:
                        inventory_text, cultivation, total_cultivation, stamina = connection.execute(
                            "SELECT inventory_json, cultivation, total_cultivation, stamina FROM players "
                            "WHERE platform=? AND platform_user_id=?",
                            (adapter, user),
                        ).fetchone()
                        battle_status, reward_status, battle_type, enemy_key = connection.execute(
                            "SELECT status, reward_status, battle_type, enemy_key FROM battle_sessions "
                            "WHERE battle_id=?",
                            (settled.data["battle_id"],),
                        ).fetchone()
                    assert json.loads(inventory_text) == (
                        {MATERIAL: 3} if outcome == "won" else {}
                    )
                    assert (cultivation, total_cultivation, stamina) == (
                        (777, 777, 85) if outcome == "won" else (0, 0, 85)
                    )
                    assert (battle_status, reward_status, battle_type, enemy_key) == (
                        "settled", "none", "pve.exploration", "enemy.mist_elite"
                    )
                    before_replay = _state(runtime)
                    replay = await _send(runtime, adapter, user, f"{user}-settle", "结算探索")
                    assert replay.data["idempotent_replay"] is True
                    assert replay.data["result"] == expected
                    assert _state(runtime) == before_replay
        finally:
            await runtime.close()

    asyncio.run(run())
