from __future__ import annotations

import asyncio
import json
import shutil
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from combat_fixtures import BALANCED_QUALIFICATION

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.events.contribution_projection import record_spirit_spring_contribution
from nonebot_plugin_xiuxian_3.xiuxian.specials.codex_projection import record_material_discoveries


POOL = "reward_pool.exploration.spring_gather"
REWARDS = {"item.herb.spirit_leaf": 7, "item.mat.array_sand": 3, "item.spirit_water": 2}


class Clock:
    def __init__(self) -> None:
        self.value = datetime(2026, 9, 23, 20, 5, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.value


@pytest.fixture(params=("qq.official", "onebot.v11"))
def adapter(request) -> str:
    return request.param


@pytest.fixture
def content_dir(tmp_path: Path) -> Path:
    target = tmp_path / "data"
    shutil.copytree(Path(__file__).parents[1] / "data", target)
    (target / "xiuxian3.sqlite3").unlink(missing_ok=True)
    _set_pool(target, REWARDS)
    return target


def _update_record(path: Path, key: str, **changes) -> None:
    document = json.loads(path.read_text(encoding="utf-8"))
    next(record for record in document["records"] if record["key"] == key).update(changes)
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _set_pool(content_dir: Path, rewards: dict[str, int]) -> None:
    _update_record(
        content_dir / "奖励" / "奖励.json", POOL,
        outcomes=[{"weight": 1, "rewards": rewards}],
    )


async def _send(runtime, adapter: str, operation: str, command: str):
    context = CommandContext(adapter=adapter, user_id="spring-content", operation_id=operation)
    return await runtime.adapters.dispatch(adapter, context, command)


async def _prepare(runtime, adapter: str) -> None:
    assert (await _send(runtime, adapter, "create", "开始修仙")).ok
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE players SET stage='cultivator', realm_key='qi_sensing', realm_layer=2, "
            "location_key='xuantian.spirit_field', stamina=30, qualification_json=?, "
            "inventory_json='{}', intro_json=?",
            (
                json.dumps(BALANCED_QUALIFICATION),
                json.dumps({"flags": ["guide.gather_blood_grass"]}),
            ),
        )


def _state(runtime) -> dict[str, list[tuple]]:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        return {
            table: connection.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
            for table in (
                "players", "exploration_sessions", "operations", "codex_entries", "battle_sessions",
                "world_event_rounds", "world_event_contributions", "world_event_contribution_events",
            )
        }


def _assert_rewards_and_contribution(runtime, rewards: dict[str, int], sources: dict[str, int]) -> None:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        inventory, = connection.execute("SELECT inventory_json FROM players").fetchone()
        assert json.loads(inventory) == rewards
        entries = connection.execute(
            "SELECT source_operation_id, quantity, applied_quantity FROM world_event_contribution_events"
        ).fetchall()
        assert sorted(entries) == sorted((source, amount, amount) for source, amount in sources.items())
        amounts = connection.execute("SELECT contribution FROM world_event_contributions").fetchall()
        assert amounts == ([(sum(sources.values()),)] if sources else [])
        assert connection.execute("SELECT COUNT(*) FROM battle_sessions").fetchone()[0] == 0


@pytest.mark.parametrize("cross_window", (False, True))
def test_spring_content_freezes_rewards_and_contribution_across_restart(
    content_dir: Path, adapter: str, cross_window: bool,
) -> None:
    async def run() -> None:
        clock = Clock()
        if cross_window:
            clock.value += timedelta(minutes=24)
        _update_record(content_dir / "道具" / "材料.json", "item.spirit_water", name="澄心泉露")
        runtime = create_runtime(data_dir=content_dir, adapters=(adapter,), clock=clock)
        try:
            await _prepare(runtime, adapter)
            started = await _send(runtime, adapter, "start", "开始探索 灵泉采集")
            assert started.code == "EXPLORATION_STARTED"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                snapshot = json.loads(connection.execute(
                    "SELECT snapshot_json FROM exploration_sessions"
                ).fetchone()[0])
                operation = json.loads(connection.execute(
                    "SELECT result_json FROM operations WHERE operation_id='start'"
                ).fetchone()[0])
            assert snapshot["reward_pool_key"] == POOL
            assert snapshot["random_seed"] == "start"
            assert snapshot["battle_chance_bp"] == 0
            assert snapshot["frozen_result"] == operation["frozen_result"] == REWARDS
        finally:
            await runtime.close()

        changed = {"item.herb.spirit_leaf": 11, "item.spirit_water": 5}
        _set_pool(content_dir, changed)
        clock.value += timedelta(minutes=2)
        recovered = create_runtime(data_dir=content_dir, adapters=(adapter,), clock=clock)
        try:
            settled = await _send(recovered, adapter, "settle", "结算探索")
            assert settled.code == "EXPLORATION_SETTLED"
            assert settled.data["result"] == REWARDS
            assert "澄心泉露" in settled.message
            assert not any(word in settled.message for word in ("会话", "快照", "冻结", "版本", "请求编号"))
            _assert_rewards_and_contribution(recovered, REWARDS, {"start": 7})
            with sqlite3.connect(recovered.settings.database_path) as connection:
                assert connection.execute(
                    "SELECT round_id FROM world_event_contribution_events"
                ).fetchall() == [("20260923",)]
            before = _state(recovered)
            replay = await _send(recovered, adapter, "settle", "结算探索")
            assert replay.data["idempotent_replay"] is True
            assert replay.data["result"] == REWARDS
            conflict = await _send(recovered, adapter, "settle", "开始探索 灵泉采集")
            assert conflict.code == "OPERATION_CONFLICT"
            assert _state(recovered) == before

            assert (await _send(recovered, adapter, "next-start", "开始探索 灵泉采集")).ok
            clock.value += timedelta(minutes=2)
            next_settled = await _send(recovered, adapter, "next-settle", "结算探索")
            assert next_settled.data["result"] == changed
            _assert_rewards_and_contribution(
                recovered,
                {key: REWARDS.get(key, 0) + changed.get(key, 0) for key in REWARDS.keys() | changed.keys()},
                {"start": 7} if cross_window else {"start": 7, "next-start": 11},
            )
            with sqlite3.connect(recovered.settings.database_path) as connection:
                assert connection.execute("SELECT stamina FROM players").fetchone()[0] == 18
        finally:
            await recovered.close()

    asyncio.run(run())


@pytest.mark.parametrize("projection", ("contribution", "codex"))
def test_spring_projection_failure_rolls_back_then_concurrent_retry_is_unique(
    content_dir: Path, adapter: str, projection: str,
) -> None:
    async def run() -> None:
        clock = Clock()
        runtime = create_runtime(data_dir=content_dir, adapters=(adapter,), clock=clock)
        try:
            await _prepare(runtime, adapter)
            assert (await _send(runtime, adapter, "start", "开始探索 灵泉采集")).ok
            clock.value += timedelta(minutes=2)
            before = _state(runtime)
            original = (
                record_spirit_spring_contribution
                if projection == "contribution" else record_material_discoveries
            )

            def fail_after_projection(*args, **kwargs):
                original(*args, **kwargs)
                raise RuntimeError("injected projection failure")

            target = (
                "nonebot_plugin_xiuxian_3.xiuxian.exploration.repository."
                "record_spirit_spring_contribution"
                if projection == "contribution" else
                "nonebot_plugin_xiuxian_3.xiuxian.exploration.repository.record_material_discoveries"
            )
            with patch(target, autospec=True, side_effect=fail_after_projection):
                failed = await _send(runtime, adapter, "settle", "结算探索")
            assert failed.code == "PERSISTENCE_ERROR"
            assert _state(runtime) == before

            results = await asyncio.gather(*(
                _send(runtime, adapter, "settle", "结算探索") for _ in range(2)
            ))
            assert all(result.code == "EXPLORATION_SETTLED" for result in results)
            assert all(result.data["result"] == REWARDS for result in results)
            assert sorted(result.data["idempotent_replay"] for result in results) == [False, True]
            _assert_rewards_and_contribution(runtime, REWARDS, {"start": 7})
            after = _state(runtime)
            assert (await _send(runtime, adapter, "settle", "结算探索")).data["idempotent_replay"] is True
            assert _state(runtime) == after
        finally:
            await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("rewards", ({"item.missing": 1}, {"item.herb.spirit_leaf": True}, {"stamina": 1}))
def test_spring_invalid_content_does_not_charge_or_create_session(
    content_dir: Path, adapter: str, rewards: dict[str, int],
) -> None:
    async def run() -> None:
        _set_pool(content_dir, rewards)
        runtime = create_runtime(data_dir=content_dir, adapters=(adapter,), clock=Clock())
        try:
            await _prepare(runtime, adapter)
            before = _state(runtime)
            rejected = await _send(runtime, adapter, "start", "开始探索 灵泉采集")
            assert rejected.code == "PERSISTENCE_ERROR"
            assert _state(runtime) == before
        finally:
            await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("expired", (False, True))
def test_spring_without_leaf_or_after_expiry_never_adds_contribution(
    content_dir: Path, adapter: str, expired: bool,
) -> None:
    async def run() -> None:
        clock = Clock()
        rewards = REWARDS if expired else {"item.spirit_water": 4, "item.mat.array_sand": 2}
        _set_pool(content_dir, rewards)
        runtime = create_runtime(data_dir=content_dir, adapters=(adapter,), clock=clock)
        try:
            await _prepare(runtime, adapter)
            assert (await _send(runtime, adapter, "start", "开始探索 灵泉采集")).ok
            before = _state(runtime)
            clock.value += timedelta(hours=25) if expired else timedelta(minutes=2)
            settled = await _send(runtime, adapter, "settle", "结算探索")
            assert settled.code == ("EXPLORATION_EXPIRED" if expired else "EXPLORATION_SETTLED")
            if not expired:
                assert settled.data["result"] == rewards
            _assert_rewards_and_contribution(runtime, {} if expired else rewards, {})
            state = _state(runtime)
            assert state["world_event_rounds"] == []
            if expired:
                assert state["codex_entries"] == before["codex_entries"]
            replay = await _send(runtime, adapter, "settle", "结算探索")
            assert replay.data["idempotent_replay"] is True
            assert _state(runtime) == state
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute("SELECT stamina FROM players").fetchone()[0] == 24
                result = json.loads(connection.execute(
                    "SELECT result_json FROM exploration_sessions"
                ).fetchone()[0])
                assert result["result"] == ({} if expired else rewards)
        finally:
            await runtime.close()

    asyncio.run(run())
