from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path
from urllib.parse import quote

import pytest

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.adventures.mainline import IRONWOOD_CRAFT_STORY_KEY, mainline_definitions
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle, ContentError
from test_companion_old_trail_mainline import _database_state, _inventory
from test_mainline_vertical_slice import MutableClock, _copy_content
from test_wilderness_idle import change_content


def test_ironwood_contract_sources_choices_and_consumers(tmp_path: Path) -> None:
    data = _copy_content(tmp_path)
    bundle = ContentBundle.load(data)
    definitions = mainline_definitions(bundle, story_key=IRONWOOD_CRAFT_STORY_KEY)
    assert [stage.key for stage in definitions] == [f"ironwood_craft.{i}" for i in (1, 2, 3)]
    route = bundle.require("livelihood", definitions[0].objectives[0]["route_key"])
    dispatch = bundle.require("livelihood", definitions[1].objectives[0]["dispatch_key"])
    commission = bundle.require("livelihood", definitions[2].objectives[0]["commission_key"])
    pools = [bundle.require("reward", route["reward_pool_key"])]
    pools += [bundle.require("reward", choice["reward_pool_key"]) for choice in route["wilderness_event"]["choices"]]
    supplied = {key for pool in pools for outcome in pool["outcomes"] for key, amount in outcome["rewards"].items() if amount > 0}
    assert {entry["item_key"] for entry in commission["inputs"]} <= supplied
    assert all({key for key in plan["cost"] if key.startswith("item.")} <= supplied for plan in dispatch["planning"]["plans"])
    assert all(len(stage.body) >= 80 and stage.actions and stage.retry_message for stage in definitions)
    path = data / "剧情/主线.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    row = next(row for row in document["records"] if row["key"] == "ironwood_craft.2")
    row["objectives"][0]["dispatch_key"] = "dispatch.missing"
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ContentError):
        mainline_definitions(ContentBundle.load(data), story_key=IRONWOOD_CRAFT_STORY_KEY)


@pytest.mark.parametrize("stage_key,source_key", [
    ("ironwood_craft.1", "idle.ironwood_gather"),
    ("ironwood_craft.2", "dispatch.ironwood_bridge_works"),
    ("ironwood_craft.3", "town_commission.repair_tools"),
])
def test_closed_pages_require_known_valid_sources(stage_key, source_key):
    def close_source(records):
        records["livelihood", source_key]["status"] = "locked"

    with pytest.raises(ContentError):
        mainline_definitions(change_content(close_source), story_key=IRONWOOD_CRAFT_STORY_KEY)

    def close_both(records):
        close_source(records)
        records["mainline", stage_key]["status"] = "locked"

    with pytest.raises(ContentError):
        mainline_definitions(change_content(close_both), story_key=IRONWOOD_CRAFT_STORY_KEY)
    definitions = mainline_definitions(change_content(close_both), story_key=IRONWOOD_CRAFT_STORY_KEY, validate_sources=False)
    assert next(stage for stage in definitions if stage.key == stage_key).runtime_status == "locked"

    def remove_source(records):
        close_both(records)
        del records["livelihood", source_key]

    with pytest.raises(ContentError):
        mainline_definitions(change_content(remove_source), story_key=IRONWOOD_CRAFT_STORY_KEY)


@pytest.mark.parametrize("adapter,choice,plan,hours", [
    ("onebot.v11", "顺纹取材", "踏勘", 1.5),
    ("qq.official", "翻根寻铁", "整治", 4),
])
def test_ironwood_public_journey_restart_replay_and_rollback(tmp_path, monkeypatch, adapter, choice, plan, hours):
    monkeypatch.setattr("nonebot_plugin_xiuxian_3.xiuxian.specials.dispatch_repository.choose_outcome", lambda *_: "success")

    async def run():
        data = _copy_content(tmp_path)
        clock = MutableClock()
        runtime = create_runtime(data_dir=data, clock=clock, adapters=(adapter,))

        async def send(command, operation=""):
            return await runtime.dispatch(CommandContext(adapter=adapter, user_id="gatherer", operation_id=operation), command)

        async def move(destination):
            started = await send(f"前往 {destination}")
            assert started.code == "TRAVEL_STARTED", started.message
            clock.advance(minutes=3)
            assert (await send("结算移动")).code == "TRAVEL_COMPLETED"

        async def restart():
            nonlocal runtime
            await runtime.close()
            runtime = create_runtime(data_dir=data, clock=clock, adapters=(adapter,))
            await runtime.repository.initialize()

        def trigger(operation):
            with runtime.repository._connect() as connection:
                connection.execute("CREATE TRIGGER fail_ironwood BEFORE INSERT ON operations "
                                   f"WHEN NEW.operation_id='{operation}' BEGIN SELECT RAISE(ABORT, 'forced ironwood failure'); END")

        def untrigger():
            with runtime.repository._connect() as connection:
                connection.execute("DROP TRIGGER fail_ironwood")

        async def rollback_retry(command, operation):
            trigger(operation)
            before = _database_state(runtime)
            if command.startswith(("领取挂机", "接受派遣", "结算派遣")):
                with pytest.raises(sqlite3.IntegrityError, match="forced ironwood failure"):
                    await send(command, operation)
            else:
                failed = await send(command, operation)
                assert failed.code == "PERSISTENCE_ERROR", failed.message
            assert _database_state(runtime) == before
            untrigger()
            result = await send(command, operation)
            assert result.ok, (result.code, result.message)
            before = _database_state(runtime)
            replay = await send(command, operation)
            assert replay.data["idempotent_replay"]
            assert _database_state(runtime) == before
            return result

        async def resupply(prefix):
            for i in range(8):
                inventory = _inventory(runtime)
                if inventory.get("item.mat.wood", 0) >= 8 and inventory.get("item.ore.ironstone", 0) >= 6:
                    return
                clock.advance(days=1)
                assert (await send("恢复状态")).ok
                assert (await send(f"开始挂机 铁木林拾材 {choice}", f"{prefix}-{i}")).ok
                clock.advance(hours=6)
                assert (await send("领取挂机", f"{prefix}-{i}-claim")).ok
            pytest.fail("public ironwood source did not supply wood and ore")

        try:
            assert (await send("开始修仙")).ok
            assert (await send("寻仙问道")).ok
            before = _database_state(runtime)
            assert (await send("开始铁木问工主线 林间备料", "denied")).code == "MAINLINE_REQUIREMENT_MISSING"
            assert _database_state(runtime) == before
            for command in ("完成引导 阅读", "前往近郊", "完成引导 采集", "完成引导 炼丹", "选择道途 器修"):
                assert (await send(command)).ok
            assert (await send("开始铁木问工主线 桥基问工", "skip-stage")).code == "MAINLINE_REQUIREMENT_MISSING"
            first = await send("开始铁木问工主线 林间备料", "first")
            assert first.code == "MAINLINE_STARTED" and "石伯" in first.message and not first.actions
            await move("铁木林")
            before = _database_state(runtime)
            assert (await send("接受派遣 铁木林桥基勘务 整治", "no-material")).code == "DISPATCH_REQUIREMENT_MISSING"
            assert _database_state(runtime) == before
            preview = await send("挂机预览 铁木林拾材")
            assert preview.ok and "顺纹取材" in preview.message and "翻根寻铁" in preview.message
            assert (await send(f"开始挂机 铁木林拾材 {choice}", "cancel-start")).ok
            assert (await send("取消挂机", "cancel")).code == "IDLE_CANCELLED"
            assert (await send("领取铁木问工主线奖励 林间备料", "cancel-story")).code == "MAINLINE_OBJECTIVES_INCOMPLETE"
            assert (await send(f"开始挂机 铁木林拾材 {choice}", "late-start")).ok
            assert (await send("领取挂机", "early")).code == "IDLE_CLAIM_TOO_EARLY"
            clock.advance(hours=31)
            late = await send("领取挂机", "late")
            assert late.data["fallback"]
            assert (await send("领取铁木问工主线奖励 林间备料", "late-story")).code == "MAINLINE_OBJECTIVES_INCOMPLETE"
            assert (await send("恢复状态")).ok
            assert (await send(f"开始挂机 铁木林拾材 {choice}", "full-start")).ok
            clock.advance(hours=6)
            await restart()
            def close_gather(records):
                records["livelihood", "idle.ironwood_gather"]["status"] = "locked"
                records["livelihood", "idle.ironwood_gather"]["name"] = "林场封山"
                records["mainline", "ironwood_craft.1"]["status"] = "locked"
                records["mainline", "ironwood_craft.1"]["name"] = "新备料文案"
                records["mainline", "ironwood_craft.1"]["first_clear_reward"] = {"spirit_stones": 999}
            runtime.repository.content = change_content(close_gather)
            before = _database_state(runtime)
            assert (await send("开始铁木问工主线 林间备料", "first")).data["idempotent_replay"]
            assert (await send("开始铁木问工主线 林间备料", "closed-new")).code == "CONTENT_CLOSED"
            assert (await send("铁木问工主线")).ok
            assert _database_state(runtime) == before
            full = await rollback_retry("领取挂机", "full-claim")
            assert not full.data["fallback"] and full.data["reward"]["item.mat.wood"] >= 1
            claimed = await rollback_retry("领取铁木问工主线奖励 林间备料", "first-claim")
            assert claimed.data["reward"] == {"spirit_stones": 10, "local_reputation": 1}
            runtime.repository.content = ContentBundle.load(data)
            await resupply("supply")
            assert (await send("恢复状态")).ok
            # Accept before starting the next page, at exactly the same clock tick.
            assert (await send(f"接受派遣 铁木林桥基勘务 {plan}", "old-dispatch")).ok
            second = await send("开始铁木问工主线 桥基问工", "second")
            assert second.ok and "鲁槐" in second.message
            clock.advance(hours=hours)
            assert (await send("结算派遣", "old-settle")).data["outcome"] == "success"
            assert (await send("领取铁木问工主线奖励 桥基问工", "old-story")).code == "MAINLINE_OBJECTIVES_INCOMPLETE"
            if adapter == "onebot.v11":
                for outcome in ("cancel", "partial", "failed", "delayed"):
                    clock.advance(days=1)
                    await resupply(f"supply-{outcome}")
                    assert (await send("恢复状态")).ok
                    monkeypatch.setattr(
                        "nonebot_plugin_xiuxian_3.xiuxian.specials.dispatch_repository.choose_outcome",
                        lambda *_, value=outcome: "success" if value == "cancel" else value,
                    )
                    inventory = _inventory(runtime)
                    accepted = await send(f"接受派遣 铁木林桥基勘务 {plan}", f"accept-{outcome}")
                    assert accepted.ok, accepted.message
                    if outcome == "cancel":
                        assert (await send("取消派遣", "cancel-dispatch")).code == "DISPATCH_CANCELLED"
                        assert _inventory(runtime) == inventory
                    else:
                        clock.advance(hours=hours)
                        if outcome == "delayed":
                            assert (await send("结算派遣", "delay-early")).code == "DISPATCH_NOT_READY"
                            clock.advance(hours=hours / 2)
                        settled = await send("结算派遣", f"settle-{outcome}")
                        assert settled.ok and settled.data["outcome"] == outcome
                    assert (await send("领取铁木问工主线奖励 桥基问工", f"story-{outcome}")).code == "MAINLINE_OBJECTIVES_INCOMPLETE"
                monkeypatch.setattr(
                    "nonebot_plugin_xiuxian_3.xiuxian.specials.dispatch_repository.choose_outcome", lambda *_: "success",
                )
                clock.advance(days=1)
                await resupply("supply-success")
                assert (await send("恢复状态")).ok
            await rollback_retry(f"接受派遣 铁木林桥基勘务 {plan}", "new-dispatch")
            assert (await send("结算派遣", "not-ready")).code == "DISPATCH_NOT_READY"
            clock.advance(hours=hours)
            await restart()
            def close_dispatch(records):
                records["livelihood", "dispatch.ironwood_bridge_works"]["status"] = "locked"
                records["livelihood", "dispatch.ironwood_bridge_works"]["name"] = "新勘务名称"
                records["mainline", "ironwood_craft.2"]["status"] = "locked"
            runtime.repository.content = change_content(close_dispatch)
            assert plan in (await send("派遣状态")).message
            settled = await rollback_retry("结算派遣", "new-settle")
            assert settled.data["outcome"] == "success"
            await rollback_retry("领取铁木问工主线奖励 桥基问工", "second-claim")
            runtime.repository.content = ContentBundle.load(data)
            await move("近郊")
            await move("青石镇")
            clock.advance(days=1)
            clock.value = clock.value.replace(hour=0, minute=0, second=0, microsecond=0)
            assert (await send("接取委托 工具修缮", "old-order")).ok
            assert (await send("交付委托 工具修缮", "old-delivery")).ok
            # A same-timestamp old delivery cannot complete a new page either.
            assert (await send("开始铁木问工主线 木石归铺", "third")).ok
            assert (await send("领取铁木问工主线奖励 木石归铺", "old-delivery-story")).code == "MAINLINE_OBJECTIVES_INCOMPLETE"
            clock.advance(days=1)
            assert (await send("接取委托 工具修缮", "expired-order")).ok
            clock.advance(hours=13)
            assert (await send("交付委托 工具修缮", "expired-delivery")).code == "COMMISSION_EXPIRED"
            assert (await send("领取铁木问工主线奖励 木石归铺", "expired-story")).code == "MAINLINE_OBJECTIVES_INCOMPLETE"
            clock.advance(days=1)
            clock.value = clock.value.replace(hour=0, minute=0, second=0, microsecond=0)
            assert (await send("接取委托 工具修缮", "new-order")).ok
            await restart()
            def close_commission(records):
                records["livelihood", "town_commission.repair_tools"]["status"] = "locked"
                records["mainline", "ironwood_craft.3"]["status"] = "locked"
            runtime.repository.content = change_content(close_commission)
            inventory = _inventory(runtime)
            delivery = await rollback_retry("交付委托 工具修缮", "new-delivery")
            assert delivery.ok
            assert _inventory(runtime)["item.mat.wood"] == inventory["item.mat.wood"] - 2
            assert _inventory(runtime).get("item.ore.ironstone", 0) == inventory["item.ore.ironstone"] - 1
            reward = await rollback_retry("领取铁木问工主线奖励 木石归铺", "third-claim")
            assert reward.data["reward"] == {"spirit_stones": 25, "local_reputation": 3, "service_reputation": 2}
            before = _database_state(runtime)
            repeated = await asyncio.gather(*(send("领取铁木问工主线奖励 木石归铺", f"another-claim-{i}") for i in range(2)))
            assert all(result.data["idempotent_replay"] for result in repeated)
            assert _database_state(runtime) == before
            assert all(row["status"] == "claimed" for row in (await send("铁木问工主线")).data["stages"])
            help_result = await send("修仙帮助 生活")
            assert "铁木问工主线" in help_result.message and not help_result.actions
            from nonebot_plugin_xiuxian_3.adapters.message.markdown import _qq_command_links, markdown_to_text

            converted = _qq_command_links(second.message, command_prefix="!")
            assert quote("!接受派遣 铁木林桥基勘务 整治", safe="") in converted
            assert "enter=false" in converted and "command:" not in markdown_to_text(second.message)
        finally:
            await runtime.close()

    asyncio.run(run())
