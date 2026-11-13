from __future__ import annotations

import asyncio
import json
from pathlib import Path
from urllib.parse import quote

import pytest

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.adventures.mainline import SPRING_SUPPER_STORY_KEY, mainline_definitions
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle, ContentError
from nonebot_plugin_xiuxian_3.xiuxian.production.rules import random_quality_bp
from test_companion_old_trail_mainline import _database_state, _inventory
from test_mainline_vertical_slice import MutableClock, _copy_content
from test_wilderness_idle import starter


@pytest.mark.parametrize("adapter,resource", [("onebot.v11", "体力"), ("qq.official", "精力")])
def test_spring_supper_public_source_cooking_choice_restart_and_rollback(tmp_path: Path, adapter: str, resource: str) -> None:
    async def run() -> None:
        data_dir = _copy_content(tmp_path)
        clock = MutableClock()
        runtime = create_runtime(data_dir=data_dir, clock=clock, adapters=(adapter,))

        async def send(command: str, operation: str = ""):
            return await runtime.dispatch(
                CommandContext(adapter=adapter, user_id="gatherer", operation_id=operation), command,
            )

        async def move(destination: str) -> None:
            started = await send(f"前往 {destination}")
            assert started.code == "TRAVEL_STARTED", started.message
            clock.advance(minutes=3)
            assert (await send("结算移动")).code == "TRAVEL_COMPLETED"

        def trigger(operation: str) -> None:
            with runtime.repository._connect() as connection:
                connection.execute(
                    "CREATE TRIGGER fail_supper BEFORE INSERT ON operations "
                    f"WHEN NEW.operation_id='{operation}' BEGIN SELECT RAISE(ABORT, 'forced supper failure'); END"
                )

        def untrigger() -> None:
            with runtime.repository._connect() as connection:
                connection.execute("DROP TRIGGER fail_supper")

        try:
            await starter(runtime, adapter=adapter, path="辅修 烹饪")
            before = _database_state(runtime)
            assert (await send("开始泉边炊烟主线 泉畦拾穗", "denied")).code == "MAINLINE_REQUIREMENT_MISSING"
            assert _database_state(runtime) == before
            # Reuse established realm growth; all travel, materials and actions remain public.
            with runtime.repository._connect() as connection:
                connection.execute("UPDATE players SET realm_layer=2")
            bonded = await send("结缘灵兽 木鼠", "bond")
            assert bonded.code == "COMPANION_BONDED", bonded.message
            instance = bonded.data["instance_id"]
            for index in range(_inventory(runtime)["item.food.coarse_spirit_rice"]):
                assert (await send(f"喂养灵兽 {instance}", f"consume-gift-{index}")).code == "COMPANION_FED"
            assert _inventory(runtime).get("item.food.coarse_spirit_rice", 0) == 0
            first = await send("开始泉边炊烟主线 泉畦拾穗", "start-1")
            assert first.code == "MAINLINE_STARTED", first.message
            assert "阿禾" in first.message and "四小时" in first.message
            assert not first.actions
            await move("青石镇")
            await move("灵泉谷")
            preview = await send("挂机预览 灵泉谷拾穗")
            assert preview.data["routes"][0]["ready"]
            assert (await send("开始挂机 灵泉谷拾穗", "cancel-start")).code == "IDLE_STARTED"
            assert (await send("取消挂机", "cancel")).code == "IDLE_CANCELLED"
            assert (await send("领取泉边炊烟主线奖励 泉畦拾穗", "cancel-claim")).code == "MAINLINE_OBJECTIVES_INCOMPLETE"
            assert (await send("开始挂机 灵泉谷拾穗", "late-start")).code == "IDLE_STARTED"
            assert (await send("领取挂机", "too-early")).code == "IDLE_CLAIM_TOO_EARLY"
            clock.advance(hours=29)
            late = await send("领取挂机", "late")
            assert late.data["fallback"]
            assert (await send("领取泉边炊烟主线奖励 泉畦拾穗", "late-claim")).code == "MAINLINE_OBJECTIVES_INCOMPLETE"
            assert (await send(f"喂养灵兽 {instance}", "consume-late-rice")).code == "COMPANION_FED"
            assert _inventory(runtime).get("item.food.coarse_spirit_rice", 0) == 0
            assert (await send("开始挂机 灵泉谷拾穗", "full-start")).code == "IDLE_STARTED"
            clock.advance(hours=4)
            await runtime.close()
            runtime = create_runtime(data_dir=data_dir, clock=clock, adapters=(adapter,))
            full = await send("领取挂机", "full")
            assert full.code == "IDLE_CLAIMED" and not full.data["fallback"]
            assert _inventory(runtime)["item.food.coarse_spirit_rice"] == full.data["reward"]["item.food.coarse_spirit_rice"]
            first_claim = await send("领取泉边炊烟主线奖励 泉畦拾穗", "claim-1")
            assert first_claim.code == "MAINLINE_REWARD_CLAIMED"
            assert len(first_claim.actions) == 1 and first_claim.actions[0].enter
            assert (await send("开始生产 灵米饭", "old-pot")).code == "PRODUCTION_STARTED"
            second = await send(first_claim.actions[0].command, "start-2")
            assert second.code == "MAINLINE_STARTED", second.message
            clock.advance(seconds=15)
            old = await send("领取生产", "old-cook")
            assert old.code == "PRODUCTION_COMPLETED", old.message
            assert (await send(f"使用物品 灵米饭 {resource}", "old-meal")).ok
            assert (await send("领取泉边炊烟主线奖励 一饭暖途", "old-claim")).code == "MAINLINE_OBJECTIVES_INCOMPLETE"
            before = _database_state(runtime)
            missing = await send("开始生产 灵米饭", "cook")
            assert missing.code == "MATERIAL_INSUFFICIENT", missing.message
            assert _database_state(runtime) == before
            clock.advance(days=1)
            assert (await send("开始挂机 灵泉谷拾穗", "resupply")).code == "IDLE_STARTED"
            clock.advance(hours=4)
            assert (await send("领取挂机", "resupply-claim")).code == "IDLE_CLAIMED"
            trigger("cook")
            before = _database_state(runtime)
            assert (await send("开始生产 灵米饭", "cook")).code == "PERSISTENCE_ERROR"
            assert _database_state(runtime) == before
            untrigger()
            assert (await send("开始生产 灵米饭", "cook")).code == "PRODUCTION_STARTED"
            assert (await send("领取泉边炊烟主线奖励 一饭暖途", "unripe-claim")).code == "MAINLINE_OBJECTIVES_INCOMPLETE"
            assert (await send("领取生产", "cook-claim")).code == "PRODUCTION_NOT_READY"
            clock.advance(seconds=15)
            await runtime.close()
            runtime = create_runtime(data_dir=data_dir, clock=clock, adapters=(adapter,))
            await runtime.repository.initialize()
            trigger("cook-claim")
            before = _database_state(runtime)
            assert (await send("领取生产", "cook-claim")).code == "PERSISTENCE_ERROR"
            assert _database_state(runtime) == before
            untrigger()
            cooked = await send("领取生产", "cook-claim")
            assert cooked.code == "PRODUCTION_COMPLETED", cooked.message
            assert cooked.data["outputs"] == {"item.food.spirit_rice": 2}
            before = _database_state(runtime)
            assert (await send("领取生产", "cook-claim")).data["idempotent_replay"]
            assert _database_state(runtime) == before
            incomplete = await send("领取泉边炊烟主线奖励 一饭暖途", "before-meal")
            assert incomplete.code == "MAINLINE_OBJECTIVES_INCOMPLETE"
            assert "吃灵米饭" in incomplete.message and "新开锅" not in incomplete.message
            before = _database_state(runtime)
            assert not (await send("使用物品 灵米饭 金钱", "bad-choice")).ok
            assert _database_state(runtime) == before
            trigger("eat")
            before = _database_state(runtime)
            assert (await send(f"使用物品 灵米饭 {resource}", "eat")).code == "PERSISTENCE_ERROR"
            assert _database_state(runtime) == before
            untrigger()
            eaten = await send(f"使用物品 灵米饭 {resource}", "eat")
            assert eaten.ok, eaten.message
            assert eaten.data["effect"]["restored"] > 0
            before = _database_state(runtime)
            assert (await send(f"使用物品 灵米饭 {resource}", "eat")).data["idempotent_replay"]
            assert _database_state(runtime) == before
            trigger("claim-2")
            before = _database_state(runtime)
            assert (await send("领取泉边炊烟主线奖励 一饭暖途", "claim-2")).code == "PERSISTENCE_ERROR"
            assert _database_state(runtime) == before
            untrigger()
            claim = await send("领取泉边炊烟主线奖励 一饭暖途", "claim-2")
            assert claim.code == "MAINLINE_REWARD_CLAIMED", claim.message
            assert claim.data["reward"] == {"spirit_stones": 20, "service_reputation": 2}
            before = _database_state(runtime)
            assert (await send("领取泉边炊烟主线奖励 一饭暖途", "claim-again")).data["idempotent_replay"]
            assert _database_state(runtime) == before
            status = await send("泉边炊烟主线")
            assert all(stage["status"] == "claimed" for stage in status.data["stages"])
            help_result = await send("修仙帮助 生活")
            assert "泉边炊烟" in help_result.message and not help_result.actions
            from nonebot_plugin_xiuxian_3.adapters.message.markdown import _qq_command_links, markdown_to_text

            converted = _qq_command_links(second.message, command_prefix="!")
            assert quote("!使用物品 灵米饭 体力", safe="") in converted
            assert quote("!使用物品 灵米饭 精力", safe="") in converted
            assert "enter=false" in converted
            assert "command:" not in markdown_to_text(second.message)
        finally:
            await runtime.close()

    asyncio.run(run())


def test_spring_supper_expired_cooking_recovers_but_zero_restoration_does_not_count(tmp_path: Path) -> None:
    async def run() -> None:
        data_dir = _copy_content(tmp_path)
        recipes_path = data_dir / "生产/配方.json"
        recipes = json.loads(recipes_path.read_text(encoding="utf-8"))
        recipe = next(row for row in recipes["records"] if row["key"] == "recipe.food.spirit_rice")
        recipe["success_threshold_bp"] = 5500
        recipes_path.write_text(json.dumps(recipes, ensure_ascii=False), encoding="utf-8")
        failed_pot = next(f"pot-{i}" for i in range(100) if random_quality_bp(f"pot-{i}") == 0)
        good_pot = next(f"pot-{i}" for i in range(100) if random_quality_bp(f"pot-{i}") == 1000)
        clock = MutableClock()
        runtime = create_runtime(data_dir=data_dir, clock=clock)

        async def send(command: str, operation: str = ""):
            return await runtime.dispatch(
                CommandContext(adapter="onebot.v11", user_id="gatherer", operation_id=operation), command,
            )

        try:
            await starter(runtime, path="辅修 烹饪")
            with runtime.repository._connect() as connection:
                connection.execute("UPDATE players SET realm_layer=2")
            assert (await send("开始泉边炊烟主线 泉畦拾穗", "first")).ok
            for destination in ("青石镇", "灵泉谷"):
                assert (await send(f"前往 {destination}")).code == "TRAVEL_STARTED"
                clock.advance(minutes=3)
                assert (await send("结算移动")).code == "TRAVEL_COMPLETED"
            assert (await send("开始挂机 灵泉谷拾穗", "glean")).ok
            clock.advance(hours=4)
            assert (await send("领取挂机", "grain")).ok
            assert (await send("领取泉边炊烟主线奖励 泉畦拾穗", "first-claim")).ok
            assert (await send("开始泉边炊烟主线 一饭暖途", "second")).ok
            assert (await send("开始生产 灵米饭", failed_pot)).code == "PRODUCTION_STARTED"
            clock.advance(seconds=15)
            failed = await send("领取生产", "burned-rice")
            assert failed.code == "PRODUCTION_COMPLETED" and not failed.data["success"]
            assert failed.data["refunds"] == {"item.food.coarse_spirit_rice": 1}
            before = _database_state(runtime)
            assert (await send("领取生产", "burned-rice")).data["idempotent_replay"]
            assert (await send("领取泉边炊烟主线奖励 一饭暖途", "failed-pot-story")).code == "MAINLINE_OBJECTIVES_INCOMPLETE"
            assert _database_state(runtime) == before
            assert (await send("开始生产 灵米饭", good_pot)).code == "PRODUCTION_STARTED"
            clock.advance(hours=25)
            assert (await send("领取生产", "expired")).code == "ORDER_EXPIRED"
            before = _database_state(runtime)
            assert (await send("领取泉边炊烟主线奖励 一饭暖途", "expired-story")).code == "MAINLINE_OBJECTIVES_INCOMPLETE"
            assert _database_state(runtime) == before
            await runtime.close()
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            recovered = await send("恢复生产", "recover-pot")
            assert recovered.code == "PRODUCTION_RECOVERED" and recovered.data["success"]
            assert recovered.data["outputs"] == {"item.food.spirit_rice": 2}
            before = _database_state(runtime)
            assert (await send("恢复生产", "recover-pot")).data["idempotent_replay"]
            assert _database_state(runtime) == before
            with runtime.repository._connect() as connection:
                snapshot = connection.execute(
                    "SELECT snapshot_json FROM mainline_runs WHERE stage_key='spring_supper.2'"
                ).fetchone()[0]
            for invalid in (-1, True, None, "missing"):
                broken = json.loads(snapshot)
                if invalid == "missing":
                    broken.pop("baseline_production_order_id")
                else:
                    broken["baseline_production_order_id"] = invalid
                with runtime.repository._connect() as connection:
                    connection.execute(
                        "UPDATE mainline_runs SET snapshot_json=? WHERE stage_key='spring_supper.2'",
                        (json.dumps(broken),),
                    )
                before = _database_state(runtime)
                assert (await send("领取泉边炊烟主线奖励 一饭暖途", f"broken-watermark-{invalid}")).code == "PERSISTENCE_ERROR"
                assert _database_state(runtime) == before
            with runtime.repository._connect() as connection:
                connection.execute(
                    "UPDATE mainline_runs SET snapshot_json=? WHERE stage_key='spring_supper.2'", (snapshot,),
                )
            clock.advance(hours=24)
            assert (await send("恢复状态", "rested")).ok
            full_meal = await send("使用物品 灵米饭 体力", "full-meal")
            assert full_meal.ok and full_meal.data["effect"]["restored"] == 0
            before = _database_state(runtime)
            assert (await send("领取泉边炊烟主线奖励 一饭暖途", "zero-restoration")).code == "MAINLINE_OBJECTIVES_INCOMPLETE"
            assert _database_state(runtime) == before
            assert (await send("开始挂机 灵泉谷拾穗", "next-glean")).code == "IDLE_STARTED"
            clock.advance(hours=4)
            assert (await send("领取挂机", "next-grain")).code == "IDLE_CLAIMED"
            meal = await send("使用物品 灵米饭 体力", "real-meal")
            assert meal.ok and meal.data["effect"]["restored"] > 0
            before = _database_state(runtime)
            assert (await send("使用物品 灵米饭 精力", "real-meal")).code == "OPERATION_CONFLICT"
            assert _database_state(runtime) == before
            await runtime.close()
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            assert (await send("领取泉边炊烟主线奖励 一饭暖途", "final-claim")).code == "MAINLINE_REWARD_CLAIMED"
        finally:
            await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("broken", ["body", "source", "food"])
def test_spring_supper_rejects_incomplete_content_and_broken_consumers(tmp_path: Path, broken: str) -> None:
    data_dir = _copy_content(tmp_path)
    if broken == "source":
        path = data_dir / "奖励" / "奖励.json"
        document = json.loads(path.read_text(encoding="utf-8"))
        pool = next(row for row in document["records"] if row["key"] == "reward_pool.idle.spring_gleaning")
        pool["outcomes"][0]["rewards"]["item.food.coarse_spirit_rice"] = 1
    else:
        path = data_dir / "剧情" / "主线.json"
        document = json.loads(path.read_text(encoding="utf-8"))
        stage = next(row for row in document["records"] if row["key"] == "spring_supper.2")
        if broken == "body":
            stage["body"] = "只有标题"
        else:
            stage["objectives"][1]["resources"] = ["void_power"]
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ContentError):
        mainline_definitions(ContentBundle.load(data_dir), story_key=SPRING_SUPPER_STORY_KEY)
