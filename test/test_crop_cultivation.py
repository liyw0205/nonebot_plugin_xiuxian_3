from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta

import pytest

from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentError, bundled_content
from nonebot_plugin_xiuxian_3.xiuxian.livelihood.cultivation_rules import freeze_cultivation, resolve_plan
from nonebot_plugin_xiuxian_3.xiuxian.livelihood.rules import crop_definitions
from nonebot_plugin_xiuxian_3.xiuxian.production.rules import random_quality_bp
from test_wilderness_idle import Clock, move, send, starter, change_content

HERB = "item.herb.blood_grass"
LEAF = "item.herb.spirit_leaf"
RICE = "item.grain.cloud_rice"


def state(runtime):
    with runtime.repository._connect() as db:
        return {table: tuple(tuple(row) for row in db.execute(f"SELECT * FROM {table} ORDER BY rowid"))
                for table in ("players", "field_plots", "operations", "codex_entries", "player_reputations", "economy_ledger_entries")}


def player(runtime):
    with runtime.repository._connect() as db:
        return dict(db.execute("SELECT * FROM players WHERE platform_user_id='gatherer'").fetchone())


async def prepare(runtime, clock, *, developed=False):
    await starter(runtime, path="辅修 烹饪")
    if developed:
        # Accumulated realm/reputation/funds only; no seeds or source evidence are injected.
        with runtime.repository._connect() as db:
            db.execute("UPDATE players SET realm_key='qi_sensing', realm_layer=2, spirit_stones=1000")
            db.execute("INSERT INTO player_reputations(player_id, local_json, service_reputation, updated_at) "
                       "SELECT id, ?, 0, ? FROM players",
                       (json.dumps({"local.xuantian.new_town": 60}), clock.value.isoformat()))
    await move(runtime, clock, "青石镇")
    result = await send(runtime, "租住居所 " + ("灵圃小院" if developed else "客房"), "lease")
    assert result.ok, result


def test_six_plans_nine_events_have_frozen_real_consumers():
    bundle = bundled_content()
    crops = crop_definitions(bundle)
    assert len(crops) == 3
    seen = set()
    for crop in crops.values():
        cultivation = crop.cultivation
        assert {plan["key"] for plan in cultivation["plans"]} == {"intensive", "patient"}
        fast, slow = cultivation["plans"]
        assert fast["required_maintenance"] > slow["required_maintenance"]
        assert fast["growth_seconds"] < slow["growth_seconds"]
        assert slow["harvest_window_seconds"] > fast["harvest_window_seconds"]
        for plan in cultivation["plans"]:
            assert resolve_plan(cultivation, plan["name"]) == plan
            expected = {event["key"] for event in plan["events"]}
            actual = {freeze_cultivation(cultivation, plan, f"matrix-{i}", bundle)["event"]["key"] for i in range(32)}
            assert actual == expected
            for event in plan["events"]:
                assert len({event[field] for field in ("start_text", "maintenance_text", "complete_text", "fallback_text")}) == 4
                assert all(value > 0 for value in event["harvest"].values())
                seen.add((crop.key, plan["key"], event["key"]))
    assert len(seen) == 9


@pytest.mark.parametrize("damage", ["number", "extra", "blank", "item", "duplicate", "recipe", "source", "source_plan"])
def test_cultivation_rejects_bad_content(damage):
    def mutate(records):
        c = records["livelihood", "crop.blood_grass"]["cultivation"]
        p = c["plans"][0]
        if damage == "number":
            p["growth_seconds"] = True
        elif damage == "extra":
            p["client_result"] = 1
        elif damage == "blank":
            p["events"][0]["complete_text"] = " "
        elif damage == "item":
            p["events"][0]["harvest"] = {"cultivation": 999}
        elif damage == "duplicate":
            c["plans"][1]["name"] = p["name"]
        elif damage == "recipe":
            c["recipe_keys"] = ["recipe.weapon.wood_sword"]
        elif damage == "source":
            c["seed_source"]["key"] = "guide.read_world"
        else:
            records["livelihood", "crop.cloud_rice"]["cultivation"]["seed_source"]["plan_key"] = "patient"
    with pytest.raises(ContentError):
        crop_definitions(change_content(mutate))


def test_public_seed_exchange_three_crops_and_food_consumption(tmp_path):
    async def run():
        clock = Clock()
        runtime = create_runtime(data_dir=tmp_path, clock=clock)
        try:
            await prepare(runtime, clock, developed=True)
            before = state(runtime)
            preview = await send(runtime, "灵田预览", "preview")
            assert preview.code == "FIELD_PREVIEW" and len(preview.data["crops"]) == 3
            assert state(runtime) == before
            assert "止血草" in preview.message and "缓养" in preview.message and "种源" in preview.message
            inventory_before = json.loads(player(runtime)["inventory_json"])
            planted = await send(runtime, "灵田播种 止血草 1 精耕", "plant-herb")
            assert planted.code == "FIELD_PLOT_PLANTED", planted
            assert json.loads(player(runtime)["inventory_json"])[HERB] == inventory_before[HERB] - 1
            for i in range(2):
                assert (await send(runtime, "灵田维护 1", f"care-herb-{i}")).ok
            clock.advance(hours=4)
            harvested = await send(runtime, "灵田收获 1", "herb-harvest")
            assert harvested.data["harvest"][RICE] == 1
            inventory = json.loads(player(runtime)["inventory_json"])
            assert inventory[RICE] == inventory_before.get(RICE, 0) + 1
            assert inventory[HERB] == inventory_before[HERB] - 1 + harvested.data["harvest"][HERB]
            assert (await send(runtime, "接取委托 止血草供应", "accept-herb")).ok
            before_delivery = player(runtime)
            delivered = await send(runtime, "交付委托 止血草供应", "deliver-herb")
            assert delivered.ok, delivered
            assert json.loads(player(runtime)["inventory_json"])[HERB] == inventory[HERB] - 3
            assert player(runtime)["spirit_stones"] == before_delivery["spirit_stones"] + 18
            rice = await send(runtime, "灵田播种 云纹稻 1 缓养", "plant-rice")
            assert rice.ok, rice
            assert json.loads(player(runtime)["inventory_json"]).get(RICE, 0) == 0
            await move(runtime, clock, "灵泉谷")
            explored = await send(runtime, "开始探索 灵泉采集", "seed-leaf")
            assert explored.ok, explored
            clock.advance(minutes=3)
            gathered = await send(runtime, "结算探索", "gather-leaf")
            assert gathered.ok and gathered.data["result"][LEAF] >= 1, gathered
            await move(runtime, clock, "青石镇")
            leaf = await send(runtime, "灵田播种 灵叶 2 缓养", "plant-leaf")
            assert leaf.ok, leaf
            assert (await send(runtime, "灵田维护 1", "care-rice")).ok
            assert (await send(runtime, "灵田维护 2", "care-leaf")).ok
            await runtime.close()
            runtime = create_runtime(data_dir=tmp_path, clock=clock)
            profile = await send(runtime, "我的灵田", "profile")
            assert len(profile.data["plots"]) == 2
            assert all(plot["cultivation"]["plan_name"] == "缓养" for plot in profile.data["plots"])
            clock.value = datetime.fromisoformat(leaf.data["harvest_at"])
            rice_reward = await send(runtime, "灵田收获 1", "rice-harvest")
            leaf_reward = await send(runtime, "灵田收获 2", "leaf-harvest")
            assert rice_reward.data["harvest"] == {RICE: 4}
            assert leaf_reward.data["harvest"] == {LEAF: 3}
            op = next(f"cook-{i}" for i in range(32) if random_quality_bp(f"cook-{i}") == 1000)
            cooking = await send(runtime, "开始生产 云纹灵米饭", op)
            assert cooking.ok, cooking
            clock.value = datetime.fromisoformat(cooking.data["ends_at"])
            meal = await send(runtime, "领取生产", "meal")
            assert meal.ok and meal.data["success"] is True, meal
            assert json.loads(player(runtime)["inventory_json"])[RICE] == 1
            consumed = await send(runtime, "使用物品 云纹灵米饭 精力", "eat")
            assert consumed.ok, consumed
            assert json.loads(player(runtime)["inventory_json"])["item.food.cloud_rice_meal"] == 1
        finally:
            await runtime.close()
    asyncio.run(run())


@pytest.mark.parametrize("command,operation", [("灵田播种 止血草 精耕", "livelihood.plant"), ("灵田维护", "livelihood.maintain_plot")])
def test_plant_and_care_faults_roll_back_then_retry(tmp_path, command, operation):
    async def run():
        clock = Clock()
        runtime = create_runtime(data_dir=tmp_path, clock=clock)
        try:
            await prepare(runtime, clock)
            if operation == "livelihood.maintain_plot":
                assert (await send(runtime, "灵田播种 止血草 精耕", "seed")).ok
            with runtime.repository._connect() as db:
                db.execute(f"CREATE TRIGGER fail_crop_write BEFORE INSERT ON operations WHEN NEW.operation_name='{operation}' "
                           "BEGIN SELECT RAISE(ABORT, 'crop write fault'); END")
            before = state(runtime)
            with pytest.raises(sqlite3.IntegrityError, match="crop write fault"):
                await send(runtime, command, "fault-retry")
            assert state(runtime) == before
            with runtime.repository._connect() as db:
                db.execute("DROP TRIGGER fail_crop_write")
            retried = await send(runtime, command, "fault-retry")
            assert retried.ok
            before = state(runtime)
            replay = await send(runtime, command, "fault-retry")
            assert replay.data["idempotent_replay"] and state(runtime) == before
        finally:
            await runtime.close()
    asyncio.run(run())


def test_qq_preview_native_event_and_message_contract(tmp_path):
    from dataclasses import replace
    from urllib.parse import unquote
    from test_adapter_simulation import _qq_group_event
    from test_messaging import FakeBot
    from nonebot_plugin_xiuxian_3.adapters.qq import normalize_event
    from nonebot_plugin_xiuxian_3.adapters.messaging import send_markdown_message, markdown_to_text

    class QQBot(FakeBot):
        __module__ = "nonebot.adapters.qq.bot"

    async def run():
        runtime = create_runtime(data_dir=tmp_path)
        try:
            event = _qq_group_event("灵田预览 止血草")
            message = normalize_event(event)
            result = await runtime.adapters.dispatch("qq.official", replace(message.context, operation_id="qq-preview"), message.text)
            assert result.code == "FIELD_PREVIEW" and not result.actions
            assert not result.message.startswith("#") and "\n>" not in result.message
            assert "mqqapi" not in result.message
            bot = QQBot()
            rendered = await send_markdown_message(bot, event, result.message, capabilities=("markdown", "keyboard"), command_prefix="!")
            assert rendered.sent_format == "markdown"
            actual = unquote(str(bot.sent[0][1]))
            assert "!灵田播种 止血草 精耕" in actual and "!灵田播种 止血草 缓养" in actual
            assert "enter=false" in actual and "keyboard" not in actual
            plain = markdown_to_text(result.message)
            assert "止血草" in plain and "精耕" in plain and "mqqapi" not in plain
            help_message = normalize_event(_qq_group_event("修仙帮助 生活"))
            help_result = await runtime.adapters.dispatch("qq.official", help_message.context, help_message.text)
            assert "灵田预览" in help_result.message and not help_result.actions
        finally:
            await runtime.close()
    asyncio.run(run())


@pytest.mark.parametrize("damage", ["null", "reward", "duplicate", "missing_text"])
def test_corrupt_planned_snapshot_is_not_downgraded(tmp_path, damage):
    async def run():
        clock = Clock()
        runtime = create_runtime(data_dir=tmp_path, clock=clock)
        try:
            await prepare(runtime, clock)
            start = await send(runtime, "灵田播种 止血草 缓养", "plant")
            assert start.ok
            with runtime.repository._connect() as db:
                raw = db.execute("SELECT snapshot_json FROM field_plots").fetchone()[0]
                snapshot = json.loads(raw)
                if damage == "null":
                    snapshot["cultivation"] = None
                elif damage == "reward":
                    snapshot["maintained_harvest"][HERB] = 99
                elif damage == "missing_text":
                    del snapshot["cultivation"]["event"]["complete_text"]
                broken = '{"cultivation":null,' + raw[1:] if damage == "duplicate" else json.dumps(snapshot)
                db.execute("UPDATE field_plots SET snapshot_json=?", (broken,))
            before = state(runtime)
            with pytest.raises(ValueError):
                await send(runtime, "灵田维护", "care")
            assert state(runtime) == before
            with runtime.repository._connect() as db:
                db.execute("UPDATE field_plots SET snapshot_json=?", (raw,))
            assert (await send(runtime, "灵田维护", "care")).ok
        finally:
            await runtime.close()
    asyncio.run(run())


@pytest.mark.parametrize("command,expected", [
    ("灵田播种 止血草 错误方案", "LIVELIHOOD_CONTENT_CLOSED"),
    ("灵田播种 止血草 9 缓养", "INVALID_FIELD_SLOT"),
    ("灵田播种 灵叶 缓养", "RESIDENCE_REQUIRED"),
    ("灵田播种 云纹稻 2 精耕 多余", "INVALID_CROP"),
    ("灵田维护 ²", "INVALID_FIELD_SLOT"),
    ("灵田收获 " + "9" * 30, "INVALID_FIELD_SLOT"),
])
def test_specific_refusal_is_zero_write(tmp_path, command, expected):
    async def run():
        clock = Clock()
        runtime = create_runtime(data_dir=tmp_path, clock=clock)
        try:
            await prepare(runtime, clock)
            before = state(runtime)
            result = await send(runtime, command, "refused")
            assert result.code == expected and result.data["reason"] and result.data["subject"]
            assert state(runtime) == before
        finally:
            await runtime.close()
    asyncio.run(run())


def test_frozen_event_large_assets_fault_retry_and_replay(tmp_path, caplog):
    async def run():
        clock = Clock()
        runtime = create_runtime(data_dir=tmp_path, clock=clock)
        try:
            await prepare(runtime, clock)
            huge = 10 ** 90
            with runtime.repository._connect() as db:
                db.execute("UPDATE players SET spirit_stones=?, cultivation=?, total_cultivation=?",
                           (str(huge).encode(), str(huge).encode(), str(huge).encode()))
            started = await send(runtime, "灵田播种 止血草 缓养", "start")
            assert started.ok, started
            before = state(runtime)
            conflict = await send(runtime, "灵田播种 止血草 精耕", "start")
            assert conflict.code == "OPERATION_CONFLICT" and state(runtime) == before
            await runtime.close()
            runtime = create_runtime(data_dir=tmp_path, clock=clock)
            runtime.repository.content = change_content(lambda records: records["livelihood", "crop.blood_grass"].update(status="locked"))
            replay = await send(runtime, "灵田播种 止血草 缓养", "start")
            assert replay.message == started.message and replay.data["idempotent_replay"]
            clock.value = datetime.fromisoformat(started.data["harvest_at"])
            with runtime.repository._connect() as db:
                db.execute("CREATE TRIGGER fail_crop BEFORE INSERT ON operations WHEN NEW.operation_id='claim' "
                           "BEGIN SELECT RAISE(ABORT, 'crop fault'); END")
            before = state(runtime)
            with pytest.raises(sqlite3.IntegrityError, match="crop fault"):
                await send(runtime, "灵田收获", "claim")
            assert state(runtime) == before
            assert "command=灵田收获" in caplog.text and "operation=claim" in caplog.text
            with runtime.repository._connect() as db:
                db.execute("DROP TRIGGER fail_crop")
            claimed = await send(runtime, "灵田收获", "claim")
            assert claimed.data["harvest"] == {HERB: 2} and not claimed.data["maintained"]
            assert "杂草" in claimed.message
            assert claimed.data["cultivation"] == started.data["cultivation"]
            assert int(player(runtime)["spirit_stones"]) == huge
            assert int(player(runtime)["cultivation"]) == huge
            before = state(runtime)
            replay = await send(runtime, "灵田收获", "claim")
            assert replay.message == claimed.message and state(runtime) == before
        finally:
            await runtime.close()
    asyncio.run(run())


def test_patient_window_wither_replant_and_concurrent_idempotency(tmp_path):
    async def run():
        clock = Clock()
        runtime = create_runtime(data_dir=tmp_path, clock=clock)
        other = None
        try:
            await prepare(runtime, clock)
            planted = await send(runtime, "灵田播种 止血草 缓养", "patient")
            assert planted.ok
            clock.value = datetime.fromisoformat(planted.data["wither_at"])
            assert (await send(runtime, "灵田收获", "at-deadline")).ok
            clock.advance(days=1)
            assert (await send(runtime, "恢复状态", "recover")).ok
            assert (await send(runtime, "租住居所 客房", "renew-before-second")).ok
            second = await send(runtime, "灵田播种 止血草 缓养", "second")
            assert second.ok
            clock.value = datetime.fromisoformat(second.data["wither_at"]) + timedelta(seconds=1)
            before = state(runtime)
            rejected = await send(runtime, "灵田收获", "late")
            assert rejected.code == "PLOT_WITHERED" and state(runtime) == before
            assert (await send(runtime, "租住居所 客房", "renew")).code == "RESIDENCE_ALREADY_ACTIVE"
            other = create_runtime(data_dir=tmp_path, clock=clock)
            results = await asyncio.gather(send(runtime, "灵田播种 止血草 缓养", "replant"), send(other, "灵田播种 止血草 缓养", "replant"))
            assert all(result.ok for result in results)
            assert results[0].data["plot_id"] == results[1].data["plot_id"]
            assert sorted(result.data["idempotent_replay"] for result in results) == [False, True]
        finally:
            if other:
                await other.close()
            await runtime.close()
    asyncio.run(run())
