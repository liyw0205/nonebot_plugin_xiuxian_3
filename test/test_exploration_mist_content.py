from __future__ import annotations

import asyncio
import json
import shutil
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.exploration.rules import battle_roll_bp
from nonebot_plugin_xiuxian_3.xiuxian.specials.codex_projection import record_material_discoveries


ADAPTERS = ("qq.official", "onebot.v11")
POOL = "reward_pool.exploration.mist_grotto"
MATERIAL = "item.mat.array_sand"
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


def _set_guardian_stats(data_dir: Path, *, outcome: str) -> None:
    stats = (
        {"hp": 1, "attack": 1, "initiative": 1, "agility": 1}
        if outcome == "won"
        else {"hp": 100_000, "attack": 100_000, "initiative": 1_000, "agility": 1_000}
    )
    _update_record(
        data_dir / "战斗" / "敌人.json",
        "enemy.mist_guardian",
        stats=stats,
    )


async def _prepare_player(
    runtime,
    adapter: str,
    user: str,
    *,
    max_hp: int = 1_000,
    initiative: int = 100,
    qualification: dict[str, int] | None = None,
) -> None:
    created = await runtime.adapters.dispatch(
        adapter, _context(adapter, user, f"{user}-create"), "开始修仙"
    )
    assert created.code == "PLAYER_CREATED"
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE players SET stage='cultivator', realm_key='qi_gathering', realm_layer=4, "
            "location_key='cave.mist_grotto', stamina=100, max_hp=?, initiative=?, "
            "qualification_json=?, inventory_json=? WHERE platform=? AND platform_user_id=?",
            (
                max_hp,
                initiative,
                json.dumps(qualification or {"body": 2_000, "agility": 2_000}),
                json.dumps({"item.cave_pass_basic": 1}),
                adapter,
                user,
            ),
        )


async def _send(runtime, adapter: str, user: str, operation: str, command: str):
    return await runtime.adapters.dispatch(adapter, _context(adapter, user, operation), command)


def _operation_for_encounter(adapter: str, threshold: int) -> str:
    return next(
        f"{adapter}-mist-{index}"
        for index in range(1_000)
        if battle_roll_bp(f"{adapter}-mist-{index}:battle") < threshold
    )


def _operation_without_encounter(adapter: str, threshold: int) -> str:
    return next(
        f"{adapter}-mist-{index}"
        for index in range(1_000)
        if battle_roll_bp(f"{adapter}-mist-{index}:battle") >= threshold
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
            for table in ("players", "exploration_sessions", "operations", "codex_entries", "battle_sessions")
        }


def _codex_rows(runtime, adapter: str, user: str) -> list[tuple]:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        return connection.execute(
            "SELECT * FROM codex_entries WHERE player_id="
            "(SELECT id FROM players WHERE platform=? AND platform_user_id=?) ORDER BY entry_key",
            (adapter, user),
        ).fetchall()


def test_mist_grotto_pool_freezes_across_restart_and_new_runs_use_current_content(tmp_path: Path) -> None:
    async def run() -> None:
        data_dir = _copy_data(tmp_path)
        _set_pool(data_dir, FROZEN_REWARDS)
        _update_record(data_dir / "道具" / "材料.json", MATERIAL, name="初开雾砂")
        runtime = create_runtime(data_dir=data_dir, adapters=ADAPTERS)
        pending: dict[str, tuple[str, str, str]] = {}
        try:
            for adapter in ADAPTERS:
                user = f"mist-freeze-{adapter}"
                await _prepare_player(runtime, adapter, user)
                start_operation = _operation_without_encounter(adapter, 2_500)
                started = await _send(runtime, adapter, user, start_operation, "开始探索 雾隐洞天探索")
                assert started.code == "EXPLORATION_STARTED"
                exploration_id = str(started.data["exploration_id"])
                _expire(runtime, exploration_id)
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    snapshot_text = connection.execute(
                        "SELECT snapshot_json FROM exploration_sessions WHERE exploration_id=?",
                        (exploration_id,),
                    ).fetchone()[0]
                    operation_text = connection.execute(
                        "SELECT result_json FROM operations WHERE operation_id=?",
                        (start_operation,),
                    ).fetchone()[0]
                snapshot = json.loads(snapshot_text)
                start_record = json.loads(operation_text)
                assert snapshot["mode_key"] == "explore.mist_grotto"
                assert snapshot["reward_pool_key"] == POOL
                assert snapshot["random_seed"] == start_operation
                assert snapshot["battle_chance_bp"] == snapshot["base_battle_chance_bp"] == 2_500
                assert snapshot["frozen_result"] == FROZEN_REWARDS
                assert start_record["frozen_result"] == FROZEN_REWARDS
                pending[adapter] = (user, exploration_id, f"{adapter}-mist-settle")
        finally:
            await runtime.close()

        _set_pool(data_dir, CHANGED_REWARDS)
        _update_record(data_dir / "道具" / "材料.json", MATERIAL, name="云雾阵砂")
        recovered = create_runtime(data_dir=data_dir, adapters=ADAPTERS)
        try:
            for adapter in ADAPTERS:
                user, exploration_id, settle_operation = pending[adapter]
                settled = await _send(recovered, adapter, user, settle_operation, "结算探索")
                assert settled.code == "EXPLORATION_SETTLED"
                assert settled.data["result"] == FROZEN_REWARDS
                assert "境内修为 +777" in settled.message
                assert "云雾阵砂" in settled.message
                assert not any(word in settled.message for word in ("会话", "快照", "冻结", "版本", "请求编号"))
                with sqlite3.connect(recovered.settings.database_path) as connection:
                    inventory_text, cultivation, total_cultivation, stamina = connection.execute(
                        "SELECT inventory_json, cultivation, total_cultivation, stamina FROM players "
                        "WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    ).fetchone()
                    session_status = connection.execute(
                        "SELECT status FROM exploration_sessions WHERE exploration_id=?", (exploration_id,)
                    ).fetchone()[0]
                assert json.loads(inventory_text) == {"item.cave_pass_basic": 1, MATERIAL: 3}
                assert (cultivation, total_cultivation, stamina, session_status) == (777, 777, 90, "settled")

                before_replay = _state(recovered)
                replay = await _send(recovered, adapter, user, settle_operation, "结算探索")
                assert replay.data["idempotent_replay"] is True
                assert replay.data["result"] == FROZEN_REWARDS
                conflict = await _send(
                    recovered, adapter, user, settle_operation, "开始探索 雾隐洞天探索"
                )
                assert conflict.code == "OPERATION_CONFLICT"
                assert _state(recovered) == before_replay

                next_start_operation = _operation_without_encounter(f"{adapter}-next", 2_500)
                next_started = await _send(
                    recovered, adapter, user, next_start_operation, "开始探索 雾隐洞天探索"
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
                assert json.loads(inventory_text) == {"item.cave_pass_basic": 1, MATERIAL: 9}
                assert (cultivation, total_cultivation, stamina) == (1_776, 1_776, 80)
        finally:
            await recovered.close()

    asyncio.run(run())


@pytest.mark.parametrize("adapter", ADAPTERS)
@pytest.mark.parametrize(
    ("location", "layer"),
    (("cave.mist_grotto", 3), ("xuantian.outskirts", 4)),
)
def test_mist_grotto_keeps_location_and_realm_gates(
    tmp_path: Path, adapter: str, location: str, layer: int,
) -> None:
    async def run() -> None:
        data_dir = _copy_data(tmp_path)
        runtime = create_runtime(data_dir=data_dir, adapters=(adapter,))
        try:
            user = f"mist-gate-{adapter}-{layer}"
            await _prepare_player(runtime, adapter, user)
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE players SET location_key=?, realm_layer=? WHERE platform=? AND platform_user_id=?",
                    (location, layer, adapter, user),
                )
            before = _state(runtime)
            denied = await _send(runtime, adapter, user, "denied", "开始探索 雾隐洞天探索")
            assert denied.code == "EXPLORATION_LOCATION_FORBIDDEN"
            assert _state(runtime) == before
        finally:
            await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_mist_grotto_rejects_invalid_pool_without_charging_or_session(
    tmp_path: Path, adapter: str,
) -> None:
    async def run() -> None:
        data_dir = _copy_data(tmp_path)
        _set_pool(data_dir, {"item.missing": 1})
        runtime = create_runtime(data_dir=data_dir, adapters=(adapter,))
        try:
            user = f"mist-invalid-{adapter}"
            await _prepare_player(runtime, adapter, user)
            before = _state(runtime)
            rejected = await _send(runtime, adapter, user, "invalid-start", "开始探索 雾隐洞天探索")
            assert rejected.code == "PERSISTENCE_ERROR"
            assert _state(runtime) == before
        finally:
            await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_mist_grotto_codex_projection_failure_rolls_back_then_retries_once(
    tmp_path: Path, adapter: str,
) -> None:
    async def run() -> None:
        data_dir = _copy_data(tmp_path)
        _set_pool(data_dir, FROZEN_REWARDS)
        runtime = create_runtime(data_dir=data_dir, adapters=(adapter,))
        try:
            user = f"mist-projection-{adapter}"
            await _prepare_player(runtime, adapter, user)
            start_operation = _operation_without_encounter(f"{adapter}-projection", 2_500)
            started = await _send(runtime, adapter, user, start_operation, "开始探索 雾隐洞天探索")
            assert started.code == "EXPLORATION_STARTED"
            exploration_id = str(started.data["exploration_id"])
            _expire(runtime, exploration_id)
            before = _state(runtime)
            original = record_material_discoveries

            def fail_after_projection(*args, **kwargs):
                original(*args, **kwargs)
                raise RuntimeError("injected codex projection failure")

            with patch(
                "nonebot_plugin_xiuxian_3.xiuxian.exploration.repository.record_material_discoveries",
                autospec=True,
                side_effect=fail_after_projection,
            ):
                failed = await _send(runtime, adapter, user, "settle", "结算探索")
            assert failed.code == "PERSISTENCE_ERROR"
            assert _state(runtime) == before

            results = await asyncio.gather(*(
                _send(runtime, adapter, user, "settle", "结算探索") for _ in range(2)
            ))
            assert all(result.code == "EXPLORATION_SETTLED" for result in results)
            assert all(result.data["result"] == FROZEN_REWARDS for result in results)
            assert sorted(result.data["idempotent_replay"] for result in results) == [False, True]
            after = _state(runtime)
            assert _codex_rows(runtime, adapter, user)
            replay = await _send(runtime, adapter, user, "settle", "结算探索")
            assert replay.data["idempotent_replay"] is True
            assert _state(runtime) == after
        finally:
            await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("outcome", ("won", "lost"))
def test_mist_grotto_real_encounters_settle_frozen_rewards_by_battle_result(
    tmp_path: Path, outcome: str,
) -> None:
    async def run() -> None:
        data_dir = _copy_data(tmp_path)
        _set_pool(data_dir, FROZEN_REWARDS)
        _set_guardian_stats(data_dir, outcome=outcome)
        runtime = create_runtime(data_dir=data_dir, adapters=ADAPTERS)
        try:
            for adapter in ADAPTERS:
                user = f"mist-battle-{outcome}-{adapter}"
                await _prepare_player(
                    runtime,
                    adapter,
                    user,
                    max_hp=20_000 if outcome == "won" else 1,
                    initiative=20_000 if outcome == "won" else 1,
                    qualification=(
                        {"body": 10_000, "agility": 10_000}
                        if outcome == "won"
                        else {"body": 0, "agility": 0}
                    ),
                )
                start_operation = _operation_for_encounter(adapter, 2_500)
                started = await _send(runtime, adapter, user, start_operation, "开始探索 雾隐洞天探索")
                assert started.code == "EXPLORATION_STARTED"
                exploration_id = str(started.data["exploration_id"])
                _expire(runtime, exploration_id)
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    snapshot = json.loads(connection.execute(
                        "SELECT snapshot_json FROM exploration_sessions WHERE exploration_id=?",
                        (exploration_id,),
                    ).fetchone()[0])
                assert snapshot["reward_pool_key"] == POOL
                assert snapshot["battle_chance_bp"] == snapshot["base_battle_chance_bp"] == 2_500
                assert snapshot["frozen_result"] == FROZEN_REWARDS
                codex_before = _codex_rows(runtime, adapter, user)

                settled = await _send(runtime, adapter, user, f"{user}-settle", "结算探索")
                assert settled.code == "EXPLORATION_SETTLED"
                assert settled.data["battle_outcome"] == outcome, settled.data
                expected = FROZEN_REWARDS if outcome == "won" else {}
                assert settled.data["result"] == expected
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    status, reward_status, battle_type, enemy_key, battle_state = connection.execute(
                        "SELECT status, reward_status, battle_type, enemy_key, state_json "
                        "FROM battle_sessions WHERE battle_id=?",
                        (settled.data["battle_id"],),
                    ).fetchone()
                    player = connection.execute(
                        "SELECT inventory_json, cultivation, total_cultivation, stamina FROM players "
                        "WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    ).fetchone()
                    session_result = json.loads(connection.execute(
                        "SELECT result_json FROM exploration_sessions WHERE exploration_id=?",
                        (exploration_id,),
                    ).fetchone()[0])
                assert (status, reward_status, battle_type, enemy_key) == (
                    "settled", "none", "pve.exploration", "enemy.mist_guardian"
                )
                state = json.loads(battle_state)
                assert state["enemy_hp" if outcome == "won" else "player_hp"] == 0
                assert session_result["frozen_result"] == FROZEN_REWARDS
                inventory_text, cultivation, total_cultivation, stamina = player
                assert json.loads(inventory_text) == {
                    "item.cave_pass_basic": 1,
                    **({MATERIAL: expected[MATERIAL]} if MATERIAL in expected else {}),
                }
                assert (cultivation, total_cultivation, stamina) == (
                    expected.get("cultivation", 0), expected.get("cultivation", 0), 90
                )
                codex_after = _codex_rows(runtime, adapter, user)
                if outcome == "won":
                    assert len(codex_after) > len(codex_before)
                else:
                    assert codex_after == codex_before

                before_replay = _state(runtime)
                replay = await _send(runtime, adapter, user, f"{user}-settle", "结算探索")
                assert replay.data["idempotent_replay"] is True
                assert replay.data["result"] == expected
                assert _state(runtime) == before_replay
        finally:
            await runtime.close()

    asyncio.run(run())
