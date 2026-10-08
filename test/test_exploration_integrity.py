from __future__ import annotations

import asyncio
import json
import shutil
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from combat_fixtures import BALANCED_QUALIFICATION

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.exploration.repository import ExplorationRepositoryMixin
from nonebot_plugin_xiuxian_3.xiuxian.exploration.rules import battle_roll_bp


ADAPTERS = ("qq.official", "onebot.v11")


def _context(adapter: str, user: str, operation_id: str) -> CommandContext:
    return CommandContext(adapter=adapter, user_id=user, operation_id=operation_id)


def _copy_content(tmp_path: Path) -> Path:
    data_dir = tmp_path / "data"
    shutil.copytree(Path(__file__).parents[1] / "data", data_dir)
    return data_dir


def _make_wood_rat_dangerous(data_dir: Path) -> None:
    path = data_dir / "战斗" / "敌人.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    enemy = next(row for row in document["records"] if row["key"] == "enemy.wood_rat")
    enemy["stats"] = {"hp": 1_000, "attack": 100, "initiative": 20, "agility": 1}
    enemy["combat_profile"] = {"random_pool_key": "battle.enemy.wood_rat", "reward": {}}
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _database_state(database_path: str) -> dict[str, list[tuple]]:
    tables = (
        "players",
        "exploration_sessions",
        "exploration_item_bindings",
        "battle_sessions",
        "battle_actions",
        "codex_entries",
        "operations",
    )
    with sqlite3.connect(database_path) as connection:
        return {
            table: connection.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
            for table in tables
        }


async def _start_gather_encounter(runtime, adapter: str, user: str) -> tuple[str, str]:
    created = await runtime.adapters.dispatch(
        adapter, _context(adapter, user, f"{user}-create"), "开始修仙"
    )
    assert created.code == "PLAYER_CREATED"
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE players SET stage='cultivator', realm_key='qi_sensing', realm_layer=2, "
            "location_key='xuantian.outskirts', stamina=30, max_hp=999, initiative=99, "
            "qualification_json=?, inventory_json='{}' WHERE platform=? AND platform_user_id=?",
            (json.dumps(BALANCED_QUALIFICATION), adapter, user),
        )
    start_operation = next(
        f"{user}-start-{index}"
        for index in range(1_000)
        if battle_roll_bp(f"{user}-start-{index}:battle") < 1_000
    )
    started = await runtime.adapters.dispatch(
        adapter,
        _context(adapter, user, start_operation),
        "开始探索 近郊采集",
    )
    assert started.code == "EXPLORATION_STARTED"
    exploration_id = str(started.data["exploration_id"])
    expired_at = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE exploration_sessions SET ends_at=? WHERE exploration_id=?",
            (expired_at, exploration_id),
        )
    return exploration_id, start_operation


def _duplicate_frozen_reward_key(result_json: str, snapshot_json: str) -> str:
    snapshot = json.loads(snapshot_json)
    frozen = snapshot["frozen_result"]
    key = next(iter(frozen))
    quantity = frozen[key]
    marker = '"frozen_result":'
    marker_index = result_json.index(marker) + len(marker)
    object_start = result_json.index("{", marker_index)
    object_end = result_json.index("}", object_start) + 1
    frozen_json = result_json[object_start:object_end]
    pair = json.dumps({key: quantity}, ensure_ascii=False, sort_keys=True)[1:-1]
    assert pair in frozen_json
    altered = frozen_json.replace(
        pair,
        f"{pair}, {json.dumps(key, ensure_ascii=False)}: {quantity + 999}",
        1,
    )
    assert altered != frozen_json
    return result_json[:object_start] + altered + result_json[object_end:]


@pytest.mark.parametrize("adapter", ADAPTERS)
@pytest.mark.parametrize("tamper", ("duplicate_reward_key", "snapshot_mismatch"))
def test_exploration_combat_reward_rejects_corrupt_pending_result_and_recovers(
    tmp_path, monkeypatch, adapter: str, tamper: str
) -> None:
    async def run() -> None:
        data_dir = _copy_content(tmp_path)
        runtime = create_runtime(data_dir=data_dir, adapters=(adapter,))
        original_settle = ExplorationRepositoryMixin._settle_exploration_combat_once
        injection: dict[str, object] = {"done": False}
        user = f"exploration-integrity-{adapter}-{tamper}"
        settle_operation = f"{user}-settle"
        try:
            exploration_id, _ = await _start_gather_encounter(runtime, adapter, user)

            def inject_before_combat_settlement(
                repository,
                platform,
                platform_user_id,
                requested_exploration_id,
                battle_id,
                operation_id,
            ):
                if not injection["done"]:
                    with repository._connect() as connection:
                        row = connection.execute(
                            "SELECT result_json, snapshot_json FROM exploration_sessions "
                            "WHERE exploration_id=?",
                            (requested_exploration_id,),
                        ).fetchone()
                        battle = connection.execute(
                            "SELECT status, result_json FROM battle_sessions WHERE battle_id=?",
                            (battle_id,),
                        ).fetchone()
                        assert row is not None
                        assert battle is not None and battle["status"] == "settled"
                        assert json.loads(battle["result_json"])["outcome"] == "won"
                        injection["original_result_json"] = str(row["result_json"])
                        injection["snapshot_json"] = str(row["snapshot_json"])
                        if tamper == "duplicate_reward_key":
                            changed = _duplicate_frozen_reward_key(
                                str(row["result_json"]), str(row["snapshot_json"])
                            )
                        else:
                            payload = json.loads(row["result_json"])
                            snapshot = json.loads(row["snapshot_json"])
                            reward_key = next(iter(snapshot["frozen_result"]))
                            payload["frozen_result"][reward_key] += 999
                            changed = json.dumps(payload, ensure_ascii=False, sort_keys=True)
                        connection.execute(
                            "UPDATE exploration_sessions SET result_json=? WHERE exploration_id=?",
                            (changed, requested_exploration_id),
                        )
                    injection["before_settlement"] = _database_state(
                        repository.settings.database_path
                    )
                    injection["done"] = True
                return original_settle(
                    repository,
                    platform,
                    platform_user_id,
                    requested_exploration_id,
                    battle_id,
                    operation_id,
                )

            monkeypatch.setattr(
                ExplorationRepositoryMixin,
                "_settle_exploration_combat_once",
                inject_before_combat_settlement,
            )
            rejected = await runtime.adapters.dispatch(
                adapter, _context(adapter, user, settle_operation), "结算探索"
            )
            assert rejected.code == "PERSISTENCE_ERROR"
            assert _database_state(runtime.settings.database_path) == injection["before_settlement"]
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE exploration_sessions SET result_json=? WHERE exploration_id=?",
                    (injection["original_result_json"], exploration_id),
                )
            recovered = await runtime.adapters.dispatch(
                adapter, _context(adapter, user, settle_operation), "结算探索"
            )
            assert recovered.code == "EXPLORATION_SETTLED"
            assert recovered.data["battle_outcome"] == "won"
            expected_reward = json.loads(str(injection["snapshot_json"]))["frozen_result"]
            assert recovered.data["result"] == expected_reward
            settled_state = _database_state(runtime.settings.database_path)

            await runtime.close()
            runtime = create_runtime(data_dir=data_dir, adapters=(adapter,))
            replay = await runtime.adapters.dispatch(
                adapter, _context(adapter, user, settle_operation), "结算探索"
            )
            assert replay.code == "EXPLORATION_SETTLED"
            assert replay.data["idempotent_replay"] is True
            assert replay.data["result"] == expected_reward
            assert _database_state(runtime.settings.database_path) == settled_state
        finally:
            await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("adapter", ADAPTERS)
@pytest.mark.parametrize("fault", ("reward_write", "operation_insert"))
def test_exploration_combat_settlement_fault_rolls_back_and_retries(
    tmp_path, monkeypatch, adapter: str, fault: str
) -> None:
    async def run() -> None:
        data_dir = _copy_content(tmp_path)
        runtime = create_runtime(data_dir=data_dir, adapters=(adapter,))
        original_settle = ExplorationRepositoryMixin._settle_exploration_combat_once
        injection: dict[str, object] = {"done": False}
        user = f"exploration-fault-{adapter}-{fault}"
        settle_operation = f"{user}-settle"
        trigger = f"injected_{fault}"
        try:
            await _start_gather_encounter(runtime, adapter, user)

            def inject_fault_once(
                repository,
                platform,
                platform_user_id,
                exploration_id,
                battle_id,
                operation_id,
            ):
                if not injection["done"]:
                    with repository._connect() as connection:
                        battle = connection.execute(
                            "SELECT status, result_json FROM battle_sessions WHERE battle_id=?",
                            (battle_id,),
                        ).fetchone()
                        assert battle is not None and battle["status"] == "settled"
                        assert json.loads(battle["result_json"])["outcome"] == "won"
                        if fault == "reward_write":
                            connection.execute(
                                f"CREATE TRIGGER {trigger} BEFORE UPDATE ON players "
                                f"WHEN NEW.platform_user_id='{user}' "
                                "BEGIN SELECT RAISE(ABORT, 'injected reward write failure'); END"
                            )
                        else:
                            connection.execute(
                                f"CREATE TRIGGER {trigger} BEFORE INSERT ON operations "
                                f"WHEN NEW.operation_id='{operation_id}' "
                                "BEGIN SELECT RAISE(ABORT, 'injected operation insert failure'); END"
                            )
                    injection["before_settlement"] = _database_state(
                        repository.settings.database_path
                    )
                    injection["done"] = True
                try:
                    return original_settle(
                        repository,
                        platform,
                        platform_user_id,
                        exploration_id,
                        battle_id,
                        operation_id,
                    )
                except sqlite3.IntegrityError:
                    injection["fault_observed"] = True
                    raise

            monkeypatch.setattr(
                ExplorationRepositoryMixin,
                "_settle_exploration_combat_once",
                inject_fault_once,
            )
            failed = await runtime.adapters.dispatch(
                adapter, _context(adapter, user, settle_operation), "结算探索"
            )
            assert failed.code == "PERSISTENCE_ERROR"
            assert injection.get("fault_observed") is True
            assert _database_state(runtime.settings.database_path) == injection["before_settlement"]
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(f"DROP TRIGGER {trigger}")
                snapshot_text = connection.execute(
                    "SELECT snapshot_json FROM exploration_sessions WHERE player_id="
                    "(SELECT id FROM players WHERE platform=? AND platform_user_id=?)",
                    (adapter, user),
                ).fetchone()[0]
            retried = await runtime.adapters.dispatch(
                adapter, _context(adapter, user, settle_operation), "结算探索"
            )
            assert retried.code == "EXPLORATION_SETTLED"
            assert retried.data["battle_outcome"] == "won"
            assert retried.data["result"] == json.loads(snapshot_text)["frozen_result"]
            state_after_retry = _database_state(runtime.settings.database_path)
            replay = await runtime.adapters.dispatch(
                adapter, _context(adapter, user, settle_operation), "结算探索"
            )
            assert replay.code == "EXPLORATION_SETTLED"
            assert replay.data["idempotent_replay"] is True
            assert _database_state(runtime.settings.database_path) == state_after_retry
        finally:
            await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("adapter", ADAPTERS)
@pytest.mark.parametrize("force_win, expected_outcome", ((True, "won"), (False, "lost")))
def test_exploration_formal_encounter_keeps_victory_and_defeat_rewards(
    tmp_path, adapter: str, force_win: bool, expected_outcome: str
) -> None:
    async def run() -> None:
        data_dir = _copy_content(tmp_path)
        if not force_win:
            _make_wood_rat_dangerous(data_dir)
        runtime = create_runtime(data_dir=data_dir, adapters=(adapter,))
        user = f"exploration-outcome-{adapter}-{expected_outcome}"
        try:
            exploration_id, _ = await _start_gather_encounter(runtime, adapter, user)
            result = await runtime.adapters.dispatch(
                adapter,
                _context(adapter, user, f"{user}-settle"),
                "结算探索",
            )
            assert result.code == "EXPLORATION_SETTLED"
            assert result.data["battle_outcome"] == expected_outcome
            with sqlite3.connect(runtime.settings.database_path) as connection:
                snapshot_text, inventory_text = connection.execute(
                    "SELECT e.snapshot_json, p.inventory_json FROM exploration_sessions e "
                    "JOIN players p ON p.id=e.player_id WHERE e.exploration_id=?",
                    (exploration_id,),
                ).fetchone()
            expected = json.loads(snapshot_text)["frozen_result"] if force_win else {}
            assert result.data["result"] == expected
            assert json.loads(inventory_text) == expected
        finally:
            await runtime.close()

    asyncio.run(run())
