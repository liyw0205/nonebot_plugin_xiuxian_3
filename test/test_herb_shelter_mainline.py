from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from urllib.parse import quote

import pytest

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.adventures.mainline import HERB_SHELTER_STORY_KEY, mainline_definitions
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle, ContentError
from nonebot_plugin_xiuxian_3.xiuxian.livelihood.rules import town_commission_definitions
from nonebot_plugin_xiuxian_3.xiuxian.production.rules import random_quality_bp
from test_companion_old_trail_mainline import _database_state, _inventory
from test_mainline_vertical_slice import MutableClock, _copy_content
from test_wilderness_idle import starter


@pytest.mark.parametrize("damage", ["body", "missing_source", "duplicate_source", "unrelated_source", "short_yield", "commission_item", "duplicate_input", "wrong_evidence", "stale_acceptance", "closed_location", "missing_codex"])
def test_herb_shelter_requires_complete_story_sources_and_consumers(tmp_path, damage):
    data = _copy_content(tmp_path)
    bundle = ContentBundle.load(data)
    stages = mainline_definitions(bundle, story_key=HERB_SHELTER_STORY_KEY)
    assert [stage.key for stage in stages] == [f"herb_shelter.{i}" for i in (1, 2, 3)]
    assert all(len(stage.body) >= 80 and stage.actions and stage.retry_message for stage in stages)
    commission = town_commission_definitions(bundle)["town_commission.shelter_medicine"]
    assert commission.inputs == {"item.pill.healing_low": 1}
    if damage in {"body", "missing_source", "duplicate_source", "unrelated_source", "wrong_evidence", "stale_acceptance", "closed_location", "missing_codex"}:
        path = data / "剧情/主线.json"
        document = json.loads(path.read_text(encoding="utf-8"))
        stage = next(row for row in document["records"] if row["key"] == "herb_shelter.2")
        objective = stage["objectives"][0]
        if damage == "body":
            stage["body"] = "只有标题"
        elif damage == "missing_source":
            objective.pop("additional_route_keys")
        elif damage == "duplicate_source":
            objective["additional_route_keys"] = [objective["route_key"]]
        elif damage == "unrelated_source":
            objective["additional_route_keys"] = ["idle.ironwood_gather"]
        elif damage == "wrong_evidence":
            stage["objectives"][1]["delivery_evidence"]["inputs"] = {"item.herb.blood_grass": 1}
        elif damage == "stale_acceptance":
            stage["objectives"][1]["delivery_evidence"]["fresh_acceptance"] = False
        elif damage == "closed_location":
            stage["objectives"][1]["delivery_evidence"]["location_key"] = "location.missing"
        else:
            final = next(row for row in document["records"] if row["key"] == "herb_shelter.3")
            final["first_clear_reward"]["codex.story.missing"] = 1
    elif damage == "short_yield":
        path = data / "奖励/奖励.json"
        document = json.loads(path.read_text(encoding="utf-8"))
        pool = next(row for row in document["records"] if row["key"] == "reward_pool.idle.herb_vale_gather")
        pool["outcomes"][0]["rewards"]["item.herb.blood_grass"] = 1
    else:
        path = data / "生活/生活.json"
        document = json.loads(path.read_text(encoding="utf-8"))
        row = next(row for row in document["records"] if row["key"] == "town_commission.shelter_medicine")
        if damage == "commission_item":
            row["inputs"][0]["item_key"] = "item.missing"
        else:
            row["inputs"].append(dict(row["inputs"][0]))
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ContentError):
        mainline_definitions(ContentBundle.load(data), story_key=HERB_SHELTER_STORY_KEY)


@pytest.mark.parametrize("adapter,choice", [("onebot.v11", "扶徒归棚"), ("qq.official", "辨叶上坡")])
def test_herb_shelter_public_gather_brew_deliver_restart_and_atomic_replay(tmp_path, adapter, choice, monkeypatch):
    async def run():
        data = _copy_content(tmp_path)
        clock = MutableClock()
        runtime = create_runtime(data_dir=data, clock=clock, adapters=(adapter,))
        sequence = 0

        async def send(command, operation="", user="gatherer"):
            nonlocal sequence
            sequence += 1
            return await runtime.dispatch(CommandContext(
                adapter=adapter, user_id=user, operation_id=operation or f"shelter-{sequence}",
                capabilities=("text", "markdown", "keyboard"),
            ), command)

        async def move(destination):
            result = await send(f"前往 {destination}")
            assert result.code == "TRAVEL_STARTED", result.message
            clock.advance(minutes=3)
            assert (await send("结算移动")).code == "TRAVEL_COMPLETED"

        async def restart():
            nonlocal runtime
            await runtime.close()
            runtime = create_runtime(data_dir=data, clock=clock, adapters=(adapter,))
            await runtime.repository.initialize()

        async def gather(command, hours, operation):
            assert (await send(command, operation)).code == "IDLE_STARTED"
            clock.advance(hours=hours)
            result = await send("领取挂机", f"{operation}-claim")
            assert result.code == "IDLE_CLAIMED" and not result.data["fallback"], result.message
            return result

        def fail_on(operation):
            with runtime.repository._connect() as connection:
                connection.execute(
                    "CREATE TRIGGER fail_shelter BEFORE INSERT ON operations "
                    f"WHEN NEW.operation_id='{operation}' BEGIN SELECT RAISE(ABORT, 'forced shelter failure'); END"
                )

        def repair():
            with runtime.repository._connect() as connection:
                connection.execute("DROP TRIGGER fail_shelter")

        async def corrupt_receipt(table, key, identifier, field, value, command, operation):
            with runtime.repository._connect() as connection:
                original = connection.execute(f"SELECT {field} FROM {table} WHERE {key}=?", (identifier,)).fetchone()[0]
                connection.execute(f"UPDATE {table} SET {field}=? WHERE {key}=?", (value, identifier))
            before = _database_state(runtime)
            result = await send(command, operation)
            assert result.code == "PERSISTENCE_ERROR", (operation, result.code, result.message)
            assert _database_state(runtime) == before
            with runtime.repository._connect() as connection:
                connection.execute(f"UPDATE {table} SET {field}=? WHERE {key}=?", (original, identifier))

        good = next(f"shelter-brew-{i}" for i in range(100) if random_quality_bp(f"shelter-brew-{i}") == 1000)
        try:
            await starter(runtime, adapter=adapter, path="辅修 炼丹")
            before = _database_state(runtime)
            assert (await send("开始百草坡药棚主线 雨棚辨药", "denied")).code == "MAINLINE_REQUIREMENT_MISSING"
            assert (await send("开始百草坡药棚主线 不存在", "invalid")).code == "INVALID_MAINLINE_COMMAND"
            assert _database_state(runtime) == before
            with runtime.repository._connect() as connection:
                connection.execute("UPDATE players SET realm_layer=2")
            before = _database_state(runtime)
            assert (await send("开始挂机 百草坡采药 扶徒归棚", "wrong-place")).code == "IDLE_REQUIREMENT_MISSING"
            assert _database_state(runtime) == before
            with runtime.repository._connect() as connection:
                preview_state = tuple(tuple(row) for row in connection.execute("SELECT * FROM players"))
                preview_operations = connection.execute("SELECT COUNT(*) FROM operations").fetchone()[0]
            for command in ("百草坡药棚主线", "挂机预览 百草坡采药", "生产预览 低阶疗伤丹"):
                assert (await send(command)).ok
            with runtime.repository._connect() as connection:
                assert tuple(tuple(row) for row in connection.execute("SELECT * FROM players")) == preview_state
                assert connection.execute("SELECT COUNT(*) FROM operations").fetchone()[0] == preview_operations
            await move("百草坡")
            await gather(f"开始挂机 百草坡采药 {choice}", 4, "old-basket")
            clock.advance(days=1)
            assert (await send("恢复状态")).ok
            first = await send("开始百草坡药棚主线 雨棚辨药", "stage-1")
            assert first.code == "MAINLINE_STARTED" and not first.actions
            before = _database_state(runtime)
            assert (await send("开始百草坡药棚主线 雨棚辨药", "stage-1")).data["idempotent_replay"]
            assert (await send("开始百草坡药棚主线 丹火济伤", "stage-1")).code == "OPERATION_CONFLICT"
            assert (await send("领取百草坡药棚主线奖励 雨棚辨药", "old-story")).code == "MAINLINE_OBJECTIVES_INCOMPLETE"
            assert _database_state(runtime) == before
            assert (await send(f"开始挂机 百草坡采药 {choice}", "cancel-start")).ok
            assert (await send("取消挂机", "cancel")).code == "IDLE_CANCELLED"
            before = _database_state(runtime)
            assert (await send("领取百草坡药棚主线奖励 雨棚辨药", "cancel-story")).code == "MAINLINE_OBJECTIVES_INCOMPLETE"
            assert _database_state(runtime) == before
            assert (await send(f"开始挂机 百草坡采药 {choice}", "late-start")).ok
            before = _database_state(runtime)
            assert (await send("领取挂机", "early")).code == "IDLE_CLAIM_TOO_EARLY"
            assert _database_state(runtime) == before
            clock.advance(hours=29)
            assert (await send("领取挂机", "late")).data["fallback"]
            before = _database_state(runtime)
            assert (await send("领取百草坡药棚主线奖励 雨棚辨药", "late-story")).code == "MAINLINE_OBJECTIVES_INCOMPLETE"
            assert _database_state(runtime) == before
            clock.advance(days=1)
            assert (await send("恢复状态")).ok
            original = _inventory(runtime)
            assert (await send(f"开始挂机 百草坡采药 {choice}", "basket")).ok
            with runtime.repository._connect() as connection:
                frozen = json.loads(connection.execute("SELECT snapshot_json FROM idle_assignments ORDER BY id DESC LIMIT 1").fetchone()[0])
            clock.advance(hours=4)
            await restart()
            full = await send("领取挂机", "basket-claim")
            assert full.code == "IDLE_CLAIMED" and full.data["reward"] == frozen["full_reward"]
            assert _inventory(runtime)["item.herb.blood_grass"] - original.get("item.herb.blood_grass", 0) == full.data["reward"]["item.herb.blood_grass"]
            with runtime.repository._connect() as connection:
                old_receipt = connection.execute("SELECT result_json FROM operations WHERE operation_id='old-basket-claim'").fetchone()[0]
            await corrupt_receipt("operations", "operation_id", "basket-claim", "result_json", old_receipt, "领取百草坡药棚主线奖励 雨棚辨药", "forged-idle")
            broken_reward = dict(frozen)
            broken_reward.pop("full_reward")
            await corrupt_receipt("idle_assignments", "assignment_id", full.data["assignment_id"], "snapshot_json", json.dumps(broken_reward), "领取百草坡药棚主线奖励 雨棚辨药", "missing-idle-reward")
            first_claim = await send("领取百草坡药棚主线奖励 雨棚辨药", "claim-1")
            assert first_claim.code == "MAINLINE_REWARD_CLAIMED" and len(first_claim.actions) == 1
            assert first_claim.actions[0].command == "开始百草坡药棚主线 herb_shelter.2" and first_claim.actions[0].enter
            second = await send(first_claim.actions[0].command, "stage-2")
            assert second.code == "MAINLINE_STARTED", second.message
            with runtime.repository._connect() as connection:
                saved_inventory = connection.execute("SELECT inventory_json FROM players").fetchone()[0]
                no_rice = json.loads(saved_inventory)
                no_rice.pop("item.food.coarse_spirit_rice", None)
                connection.execute("UPDATE players SET inventory_json=?", (json.dumps(no_rice),))
            before = _database_state(runtime)
            assert (await send("开始生产 低阶疗伤丹", "no-rice")).code == "MATERIAL_INSUFFICIENT"
            assert _database_state(runtime) == before
            with runtime.repository._connect() as connection:
                connection.execute("UPDATE players SET inventory_json=?", (saved_inventory,))
                saved_durability = connection.execute("SELECT durability_json FROM players").fetchone()[0]
                worn = json.loads(saved_durability)
                worn["item.tool.basic_furnace"] = 0
                connection.execute("UPDATE players SET durability_json=?", (json.dumps(worn),))
            before = _database_state(runtime)
            assert (await send("开始生产 低阶疗伤丹", "worn-furnace")).code == "TOOL_DURABILITY_INSUFFICIENT"
            assert _database_state(runtime) == before
            with runtime.repository._connect() as connection:
                connection.execute("UPDATE players SET durability_json=?", (saved_durability,))
            await restart()
            resumed = await send("百草坡药棚主线")
            current = next(item for item in resumed.data["stages"] if item["key"] == "herb_shelter.2")
            assert current["actions"] == second.data["actions"] and current["body"] in second.message
            assert current["retry_message"] in resumed.message and "交付委托" in resumed.message
            with runtime.repository._connect() as connection:
                snapshot = connection.execute(
                    "SELECT snapshot_json FROM mainline_runs WHERE stage_key='herb_shelter.2'"
                ).fetchone()[0]
            for index, invalid in enumerate((None, [], [True], ["idle.spring_glean"] * 2, ["idle.herb_vale_gather"])):
                broken = json.loads(snapshot)
                broken["definition"]["objectives"][0]["additional_route_keys"] = invalid
                with runtime.repository._connect() as connection:
                    connection.execute(
                        "UPDATE mainline_runs SET snapshot_json=? WHERE stage_key='herb_shelter.2'",
                        (json.dumps(broken),),
                    )
                before = _database_state(runtime)
                assert (await send("领取百草坡药棚主线奖励 丹火济伤", f"bad-sources-{index}")).code == "PERSISTENCE_ERROR"
                assert (await send("百草坡药棚主线", f"bad-status-{index}")).code == "PERSISTENCE_ERROR"
                assert _database_state(runtime) == before
            with runtime.repository._connect() as connection:
                connection.execute(
                    "UPDATE mainline_runs SET snapshot_json=? WHERE stage_key='herb_shelter.2'", (snapshot,),
                )
            await corrupt_receipt("mainline_runs", "stage_key", "herb_shelter.2", "snapshot_json", snapshot.replace('"definition":', '"definition": {}, "definition":', 1), "百草坡药棚主线", "duplicate-story-json")
            # Acquire both recipe inputs through public producers, not inventory fixtures.
            for index in range(8):
                if _inventory(runtime).get("item.herb.blood_grass", 0) >= 12:
                    break
                clock.advance(days=1)
                assert (await send("恢复状态")).ok
                await gather("开始挂机 百草坡采药 扶徒归棚", 4, f"herbs-{index}")
            await move("近郊")
            await move("青石镇")
            await move("灵泉谷")
            rice_before = _inventory(runtime).get("item.food.coarse_spirit_rice", 0)
            rice = await gather("开始挂机 灵泉谷拾穗", 4, "rice")
            assert _inventory(runtime)["item.food.coarse_spirit_rice"] - rice_before == rice.data["reward"]["item.food.coarse_spirit_rice"]
            failed_operation = next(f"shelter-fail-{i}" for i in range(100) if random_quality_bp(f"shelter-fail-{i}") == 0)
            assert (await send("开始生产 低阶疗伤丹", failed_operation)).code == "PRODUCTION_STARTED"
            clock.advance(seconds=30)
            failed = await send("领取生产", "failed-brew-claim")
            assert failed.code == "PRODUCTION_COMPLETED" and not failed.data["success"]
            before = _database_state(runtime)
            assert (await send("领取百草坡药棚主线奖励 丹火济伤", "failed-brew-story")).code == "MAINLINE_OBJECTIVES_INCOMPLETE"
            assert _database_state(runtime) == before
            original = _inventory(runtime)
            started = await send("开始生产 低阶疗伤丹", good)
            assert started.code == "PRODUCTION_STARTED", started.message
            assert original["item.herb.blood_grass"] - _inventory(runtime)["item.herb.blood_grass"] == 2
            assert original["item.food.coarse_spirit_rice"] - _inventory(runtime)["item.food.coarse_spirit_rice"] == 1
            clock.advance(seconds=30)
            await restart()
            brewed = await send("领取生产", "brew-claim")
            assert brewed.code == "PRODUCTION_COMPLETED" and brewed.data["success"], brewed.message
            await corrupt_receipt("production_orders", "order_id", brewed.data["order_id"], "operation_id", "missing-brew", "领取百草坡药棚主线奖励 丹火济伤", "forged-brew")
            before = _database_state(runtime)
            assert (await send("领取生产", "brew-claim")).data["idempotent_replay"]
            missing = await send("领取百草坡药棚主线奖励 丹火济伤", "brew-only")
            assert missing.code == "MAINLINE_OBJECTIVES_INCOMPLETE" and "药棚救治" in missing.message
            assert _database_state(runtime) == before
            await move("青石镇")
            clock.value = (clock.value + timedelta(days=1)).replace(hour=16, minute=0, second=0)
            board = await send("城镇委托")
            assert "药棚救治" in board.message
            before = _database_state(runtime)
            assert (await send("接取委托 药棚救治", "medicine-after-deadline")).code == "COMMISSION_EXPIRED"
            assert _database_state(runtime) == before
            clock.value = (clock.value + timedelta(days=1)).replace(hour=0, minute=0, second=0)
            accepted = await send("接取委托 药棚救治", "medicine-accept")
            assert accepted.code == "COMMISSION_ACCEPTED", accepted.message
            original = _inventory(runtime)
            fail_on("medicine-deliver")
            before = _database_state(runtime)
            assert (await send("交付委托 药棚救治", "medicine-deliver")).code == "PERSISTENCE_ERROR"
            assert _database_state(runtime) == before
            repair()
            delivered = await send("交付委托 药棚救治", "medicine-deliver")
            assert delivered.code == "COMMISSION_DELIVERED", delivered.message
            assert original["item.pill.healing_low"] - _inventory(runtime).get("item.pill.healing_low", 0) == 1
            before = _database_state(runtime)
            assert (await send("交付委托 药棚救治", "medicine-deliver")).data["idempotent_replay"]
            assert (await send("交付委托 止血草供应", "medicine-deliver")).code == "OPERATION_CONFLICT"
            assert _database_state(runtime) == before
            for field, value in (("accept_operation_id", "missing-accept"), ("deliver_operation_id", "missing-deliver"), ("snapshot_json", "{}")):
                await corrupt_receipt("town_commission_claims", "claim_id", accepted.data["claim_id"], field, value, "领取百草坡药棚主线奖励 丹火济伤", f"bad-medicine-{field}")
            with runtime.repository._connect() as connection:
                receipt = json.loads(connection.execute("SELECT result_json FROM operations WHERE operation_id='medicine-deliver'").fetchone()[0])
            receipt["player"]["player_id"] = "someone-else"
            await corrupt_receipt("operations", "operation_id", "medicine-deliver", "result_json", json.dumps(receipt), "领取百草坡药棚主线奖励 丹火济伤", "foreign-medicine")
            fail_on("claim-2")
            before = _database_state(runtime)
            assert (await send("领取百草坡药棚主线奖励 丹火济伤", "claim-2")).code == "PERSISTENCE_ERROR"
            assert _database_state(runtime) == before
            repair()
            second_claim = await send("领取百草坡药棚主线奖励 丹火济伤", "claim-2")
            assert second_claim.code == "MAINLINE_REWARD_CLAIMED", second_claim.message
            assert (await send("接取委托 止血草供应", "old-herb-accept")).code == "COMMISSION_ACCEPTED"
            assert (await send(second_claim.actions[0].command, "stage-3")).ok
            assert (await send("交付委托 止血草供应", "old-herb-deliver")).code == "COMMISSION_DELIVERED"
            before = _database_state(runtime)
            assert (await send("领取百草坡药棚主线奖励 留根归铺", "old-herb-story")).code == "MAINLINE_OBJECTIVES_INCOMPLETE"
            assert _database_state(runtime) == before
            clock.advance(days=1)
            assert (await send("接取委托 止血草供应", "herb-accept")).code == "COMMISSION_ACCEPTED"
            original = _inventory(runtime)
            # Closure blocks new work but preserves this accepted order and frozen story.
            for relative, keys in (("剧情/主线.json", {"herb_shelter.1", "herb_shelter.2", "herb_shelter.3"}), ("生活/生活.json", {"town_commission.herb_supply", "town_commission.shelter_medicine"}), ("图鉴/条目.json", {"codex.story.herb_shelter"})):
                path = data / relative
                document = json.loads(path.read_text(encoding="utf-8"))
                for item in document["records"]:
                    if item["key"] in keys:
                        item["status"] = "locked"
                        if "body" in item:
                            item["body"] = "关闭后的新文案不应覆盖已冻结的行动说明。" * 5
                path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
            await restart()
            assert (await send("开始百草坡药棚主线 雨棚辨药", "closed-stage")).code == "CONTENT_CLOSED"
            assert (await send("接取委托 止血草供应", "closed-order")).code == "LIVELIHOOD_CONTENT_CLOSED"
            resumed = await send("百草坡药棚主线")
            assert resumed.ok and "关闭后的新文案" not in resumed.message
            deliveries = await asyncio.gather(send("交付委托 止血草供应", "herb-deliver"), send("交付委托 止血草供应", "herb-deliver-other"))
            assert sorted(result.code for result in deliveries) == ["COMMISSION_ALREADY_DELIVERED", "COMMISSION_DELIVERED"], [(result.code, result.message) for result in deliveries]
            winner = next(operation for operation, result in zip(("herb-deliver", "herb-deliver-other"), deliveries) if result.ok)
            before = _database_state(runtime)
            assert (await send("交付委托 止血草供应", winner)).data["idempotent_replay"]
            assert _database_state(runtime) == before
            assert original["item.herb.blood_grass"] - _inventory(runtime)["item.herb.blood_grass"] == 3
            await restart()
            fail_on("claim-3-rollback")
            before = _database_state(runtime)
            assert (await send("领取百草坡药棚主线奖励 留根归铺", "claim-3-rollback")).code == "PERSISTENCE_ERROR"
            assert _database_state(runtime) == before
            repair()
            claims = await asyncio.gather(
                send("领取百草坡药棚主线奖励 留根归铺", "claim-3a"),
                send("领取百草坡药棚主线奖励 留根归铺", "claim-3b"),
            )
            assert all(result.ok for result in claims)
            assert sum(not result.data["idempotent_replay"] for result in claims) == 1
            before = _database_state(runtime)
            assert (await send("领取百草坡药棚主线奖励 留根归铺", "claim-3a")).data["idempotent_replay"]
            assert _database_state(runtime) == before
            with runtime.repository._connect() as connection:
                assert connection.execute("SELECT COUNT(*) FROM codex_entries WHERE entry_key='codex.story.herb_shelter'").fetchone()[0] == 1
                assert connection.execute("SELECT COUNT(*) FROM activity_events WHERE event_key='story.mainline.herb_shelter:herb_shelter.3'").fetchone()[0] == 1
            status = await send("百草坡药棚主线")
            assert all(stage["status"] == "claimed" for stage in status.data["stages"])
            for category in ("探索", "生活"):
                help_result = await send(f"修仙帮助 {category}")
                assert "百草坡药棚主线" in help_result.message
            from nonebot_plugin_xiuxian_3.adapters.message.markdown import _qq_command_links, markdown_to_text

            converted = _qq_command_links(second.message, command_prefix="!")
            assert quote("!交付委托 药棚救治", safe="") in converted and "enter=false" in converted
            assert "command:" not in markdown_to_text(second.message)
            from nonebot_plugin_xiuxian_3.adapters.message import markdown

            class Bot:
                async def send(self, event, message, **kwargs):
                    self.message = message
                    return {"id": "reply"}

            monkeypatch.setattr(markdown, "qq_markdown_segment", lambda body, command_prefix="": markdown._qq_command_links(body, command_prefix=command_prefix))
            bot = Bot()
            rendered = await markdown.send_markdown_message(bot, object(), resumed.message, capabilities=("markdown",), command_prefix="!")
            assert rendered.sent_format == "markdown" and "enter=false" in bot.message
            rendered = await markdown.send_markdown_message(bot, object(), resumed.message)
            assert rendered.sent_format == "text" and "command:" not in bot.message and "PERSISTENCE_ERROR" not in bot.message
        finally:
            await runtime.close()
    asyncio.run(run())
