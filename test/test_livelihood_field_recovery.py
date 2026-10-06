from __future__ import annotations

import asyncio
import json
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from test_adapter_simulation import _onebot_group_event, _qq_group_event

from nonebot_plugin_xiuxian_3.adapters.onebot import normalize_event
from nonebot_plugin_xiuxian_3.adapters.qq import normalize_event as normalize_qq_event
from nonebot_plugin_xiuxian_3.runtime import create_runtime

ADAPTERS = ("qq.official", "onebot.v11")
START = datetime(2026, 9, 22, tzinfo=UTC)
HERB = "item.herb.blood_grass"
LOCAL_REPUTATION = "local.xuantian.new_town"


class Clock:
    def __init__(self) -> None:
        self.value = START

    def __call__(self) -> datetime:
        return self.value

    def at(self, hours: int) -> None:
        self.value = START + timedelta(hours=hours)


async def _send(runtime, adapter: str, operation: str, command: str):
    message = (
        normalize_qq_event(_qq_group_event(command))
        if adapter == "qq.official"
        else normalize_event(_onebot_group_event(command))
    )
    return await runtime.adapters.dispatch(
        adapter, replace(message.context, operation_id=operation), message.text
    )


async def _cross_lease(runtime, clock: Clock, adapter: str) -> dict:
    for operation, command in (
        ("create", "开始修仙"),
        ("seek", "寻仙问道"),
        ("lease-old", "租住居所"),
    ):
        result = await _send(runtime, adapter, operation, command)
        assert result.ok, result
    clock.at(48)
    old = await _send(runtime, adapter, "plant-old", "灵田播种 止血草")
    assert old.code == "FIELD_PLOT_PLANTED", old
    maintained = await _send(runtime, adapter, "maintain-old", "灵田维护")
    assert maintained.code == "FIELD_PLOT_MAINTAINED", maintained
    clock.at(72)
    leased = await _send(runtime, adapter, "lease-new", "租住居所")
    assert leased.code == "RESIDENCE_LEASED", leased
    new = await _send(runtime, adapter, "plant-new", "灵田播种 止血草")
    assert new.code == "FIELD_PLOT_PLANTED", new
    with sqlite3.connect(runtime.settings.database_path) as connection:
        assert connection.execute(
            "SELECT COUNT(DISTINCT residence_id) FROM field_plots"
        ).fetchone()[0] == 2
    return {"old": old, "new": new, "maintained": maintained}


def _state(runtime) -> dict[str, list]:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        return {
            table: connection.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
            for table in (
                "players",
                "residences",
                "field_plots",
                "player_reputations",
                "codex_entries",
                "operations",
            )
        }


def _player(runtime) -> dict:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.row_factory = sqlite3.Row
        return dict(connection.execute("SELECT * FROM players").fetchone())


def _json_column(runtime, table: str, key: str, value: str, column: str) -> str:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        return connection.execute(
            f"SELECT {column} FROM {table} WHERE {key}=?", (value,)
        ).fetchone()[0]


def _replace_json(runtime, table: str, key: str, value: str, column: str, raw: str) -> None:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        cursor = connection.execute(
            f"UPDATE {table} SET {column}=? WHERE {key}=?", (raw, value)
        )
        assert cursor.rowcount == 1


def _corrupt_snapshot(raw: str, damage: str) -> str:
    if damage == "malformed":
        return "{"
    if damage == "duplicate_field":
        return '{"maintenance_energy":99,' + raw[1:]
    document = json.loads(raw)
    if damage == "resource_reward":
        document["maintained_harvest"]["cultivation"] = 9
        document["harvest_labels"]["cultivation"] = "修为"
        return json.dumps(document, ensure_ascii=False)
    if damage == "resource_reputation":
        document["reputation_key"] = "cultivation"
        return json.dumps(document, ensure_ascii=False)
    document["maintained_harvest"] = "duplicate_reward_placeholder"
    return json.dumps(document, ensure_ascii=False).replace(
        '"duplicate_reward_placeholder"',
        f'{{"{HERB}":999,"{HERB}":3}}',
    )


@pytest.mark.parametrize("adapter", ADAPTERS)
@pytest.mark.parametrize(
    ("command", "damage"),
    tuple(
        (command, damage)
        for command in ("我的灵田", "灵田维护", "灵田收获")
        for damage in ("malformed", "duplicate_field", "duplicate_reward")
    ) + (("灵田收获", "resource_reward"), ("灵田收获", "resource_reputation")),
)
def test_cross_lease_corrupt_selected_snapshot_rolls_back_and_can_retry(
    tmp_path: Path, adapter: str, command: str, damage: str
) -> None:
    async def run() -> None:
        clock = Clock()
        runtime = create_runtime(data_dir=tmp_path, clock=clock, adapters=(adapter,))
        try:
            plots = await _cross_lease(runtime, clock, adapter)
            clock.at(74)
            chosen = plots["new" if command == "灵田维护" else "old"]
            plot_id = chosen.data["plot_id"]
            raw = _json_column(runtime, "field_plots", "plot_id", plot_id, "snapshot_json")
            _replace_json(
                runtime, "field_plots", "plot_id", plot_id, "snapshot_json",
                _corrupt_snapshot(raw, damage),
            )
            before = _state(runtime)
            rejected = await _send(runtime, adapter, "retry-corrupt", command)
            assert rejected.code == "PERSISTENCE_ERROR", rejected
            assert _state(runtime) == before

            _replace_json(runtime, "field_plots", "plot_id", plot_id, "snapshot_json", raw)
            retried = await _send(runtime, adapter, "retry-corrupt", command)
            assert retried.ok, retried
            assert retried.data["plot_id"] == plot_id
            if command != "我的灵田":
                settled = _state(runtime)
                replay = await _send(runtime, adapter, "retry-corrupt", command)
                assert replay.ok and replay.data["idempotent_replay"] is True
                assert replay.data["plot_id"] == plot_id
                assert _state(runtime) == settled
        finally:
            await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("adapter", ADAPTERS)
@pytest.mark.parametrize(
    ("operation", "command"),
    (("plant-old", "灵田播种 止血草"), ("maintain-old", "灵田维护"), ("harvest-old", "灵田收获")),
)
@pytest.mark.parametrize("damage", ("malformed", "duplicate_field"))
def test_field_operation_json_is_strict_and_replay_precedes_plot_selection(
    tmp_path: Path, adapter: str, operation: str, command: str, damage: str
) -> None:
    async def run() -> None:
        clock = Clock()
        runtime = create_runtime(data_dir=tmp_path, clock=clock, adapters=(adapter,))
        try:
            plots = await _cross_lease(runtime, clock, adapter)
            clock.at(74)
            if operation == "harvest-old":
                harvested = await _send(runtime, adapter, operation, command)
                assert harvested.code == "FIELD_PLOT_HARVESTED", harvested
                assert harvested.data["plot_id"] == plots["old"].data["plot_id"]
            raw = _json_column(runtime, "operations", "operation_id", operation, "result_json")
            broken = "{" if damage == "malformed" else '{"plot_id":"another-plot",' + raw[1:]
            _replace_json(runtime, "operations", "operation_id", operation, "result_json", broken)
            before = _state(runtime)
            rejected = await _send(runtime, adapter, operation, command)
            assert rejected.code == "PERSISTENCE_ERROR", rejected
            assert _state(runtime) == before

            _replace_json(runtime, "operations", "operation_id", operation, "result_json", raw)
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute("UPDATE field_plots SET snapshot_json='{'")
            await runtime.close()
            runtime = create_runtime(data_dir=tmp_path, clock=clock, adapters=(adapter,))
            await runtime.repository.initialize()
            before_replay = _state(runtime)
            replay = await _send(runtime, adapter, operation, command)
            assert replay.ok and replay.data["idempotent_replay"] is True, replay
            assert replay.data["plot_id"] == plots["old"].data["plot_id"]
            assert _state(runtime) == before_replay
        finally:
            await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("adapter", ADAPTERS)
@pytest.mark.parametrize("failure_table", ("codex_entries", "operations"))
def test_cross_lease_harvest_failure_rolls_back_rewards_codex_and_ledger(
    tmp_path: Path, adapter: str, failure_table: str
) -> None:
    async def run() -> None:
        clock = Clock()
        runtime = create_runtime(data_dir=tmp_path, clock=clock, adapters=(adapter,))
        try:
            plots = await _cross_lease(runtime, clock, adapter)
            clock.at(74)
            with sqlite3.connect(runtime.settings.database_path) as connection:
                operation_column = (
                    "first_seen_operation_id" if failure_table == "codex_entries" else "operation_id"
                )
                connection.execute(
                    f"CREATE TRIGGER fail_field_harvest BEFORE INSERT ON {failure_table} "
                    f"WHEN NEW.{operation_column}='harvest-retry' BEGIN "
                    "SELECT RAISE(ABORT, 'injected field harvest failure'); END"
                )
            before = _state(runtime)
            player_before = _player(runtime)
            failed = await _send(runtime, adapter, "harvest-retry", "灵田收获")
            assert failed.code == "PERSISTENCE_ERROR", failed
            assert _state(runtime) == before
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute("DROP TRIGGER fail_field_harvest")

            await runtime.close()
            runtime = create_runtime(data_dir=tmp_path, clock=clock, adapters=(adapter,))
            retried = await _send(runtime, adapter, "harvest-retry", "灵田收获")
            assert retried.code == "FIELD_PLOT_HARVESTED", retried
            assert retried.data["plot_id"] == plots["old"].data["plot_id"]
            assert retried.data["harvest"] == {HERB: 3}
            player_after = _player(runtime)
            assert json.loads(player_after["inventory_json"])[HERB] == json.loads(player_before["inventory_json"])[HERB] + 3
            assert player_after["energy"] == player_before["energy"]
            assert player_after["spirit_stones"] == player_before["spirit_stones"]
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute(
                    "SELECT COUNT(*) FROM operations WHERE operation_id='harvest-retry'"
                ).fetchone()[0] == 1
                assert connection.execute(
                    "SELECT COUNT(*) FROM codex_entries WHERE entry_key='codex.material.blood_grass'"
                ).fetchone()[0] == 1
                assert connection.execute(
                    "SELECT status FROM field_plots WHERE plot_id=?", (plots["new"].data["plot_id"],)
                ).fetchone()[0] == "growing"
                reputation = json.loads(connection.execute("SELECT local_json FROM player_reputations").fetchone()[0])
                assert reputation[LOCAL_REPUTATION] == 1
            settled = _state(runtime)
            replay = await _send(runtime, adapter, "harvest-retry", "灵田收获")
            assert replay.ok and replay.data["idempotent_replay"] is True
            assert _state(runtime) == settled
        finally:
            await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_separate_runtimes_share_field_idempotency_under_concurrent_commands(
    tmp_path: Path, adapter: str
) -> None:
    async def run() -> None:
        clock = Clock()
        first = create_runtime(data_dir=tmp_path, clock=clock, adapters=(adapter,))
        second = None
        try:
            plots = await _cross_lease(first, clock, adapter)
            second = create_runtime(data_dir=tmp_path, clock=clock, adapters=(adapter,))
            await second.repository.initialize()
            player_before = _player(first)
            maintained = await asyncio.gather(
                _send(first, adapter, "maintain-concurrent", "灵田维护"),
                _send(second, adapter, "maintain-concurrent", "灵田维护"),
            )
            assert all(result.code == "FIELD_PLOT_MAINTAINED" for result in maintained), maintained
            assert sorted(result.data["idempotent_replay"] for result in maintained) == [False, True]
            assert {result.data["plot_id"] for result in maintained} == {plots["new"].data["plot_id"]}
            assert _player(first)["energy"] == player_before["energy"] - 1
            clock.at(74)
            harvested = await asyncio.gather(
                _send(first, adapter, "harvest-concurrent", "灵田收获"),
                _send(second, adapter, "harvest-concurrent", "灵田收获"),
            )
            assert all(result.code == "FIELD_PLOT_HARVESTED" for result in harvested), harvested
            assert sorted(result.data["idempotent_replay"] for result in harvested) == [False, True]
            assert {result.data["plot_id"] for result in harvested} == {plots["old"].data["plot_id"]}
            assert all(result.data["harvest"] == {HERB: 3} for result in harvested)
            player_after = _player(first)
            assert json.loads(player_after["inventory_json"])[HERB] == json.loads(player_before["inventory_json"])[HERB] + 3
            assert player_after["energy"] == player_before["energy"] - 1
            assert player_after["spirit_stones"] == player_before["spirit_stones"]
            with sqlite3.connect(first.settings.database_path) as connection:
                assert connection.execute(
                    "SELECT operation_id, COUNT(*) FROM operations WHERE operation_id IN "
                    "('maintain-concurrent', 'harvest-concurrent') GROUP BY operation_id ORDER BY operation_id"
                ).fetchall() == [("harvest-concurrent", 1), ("maintain-concurrent", 1)]
                assert connection.execute(
                    "SELECT COUNT(*) FROM codex_entries WHERE entry_key='codex.material.blood_grass'"
                ).fetchone()[0] == 1
                assert connection.execute(
                    "SELECT maintenance_count, status FROM field_plots WHERE plot_id=?",
                    (plots["new"].data["plot_id"],),
                ).fetchone() == (1, "growing")
            settled = _state(first)
            conflict = await _send(first, adapter, "harvest-concurrent", "灵田维护")
            assert conflict.code == "OPERATION_CONFLICT", conflict
            assert _state(first) == settled
            await first.close()
            first = create_runtime(data_dir=tmp_path, clock=clock, adapters=(adapter,))
            for operation, command in (
                ("maintain-concurrent", "灵田维护"), ("harvest-concurrent", "灵田收获")
            ):
                replay = await _send(first, adapter, operation, command)
                assert replay.ok and replay.data["idempotent_replay"] is True, replay
            assert _state(first) == settled
        finally:
            await first.close()
            if second is not None:
                await second.close()

    asyncio.run(run())


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_corrupt_unselected_active_plot_prevents_partial_cross_lease_harvest(
    tmp_path: Path, adapter: str
) -> None:
    async def run() -> None:
        clock = Clock()
        runtime = create_runtime(data_dir=tmp_path, clock=clock, adapters=(adapter,))
        try:
            plots = await _cross_lease(runtime, clock, adapter)
            clock.at(74)
            new_id = plots["new"].data["plot_id"]
            raw = _json_column(runtime, "field_plots", "plot_id", new_id, "snapshot_json")
            _replace_json(runtime, "field_plots", "plot_id", new_id, "snapshot_json", "{")
            before = _state(runtime)
            rejected = await _send(runtime, adapter, "unselected-retry", "灵田收获")
            assert rejected.code == "PERSISTENCE_ERROR", rejected
            assert _state(runtime) == before
            _replace_json(runtime, "field_plots", "plot_id", new_id, "snapshot_json", raw)
            retried = await _send(runtime, adapter, "unselected-retry", "灵田收获")
            assert retried.code == "FIELD_PLOT_HARVESTED", retried
            assert retried.data["plot_id"] == plots["old"].data["plot_id"]
            assert retried.data["harvest"] == {HERB: 3}
        finally:
            await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_competing_harvest_operations_settle_the_only_mature_plot_once(
    tmp_path: Path, adapter: str
) -> None:
    async def run() -> None:
        clock = Clock()
        first = create_runtime(data_dir=tmp_path, clock=clock, adapters=(adapter,))
        second = None
        try:
            plots = await _cross_lease(first, clock, adapter)
            clock.at(74)
            second = create_runtime(data_dir=tmp_path, clock=clock, adapters=(adapter,))
            await second.repository.initialize()
            player_before = _player(first)
            results = await asyncio.gather(
                _send(first, adapter, "harvest-race-one", "灵田收获"),
                _send(second, adapter, "harvest-race-two", "灵田收获"),
            )
            assert sorted(result.code for result in results) == ["FIELD_PLOT_HARVESTED", "PLOT_NOT_READY"], results
            success = next(result for result in results if result.ok)
            failure = next(result for result in results if not result.ok)
            assert success.data["plot_id"] == plots["old"].data["plot_id"]
            assert success.data["harvest"] == {HERB: 3}
            player_after = _player(first)
            assert json.loads(player_after["inventory_json"])[HERB] == json.loads(player_before["inventory_json"])[HERB] + 3
            assert player_after["energy"] == player_before["energy"]
            assert player_after["spirit_stones"] == player_before["spirit_stones"]
            with sqlite3.connect(first.settings.database_path) as connection:
                assert connection.execute(
                    "SELECT operation_id FROM operations WHERE operation_id IN "
                    "('harvest-race-one', 'harvest-race-two')"
                ).fetchall() == [(success.operation_id,)]
                assert connection.execute(
                    "SELECT status FROM field_plots ORDER BY id"
                ).fetchall() == [("harvested",), ("growing",)]
                assert connection.execute(
                    "SELECT COUNT(*) FROM codex_entries WHERE entry_key='codex.material.blood_grass'"
                ).fetchone()[0] == 1
                reputation = json.loads(connection.execute("SELECT local_json FROM player_reputations").fetchone()[0])
                assert reputation[LOCAL_REPUTATION] == 1
            settled = _state(first)
            replay = await _send(second, adapter, success.operation_id, "灵田收获")
            assert replay.ok and replay.data["idempotent_replay"] is True, replay
            retry = await _send(first, adapter, failure.operation_id, "灵田收获")
            assert retry.code == "PLOT_NOT_READY", retry
            assert _state(first) == settled
        finally:
            await first.close()
            if second is not None:
                await second.close()

    asyncio.run(run())


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_replant_after_withering_rolls_back_cleanup_when_ledger_fails(
    tmp_path: Path, adapter: str
) -> None:
    async def run() -> None:
        clock = Clock()
        runtime = create_runtime(data_dir=tmp_path, clock=clock, adapters=(adapter,))
        try:
            for operation, command in (
                ("create", "开始修仙"),
                ("seek", "寻仙问道"),
                ("lease", "租住居所"),
            ):
                result = await _send(runtime, adapter, operation, command)
                assert result.ok, result
            planted = await _send(runtime, adapter, "plant-before-wither", "灵田播种 止血草")
            assert planted.code == "FIELD_PLOT_PLANTED", planted
            clock.at(29)
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute(
                    "SELECT status FROM field_plots WHERE plot_id=?", (planted.data["plot_id"],)
                ).fetchone()[0] == "growing"
                connection.execute(
                    "CREATE TRIGGER fail_field_replant BEFORE INSERT ON operations "
                    "WHEN NEW.operation_id='plant-after-wither' BEGIN "
                    "SELECT RAISE(ABORT, 'injected field replant failure'); END"
                )
            before = _state(runtime)
            player_before = _player(runtime)
            failed = await _send(runtime, adapter, "plant-after-wither", "灵田播种 止血草")
            assert failed.code == "PERSISTENCE_ERROR", failed
            assert _state(runtime) == before
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute("DROP TRIGGER fail_field_replant")

            await runtime.close()
            runtime = create_runtime(data_dir=tmp_path, clock=clock, adapters=(adapter,))
            retried = await _send(runtime, adapter, "plant-after-wither", "灵田播种 止血草")
            assert retried.code == "FIELD_PLOT_PLANTED", retried
            assert retried.data["plot_id"] != planted.data["plot_id"]
            player_after = _player(runtime)
            assert json.loads(player_after["inventory_json"])[HERB] == json.loads(player_before["inventory_json"])[HERB] - 1
            assert player_after["energy"] == player_before["energy"] - 1
            assert player_after["spirit_stones"] == player_before["spirit_stones"]
            assert player_after["cultivation"] == player_before["cultivation"]
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute(
                    "SELECT status FROM field_plots ORDER BY id"
                ).fetchall() == [("withered",), ("growing",)]
                assert connection.execute(
                    "SELECT COUNT(DISTINCT residence_id) FROM field_plots"
                ).fetchone()[0] == 1
                assert connection.execute(
                    "SELECT COUNT(*) FROM operations WHERE operation_id='plant-after-wither'"
                ).fetchone()[0] == 1
            settled = _state(runtime)
            assert settled["codex_entries"] == before["codex_entries"]
            assert settled["player_reputations"] == before["player_reputations"]
            replay = await _send(runtime, adapter, "plant-after-wither", "灵田播种 止血草")
            assert replay.ok and replay.data["idempotent_replay"] is True, replay
            assert replay.data["plot_id"] == retried.data["plot_id"]
            assert _state(runtime) == settled
        finally:
            await runtime.close()

    asyncio.run(run())
