from __future__ import annotations

import asyncio
import json
import shutil
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pytest
from combat_fixtures import BALANCED_QUALIFICATION

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.exploration.rules import battle_roll_bp


def _context(adapter: str, user: str, operation_id: str) -> CommandContext:
    return CommandContext(adapter=adapter, user_id=user, operation_id=operation_id)


def _replace_gather_pool(path: Path, rewards: dict[str, int]) -> None:
    document = json.loads(path.read_text(encoding="utf-8"))
    pool = next(
        row for row in document["records"] if row["key"] == "reward_pool.exploration.gather_outskirts"
    )
    pool["outcomes"] = [{"weight": 1, "rewards": rewards}]
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _replace_wood_rat_stats(path: Path, *, hp: int, attack: int, initiative: int) -> None:
    document = json.loads(path.read_text(encoding="utf-8"))
    enemy = next(row for row in document["records"] if row["key"] == "enemy.wood_rat")
    enemy["stats"] = {"hp": hp, "attack": attack, "initiative": initiative}
    enemy["stats"]["agility"] = 1
    enemy["combat_profile"] = {"random_pool_key": "battle.enemy.wood_rat", "reward": {}}
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _replace_item_name(path: Path, key: str, name: str) -> None:
    document = json.loads(path.read_text(encoding="utf-8"))
    item = next(row for row in document["records"] if row["key"] == key)
    item["name"] = name
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _assert_cultivation_message(message: str) -> None:
    assert not any(word in message for word in ("会话", "快照", "冻结", "版本", "请求编号"))


def _prepare_mortal(runtime, adapter: str, user: str) -> None:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE players SET stage='mortal', realm_key='mortal', realm_layer=0, "
            "location_key='xuantian.outskirts', stamina=30, inventory_json=?, qualification_json=? "
            "WHERE platform=? AND platform_user_id=?",
            (
                json.dumps({}, ensure_ascii=False),
                json.dumps(BALANCED_QUALIFICATION),
                adapter,
                user,
            ),
        )


def _expire_exploration(runtime, exploration_id: str) -> None:
    old = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE exploration_sessions SET ends_at=? WHERE exploration_id=?",
            (old, exploration_id),
        )


def _stored_state(runtime) -> dict[str, list[tuple]]:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        return {
            table: connection.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
            for table in ("players", "exploration_sessions", "operations", "codex_entries")
        }


@pytest.mark.parametrize("adapter", ("qq.official", "onebot.v11"))
def test_gather_invalid_content_does_not_charge_or_create_session(adapter: str) -> None:
    async def run() -> None:
        with TemporaryDirectory() as temp:
            data_dir = Path(temp) / "data"
            shutil.copytree(Path(__file__).parents[1] / "data", data_dir)
            _replace_gather_pool(data_dir / "奖励" / "奖励.json", {"item.missing": 1})
            runtime = create_runtime(data_dir=data_dir, adapters=(adapter,))
            try:
                user = "gather-invalid"
                assert (await runtime.adapters.dispatch(
                    adapter, _context(adapter, user, "create"), "开始修仙"
                )).ok
                _prepare_mortal(runtime, adapter, user)
                before = _stored_state(runtime)
                rejected = await runtime.adapters.dispatch(
                    adapter, _context(adapter, user, "invalid-start"), "开始探索 近郊采集"
                )
                assert rejected.code == "PERSISTENCE_ERROR"
                assert _stored_state(runtime) == before
            finally:
                await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("adapter", ("qq.official", "onebot.v11"))
def test_gather_failure_rolls_back_assets_session_and_operation_then_retries(adapter: str) -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, adapters=(adapter,))
            try:
                user = "gather-atomic"
                assert (await runtime.adapters.dispatch(
                    adapter, _context(adapter, user, "create"), "开始修仙"
                )).ok
                _prepare_mortal(runtime, adapter, user)
                operation = next(
                    f"atomic-{index}" for index in range(1000)
                    if battle_roll_bp(f"atomic-{index}:battle") >= 1000
                )
                started = await runtime.adapters.dispatch(
                    adapter, _context(adapter, user, operation), "开始探索 近郊采集"
                )
                assert started.ok
                _expire_exploration(runtime, started.data["exploration_id"])
                before = _stored_state(runtime)
                with patch(
                    "nonebot_plugin_xiuxian_3.xiuxian.exploration.repository.record_material_discoveries",
                    side_effect=RuntimeError("injected projection failure"),
                ):
                    rejected = await runtime.adapters.dispatch(
                        adapter, _context(adapter, user, "settle"), "结算探索"
                    )
                assert rejected.code == "PERSISTENCE_ERROR"
                assert _stored_state(runtime) == before
                settled, replay = await asyncio.gather(*(
                    runtime.adapters.dispatch(adapter, _context(adapter, user, "settle"), "结算探索")
                    for _ in range(2)
                ))
                assert settled.ok and replay.ok
                assert settled.data["result"] == replay.data["result"]
                assert sorted((settled.data["idempotent_replay"], replay.data["idempotent_replay"])) == [False, True]
                after = _stored_state(runtime)
                replay = await runtime.adapters.dispatch(
                    adapter, _context(adapter, user, "settle"), "结算探索"
                )
                assert replay.data["idempotent_replay"] is True
                assert _stored_state(runtime) == after
            finally:
                await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("frozen_result", (None, {"item.herb.blood_grass": True}, {"item.herb.blood_grass": 1.5}))
def test_gather_invalid_snapshot_is_not_redrawn_or_coerced(frozen_result) -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            try:
                adapter, user = "qq.official", "gather-snapshot"
                assert (await runtime.adapters.dispatch(
                    adapter, _context(adapter, user, "create"), "开始修仙"
                )).ok
                _prepare_mortal(runtime, adapter, user)
                operation = next(
                    f"snapshot-{index}" for index in range(1000)
                    if battle_roll_bp(f"snapshot-{index}:battle") >= 1000
                )
                started = await runtime.adapters.dispatch(
                    adapter, _context(adapter, user, operation), "开始探索 近郊采集"
                )
                assert started.ok
                exploration_id = started.data["exploration_id"]
                _expire_exploration(runtime, exploration_id)
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    snapshot = json.loads(connection.execute(
                        "SELECT snapshot_json FROM exploration_sessions WHERE exploration_id=?", (exploration_id,)
                    ).fetchone()[0])
                    snapshot["frozen_result"] = frozen_result
                    connection.execute(
                        "UPDATE exploration_sessions SET snapshot_json=? WHERE exploration_id=?",
                        (json.dumps(snapshot), exploration_id),
                    )
                before = _stored_state(runtime)
                failed = await runtime.adapters.dispatch(
                    adapter, _context(adapter, user, "settle"), "结算探索"
                )
                assert failed.code == "PERSISTENCE_ERROR"
                assert _stored_state(runtime) == before
            finally:
                await runtime.close()

    asyncio.run(run())


def test_gather_outskirts_freezes_content_rewards_across_restart_on_both_adapters() -> None:
    async def run() -> None:
        with TemporaryDirectory() as temp:
            data_dir = Path(temp) / "data"
            shutil.copytree(Path(__file__).parents[1] / "data", data_dir)
            reward_path = data_dir / "奖励" / "奖励.json"
            frozen_rewards = {
                "item.herb.blood_grass": 3,
                "item.ore.ironstone": 2,
                "item.mat.wood": 1,
            }
            changed_rewards = {
                "item.herb.blood_grass": 9,
                "item.ore.ironstone": 8,
                "item.mat.wood": 7,
            }
            _replace_gather_pool(reward_path, frozen_rewards)
            _replace_item_name(data_dir / "道具" / "材料.json", "item.mat.wood", "青纹木")

            adapters = ("qq.official", "onebot.v11")
            runtime = create_runtime(data_dir=data_dir, adapters=adapters)
            pending: dict[str, tuple[str, str, str]] = {}
            try:
                for adapter in adapters:
                    user = f"gather-content-{adapter}"
                    created = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, user, f"{adapter}-create"),
                        "开始修仙",
                    )
                    assert created.code == "PLAYER_CREATED"
                    _prepare_mortal(runtime, adapter, user)
                    start_operation = next(
                        f"{adapter}-gather-{index}"
                        for index in range(1_000)
                        if battle_roll_bp(f"{adapter}-gather-{index}:battle") >= 1_000
                    )
                    started = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, user, start_operation),
                        "开始探索 近郊采集",
                    )
                    assert started.code == "EXPLORATION_STARTED"
                    _assert_cultivation_message(started.message)
                    exploration_id = str(started.data["exploration_id"])
                    _expire_exploration(runtime, exploration_id)
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
                    operation = json.loads(operation_text)
                    assert snapshot["reward_pool_key"] == "reward_pool.exploration.gather_outskirts"
                    assert snapshot["random_seed"] == start_operation
                    assert snapshot["frozen_result"] == frozen_rewards
                    assert operation["frozen_result"] == frozen_rewards
                    pending[adapter] = (user, exploration_id, f"{adapter}-gather-settle")
            finally:
                await runtime.close()

            # The running process has gone away before content changes; recovery
            # must use the reward frozen in each session rather than this new pool.
            _replace_gather_pool(reward_path, changed_rewards)
            recovered = create_runtime(data_dir=data_dir, adapters=adapters)
            try:
                for adapter in adapters:
                    user, exploration_id, settle_operation = pending[adapter]
                    settled = await recovered.adapters.dispatch(
                        adapter,
                        _context(adapter, user, settle_operation),
                        "结算探索",
                    )
                    assert settled.code == "EXPLORATION_SETTLED"
                    assert settled.data["result"] == frozen_rewards
                    assert "青纹木" in settled.message
                    _assert_cultivation_message(settled.message)
                    with sqlite3.connect(recovered.settings.database_path) as connection:
                        inventory_text = connection.execute(
                            "SELECT inventory_json FROM players WHERE platform=? AND platform_user_id=?",
                            (adapter, user),
                        ).fetchone()[0]
                        status = connection.execute(
                            "SELECT status FROM exploration_sessions WHERE exploration_id=?",
                            (exploration_id,),
                        ).fetchone()[0]
                    assert json.loads(inventory_text) == frozen_rewards
                    assert status == "settled"

                    replay = await recovered.adapters.dispatch(
                        adapter,
                        _context(adapter, user, settle_operation),
                        "结算探索",
                    )
                    assert replay.code == "EXPLORATION_SETTLED"
                    assert replay.data["idempotent_replay"] is True
                    assert replay.data["result"] == frozen_rewards

                    conflict = await recovered.adapters.dispatch(
                        adapter,
                        _context(adapter, user, settle_operation),
                        "开始探索 近郊采集",
                    )
                    assert conflict.code == "OPERATION_CONFLICT"
                    with sqlite3.connect(recovered.settings.database_path) as connection:
                        inventory_text = connection.execute(
                            "SELECT inventory_json FROM players WHERE platform=? AND platform_user_id=?",
                            (adapter, user),
                        ).fetchone()[0]
                    assert json.loads(inventory_text) == frozen_rewards

                    next_operation = next(
                        f"{adapter}-gather-changed-{index}"
                        for index in range(1_000)
                        if battle_roll_bp(f"{adapter}-gather-changed-{index}:battle") >= 1_000
                    )
                    next_started = await recovered.adapters.dispatch(
                        adapter,
                        _context(adapter, user, next_operation),
                        "开始探索 近郊采集",
                    )
                    assert next_started.code == "EXPLORATION_STARTED"
                    _expire_exploration(recovered, str(next_started.data["exploration_id"]))
                    next_settled = await recovered.adapters.dispatch(
                        adapter,
                        _context(adapter, user, f"{adapter}-changed-settle"),
                        "结算探索",
                    )
                    assert next_settled.code == "EXPLORATION_SETTLED"
                    assert next_settled.data["result"] == changed_rewards
                    assert "青纹木" in next_settled.message
                    _assert_cultivation_message(next_settled.message)
                    with sqlite3.connect(recovered.settings.database_path) as connection:
                        inventory_text = connection.execute(
                            "SELECT inventory_json FROM players WHERE platform=? AND platform_user_id=?",
                            (adapter, user),
                        ).fetchone()[0]
                    assert json.loads(inventory_text) == {
                        key: frozen_rewards[key] + changed_rewards[key] for key in frozen_rewards
                    }
            finally:
                await recovered.close()

    asyncio.run(run())


def test_gather_outskirts_encounter_rewards_follow_battle_result_on_both_adapters() -> None:
    async def run() -> None:
        for outcome in ("won", "lost"):
            with TemporaryDirectory() as temp:
                data_dir = Path(temp) / "data"
                shutil.copytree(Path(__file__).parents[1] / "data", data_dir)
                frozen_rewards = {"item.herb.blood_grass": 3, "item.mat.wood": 1}
                _replace_gather_pool(data_dir / "奖励" / "奖励.json", frozen_rewards)
                if outcome == "lost":
                    _replace_wood_rat_stats(
                        data_dir / "战斗" / "敌人.json", hp=1_000, attack=100, initiative=20
                    )
                runtime = create_runtime(data_dir=data_dir, adapters=("qq.official", "onebot.v11"))
                try:
                    for adapter in ("qq.official", "onebot.v11"):
                        user = f"gather-battle-{adapter}-{outcome}"
                        assert (
                            await runtime.adapters.dispatch(
                                adapter, _context(adapter, user, f"{user}-create"), "开始修仙"
                            )
                        ).code == "PLAYER_CREATED"
                        _prepare_mortal(runtime, adapter, user)
                        with sqlite3.connect(runtime.settings.database_path) as connection:
                            connection.execute(
                                "UPDATE players SET stage='cultivator', realm_key='qi_sensing', realm_layer=2, "
                                "max_hp=?, initiative=? "
                                "WHERE platform=? AND platform_user_id=?",
                                (
                                    999,
                                    99,
                                    adapter,
                                    user,
                                ),
                            )
                        start_operation = next(
                            f"{user}-start-{index}"
                            for index in range(1_000)
                            if battle_roll_bp(f"{user}-start-{index}:battle") < 1_000
                        )
                        started = await runtime.adapters.dispatch(
                            adapter, _context(adapter, user, start_operation), "开始探索 近郊采集"
                        )
                        assert started.code == "EXPLORATION_STARTED"
                        exploration_id = str(started.data["exploration_id"])
                        _expire_exploration(runtime, exploration_id)
                        with sqlite3.connect(runtime.settings.database_path) as connection:
                            codex_before = connection.execute(
                                "SELECT * FROM codex_entries WHERE player_id="
                                "(SELECT id FROM players WHERE platform=? AND platform_user_id=?) ORDER BY entry_key",
                                (adapter, user),
                            ).fetchall()
                        settled = await runtime.adapters.dispatch(
                            adapter, _context(adapter, user, f"{user}-settle"), "结算探索"
                        )
                        assert settled.code == "EXPLORATION_SETTLED"
                        assert settled.data["battle_outcome"] == outcome, (adapter, outcome, settled.data)
                        guidance_claim = await runtime.adapters.dispatch(
                            adapter,
                            _context(adapter, user, f"{user}-gather-guidance-claim"),
                            "领取引路嘉奖 第一次采集",
                        )
                        if outcome == "won":
                            assert guidance_claim.code == "GUIDANCE_REWARD_CLAIMED"
                        else:
                            assert guidance_claim.code == "QUEST_REQUIREMENT_MISSING"
                        rewards = frozen_rewards if outcome == "won" else {}
                        assert settled.data["result"] == rewards
                        expected_inventory = dict(rewards)
                        if outcome == "won":
                            expected_inventory["item.herb.blood_grass"] += 2
                            expected_inventory["item.manual.sunrise_breath"] = 1
                        with sqlite3.connect(runtime.settings.database_path) as connection:
                            codex_after_settle = connection.execute(
                                "SELECT * FROM codex_entries WHERE player_id="
                                "(SELECT id FROM players WHERE platform=? AND platform_user_id=?) ORDER BY entry_key",
                                (adapter, user),
                            ).fetchall()
                        replay = await runtime.adapters.dispatch(
                            adapter, _context(adapter, user, f"{user}-settle"), "结算探索"
                        )
                        assert replay.data["idempotent_replay"] is True
                        with sqlite3.connect(runtime.settings.database_path) as connection:
                            inventory_text, cultivation, stones, stamina = connection.execute(
                                "SELECT inventory_json, cultivation, spirit_stones, stamina FROM players "
                                "WHERE platform=? AND platform_user_id=?",
                                (adapter, user),
                            ).fetchone()
                            status, reward_status, battle_type, state_text = connection.execute(
                                "SELECT status, reward_status, battle_type, state_json "
                                "FROM battle_sessions WHERE battle_id=?",
                                (settled.data["battle_id"],),
                            ).fetchone()
                            result_text = connection.execute(
                                "SELECT result_json FROM exploration_sessions WHERE exploration_id=?",
                                (exploration_id,),
                            ).fetchone()[0]
                            codex_after_replay = connection.execute(
                                "SELECT * FROM codex_entries WHERE player_id="
                                "(SELECT id FROM players WHERE platform=? AND platform_user_id=?) ORDER BY entry_key",
                                (adapter, user),
                            ).fetchall()
                        assert json.loads(inventory_text) == expected_inventory
                        assert cultivation == (30 if outcome == "won" else 0)
                        assert stones == 0
                        assert stamina == 27
                        assert status == "settled"
                        assert reward_status == "none"
                        assert battle_type == "pve.exploration"
                        state = json.loads(state_text)
                        assert state["round_no"] >= 1
                        assert state["enemy_hp" if outcome == "won" else "player_hp"] == 0
                        assert json.loads(result_text)["frozen_result"] == frozen_rewards
                        assert codex_after_replay == codex_after_settle
                        if outcome == "won":
                            assert len(codex_after_settle) > len(codex_before)
                        else:
                            assert codex_after_settle == codex_before
                finally:
                    await runtime.close()

    asyncio.run(run())
