from __future__ import annotations

import asyncio
import json
import sqlite3
from dataclasses import replace
from datetime import timedelta
from urllib.parse import unquote

import pytest

from nonebot_plugin_xiuxian_3.adapters.messaging import send_markdown_message
from nonebot_plugin_xiuxian_3.adapters.onebot import normalize_event as normalize_onebot
from nonebot_plugin_xiuxian_3.adapters.qq import normalize_event as normalize_qq
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.adventures.mainline import mainline_definitions
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentError
from nonebot_plugin_xiuxian_3.xiuxian.production.rules import random_quality_bp
from test_adapter_simulation import _onebot_group_event, _qq_group_event
from test_companion_old_trail_mainline import _database_state, _inventory
from test_mainline_vertical_slice import _copy_content
from test_messaging import FakeBot
from test_wilderness_idle import Clock, change_content, starter


class FieldJourney:
    def __init__(self, path, adapter):
        self.path, self.adapter = path, adapter
        self.clock = Clock()
        self.runtime = create_runtime(data_dir=path, clock=self.clock, adapters=(adapter,))
        self.sequence = 0

    async def send(self, command, operation="", *, user="gatherer", writable=True):
        self.sequence += 1
        event = (_qq_group_event(command, message_id=f"field-{self.sequence}")
                 if self.adapter == "qq.official" else _onebot_group_event(command, message_id=self.sequence))
        normalized = (normalize_qq if self.adapter == "qq.official" else normalize_onebot)(event)
        context = replace(normalized.context, user_id=user, operation_id=operation or f"field-{self.sequence}",
                          can_write_assets=writable, capabilities=("text", "markdown", "keyboard"))
        return await self.runtime.adapters.dispatch(self.adapter, context, normalized.text)

    async def move(self, destination):
        result = await self.send(f"前往 {destination}")
        assert result.code == "TRAVEL_STARTED", result.message
        self.clock.advance(minutes=3)
        assert (await self.send("结算移动")).code == "TRAVEL_COMPLETED"

    async def next_day(self):
        self.clock.value = (self.clock.value + timedelta(days=1)).replace(hour=0, minute=0, second=0)
        assert (await self.send("恢复状态")).ok

    async def restart(self):
        await self.runtime.close()
        self.runtime = create_runtime(data_dir=self.path, clock=self.clock, adapters=(self.adapter,))
        await self.runtime.repository.initialize()

    def fail(self, operation):
        with self.runtime.repository._connect() as db:
            db.execute("CREATE TRIGGER fail_field_journey BEFORE INSERT ON operations "
                       f"WHEN NEW.operation_id='{operation}' BEGIN SELECT RAISE(ABORT, 'field journey fault'); END")

    def repair(self):
        with self.runtime.repository._connect() as db:
            db.execute("DROP TRIGGER fail_field_journey")

    async def render(self, result, expected_command, *, keyboard=False):
        class QQBot(FakeBot):
            __module__ = "nonebot.adapters.qq.bot"

        class OneBot(FakeBot):
            __module__ = "nonebot.adapters.onebot.v11.bot"

        bot = QQBot() if self.adapter == "qq.official" else OneBot()
        event = _qq_group_event("主线") if self.adapter == "qq.official" else _onebot_group_event("主线")
        before = _database_state(self.runtime)
        receipt = await send_markdown_message(
            bot, event, result.message, actions=result.actions,
            capabilities=("markdown", "keyboard") if self.adapter == "qq.official" else ("text",),
            command_prefix="!",
        )
        assert len(bot.sent) == 1 and _database_state(self.runtime) == before
        message = bot.sent[0][1]
        if self.adapter == "qq.official":
            assert receipt.sent_format == ("markdown+keyboard" if keyboard else "markdown")
            segments = tuple(message) if keyboard else (message,)
            assert any(segment.type == "markdown" for segment in segments)
            actual = unquote(str(message))
            assert "!" + expected_command in actual
            if keyboard:
                assert sum(segment.type == "keyboard" for segment in segments) == 1
                assert len(result.actions) == 1
            else:
                assert "enter=false" in actual
        else:
            assert receipt.sent_format == "text"
            actual = str(message)
            assert expected_command in actual and "mqqapi" not in actual and "command:" not in actual


@pytest.mark.parametrize("damage", ["quantity", "empty", "duplicate", "plan", "crop", "yield", "body", "extra"])
def test_field_story_requires_real_sufficient_crop_plans(damage):
    def mutate(records):
        stage = records["mainline", "field_seeds.2"]
        objective = stage["objectives"][0]
        if damage == "quantity":
            objective["quantity"] = True
        elif damage == "empty":
            objective["plan_keys"] = []
        elif damage == "duplicate":
            objective["plan_keys"] *= 2
        elif damage == "plan":
            objective["plan_keys"] = ["patient"]
        elif damage == "crop":
            objective["crop_key"] = "crop.missing"
        elif damage == "yield":
            records["livelihood", "crop.blood_grass"]["cultivation"]["plans"][0]["events"][0]["harvest"].pop("item.grain.cloud_rice")
        elif damage == "body":
            stage["body"] = "只有标题"
        else:
            objective["client_result"] = True
    with pytest.raises(ContentError):
        mainline_definitions(change_content(mutate), story_key="story.mainline.field_seeds")


@pytest.mark.parametrize("adapter", ["onebot.v11", "qq.official"])
def test_seed_exchange_public_story_farming_delivery_and_message_contract(tmp_path, adapter):
    async def run():
        j = FieldJourney(_copy_content(tmp_path), adapter)
        try:
            await starter(j.runtime, adapter=adapter, path="辅修 烹饪")
            before = _database_state(j.runtime)
            assert (await j.send("开始药畦换种主线 归镇认畦")).code == "MAINLINE_REQUIREMENT_MISSING"
            assert (await j.send("开始药畦换种主线 不存在")).code == "INVALID_MAINLINE_COMMAND"
            assert _database_state(j.runtime) == before
            with j.runtime.repository._connect() as db:
                db.execute("UPDATE players SET realm_layer=2, spirit_stones=1000")
            before = _database_state(j.runtime)
            assert not (await j.send("开始药畦换种主线 归镇认畦", writable=False)).ok
            assert _database_state(j.runtime) == before
            assert (await j.send("开始药畦换种主线 归镇认畦", "stage-1")).ok
            await j.move("青石镇")
            first = await j.send("领取药畦换种主线奖励 归镇认畦", "claim-1")
            assert first.ok and first.actions[0].command == "开始药畦换种主线 field_seeds.2"
            await j.render(first, first.actions[0].command, keyboard=True)
            assert (await j.send("租住居所 客房", "rent")).ok
            # Same-time planting before stage start must remain stale after harvest.
            assert (await j.send("灵田播种 止血草 精耕", "old-plant")).ok
            second = await j.send(first.actions[0].command, "stage-2")
            assert second.ok
            await j.render(second, "灵田播种 止血草 精耕")
            before = _database_state(j.runtime)
            assert (await j.send(first.actions[0].command, "stage-2")).data["idempotent_replay"]
            assert (await j.send("开始药畦换种主线 归镇认畦", "stage-2")).code == "OPERATION_CONFLICT"
            assert _database_state(j.runtime) == before
            for index in range(2):
                assert (await j.send("灵田维护 1", f"old-care-{index}")).ok
            j.clock.advance(hours=4)
            assert (await j.send("灵田收获 1", "old-harvest")).ok
            claim = "领取药畦换种主线奖励 分苗换种"
            before = _database_state(j.runtime)
            incomplete = await j.send(claim)
            assert incomplete.code == "MAINLINE_OBJECTIVES_INCOMPLETE" and "我的灵田" in incomplete.message
            assert _database_state(j.runtime) == before
            await j.next_day()
            assert (await j.send("灵田播种 止血草 精耕", "untended")).ok
            j.clock.advance(hours=4)
            assert (await j.send("灵田收获 1", "untended-harvest")).ok
            assert (await j.send(claim)).code == "MAINLINE_OBJECTIVES_INCOMPLETE"
            await j.next_day()
            before = _database_state(j.runtime)
            assert not (await j.send("灵田播种 止血草 0 精耕")).ok
            assert not (await j.send("灵田播种 止血草 错误方案")).ok
            assert _database_state(j.runtime) == before
            assert (await j.send("灵田播种 止血草 精耕", "new-plant")).ok
            for index in range(2):
                assert (await j.send("灵田维护 1", f"care-{index}")).ok
            before = _database_state(j.runtime)
            assert not (await j.send("灵田收获 1", "harvest")).ok
            assert _database_state(j.runtime) == before
            j.clock.advance(hours=4)
            await j.restart()
            j.fail("harvest")
            before = _database_state(j.runtime)
            with pytest.raises(sqlite3.IntegrityError, match="field journey fault"):
                await j.send("灵田收获 1", "harvest")
            assert _database_state(j.runtime) == before
            j.repair()
            old = _inventory(j.runtime)
            harvested = await j.send("灵田收获 1", "harvest")
            assert harvested.ok and harvested.data["harvest"]["item.grain.cloud_rice"] == 1
            assert _inventory(j.runtime)["item.grain.cloud_rice"] == old["item.grain.cloud_rice"] + 1
            before = _database_state(j.runtime)
            assert (await j.send("灵田收获 1", "harvest")).data["idempotent_replay"]
            assert _database_state(j.runtime) == before
            with j.runtime.repository._connect() as db:
                receipt = db.execute("SELECT result_json FROM operations WHERE operation_id='harvest'").fetchone()[0]
                damaged = json.loads(receipt)
                damaged["harvest"]["item.grain.cloud_rice"] = True
                db.execute("UPDATE operations SET result_json=? WHERE operation_id='harvest'", (json.dumps(damaged),))
            before = _database_state(j.runtime)
            assert (await j.send(claim)).code == "PERSISTENCE_ERROR"
            assert _database_state(j.runtime) == before
            assert (await j.send("开始修仙", user="other-farmer")).ok
            with j.runtime.repository._connect() as db:
                owner = db.execute("SELECT player_id FROM operations WHERE operation_id='harvest'").fetchone()[0]
                other = db.execute("SELECT id FROM players WHERE platform_user_id='other-farmer'").fetchone()[0]
                db.execute("UPDATE operations SET result_json=? WHERE operation_id='harvest'", (receipt,))
                db.execute("UPDATE operations SET player_id=? WHERE operation_id='harvest'", (other,))
            before = _database_state(j.runtime)
            assert (await j.send(claim)).code == "MAINLINE_OBJECTIVES_INCOMPLETE"
            assert _database_state(j.runtime) == before
            with j.runtime.repository._connect() as db:
                db.execute("UPDATE operations SET player_id=? WHERE operation_id='harvest'", (owner,))
            with j.runtime.repository._connect() as db:
                saved = db.execute("SELECT snapshot_json FROM mainline_runs WHERE stage_key='field_seeds.2'").fetchone()[0]
            for damage in ("quantity", "baseline"):
                broken = json.loads(saved)
                if damage == "baseline":
                    broken.pop("baseline_operation_rowid")
                else:
                    broken["definition"]["objectives"][0]["quantity"] = True
                with j.runtime.repository._connect() as db:
                    db.execute("UPDATE mainline_runs SET snapshot_json=? WHERE stage_key='field_seeds.2'", (json.dumps(broken),))
                before = _database_state(j.runtime)
                assert (await j.send(claim, "claim-2")).code == "PERSISTENCE_ERROR"
                assert _database_state(j.runtime) == before
            with j.runtime.repository._connect() as db:
                db.execute("UPDATE mainline_runs SET snapshot_json=? WHERE stage_key='field_seeds.2'", (saved,))
            j.fail("claim-2")
            before = _database_state(j.runtime)
            assert (await j.send(claim, "claim-2")).code == "PERSISTENCE_ERROR"
            assert _database_state(j.runtime) == before
            j.repair()
            assert (await j.send(claim, "claim-2")).ok
            assert (await j.send("开始药畦换种主线 药畦入铺", "stage-3")).ok
            await j.next_day()
            assert (await j.send("接取委托 止血草供应", "accept")).ok
            original = _inventory(j.runtime)
            assert (await j.send("交付委托 止血草供应", "deliver")).ok
            assert original["item.herb.blood_grass"] - _inventory(j.runtime)["item.herb.blood_grass"] == 3
            await j.restart()
            content = j.runtime.repository.content
            records = dict(content._records)
            for key, row in list(records.items()):
                if key[1].startswith("field_seeds."):
                    records[key] = {**row, "status": "locked"}
            j.runtime.repository.content = replace(content, _records=records)
            final_command = "领取药畦换种主线奖励 药畦入铺"
            results = await asyncio.gather(j.send(final_command, "final-a"), j.send(final_command, "final-b"))
            assert all(result.ok for result in results)
            assert sum(not result.data["idempotent_replay"] for result in results) == 1
            before = _database_state(j.runtime)
            assert (await j.send(final_command, "final-a")).data["idempotent_replay"]
            assert _database_state(j.runtime) == before
            j.runtime.repository.content = content
            assert all(row["status"] == "claimed" for row in (await j.send("药畦换种主线")).data["stages"])
            assert "药畦换种主线" in (await j.send("修仙帮助 生活")).message
        finally:
            await j.runtime.close()
    asyncio.run(run())


@pytest.mark.parametrize("damage", ["plan", "quantity", "source", "empty", "extra", "consumer"])
def test_rice_story_production_source_and_consumer_validation(damage):
    def mutate(records):
        source = records["mainline", "rice_table.2"]["objectives"][0]["crop_source"]
        if damage == "plan":
            source["plan_keys"] = ["missing"]
        elif damage == "quantity":
            records["recipe", "recipe.food.cloud_rice_meal"]["inputs"]["item.grain.cloud_rice"] = 20
        elif damage == "source":
            source["crop_key"] = "crop.spirit_leaf"
        elif damage == "empty":
            source["plan_keys"] = []
        elif damage == "extra":
            source["client_amount"] = 50
        else:
            records["livelihood", "town_commission.rice_hospitality"]["inputs"][0]["item_key"] = "item.missing"
    with pytest.raises(ContentError):
        mainline_definitions(change_content(mutate), story_key="story.mainline.rice_table")


@pytest.mark.parametrize("adapter,plan,hours,care", [("onebot.v11", "精耕", 6, 3), ("qq.official", "缓养", 10, 1)])
def test_rice_table_public_crop_cooking_recovery_and_delivery(tmp_path, adapter, plan, hours, care):
    async def run():
        j = FieldJourney(_copy_content(tmp_path), adapter)
        try:
            await starter(j.runtime, adapter=adapter, path="辅修 烹饪")
            before = _database_state(j.runtime)
            assert (await j.send("开始云稻炊香主线 稻畦起穗")).code == "MAINLINE_REQUIREMENT_MISSING"
            assert (await j.send("开始云稻炊香主线 稻畦起穗 多余参数")).code == "INVALID_MAINLINE_COMMAND"
            assert _database_state(j.runtime) == before
            # Realm/funds/reputation are established growth; all seed/food evidence
            # comes from real public producers below.
            with j.runtime.repository._connect() as db:
                db.execute("UPDATE players SET realm_layer=2, spirit_stones=1000")
                db.execute("INSERT INTO player_reputations(player_id, local_json, service_reputation, updated_at) "
                           "SELECT id, ?, 0, ? FROM players", (json.dumps({"local.xuantian.new_town": 60}), j.clock.value.isoformat()))
            await j.move("青石镇")
            assert (await j.send("租住居所 灵圃小院")).ok
            assert (await j.send("开始云稻炊香主线 稻畦起穗", "rice-stage-1")).ok
            before = _database_state(j.runtime)
            assert not (await j.send("灵田播种 云纹稻 1 缓养", "no-seed")).ok
            assert _database_state(j.runtime) == before
            assert (await j.send("灵田播种 止血草 1 精耕", "seed-source")).ok
            for _ in range(2):
                assert (await j.send("灵田维护 1")).ok
            j.clock.advance(hours=4)
            assert (await j.send("灵田收获 1")).data["harvest"]["item.grain.cloud_rice"] == 1
            assert (await j.send(f"灵田播种 云纹稻 1 {plan}", "rice-plant")).ok
            before = _database_state(j.runtime)
            assert (await j.send(f"灵田播种 云纹稻 1 {plan}", "rice-plant")).data["idempotent_replay"]
            other = "缓养" if plan == "精耕" else "精耕"
            assert (await j.send(f"灵田播种 云纹稻 1 {other}", "rice-plant")).code == "OPERATION_CONFLICT"
            assert _database_state(j.runtime) == before
            for _ in range(care):
                assert (await j.send("灵田维护 1")).ok
            j.clock.advance(hours=hours)
            await j.restart()
            original = _inventory(j.runtime)
            harvested = await j.send("灵田收获 1", "rice-harvest")
            assert harvested.ok
            assert _inventory(j.runtime)["item.grain.cloud_rice"] == original.get("item.grain.cloud_rice", 0) + harvested.data["harvest"]["item.grain.cloud_rice"]
            first = await j.send("领取云稻炊香主线奖励 稻畦起穗", "rice-claim-1")
            assert first.ok
            await j.render(first, "开始云稻炊香主线 rice_table.2", keyboard=True)
            second = await j.send(first.actions[0].command, "rice-stage-2")
            assert second.ok
            await j.render(second, "开始生产 云纹灵米饭")
            good = next(f"rice-cook-{i}" for i in range(200) if random_quality_bp(f"rice-cook-{i}") == 1000)
            before_inventory = _inventory(j.runtime)
            started = await j.send("开始生产 云纹灵米饭", good)
            assert started.ok, started.message
            assert before_inventory["item.grain.cloud_rice"] - _inventory(j.runtime)["item.grain.cloud_rice"] == 3
            j.clock.advance(seconds=30)
            await j.restart()
            made = await j.send("领取生产", "rice-cooked")
            assert made.ok and made.data["success"]
            claim = "领取云稻炊香主线奖励 新米开甑"
            before = _database_state(j.runtime)
            assert (await j.send(claim)).code == "MAINLINE_OBJECTIVES_INCOMPLETE"
            assert _database_state(j.runtime) == before
            ate = await j.send("使用物品 云纹灵米饭 精力", "eat-rice")
            assert ate.ok, ate.message
            assert _inventory(j.runtime)["item.food.cloud_rice_meal"] == 1
            j.fail("rice-claim-2")
            before = _database_state(j.runtime)
            assert (await j.send(claim, "rice-claim-2")).code == "PERSISTENCE_ERROR"
            assert _database_state(j.runtime) == before
            j.repair()
            assert (await j.send(claim, "rice-claim-2")).ok
            before = _database_state(j.runtime)
            assert (await j.send(claim, "rice-claim-2")).data["idempotent_replay"]
            assert _database_state(j.runtime) == before
            assert (await j.send("开始云稻炊香主线 一饭留客", "rice-stage-3")).ok
            await j.next_day()
            assert (await j.send("接取委托 云饭待客", "rice-accept")).ok
            j.fail("rice-deliver")
            before = _database_state(j.runtime)
            assert (await j.send("交付委托 云饭待客", "rice-deliver")).code == "PERSISTENCE_ERROR"
            assert _database_state(j.runtime) == before
            j.repair()
            assert (await j.send("交付委托 云饭待客", "rice-deliver")).ok
            assert _inventory(j.runtime).get("item.food.cloud_rice_meal", 0) == 0
            await j.restart()
            command = "领取云稻炊香主线奖励 一饭留客"
            final = await j.send(command, "rice-final")
            assert final.ok
            before = _database_state(j.runtime)
            assert (await j.send(command, "rice-final")).data["idempotent_replay"]
            assert (await j.send("交付委托 云饭待客", "rice-deliver")).data["idempotent_replay"]
            assert _database_state(j.runtime) == before
            assert all(row["status"] == "claimed" for row in (await j.send("云稻炊香主线")).data["stages"])
        finally:
            await j.runtime.close()
    asyncio.run(run())
