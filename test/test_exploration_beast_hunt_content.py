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
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle
from nonebot_plugin_xiuxian_3.xiuxian.rewards.rules import reward_pool_map


ADAPTERS = ("qq.official", "onebot.v11")
POOL = "reward_pool.exploration.beast_hunt"
FROZEN_REWARDS = {"item.beast_blood": 4}
CHANGED_REWARDS = {"item.clue.beast_bloodline": 2}


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


def _set_guardian(data_dir: Path, *, outcome: str) -> None:
    stats = (
        {"hp": 1, "attack": 1, "initiative": 1, "agility": 1}
        if outcome == "won"
        else {"hp": 100_000, "attack": 100_000, "initiative": 1_000, "agility": 1_000}
    )
    _update_record(
        data_dir / "战斗" / "敌人.json",
        "enemy.beast_guardian",
        stats=stats,
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
            "UPDATE players SET stage='cultivator', realm_key='nascent_soul', realm_layer=1, "
            "location_key='beast.ten_thousand_hills', stamina=100, stamina_max=100, "
            "energy=30, energy_max=30, bloodline_stability=33, max_hp=?, initiative=?, "
            "qualification_json=?, faction_reputation_json=? WHERE platform=? AND platform_user_id=?",
            (
                max_hp,
                initiative,
                json.dumps(qualification),
                json.dumps({"beast": 200}),
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


def test_beast_hunt_pool_freezes_across_restart_and_new_runs_use_current_content(
    tmp_path: Path,
) -> None:
    async def run() -> None:
        data_dir = _copy_data(tmp_path)
        _set_pool(data_dir, FROZEN_REWARDS)
        runtime = create_runtime(data_dir=data_dir, adapters=ADAPTERS)
        pending: dict[str, tuple[str, str, str]] = {}
        try:
            for adapter in ADAPTERS:
                user = f"beast-freeze-{adapter}"
                await _prepare_player(runtime, adapter, user)
                start_operation = f"{adapter}-beast-hunt"
                started = await _send(
                    runtime, adapter, user, start_operation, "开始探索 万兽山狩猎"
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
                assert snapshot["frozen_result"] == FROZEN_REWARDS
                assert "battle_failure_result" not in snapshot
                pending[adapter] = (user, exploration_id, f"{adapter}-beast-settle")
        finally:
            await runtime.close()

        _set_pool(data_dir, CHANGED_REWARDS)
        recovered = create_runtime(data_dir=data_dir, adapters=ADAPTERS)
        try:
            for adapter in ADAPTERS:
                user, exploration_id, settle_operation = pending[adapter]
                _expire(recovered, exploration_id)
                settled = await _send(recovered, adapter, user, settle_operation, "结算探索")
                assert settled.code == "EXPLORATION_SETTLED"
                assert settled.data["battle_outcome"] == "won"
                assert settled.data["result"] == FROZEN_REWARDS
                with sqlite3.connect(recovered.settings.database_path) as connection:
                    inventory_text, stamina, energy = connection.execute(
                        "SELECT players.inventory_json, players.stamina, players.energy "
                        "FROM players JOIN exploration_sessions ON exploration_sessions.player_id=players.id "
                        "WHERE exploration_id=?",
                        (exploration_id,),
                    ).fetchone()
                    battle_type, enemy_key = connection.execute(
                        "SELECT battle_type, enemy_key FROM battle_sessions WHERE battle_id=?",
                        (settled.data["battle_id"],),
                    ).fetchone()
                assert json.loads(inventory_text) == FROZEN_REWARDS
                assert (stamina, energy) == (80, 30)
                assert (battle_type, enemy_key) == ("pve.exploration", "enemy.beast_guardian")

                before_replay = _state(recovered)
                replay = await _send(recovered, adapter, user, settle_operation, "结算探索")
                assert replay.data["idempotent_replay"] is True
                conflict = await _send(
                    recovered, adapter, user, settle_operation, "开始探索 万兽山狩猎"
                )
                assert conflict.code == "OPERATION_CONFLICT"
                assert _state(recovered) == before_replay

                next_start = f"{adapter}-beast-hunt-next"
                next_started = await _send(
                    recovered, adapter, user, next_start, "开始探索 妖界万兽山探索"
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
                assert next_snapshot["frozen_result"] == CHANGED_REWARDS
                _expire(recovered, next_id)
                next_settled = await _send(
                    recovered, adapter, user, f"{adapter}-beast-next-settle", "结算探索"
                )
                assert next_settled.data["result"] == CHANGED_REWARDS
                with sqlite3.connect(recovered.settings.database_path) as connection:
                    inventory_text, stamina = connection.execute(
                        "SELECT inventory_json, stamina FROM players "
                        "WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    ).fetchone()
                assert json.loads(inventory_text) == {**FROZEN_REWARDS, **CHANGED_REWARDS}
                assert stamina == 60
        finally:
            await recovered.close()

    asyncio.run(run())


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_beast_hunt_rejects_invalid_pool_without_cost_or_session(
    tmp_path: Path, adapter: str
) -> None:
    async def run() -> None:
        data_dir = _copy_data(tmp_path)
        _set_pool(data_dir, {"item.missing": 2})
        runtime = create_runtime(data_dir=data_dir, adapters=(adapter,))
        try:
            user = f"beast-invalid-{adapter}"
            await _prepare_player(runtime, adapter, user)
            before = _state(runtime)
            rejected = await _send(
                runtime, adapter, user, "invalid-beast-hunt", "开始探索 万兽山狩猎"
            )
            assert rejected.code == "PERSISTENCE_ERROR", (rejected.code, rejected.message)
            assert _state(runtime) == before
        finally:
            await runtime.close()

    asyncio.run(run())


def test_beast_hunt_no_reward_outcome_still_settles_real_battle_on_both_adapters(
    tmp_path: Path,
) -> None:
    async def run() -> None:
        data_dir = _copy_data(tmp_path)
        bundle = ContentBundle.load(data_dir)
        runtime = create_runtime(data_dir=data_dir, adapters=ADAPTERS)
        try:
            for adapter in ADAPTERS:
                user = f"beast-empty-{adapter}"
                await _prepare_player(runtime, adapter, user)
                start_operation = next(
                    f"{adapter}-beast-empty-{index}"
                    for index in range(2_000)
                    if reward_pool_map(
                        POOL,
                        f"{adapter}-beast-empty-{index}:reward",
                        bundle,
                    ) == {}
                )
                started = await _send(
                    runtime, adapter, user, start_operation, "开始探索 万兽山狩猎"
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
                assert snapshot["frozen_result"] == {}
                _expire(runtime, exploration_id)
                settled = await _send(
                    runtime, adapter, user, f"{user}-settle", "结算探索"
                )
                assert settled.code == "EXPLORATION_SETTLED"
                assert settled.data["battle_outcome"] == "won"
                assert settled.data["result"] == {}
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    inventory_text, stamina = connection.execute(
                        "SELECT inventory_json, stamina FROM players "
                        "WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    ).fetchone()
                    reward_bindings = connection.execute(
                        "SELECT COUNT(*) FROM exploration_item_bindings WHERE player_id="
                        "(SELECT id FROM players WHERE platform=? AND platform_user_id=?)",
                        (adapter, user),
                    ).fetchone()[0]
                assert json.loads(inventory_text) == {}
                assert stamina == 80
                assert reward_bindings == 0
        finally:
            await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("adapter", ADAPTERS)
@pytest.mark.parametrize("outcome", ("won", "lost"))
def test_beast_hunt_real_battles_settle_frozen_rewards_by_battle_result(
    tmp_path: Path, adapter: str, outcome: str
) -> None:
    async def run() -> None:
        data_dir = _copy_data(tmp_path)
        _set_pool(data_dir, FROZEN_REWARDS)
        _set_guardian(data_dir, outcome=outcome)
        runtime = create_runtime(data_dir=data_dir, adapters=(adapter,))
        try:
            user = f"beast-battle-{outcome}-{adapter}"
            await _prepare_player(runtime, adapter, user, outcome=outcome)
            started = await _send(
                runtime, adapter, user, f"{user}-start", "开始探索 万兽山狩猎"
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
            assert snapshot["frozen_result"] == FROZEN_REWARDS

            settle_operation = f"{user}-settle"
            settled = await _send(runtime, adapter, user, settle_operation, "结算探索")
            assert settled.code == "EXPLORATION_SETTLED"
            assert settled.data["battle_outcome"] == outcome
            expected = FROZEN_REWARDS if outcome == "won" else {}
            assert settled.data["result"] == expected
            with sqlite3.connect(runtime.settings.database_path) as connection:
                status, reward_status, battle_type, enemy_key = connection.execute(
                    "SELECT status, reward_status, battle_type, enemy_key FROM battle_sessions "
                    "WHERE battle_id=?",
                    (settled.data["battle_id"],),
                ).fetchone()
                inventory_text, stamina, stability = connection.execute(
                    "SELECT inventory_json, stamina, bloodline_stability FROM players "
                    "WHERE platform=? AND platform_user_id=?",
                    (adapter, user),
                ).fetchone()
            assert (status, reward_status, battle_type, enemy_key) == (
                "settled", "none", "pve.exploration", "enemy.beast_guardian"
            )
            assert json.loads(inventory_text) == expected
            assert (stamina, stability) == (80, 33)

            before_replay = _state(runtime)
            replay = await _send(runtime, adapter, user, settle_operation, "结算探索")
            assert replay.data["idempotent_replay"] is True
            assert replay.data["result"] == expected
            assert _state(runtime) == before_replay
        finally:
            await runtime.close()

    asyncio.run(run())
