from __future__ import annotations

import asyncio
import json
import sqlite3
from unittest.mock import patch

import pytest

from test_gacha_codex import ADAPTERS, USER, _database, _send, _setup


def _state(runtime):
    with sqlite3.connect(runtime.settings.database_path) as connection:
        player = connection.execute(
            "SELECT spirit_stones, inventory_json FROM players WHERE platform_user_id=?", (USER,)
        ).fetchone()
        pool = connection.execute(
            "SELECT pity_count,total_draws FROM fate_pools WHERE player_id=(SELECT id FROM players WHERE platform_user_id=?)",
            (USER,),
        ).fetchone()
        rolls = connection.execute(
            "SELECT COUNT(*) FROM fate_rolls WHERE player_id=(SELECT id FROM players WHERE platform_user_id=?)", (USER,)
        ).fetchone()[0]
        codex = connection.execute(
            "SELECT entry_key,first_seen_operation_id FROM codex_entries WHERE player_id=(SELECT id FROM players WHERE platform_user_id=?) ORDER BY entry_key",
            (USER,),
        ).fetchall()
    return (player[0], json.loads(player[1]), pool, rolls, tuple(codex))


def _material_codex(runtime):
    return tuple(row for row in _state(runtime)[4] if row[0] == "codex.material.ironstone")


async def _refused(runtime, adapter, operation, command, code="PERSISTENCE_ERROR"):
    before = _database(runtime)
    result = await _send(runtime, adapter, operation, command)
    assert not result.ok, result
    assert result.code == code, result
    assert _database(runtime) == before
    return result


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_gacha_codex_and_operation_failures_roll_back_and_retry(tmp_path, adapter):
    async def run():
        runtime = await _setup(tmp_path, adapter)
        operation = "audit-material-11"
        command = "机缘寻宝 单抽"
        with patch(
            "nonebot_plugin_xiuxian_3.xiuxian.routine.repository.record_material_discoveries",
            side_effect=RuntimeError("codex write failed"),
        ):
            await _refused(runtime, adapter, operation, command)
        assert _state(runtime)[3] == 0
        result = await _send(runtime, adapter, operation, command)
        assert result.code == "FATE_POOL_ROLLED", result
        assert result.data["reward"].get("item.ore.ironstone", 0) > 0
        assert _material_codex(runtime) == (("codex.material.ironstone", operation),)
        await runtime.close()

        runtime = await _setup(tmp_path / "trigger", adapter)
        with sqlite3.connect(runtime.settings.database_path) as connection:
            connection.execute(
                """CREATE TRIGGER fail_fate_operation AFTER INSERT ON operations
                   WHEN NEW.operation_name = 'routine.roll_fate_pool'
                   BEGIN SELECT RAISE(ABORT, 'operation write failed'); END"""
            )
        await _refused(runtime, adapter, operation, command)
        assert _state(runtime)[3] == 0
        with sqlite3.connect(runtime.settings.database_path) as connection:
            connection.execute("DROP TRIGGER fail_fate_operation")
        result = await _send(runtime, adapter, operation, command)
        assert result.code == "FATE_POOL_ROLLED", result
        assert result.data["reward"].get("item.ore.ironstone", 0) > 0
        assert _material_codex(runtime) == (("codex.material.ironstone", operation),)
        await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_gacha_corrupt_operation_is_read_only_until_repaired(tmp_path, adapter):
    async def run():
        runtime = await _setup(tmp_path, adapter)
        operation = "audit-material-11"
        command = "机缘寻宝 单抽"
        result = await _send(runtime, adapter, operation, command)
        assert result.code == "FATE_POOL_ROLLED", result
        with sqlite3.connect(runtime.settings.database_path) as connection:
            original = connection.execute(
                "SELECT result_json FROM operations WHERE operation_id=?", (operation,)
            ).fetchone()[0]
        corruptions = (
            "{",
            "[]",
            original[:-1] + ',"draw_count":1}',
        )
        for corrupt in corruptions:
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute("UPDATE operations SET result_json=? WHERE operation_id=?", (corrupt, operation))
            await _refused(runtime, adapter, operation, command)
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute("UPDATE operations SET result_json=? WHERE operation_id=?", (original, operation))
        conflict = await _send(runtime, adapter, operation, "机缘寻宝 十连")
        assert not conflict.ok and conflict.code == "OPERATION_CONFLICT", conflict
        before = _database(runtime)
        replay = await _send(runtime, adapter, operation, command)
        assert replay.ok and replay.data["idempotent_replay"] is True
        assert _database(runtime) == before
        await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_gacha_same_operation_concurrent_runtime_settles_once(tmp_path, adapter):
    async def run():
        first = await _setup(tmp_path, adapter)
        second = __import__("test_gacha_codex", fromlist=["_setup"])
        runtime_two = await second._setup(tmp_path / "second", adapter)
        # Point the second runtime at the first runtime's database/content while
        # retaining its own adapter facade and connection lifecycle.
        await runtime_two.close()
        runtime_two = __import__("nonebot_plugin_xiuxian_3.runtime", fromlist=["create_runtime"]).create_runtime(
            data_dir=tmp_path / "data", adapters=(adapter,)
        )
        results = await asyncio.gather(
            _send(first, adapter, "audit-material-11", "机缘寻宝 单抽"),
            _send(runtime_two, adapter, "audit-material-11", "机缘寻宝 单抽"),
        )
        assert all(result.code == "FATE_POOL_ROLLED" for result in results), results
        assert sum(result.data["idempotent_replay"] for result in results) == 1
        state = _state(first)
        assert state[3] == 1
        assert _material_codex(first) == (("codex.material.ironstone", "audit-material-11"),)
        await first.close()
        await runtime_two.close()

    asyncio.run(run())
