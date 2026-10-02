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
from nonebot_plugin_xiuxian_3.xiuxian.exploration.rules import settlement_result
from nonebot_plugin_xiuxian_3.xiuxian.rewards.rules import reward_pool_uses_item_weight_bonus


ADAPTERS = ("qq.official", "onebot.v11")
POOL = "reward_pool.exploration.demon_abyss"
FROZEN_REWARDS = {"item.demon_core": 3}
CHANGED_REWARDS = {"item.clue.demon_contract": 2}


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


def _set_pool(data_dir: Path, outcomes: list[dict[str, object]]) -> None:
    _update_record(
        data_dir / "奖励" / "奖励.json",
        POOL,
        outcomes=outcomes,
    )


async def _prepare_player(runtime, adapter: str, user: str) -> None:
    created = await runtime.adapters.dispatch(
        adapter, _context(adapter, user, f"{user}-create"), "开始修仙"
    )
    assert created.code == "PLAYER_CREATED"
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE players SET stage='cultivator', realm_key='nascent_soul', realm_layer=1, "
            "location_key='demon.fallen_ruins', stamina=100, stamina_max=100, "
            "energy=30, energy_max=30, soul_power=100, soul_power_max=100, max_hp=20000, "
            "initiative=20000, qualification_json=?, faction_reputation_json=? "
            "WHERE platform=? AND platform_user_id=?",
            (json.dumps({"body": 10_000, "agility": 10_000}), "{}", adapter, user),
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


def test_demon_abyss_pool_freezes_across_restart_and_new_runs_read_current_content(
    tmp_path: Path,
) -> None:
    async def run() -> None:
        data_dir = _copy_data(tmp_path)
        _set_pool(data_dir, [{"weight": 1, "rewards": FROZEN_REWARDS}])
        runtime = create_runtime(data_dir=data_dir, adapters=ADAPTERS)
        pending: dict[str, tuple[str, str, str]] = {}
        try:
            for adapter in ADAPTERS:
                user = f"demon-freeze-{adapter}"
                await _prepare_player(runtime, adapter, user)
                start_operation = f"{adapter}-demon-abyss"
                started = await _send(
                    runtime, adapter, user, start_operation, "开始探索 魔界堕落遗迹探索"
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
                assert snapshot["pollution_before"] == 0
                assert snapshot["pollution_after"] == 10
                pending[adapter] = (user, exploration_id, f"{adapter}-demon-settle")
        finally:
            await runtime.close()

        _set_pool(data_dir, [{"weight": 1, "rewards": CHANGED_REWARDS}])
        recovered = create_runtime(data_dir=data_dir, adapters=ADAPTERS)
        try:
            for adapter in ADAPTERS:
                user, exploration_id, settle_operation = pending[adapter]
                _expire(recovered, exploration_id)
                settled = await _send(
                    recovered, adapter, user, settle_operation, "结算探索"
                )
                assert settled.code == "EXPLORATION_SETTLED"
                assert settled.data["battle_outcome"] == "won"
                assert settled.data["result"] == FROZEN_REWARDS
                with sqlite3.connect(recovered.settings.database_path) as connection:
                    inventory_text, pollution = connection.execute(
                        "SELECT players.inventory_json, players.pollution FROM players "
                        "JOIN exploration_sessions ON exploration_sessions.player_id=players.id "
                        "WHERE exploration_id=?",
                        (exploration_id,),
                    ).fetchone()
                    battle_type, enemy_key = connection.execute(
                        "SELECT battle_type, enemy_key FROM battle_sessions WHERE battle_id=?",
                        (settled.data["battle_id"],),
                    ).fetchone()
                assert json.loads(inventory_text) == FROZEN_REWARDS
                assert pollution == 10
                assert (battle_type, enemy_key) == (
                    "pve.exploration", "enemy.demon_ruins_scout"
                )

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
                    "开始探索 魔界堕落遗迹探索",
                )
                assert conflict.code == "OPERATION_CONFLICT"
                assert _state(recovered) == before_replay

                next_start = f"{adapter}-demon-abyss-next"
                next_started = await _send(
                    recovered,
                    adapter,
                    user,
                    next_start,
                    "开始探索 魔界堕落遗迹探索",
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
                    recovered, adapter, user, f"{adapter}-demon-next-settle", "结算探索"
                )
                assert next_settled.data["result"] == CHANGED_REWARDS
                with sqlite3.connect(recovered.settings.database_path) as connection:
                    inventory_text = connection.execute(
                        "SELECT inventory_json FROM players "
                        "WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    ).fetchone()[0]
                assert json.loads(inventory_text) == {
                    **FROZEN_REWARDS,
                    **CHANGED_REWARDS,
                }
        finally:
            await recovered.close()

    asyncio.run(run())


@pytest.mark.parametrize("adapter", ADAPTERS)
@pytest.mark.parametrize(
    "invalid_changes",
    (
        pytest.param(
            {"outcomes": [{"weight": 1, "rewards": {"item.missing": 1}}]},
            id="missing-item",
        ),
        pytest.param({"item_weight_bonus": "yes"}, id="invalid-bonus-type"),
    ),
)
def test_demon_abyss_rejects_invalid_pool_without_cost_or_session(
    tmp_path: Path, adapter: str, invalid_changes: dict[str, object]
) -> None:
    async def run() -> None:
        data_dir = _copy_data(tmp_path)
        _update_record(
            data_dir / "奖励" / "奖励.json",
            POOL,
            **invalid_changes,
        )
        runtime = create_runtime(data_dir=data_dir, adapters=(adapter,))
        try:
            user = f"demon-invalid-{adapter}"
            await _prepare_player(runtime, adapter, user)
            before = _state(runtime)
            rejected = await _send(
                runtime, adapter, user, "invalid-demon-abyss", "开始探索 魔界堕落遗迹探索"
            )
            assert rejected.code == "PERSISTENCE_ERROR"
            assert _state(runtime) == before
        finally:
            await runtime.close()

    asyncio.run(run())


def test_demon_abyss_no_reward_still_settles_real_battle_on_both_adapters(
    tmp_path: Path,
) -> None:
    async def run() -> None:
        data_dir = _copy_data(tmp_path)
        _set_pool(data_dir, [{"weight": 1, "no_reward": True}])
        runtime = create_runtime(data_dir=data_dir, adapters=ADAPTERS)
        try:
            for adapter in ADAPTERS:
                user = f"demon-empty-{adapter}"
                await _prepare_player(runtime, adapter, user)
                started = await _send(
                    runtime, adapter, user, f"{user}-start", "开始探索 魔界堕落遗迹探索"
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
                    inventory_text, pollution, reward_status, enemy_key = connection.execute(
                        "SELECT players.inventory_json, players.pollution, battle_sessions.reward_status, "
                        "battle_sessions.enemy_key FROM players "
                        "JOIN battle_sessions ON battle_sessions.battle_id=? "
                        "WHERE players.platform=? AND players.platform_user_id=?",
                        (settled.data["battle_id"], adapter, user),
                    ).fetchone()
                assert json.loads(inventory_text) == {}
                assert pollution == 10
                assert (reward_status, enemy_key) == ("none", "enemy.demon_ruins_scout")
        finally:
            await runtime.close()

    asyncio.run(run())


def test_demon_abyss_fortune_weighting_is_pool_configured_and_item_only(tmp_path: Path) -> None:
    data_dir = _copy_data(tmp_path)
    bundle = ContentBundle.load(data_dir)
    assert reward_pool_uses_item_weight_bonus(POOL, bundle)
    assert not reward_pool_uses_item_weight_bonus(
        "reward_pool.exploration.cloud_mine", bundle
    )

    changed_seed = next(
        f"demon-fortune-{index}"
        for index in range(10_000)
        if settlement_result("explore.demon_abyss", f"demon-fortune-{index}", content=bundle)
        != settlement_result(
            "explore.demon_abyss",
            f"demon-fortune-{index}",
            drop_weight_bp=100_000,
            content=bundle,
        )
    )
    boosted = settlement_result(
        "explore.demon_abyss",
        changed_seed,
        drop_weight_bp=100_000,
        content=bundle,
    )
    assert boosted and all(key.startswith("item.") for key in boosted)

    _update_record(
        data_dir / "奖励" / "奖励.json",
        POOL,
        item_weight_bonus=False,
    )
    disabled_bundle = ContentBundle.load(data_dir)
    unchanged = settlement_result(
        "explore.demon_abyss",
        changed_seed,
        drop_weight_bp=100_000,
        content=disabled_bundle,
    )
    baseline = settlement_result(
        "explore.demon_abyss", changed_seed, content=disabled_bundle
    )
    assert unchanged == baseline
