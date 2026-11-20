from __future__ import annotations

import asyncio
import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle, ContentError
from nonebot_plugin_xiuxian_3.xiuxian.progression.recovery_rules import bloodline_recovery_rule, endgame_stamina_rule
from test_progression import MutableClock
from test_progression_content import _enter_cultivator


@pytest.mark.parametrize("adapter", ["qq.official", "onebot.v11"])
def test_bloodline_recovery_periods_rollback_replay_concurrency_and_cap(tmp_path: Path, adapter: str) -> None:
    async def run():
        clock = MutableClock()
        runtime = create_runtime(data_dir=tmp_path, clock=clock)

        async def dispatch(request, command="恢复状态", operation=""):
            return await runtime.adapters.dispatch(adapter, CommandContext(
                adapter=adapter, user_id="bloodline", request_id=request, operation_id=operation,
            ), command)

        def state():
            with sqlite3.connect(runtime.settings.database_path) as connection:
                return connection.execute(
                    "SELECT bloodline_stability, updated_at FROM players WHERE platform_user_id='bloodline'"
                ).fetchone(), connection.execute(
                    "SELECT COUNT(*) FROM operations WHERE operation_name='player.recover_resources'"
                ).fetchone()[0]

        try:
            assert (await dispatch("create", "开始修仙")).ok
            clock.advance(days=1)
            beginner = await dispatch("beginner")
            assert beginner.data["bloodline_stability"] == 0
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE players SET stage='cultivator', realm_key='nascent_soul', realm_layer=1 "
                    "WHERE platform_user_id='bloodline'"
                )
            clock.advance(minutes=29)
            assert (await dispatch("early")).data["recovered_bloodline_stability"] == 0
            clock.advance(minutes=1)
            before = state()
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "CREATE TRIGGER reject_recovery BEFORE INSERT ON operations "
                    "WHEN NEW.operation_id='recover-once' BEGIN SELECT RAISE(ABORT, 'test rollback'); END"
                )
            failed = await dispatch("failed", operation="recover-once")
            assert failed.code == "PERSISTENCE_ERROR"
            assert state() == before
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute("DROP TRIGGER reject_recovery")
            recovered = await dispatch("success", operation="recover-once")
            assert recovered.code == "RESOURCES_RECOVERED"
            assert recovered.data["recovered_bloodline_stability"] == 1
            assert recovered.data["bloodline_stability"] == 1
            clock.advance(hours=1)
            concurrent = await asyncio.gather(dispatch("concurrent-a"), dispatch("concurrent-b"))
            assert sum(result.data["recovered_bloodline_stability"] for result in concurrent) == 2
            before_replay = state()
            replay = await dispatch("replay", operation="recover-once")
            assert replay.data["idempotent_replay"] is True
            assert replay.data["bloodline_stability"] == 1
            assert state() == before_replay
            clock.advance(days=3)
            capped = await dispatch("cap")
            assert capped.data["bloodline_stability"] == 100
            assert capped.data["recovered_bloodline_stability"] == 97
            clock.advance(days=1)
            assert (await dispatch("full")).data["recovered_bloodline_stability"] == 0
        finally:
            await runtime.close()

    asyncio.run(run())


def test_bloodline_recovery_consumes_configured_rate_and_preserves_exploration_snapshot(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    shutil.copytree(Path(__file__).parents[1] / "data", data_dir)
    path = data_dir / "养成/规则.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    rule = next(row for row in document["records"] if row["key"] == "recovery.bloodline")
    rule.update(per_period=3, maximum=60)
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")

    async def run():
        clock = MutableClock()
        runtime = create_runtime(data_dir=data_dir, clock=clock)
        async def dispatch(request, command="恢复状态"):
            return await runtime.adapters.dispatch("qq.official", CommandContext(
                adapter="qq.official", user_id="configured", request_id=request,
            ), command)
        try:
            await _enter_cultivator(runtime, "qq.official", "configured")
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE players SET stage='cultivator', realm_key='nascent_soul', realm_layer=1, "
                    "location_key='beast.ten_thousand_hills', stamina=50, stamina_max=50"
                )
            clock.advance(hours=1)
            assert (await dispatch("rate")).data["bloodline_stability"] == 6
            started = await dispatch("explore", "开始探索 万兽山狩猎")
            assert started.code == "EXPLORATION_STARTED"
            clock.advance(hours=1)
            blocked = await dispatch("snapshot")
            assert blocked.data["recovered_bloodline_stability"] == 0
            assert blocked.data["bloodline_stability"] == 6
        finally:
            await runtime.close()
    asyncio.run(run())


@pytest.mark.parametrize("field,value", [
    ("per_period", True), ("per_period", 0), ("per_period", 101),
    ("maximum", -1), ("maximum", 101), ("required_realm", "missing"),
    ("required_layer", 11),
])
def test_bloodline_recovery_rule_rejects_invalid_content(tmp_path: Path, field, value) -> None:
    data_dir = tmp_path / "data"
    shutil.copytree(Path(__file__).parents[1] / "data", data_dir)
    path = data_dir / "养成/规则.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    rule = next(row for row in document["records"] if row["key"] == "recovery.bloodline")
    rule[field] = value
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ContentError, match="recovery.bloodline"):
        bloodline_recovery_rule(ContentBundle.load(data_dir))


@pytest.mark.parametrize("adapter", ["qq.official", "onebot.v11"])
@pytest.mark.parametrize("capacity", [50, 100])
def test_endgame_stamina_capacity_recovers_legacy_players_without_lowering_existing_capacity(
    tmp_path: Path, adapter: str, capacity: int,
) -> None:
    async def run():
        clock = MutableClock()
        runtime = create_runtime(data_dir=tmp_path, clock=clock)
        async def dispatch(request):
            return await runtime.adapters.dispatch(adapter, CommandContext(
                adapter=adapter, user_id="capacity", request_id=request,
            ), "恢复状态")
        try:
            await _enter_cultivator(runtime, adapter, "capacity")
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE players SET realm_key='void_refining', realm_layer=10, stamina=?, stamina_max=?",
                    (capacity, capacity),
                )
            assert (await dispatch("before-union")).data["stamina_max"] == capacity
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute("UPDATE players SET realm_key='dao_union', realm_layer=1")
            clock.advance(minutes=29)
            recovered = await dispatch("capacity")
            assert recovered.data["stamina_max"] == max(60, capacity)
            assert recovered.data["stamina"] == capacity
            assert recovered.data["recovered_stamina"] == 0
            replay = await dispatch("capacity")
            assert replay.data["idempotent_replay"] is True
            assert replay.data["stamina_max"] == max(60, capacity)
            clock.advance(minutes=1)
            assert (await dispatch("period")).data["stamina"] == min(capacity + 1, max(60, capacity))
            clock.advance(hours=5)
            full = await dispatch("full")
            assert full.data["stamina"] == max(60, capacity)
            assert full.data["stamina_max"] == max(60, capacity)
        finally:
            await runtime.close()
    asyncio.run(run())


@pytest.mark.parametrize("field,value", [
    ("minimum_capacity", True), ("minimum_capacity", 0),
    ("minimum_capacity", 60.5), ("required_realm", "missing"),
    ("required_layer", True), ("required_layer", 11),
])
def test_endgame_stamina_capacity_rejects_invalid_content(tmp_path: Path, field, value) -> None:
    data_dir = tmp_path / "data"
    shutil.copytree(Path(__file__).parents[1] / "data", data_dir)
    path = data_dir / "养成/规则.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    rule = next(row for row in document["records"] if row["key"] == "recovery.endgame_stamina")
    rule[field] = value
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ContentError, match="recovery.endgame_stamina"):
        endgame_stamina_rule(ContentBundle.load(data_dir))
