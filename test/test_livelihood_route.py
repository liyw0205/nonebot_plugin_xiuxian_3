from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import shutil
import sqlite3

import pytest

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.companions.rules import mount_transport_injury_roll_bp
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle, ContentError
from nonebot_plugin_xiuxian_3.xiuxian.persistence.errors import RouteCargoRequirementError
from nonebot_plugin_xiuxian_3.xiuxian.livelihood.route_rules import (
    ROUTE_NEW_TOWN_OUTSKIRTS,
    route_definition,
    route_definitions,
)
from test_livelihood import MutableClock, _onebot_event, _qq_event


def _content(tmp_path: Path) -> Path:
    data_dir = tmp_path / "data"
    shutil.copytree(Path(__file__).parents[1] / "data", data_dir)
    return data_dir


def _edit_record(data_dir: Path, relative_path: str, key: str, change) -> None:
    path = data_dir / relative_path
    document = json.loads(path.read_text(encoding="utf-8"))
    record = next(row for row in document["records"] if row["key"] == key)
    change(record)
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")


def _context(operation: str, user: str = "route-recovery") -> CommandContext:
    return CommandContext(adapter="web", user_id=user, operation_id=operation)


async def _prepare(runtime, user: str = "route-recovery") -> int:
    assert (await runtime.dispatch(_context("create", user), "开始修仙")).ok
    assert (await runtime.dispatch(_context("seek", user), "寻仙问道")).ok
    with sqlite3.connect(runtime.settings.database_path) as connection:
        return connection.execute(
            "SELECT id FROM players WHERE platform='web' AND platform_user_id=?", (user,)
        ).fetchone()[0]


def _state(runtime, player_id: int) -> dict:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.row_factory = sqlite3.Row
        return {
            "player": dict(connection.execute(
                "SELECT * FROM players WHERE id=?", (player_id,)
            ).fetchone()),
            "reputation": [dict(row) for row in connection.execute(
                "SELECT * FROM player_reputations WHERE player_id=?", (player_id,)
            )],
            "routes": [dict(row) for row in connection.execute(
                "SELECT * FROM livelihood_trade_routes WHERE player_id=? ORDER BY id", (player_id,)
            )],
            "companions": [dict(row) for row in connection.execute(
                "SELECT * FROM companion_instances WHERE player_id=? ORDER BY id", (player_id,)
            )],
            "operations": [dict(row) for row in connection.execute(
                "SELECT * FROM operations WHERE player_id=? ORDER BY operation_id", (player_id,)
            )],
        }


def _assert_player_copy(message: str) -> None:
    for forbidden in ("route.", "item.", "local.", "xuantian.", "请求编号", "in_transit", "settled"):
        assert forbidden not in message


def test_route_identity_cost_cargo_stage_and_reward_follow_content(tmp_path: Path) -> None:
    async def run() -> None:
        data_dir = _content(tmp_path)

        def change_route(row):
            row.update(
                name="青石药车", aliases=["药车"], allowed_stages=["seeker"],
                duration_seconds=77, delay_chance_bp=10_000, delay_seconds=13,
                daily_limit=1, random_pool="route.medicine_cart",
            )
            row["cost"]["stamina"] = 4
            row["reward"].update(
                amount=37, reputation_key="local.xuantian.cloud_city", reputation=6,
            )
            row["cargo"].update(
                max_value=22, unit_values={"item.food.coarse_spirit_rice": 21},
                aliases={"药车粮": "item.food.coarse_spirit_rice"},
                default_item_key="item.food.coarse_spirit_rice",
            )

        _edit_record(data_dir, "生活/生活.json", ROUTE_NEW_TOWN_OUTSKIRTS, change_route)
        _edit_record(
            data_dir, "地图/地点.json", "xuantian.cloud_city",
            lambda row: row.update(local_reputation_maximum=4),
        )
        clock = MutableClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
        runtime = create_runtime(data_dir=data_dir, clock=clock)
        player_id = await _prepare(runtime)
        definition = route_definition(ROUTE_NEW_TOWN_OUTSKIRTS, runtime.repository.content)
        assert definition.random_pool == "route.medicine_cart"
        assert definition.local_reputation_key == "local.xuantian.cloud_city"
        assert definition.local_reputation_maximum == 4
        preview = await runtime.dispatch(_context("preview"), "运输预览 药车")
        assert preview.code == "ROUTE_PREVIEW"
        assert preview.data["ready"] is False
        assert preview.data["cargo_key"] == "item.food.coarse_spirit_rice"
        assert preview.data["cargo_value"] == 21
        assert preview.data["duration_seconds"] == 77
        assert "青石药车" in preview.message
        assert "修行阶段" in preview.data["missing"]
        _assert_player_copy(preview.message)
        before = _state(runtime, player_id)
        missing = await runtime.dispatch(_context("missing-stage"), "开始运输 药车 药车粮")
        assert missing.code == "ROUTE_REQUIREMENT_MISSING"
        assert _state(runtime, player_id) == before
        with sqlite3.connect(runtime.settings.database_path) as connection:
            connection.execute("UPDATE players SET stage='seeker' WHERE id=?", (player_id,))
        before = _state(runtime, player_id)
        excessive = await runtime.dispatch(_context("cargo-too-high"), "开始运输 药车 药车粮 2")
        assert excessive.code == "ROUTE_CARGO_LOCKED"
        assert _state(runtime, player_id) == before
        started = await runtime.dispatch(_context("start"), "开始运输 药车")
        assert started.code == "ROUTE_STARTED"
        assert started.data["reward_stones"] == 37
        assert started.data["delay_seconds"] == 13
        assert datetime.fromisoformat(started.data["arrives_at"]) - clock.value == timedelta(seconds=90)
        _assert_player_copy(started.message)
        clock.advance(seconds=90)
        settled = await runtime.dispatch(_context("settle"), f"结算运输 {started.data['route_id']}")
        assert settled.code == "ROUTE_SETTLED"
        assert settled.data["local_reputation_delta"] == 4
        after = _state(runtime, player_id)
        assert after["player"]["spirit_stones"] == 137
        assert after["player"]["stamina"] == 26
        assert after["player"]["location_key"] == "xuantian.outskirts"
        assert json.loads(after["player"]["inventory_json"])["item.food.coarse_spirit_rice"] == 2
        assert json.loads(after["reputation"][0]["local_json"]) == {"local.xuantian.cloud_city": 4}
        assert json.loads(after["routes"][0]["snapshot_json"])["random_pool"] == "route.medicine_cart"
        _assert_player_copy(settled.message)
        await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("before", [3, 6])
@pytest.mark.parametrize("change", ["reward", "locked_route", "invalid_cap", "locked_destination", "cargo_name", "missing_cargo"])
def test_frozen_route_replays_and_settles_after_content_change(
    tmp_path: Path, before: int, change: str,
) -> None:
    async def run() -> None:
        data_dir = _content(tmp_path)

        def freeze_reward(row):
            row["reward"].update(
                amount=19, reputation_key="local.xuantian.cloud_city", reputation=3,
            )
            row.update(delay_chance_bp=10_000, delay_seconds=9)

        _edit_record(data_dir, "生活/生活.json", ROUTE_NEW_TOWN_OUTSKIRTS, freeze_reward)
        _edit_record(
            data_dir, "地图/地点.json", "xuantian.cloud_city",
            lambda row: row.update(local_reputation_maximum=4),
        )
        clock = MutableClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
        runtime = create_runtime(data_dir=data_dir, clock=clock)
        player_id = await _prepare(runtime)
        with sqlite3.connect(runtime.settings.database_path) as connection:
            connection.execute(
                "INSERT INTO player_reputations(player_id, local_json, service_reputation, updated_at) "
                "VALUES (?, ?, 23, ?)",
                (player_id, json.dumps({"local.xuantian.cloud_city": before, "local.xuantian.new_town": 8}), clock.value.isoformat()),
            )
        started = await runtime.dispatch(_context("start"), "开始运输 止血草 1")
        assert started.code == "ROUTE_STARTED"
        frozen = json.loads(_state(runtime, player_id)["routes"][0]["snapshot_json"])
        assert frozen["local_reputation_key"] == "local.xuantian.cloud_city"
        assert frozen["local_reputation_maximum"] == 4
        assert frozen["cargo"] == {"item.herb.blood_grass": 1}
        assert frozen["cargo_name"] == "止血草"
        assert frozen["delay_seconds"] == 9
        await runtime.close()

        if change == "reward":
            def change_reward(row):
                row["reward"].update(amount=88, reputation_key="local.xuantian.new_town", reputation=10)
                row.update(delay_chance_bp=0, delay_seconds=400, duration_seconds=1800)
                row["cargo"]["unit_values"]["item.herb.blood_grass"] = 99
            _edit_record(data_dir, "生活/生活.json", ROUTE_NEW_TOWN_OUTSKIRTS, change_reward)
            _edit_record(data_dir, "地图/地点.json", "xuantian.cloud_city", lambda row: row.update(local_reputation_maximum=99))
        elif change == "locked_route":
            _edit_record(data_dir, "生活/生活.json", ROUTE_NEW_TOWN_OUTSKIRTS, lambda row: row.update(status="locked"))
        elif change == "invalid_cap":
            _edit_record(data_dir, "地图/地点.json", "xuantian.cloud_city", lambda row: row.pop("local_reputation_maximum"))
        elif change == "cargo_name":
            _edit_record(data_dir, "道具/材料.json", "item.herb.blood_grass", lambda row: row.update(name="灵血草"))
        elif change == "missing_cargo":
            path = data_dir / "道具" / "材料.json"
            document = json.loads(path.read_text(encoding="utf-8"))
            document["records"] = [row for row in document["records"] if row["key"] != "item.herb.blood_grass"]
            path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
        else:
            _edit_record(data_dir, "地图/地点.json", "xuantian.outskirts", lambda row: row.update(status="locked"))
        runtime = create_runtime(data_dir=data_dir, clock=clock)
        replay_start = await runtime.dispatch(_context("start"), "开始运输 止血草 1")
        assert replay_start.data == {**started.data, "idempotent_replay": True}
        assert "止血草" in replay_start.message
        if change not in {"reward", "cargo_name"}:
            unchanged = _state(runtime, player_id)
            new_start = await runtime.dispatch(_context("new-start"), "开始运输 止血草 1")
            assert new_start.code == "LIVELIHOOD_CONTENT_CLOSED"
            assert _state(runtime, player_id) == unchanged
        conflict = await runtime.dispatch(_context("start"), "开始运输 止血草 2")
        assert conflict.code == "OPERATION_CONFLICT"
        _assert_player_copy(conflict.message)
        clock.advance(minutes=11)
        settled = await runtime.dispatch(_context("settle"), f"结算运输 {started.data['route_id']}")
        assert settled.code == "ROUTE_SETTLED"
        assert settled.data["reward_stones"] == 19
        assert settled.data["local_reputation_before"] == before
        assert settled.data["local_reputation_after"] == max(before, 4)
        assert settled.data["local_reputation_delta"] == max(before, 4) - before
        assert f"地方名望**：+{max(before, 4) - before}" in settled.message
        assert settled.data["delay_seconds"] == 9
        assert "止血草" in settled.message
        assert "灵血草" not in settled.message
        _assert_player_copy(settled.message)
        state = _state(runtime, player_id)
        assert state["player"]["spirit_stones"] == 119
        assert state["player"]["stamina"] == 28
        assert state["player"]["location_key"] == "xuantian.outskirts"
        assert json.loads(state["player"]["inventory_json"])["item.herb.blood_grass"] == 2
        assert json.loads(state["reputation"][0]["local_json"]) == {
            "local.xuantian.cloud_city": max(before, 4), "local.xuantian.new_town": 8,
        }
        assert state["reputation"][0]["service_reputation"] == 23
        assert state["player"]["cultivation"] == state["player"]["total_cultivation"] == 0
        assert json.loads(state["routes"][0]["snapshot_json"]) == frozen
        result = json.loads(state["routes"][0]["result_json"])
        assert result["local_reputation_before"] == before
        assert result["local_reputation_after"] == max(before, 4)
        await runtime.close()
        runtime = create_runtime(data_dir=data_dir, clock=clock)
        replay = await runtime.dispatch(_context("settle"), f"结算运输 {started.data['route_id']}")
        assert replay.data == {**settled.data, "idempotent_replay": True}
        conflict = await runtime.dispatch(_context("settle"), "结算运输 another-route")
        assert conflict.code == "OPERATION_CONFLICT"
        _assert_player_copy(conflict.message)
        assert _state(runtime, player_id) == state
        assert sum(row["operation_id"] == "settle" for row in state["operations"]) == 1
        await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("failure", ["reputation", "route", "operation"])
def test_route_settlement_rolls_back_player_mount_and_ledger_on_failure(
    tmp_path: Path, failure: str,
) -> None:
    async def run() -> None:
        data_dir = _content(tmp_path)
        clock = MutableClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
        runtime = create_runtime(data_dir=data_dir, clock=clock)
        player_id = await _prepare(runtime)
        with sqlite3.connect(runtime.settings.database_path) as connection:
            connection.execute(
                "INSERT INTO activity_events(player_id, event_key, source_operation_id, occurred_at) "
                "VALUES (?, 'story.mainline.xuantian', 'story-seed', ?)",
                (player_id, clock.value.isoformat()),
            )
            connection.execute(
                "INSERT INTO player_reputations(player_id, local_json, service_reputation, updated_at) "
                "VALUES (?, ?, 23, ?)",
                (player_id, json.dumps({"local.xuantian.new_town": 8}), clock.value.isoformat()),
            )
        bonded = await runtime.dispatch(_context("bond"), "结缘灵骑 竹鹿")
        assert bonded.code == "COMPANION_BONDED"
        mount_id = bonded.data["instance_id"]
        operation = "start-with-mount"
        while mount_transport_injury_roll_bp(operation) < 1000:
            operation += "-retry"
        started = await runtime.dispatch(_context(operation), f"开始运输 止血草 1 {mount_id}")
        assert started.code == "ROUTE_STARTED"
        clock.advance(minutes=20)
        before = _state(runtime, player_id)
        assert before["companions"][0]["status"] == "travelling"
        assert before["companions"][0]["experience"] == 0
        conditions = {
            "reputation": "BEFORE INSERT ON player_reputations",
            "route": "BEFORE UPDATE ON livelihood_trade_routes WHEN NEW.status='settled'",
            "operation": "BEFORE INSERT ON operations WHEN NEW.operation_id='settle-retry'",
        }
        with sqlite3.connect(runtime.settings.database_path) as connection:
            connection.execute(
                f"CREATE TRIGGER injected_route_failure {conditions[failure]} "
                "BEGIN SELECT RAISE(ABORT, 'injected route failure'); END"
            )
        with pytest.raises(sqlite3.IntegrityError, match="injected route failure"):
            await runtime.repository.settle_route(
                platform="web", platform_user_id="route-recovery",
                route_id=started.data["route_id"], operation_id="settle-retry",
            )
        assert _state(runtime, player_id) == before
        with sqlite3.connect(runtime.settings.database_path) as connection:
            connection.execute("DROP TRIGGER injected_route_failure")
        await runtime.close()
        runtime = create_runtime(data_dir=data_dir, clock=clock)
        settled = await runtime.dispatch(_context("settle-retry"), f"结算运输 {started.data['route_id']}")
        assert settled.code == "ROUTE_SETTLED"
        assert settled.data["mount_experience"] == 5
        after = _state(runtime, player_id)
        assert after["player"]["spirit_stones"] == before["player"]["spirit_stones"] + 12
        assert after["player"]["inventory_json"] == before["player"]["inventory_json"]
        assert after["player"]["stamina"] == before["player"]["stamina"]
        assert after["player"]["location_key"] == "xuantian.outskirts"
        assert after["companions"][0]["status"] == "available"
        assert after["companions"][0]["experience"] == 5
        assert after["companions"][0]["stamina"] == before["companions"][0]["stamina"]
        assert json.loads(after["reputation"][0]["local_json"])["local.xuantian.new_town"] == 10
        assert after["reputation"][0]["service_reputation"] == 23
        assert after["routes"][0]["status"] == "settled"
        replay = await runtime.dispatch(_context("settle-retry"), f"结算运输 {started.data['route_id']}")
        assert replay.data == {**settled.data, "idempotent_replay": True}
        assert _state(runtime, player_id) == after
        await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("fault", ["reputation_reference", "cargo_reference", "cap", "locked_source", "locked_destination", "default_cargo"])
def test_invalid_route_content_refuses_without_spending(tmp_path: Path, fault: str) -> None:
    async def run() -> None:
        data_dir = _content(tmp_path)
        runtime = create_runtime(data_dir=data_dir)
        player_id = await _prepare(runtime)
        before = _state(runtime, player_id)
        await runtime.close()
        if fault == "cap":
            _edit_record(data_dir, "地图/地点.json", "xuantian.new_town", lambda row: row.update(local_reputation_maximum=0))
        elif fault.startswith("locked_"):
            key = "xuantian.new_town" if fault == "locked_source" else "xuantian.outskirts"
            _edit_record(data_dir, "地图/地点.json", key, lambda row: row.update(status="locked"))
        else:
            def break_route(row):
                if fault == "reputation_reference":
                    row["reward"]["reputation_key"] = "local.missing.place"
                elif fault == "cargo_reference":
                    row["cargo"]["unit_values"]["item.missing.cargo"] = 1
                else:
                    row["cargo"]["default_item_key"] = "item.missing.cargo"
            _edit_record(data_dir, "生活/生活.json", ROUTE_NEW_TOWN_OUTSKIRTS, break_route)
        runtime = create_runtime(data_dir=data_dir)
        preview = await runtime.dispatch(_context("bad-preview"), "运输预览 止血草 1")
        assert preview.code == "LIVELIHOOD_CONTENT_CLOSED"
        started = await runtime.dispatch(_context("bad-start"), "开始运输 止血草 1")
        assert started.code == "LIVELIHOOD_CONTENT_CLOSED"
        assert _state(runtime, player_id) == before
        _assert_player_copy(started.message)
        await runtime.close()

    asyncio.run(run())


def test_concurrent_route_settlement_grants_once(tmp_path: Path) -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
        runtime = create_runtime(data_dir=tmp_path, clock=clock)
        player_id = await _prepare(runtime)
        started = await runtime.dispatch(_context("start"), "开始运输 止血草 1")
        assert started.code == "ROUTE_STARTED"
        clock.advance(minutes=20)
        results = await asyncio.gather(*(
            runtime.dispatch(_context(operation), f"结算运输 {started.data['route_id']}")
            for operation in ("settle-a", "settle-b")
        ))
        assert {result.code for result in results} == {"ROUTE_SETTLED", "ROUTE_ALREADY_SETTLED"}
        state = _state(runtime, player_id)
        assert state["player"]["spirit_stones"] == 112
        assert json.loads(state["reputation"][0]["local_json"])["local.xuantian.new_town"] == 2
        assert sum(row["operation_name"] == "livelihood.settle_route" for row in state["operations"]) == 1
        await runtime.close()

    asyncio.run(run())


def test_route_preview_outside_source_uses_bundled_location_name(tmp_path: Path) -> None:
    async def run() -> None:
        runtime = create_runtime(data_dir=tmp_path)
        player_id = await _prepare(runtime)
        with sqlite3.connect(runtime.settings.database_path) as connection:
            connection.execute("UPDATE players SET location_key='xuantian.outskirts' WHERE id=?", (player_id,))
        before = _state(runtime, player_id)
        preview = await runtime.dispatch(_context("preview"), "运输预览 止血草 1")
        assert preview.code == "ROUTE_PREVIEW"
        assert preview.data["ready"] is False
        assert "青石镇" in preview.data["missing"]
        assert _state(runtime, player_id) == before
        _assert_player_copy(preview.message)
        await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("local_json", ["{", "[]", '{"local.xuantian.new_town": true}'])
def test_invalid_reputation_json_rolls_back_route_settlement(tmp_path: Path, local_json: str) -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
        runtime = create_runtime(data_dir=tmp_path, clock=clock)
        player_id = await _prepare(runtime)
        started = await runtime.dispatch(_context("start"), "开始运输 止血草 1")
        assert started.ok
        with sqlite3.connect(runtime.settings.database_path) as connection:
            connection.execute(
                "INSERT INTO player_reputations(player_id, local_json, updated_at) VALUES (?, ?, ?)",
                (player_id, local_json, clock.value.isoformat()),
            )
        clock.advance(minutes=20)
        before = _state(runtime, player_id)
        with pytest.raises(ValueError, match="player local reputation"):
            await runtime.repository.settle_route(
                platform="web", platform_user_id="route-recovery",
                route_id=started.data["route_id"], operation_id="settle",
            )
        assert _state(runtime, player_id) == before
        await runtime.close()

    asyncio.run(run())


def test_zero_route_reward_moves_player_without_creating_reputation(tmp_path: Path) -> None:
    async def run() -> None:
        data_dir = _content(tmp_path)
        _edit_record(
            data_dir, "生活/生活.json", ROUTE_NEW_TOWN_OUTSKIRTS,
            lambda row: row["reward"].update(amount=0, reputation=0),
        )
        clock = MutableClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
        runtime = create_runtime(data_dir=data_dir, clock=clock)
        player_id = await _prepare(runtime)
        started = await runtime.dispatch(_context("start"), "开始运输 止血草 1")
        assert started.ok
        clock.advance(minutes=20)
        settled = await runtime.dispatch(_context("settle"), "结算运输")
        assert settled.code == "ROUTE_SETTLED"
        assert settled.data["reward_stones"] == 0
        assert settled.data["local_reputation_delta"] == 0
        after = _state(runtime, player_id)
        assert after["player"]["spirit_stones"] == 100
        assert after["player"]["location_key"] == "xuantian.outskirts"
        assert after["reputation"] == []
        await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("quantity", [True, 1.5, "1"])
def test_repository_rejects_non_integer_cargo_quantities(tmp_path: Path, quantity) -> None:
    async def run() -> None:
        runtime = create_runtime(data_dir=tmp_path)
        player_id = await _prepare(runtime)
        before = _state(runtime, player_id)
        with pytest.raises(RouteCargoRequirementError):
            await runtime.repository.start_route(
                platform="web", platform_user_id="route-recovery", route_key=ROUTE_NEW_TOWN_OUTSKIRTS,
                cargo_key="item.herb.blood_grass", cargo_quantity=quantity, operation_id="invalid-start",
                request_args=(),
            )
        assert _state(runtime, player_id) == before
        await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("stages", [["unknown"], [" "], [True]])
def test_route_contract_rejects_unknown_stages(tmp_path: Path, stages) -> None:
    data_dir = _content(tmp_path)
    _edit_record(
        data_dir, "生活/生活.json", ROUTE_NEW_TOWN_OUTSKIRTS,
        lambda row: row.update(allowed_stages=stages),
    )
    with pytest.raises(ContentError, match="allowed_stages"):
        route_definitions(ContentBundle.load(data_dir))


@pytest.mark.parametrize("change", ["replace", "remove"])
def test_implicit_cargo_request_replays_before_current_default_is_resolved(tmp_path: Path, change: str) -> None:
    async def run() -> None:
        data_dir = _content(tmp_path)
        clock = MutableClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
        runtime = create_runtime(data_dir=data_dir, clock=clock)
        player_id = await _prepare(runtime)
        started = await runtime.dispatch(_context("start"), "开始运输")
        assert started.code == "ROUTE_STARTED"
        assert started.data["cargo_key"] == "item.herb.blood_grass"
        await runtime.close()

        def change_default(row):
            if change == "replace":
                row["cargo"]["default_item_key"] = "item.food.coarse_spirit_rice"
            else:
                row["cargo"].pop("default_item_key")

        _edit_record(data_dir, "生活/生活.json", ROUTE_NEW_TOWN_OUTSKIRTS, change_default)
        runtime = create_runtime(data_dir=data_dir, clock=clock)
        before = _state(runtime, player_id)
        replay = await runtime.dispatch(_context("start"), "开始运输")
        assert replay.data == {**started.data, "idempotent_replay": True}
        assert _state(runtime, player_id) == before
        assert "止血草" in replay.message
        clock.advance(minutes=20)
        assert (await runtime.dispatch(_context("settle"), "结算运输")).code == "ROUTE_SETTLED"
        with sqlite3.connect(runtime.settings.database_path) as connection:
            connection.execute("UPDATE players SET location_key='xuantian.new_town' WHERE id=?", (player_id,))
        before = _state(runtime, player_id)
        next_route = await runtime.dispatch(_context("next-start"), "开始运输")
        if change == "replace":
            assert next_route.code == "ROUTE_STARTED"
            assert next_route.data["cargo_key"] == "item.food.coarse_spirit_rice"
            state = _state(runtime, player_id)
            inventory = json.loads(state["player"]["inventory_json"])
            assert inventory["item.food.coarse_spirit_rice"] == 2
            assert inventory["item.herb.blood_grass"] == 2
        else:
            assert next_route.code == "LIVELIHOOD_CONTENT_CLOSED"
            assert _state(runtime, player_id) == before
        await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("kind", ["onebot", "qq"])
def test_explicit_route_and_cargo_alias_replay_after_content_rename_and_close(
    tmp_path: Path, kind: str,
) -> None:
    pytest.importorskip("nonebot")

    async def run() -> None:
        data_dir = _content(tmp_path)
        _edit_record(
            data_dir,
            "生活/生活.json",
            ROUTE_NEW_TOWN_OUTSKIRTS,
            lambda row: row.update(
                name="青石药车",
                aliases=["旧商路"],
                cargo={
                    **row["cargo"],
                    "aliases": {**row["cargo"]["aliases"], "旧灵草": "item.herb.blood_grass"},
                },
            ),
        )
        clock = MutableClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
        runtime = create_runtime(data_dir=data_dir, clock=clock)
        adapter = "onebot.v11" if kind == "onebot" else "qq.official"
        user_id = "1001" if kind == "onebot" else "qq-user-1"

        def event(text: str, message_id: int):
            if kind == "onebot":
                return _onebot_event(text, message_id, user_id=1001, group_id=2002)
            return _qq_event(text, f"route-alias-{message_id}", member_openid=user_id, group_openid="qq-group")

        async def send(text: str, message_id: int):
            from nonebot_plugin_xiuxian_3.adapters.onebot import normalize_event
            from nonebot_plugin_xiuxian_3.adapters.qq import normalize_event as normalize_qq_event

            raw = event(text, message_id)
            normalized = normalize_event(raw) if kind == "onebot" else normalize_qq_event(raw)
            return await runtime.adapters.dispatch(adapter, normalized.context, normalized.text)

        assert (await send("开始修仙", 9000)).ok
        assert (await send("寻仙问道", 9001)).ok
        started = await send("开始运输 旧商路 旧灵草 1", 9002)
        assert started.code == "ROUTE_STARTED"
        route_id = started.data["route_id"]
        with sqlite3.connect(runtime.settings.database_path) as connection:
            before = connection.execute(
                "SELECT stamina, inventory_json FROM players WHERE platform=? AND platform_user_id=?",
                (adapter, user_id),
            ).fetchone()
        await runtime.close()

        def close_and_rename(row):
            row.update(name="新商路", aliases=[], status="locked")
            row["cargo"]["aliases"].pop("旧灵草", None)

        _edit_record(data_dir, "生活/生活.json", ROUTE_NEW_TOWN_OUTSKIRTS, close_and_rename)
        runtime = create_runtime(data_dir=data_dir, clock=clock)
        replay = await send("开始运输 旧商路 旧灵草 1", 9002)
        assert replay.data == {**started.data, "idempotent_replay": True}
        with sqlite3.connect(runtime.settings.database_path) as connection:
            after = connection.execute(
                "SELECT stamina, inventory_json FROM players WHERE platform=? AND platform_user_id=?",
                (adapter, user_id),
            ).fetchone()
        assert after == before
        conflict = await send("开始运输 旧商路 旧灵草 2", 9002)
        assert conflict.code == "OPERATION_CONFLICT"
        with sqlite3.connect(runtime.settings.database_path) as connection:
            assert connection.execute(
                "SELECT COUNT(*) FROM livelihood_trade_routes WHERE route_id=?", (route_id,)
            ).fetchone()[0] == 1
        clock.advance(minutes=20)
        settled = await send(f"结算运输 {route_id}", 9003)
        assert settled.code == "ROUTE_SETTLED"
        assert "青石药车" in settled.message
        assert "新商路" not in settled.message
        await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("result_json", ["{", "[]", '{"status":"settled"}'])
def test_route_start_replay_rejects_corrupt_operation_without_writing(
    tmp_path: Path, result_json: str,
) -> None:
    async def run() -> None:
        runtime = create_runtime(data_dir=tmp_path)
        player_id = await _prepare(runtime)
        started = await runtime.dispatch(_context("start"), "开始运输 止血草 1")
        assert started.code == "ROUTE_STARTED"
        with sqlite3.connect(runtime.settings.database_path) as connection:
            connection.execute(
                "UPDATE operations SET result_json=? WHERE operation_id=?",
                (result_json, "start"),
            )
        before = _state(runtime, player_id)
        replay = await runtime.dispatch(_context("start"), "开始运输 止血草 1")
        assert replay.code == "PERSISTENCE_ERROR"
        assert _state(runtime, player_id) == before
        await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("missing", ["source_location", "destination_location", "allowed_stages", "random_pool", "desc", "default_item_key"])
def test_route_contract_has_no_silent_defaults(tmp_path: Path, missing: str) -> None:
    data_dir = _content(tmp_path)

    def remove_field(row):
        if missing == "default_item_key":
            row["cargo"].pop(missing)
        else:
            row.pop(missing)

    _edit_record(data_dir, "生活/生活.json", ROUTE_NEW_TOWN_OUTSKIRTS, remove_field)
    with pytest.raises(ContentError):
        route_definitions(ContentBundle.load(data_dir))


@pytest.mark.parametrize("field", ["stamina", "duration_seconds", "amount", "reputation", "max_value", "unit_value"])
def test_route_contract_rejects_boolean_numbers(tmp_path: Path, field: str) -> None:
    data_dir = _content(tmp_path)

    def boolean_field(row):
        if field == "stamina":
            row["cost"][field] = True
        elif field in {"amount", "reputation"}:
            row["reward"][field] = True
        elif field == "max_value":
            row["cargo"][field] = True
        elif field == "unit_value":
            row["cargo"]["unit_values"]["item.herb.blood_grass"] = True
        else:
            row[field] = True

    _edit_record(data_dir, "生活/生活.json", ROUTE_NEW_TOWN_OUTSKIRTS, boolean_field)
    with pytest.raises(ContentError):
        route_definitions(ContentBundle.load(data_dir))


@pytest.mark.parametrize("kind", ["onebot", "qq"])
def test_real_adapter_events_settle_custom_route_once(tmp_path: Path, kind: str) -> None:
    pytest.importorskip("nonebot")
    from nonebot_plugin_xiuxian_3.adapters.onebot import normalize_event
    from nonebot_plugin_xiuxian_3.adapters.qq import normalize_event as normalize_qq_event

    async def run() -> None:
        data_dir = _content(tmp_path)
        _edit_record(
            data_dir, "生活/生活.json", ROUTE_NEW_TOWN_OUTSKIRTS,
            lambda row: row["reward"].update(amount=23, reputation=6),
        )
        _edit_record(data_dir, "地图/地点.json", "xuantian.new_town", lambda row: row.update(local_reputation_maximum=4))
        clock = MutableClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
        runtime = create_runtime(data_dir=data_dir, clock=clock)

        async def send(text: str, number: int):
            event = _onebot_event(text, number) if kind == "onebot" else _qq_event(text, f"route-{number}")
            normalized = normalize_event(event) if kind == "onebot" else normalize_qq_event(event)
            adapter = "onebot.v11" if kind == "onebot" else "qq.official"
            return await runtime.adapters.dispatch(adapter, normalized.context, normalized.text), normalized

        assert (await send("开始修仙", 8000))[0].ok
        assert (await send("寻仙问道", 8001))[0].ok
        assert (await send("运输预览 止血草 1", 8002))[0].code == "ROUTE_PREVIEW"
        started, _ = await send("开始运输 止血草 1", 8003)
        assert started.code == "ROUTE_STARTED"
        clock.advance(minutes=20)
        settled, normalized = await send(f"结算运输 {started.data['route_id']}", 8004)
        assert settled.code == "ROUTE_SETTLED"
        assert settled.data["reward_stones"] == 23
        assert settled.data["local_reputation_delta"] == 4
        replay, _ = await send(f"结算运输 {started.data['route_id']}", 8004)
        assert replay.data == {**settled.data, "idempotent_replay": True}
        with sqlite3.connect(runtime.settings.database_path) as connection:
            stones, location, local_json, cultivation, total = connection.execute(
                "SELECT p.spirit_stones, p.location_key, r.local_json, p.cultivation, p.total_cultivation "
                "FROM players p JOIN player_reputations r ON r.player_id=p.id "
                "WHERE p.platform=? AND p.platform_user_id=?",
                (normalized.context.adapter, normalized.context.user_id),
            ).fetchone()
            operation_count = connection.execute(
                "SELECT COUNT(*) FROM operations WHERE operation_id=?", (normalized.context.operation_id,)
            ).fetchone()[0]
        assert stones == 123
        assert location == "xuantian.outskirts"
        assert json.loads(local_json) == {"local.xuantian.new_town": 4}
        assert (cultivation, total) == (0, 0)
        assert operation_count == 1
        _assert_player_copy(settled.message)
        await runtime.close()

    asyncio.run(run())
