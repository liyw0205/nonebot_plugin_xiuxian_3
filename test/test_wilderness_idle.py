from __future__ import annotations

import asyncio
import copy
import json
import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle, ContentError, bundled_content
from nonebot_plugin_xiuxian_3.xiuxian.rewards.rules import reward_pool_outcomes
from nonebot_plugin_xiuxian_3.xiuxian.specials.idle_rules import idle_route_definitions


ROUTES = (
    ("idle.herb_vale_gather", "百草坡采药", "百草坡", 4),
    ("idle.ironwood_gather", "铁木林拾材", "铁木林", 6),
    ("idle.basalt_sifting", "玄武岩径筛砂", "玄武岩径", 8),
    ("idle.spring_gleaning", "灵泉谷拾穗", "灵泉谷", 4),
)


class Clock:
    def __init__(self):
        self.value = datetime(2026, 11, 12, tzinfo=timezone.utc)

    def __call__(self):
        return self.value

    def advance(self, **kwargs):
        self.value += timedelta(**kwargs)


async def send(runtime, command, operation="", *, user="gatherer", adapter="onebot.v11"):
    result = await runtime.adapters.dispatch(
        adapter, CommandContext(adapter=adapter, user_id=user, operation_id=operation), command,
    )
    return result


async def starter(runtime, *, user="gatherer", adapter="onebot.v11", path="器修"):
    for command in (
        "开始修仙", "寻仙问道", "完成引导 阅读", "前往近郊",
        "完成引导 采集", "完成引导 炼丹", f"选择道途 {path}",
    ):
        result = await send(runtime, command, user=user, adapter=adapter)
        assert result.ok, (command, result.code, result.message)


async def move(runtime, clock, destination):
    started = await send(runtime, f"前往 {destination}")
    assert started.code == "TRAVEL_STARTED", (destination, started.code, started.message)
    clock.advance(minutes=3)
    settled = await send(runtime, "结算移动")
    assert settled.code == "TRAVEL_COMPLETED", settled.message


def state(runtime):
    with sqlite3.connect(runtime.settings.database_path) as connection:
        return {
            table: connection.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
            for table in ("players", "idle_assignments", "operations", "codex_entries", "player_reputations", "economy_ledger_entries")
        }


def change_content(mutate):
    base = bundled_content()
    records = copy.deepcopy(dict(base._records))
    mutate(records)
    return replace(base, _records=records)


def test_four_routes_have_distinct_material_consumers_and_complete_only_journals():
    bundle = bundled_content()
    definitions = idle_route_definitions(bundle)
    for key, name, _, hours in ROUTES:
        route = definitions[key]
        assert route.label == name and route.duration_seconds == hours * 3600
        assert route.required_location and route.daily_limit == 1
        for _, reward in reward_pool_outcomes(route.pool_key, bundle):
            assert any(item.startswith("codex.story.") for item in reward)
            assert set(reward) <= {"item.herb.blood_grass", "item.herb.spirit_leaf", "item.mat.wood", "item.ore.ironstone", "item.mat.array_sand", "item.food.coarse_spirit_rice", *[item for item in reward if item.startswith("codex.story.")]}
        for _, reward in reward_pool_outcomes(route.fallback_pool_key, bundle):
            assert not any(item.startswith("codex.") for item in reward)
        assert route.gathering_journal["start_text"] != route.gathering_journal["complete_text"]
        assert all(use["command"].startswith("生产预览 ") for use in route.gathering_journal["uses"])
    assert len({definitions[key].gathering_journal["complete_text"] for key, *_ in ROUTES}) == 4


@pytest.mark.parametrize("bad", ["blank", "extra", "duplicate", "missing_recipe", "unrelated_recipe", "locked_recipe", "fallback_codex"])
def test_invalid_journal_content_is_rejected(bad):
    def mutate(records):
        row = records["livelihood", ROUTES[0][0]]
        journal = row["gathering_journal"]
        if bad == "blank":
            journal["complete_text"] = " "
        elif bad == "extra":
            journal["unconsumed"] = True
        elif bad == "duplicate":
            journal["recipe_keys"] *= 2
        elif bad == "missing_recipe":
            journal["recipe_keys"] = ["recipe.missing"]
        elif bad == "unrelated_recipe":
            journal["recipe_keys"] = ["recipe.food.cloud_rice_meal"]
        elif bad == "locked_recipe":
            records["recipe", "recipe.pill.healing_low"]["status"] = "locked"
        else:
            records["reward", row["fallback_reward_pool_key"]]["outcomes"][0]["rewards"]["codex.story.herb_vale_gather"] = 1
    with pytest.raises(ContentError, match="idle route"):
        idle_route_definitions(change_content(mutate))


def test_public_travel_gathering_journals_and_real_cooking_chain(tmp_path: Path):
    async def run():
        clock = Clock()
        runtime = create_runtime(data_dir=tmp_path, clock=clock)
        try:
            await starter(runtime, path="辅修 烹饪")
            assert (await send(runtime, "采集行记")).data["journals"] == []
            before = state(runtime)
            missing = await send(runtime, "开始挂机 百草坡采药", "herbs-start")
            assert missing.code == "IDLE_REQUIREMENT_MISSING"
            assert "百草坡" in missing.message and missing.data["reason"] and missing.data["subject"]
            assert state(runtime) == before
            for index, (key, name, destination, hours) in enumerate(ROUTES):
                if index == 1:
                    await move(runtime, clock, "近郊")
                elif index == 2:
                    assert (await send(runtime, "租住居所 客房")).ok
                    for _ in range(2):
                        assert (await send(runtime, "休整")).ok
                        clock.advance(minutes=30)
                        assert (await send(runtime, "结算休整")).ok
                    # A developed-role fixture avoids repeating the already delivered growth chain.
                    # No inventory, location, quest or source evidence is injected.
                    with sqlite3.connect(runtime.settings.database_path) as connection:
                        connection.execute("UPDATE players SET realm_key='qi_gathering', realm_layer=1 WHERE platform_user_id='gatherer'")
                    await move(runtime, clock, "近郊")
                elif index == 3:
                    await move(runtime, clock, "近郊")
                    await move(runtime, clock, "青石镇")
                await move(runtime, clock, destination)
                before = state(runtime)
                preview = await send(runtime, f"挂机预览 {name}")
                assert preview.ok and preview.data["routes"][0]["ready"], preview.message
                assert "完整所得" in preview.message and "逾时所得" in preview.message and "材料去向" in preview.message
                assert len(preview.actions) == 1 and preview.actions[0].enter
                assert state(runtime) == before
                started = await send(runtime, preview.actions[0].command, f"start-{index}")
                assert started.code == "IDLE_STARTED", started.message
                assert not (await send(runtime, preview.actions[0].command, f"start-{index}")).actions
                before = state(runtime)
                current = await send(runtime, "挂机状态")
                assert current.data["remaining_seconds"] == hours * 3600 and current.data["cancellable"]
                assert state(runtime) == before
                assert (await send(runtime, "领取挂机", f"claim-{index}")).code == "IDLE_CLAIM_TOO_EARLY"
                assert state(runtime) == before
                assert (await send(runtime, "开始挂机 镇中行旅")).code == "IDLE_BUSY"
                assert state(runtime) == before
                clock.advance(hours=hours)
                current = await send(runtime, "挂机状态")
                assert current.data["claimable"] and current.actions[0].command == "领取挂机"
                claimed = await send(runtime, "领取挂机", f"claim-{index}")
                assert claimed.ok and not claimed.data["fallback"], claimed.message
                assert claimed.data["route_key"] == key and "材料去向" in claimed.message
                before = state(runtime)
                replay = await send(runtime, "领取挂机", f"claim-{index}")
                assert replay.data["idempotent_replay"] and replay.message == claimed.message
                assert state(runtime) == before
                journals = await send(runtime, "采集行记")
                assert len(journals.data["journals"]) == index + 1
            assert (await send(runtime, "挂机状态")).data["assignment"] is None
            with sqlite3.connect(runtime.settings.database_path) as connection:
                inventory = json.loads(connection.execute("SELECT inventory_json FROM players WHERE platform_user_id='gatherer'").fetchone()[0])
                rice = inventory["item.food.coarse_spirit_rice"]
                assert rice >= 2
                assert connection.execute("SELECT count(*) FROM codex_entries WHERE entry_key LIKE 'codex.story.%'").fetchone()[0] == 4
            started = await send(runtime, "开始生产 灵米饭", "cook")
            assert started.code == "PRODUCTION_STARTED", started.message
            clock.advance(seconds=15)
            cooked = await send(runtime, "领取生产", "cook-claim")
            assert cooked.code == "PRODUCTION_COMPLETED" and cooked.data["success"], cooked.message
            assert cooked.data["outputs"] == {"item.food.spirit_rice": 2}
            with sqlite3.connect(runtime.settings.database_path) as connection:
                inventory = json.loads(connection.execute("SELECT inventory_json FROM players WHERE platform_user_id='gatherer'").fetchone()[0])
                assert inventory.get("item.food.coarse_spirit_rice", 0) == rice - 2
                assert inventory["item.food.spirit_rice"] == 2
        finally:
            await runtime.close()
    asyncio.run(run())


def test_specific_gates_and_operation_conflicts_do_not_write(tmp_path):
    async def run():
        clock = Clock()
        runtime = create_runtime(data_dir=tmp_path, clock=clock)
        try:
            await starter(runtime)
            before = state(runtime)
            for command in ("挂机预览 不存在的采集", "开始挂机 不存在的采集"):
                denied = await send(runtime, command, "missing")
                assert denied.code == "IDLE_ROUTE_NOT_FOUND"
                assert denied.data["subject"] == "不存在的采集" and "不存在的采集" in denied.data["reason"]
                assert state(runtime) == before
            denied = await send(runtime, "开始挂机 玄武岩径筛砂", "gate")
            assert denied.code == "IDLE_REQUIREMENT_MISSING"
            assert "聚气" in denied.message and "玄武岩径" in denied.message
            assert state(runtime) == before
            await move(runtime, clock, "百草坡")
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute("UPDATE players SET energy=0 WHERE platform_user_id='gatherer'")
            before = state(runtime)
            preview = await send(runtime, "挂机预览 百草坡采药")
            assert not preview.data["routes"][0]["ready"] and not preview.actions
            denied = await send(runtime, "开始挂机 百草坡采药", "energy")
            assert denied.code == "IDLE_REQUIREMENT_MISSING" and "精力不足" in denied.message
            assert state(runtime) == before
            assert (await send(runtime, "租住居所 客房")).ok
            assert (await send(runtime, "休整")).ok
            clock.advance(minutes=30)
            assert (await send(runtime, "结算休整")).ok
            assert (await send(runtime, "开始挂机 百草坡采药", "start")).ok
            before = state(runtime)
            conflict = await send(runtime, "开始挂机 灵泉谷拾穗", "start")
            assert conflict.code == "OPERATION_CONFLICT" and state(runtime) == before
        finally:
            await runtime.close()
    asyncio.run(run())


@pytest.mark.parametrize("command", ["挂机预览 百草坡采药", "开始挂机 百草坡采药"])
def test_broken_route_content_is_not_a_known_rejection(tmp_path, caplog, command):
    async def run():
        runtime = create_runtime(data_dir=tmp_path, clock=Clock())
        try:
            await starter(runtime)
            def corrupt(records):
                records["livelihood", ROUTES[0][0]]["gathering_journal"]["complete_text"] = " "
            runtime.repository.content = change_content(corrupt)
            before = state(runtime)
            with pytest.raises(ContentError, match="gathering_journal"):
                await send(runtime, command, "broken-content")
            assert state(runtime) == before
            assert f"command={command.split()[0]}" in caplog.text
            assert "Traceback" in caplog.text
        finally:
            await runtime.close()
    asyncio.run(run())


def test_old_snapshot_and_large_player_values_survive_restart(tmp_path):
    async def run():
        clock = Clock()
        runtime = create_runtime(data_dir=tmp_path, clock=clock)
        huge = 10 ** 100
        try:
            assert (await send(runtime, "开始修仙")).ok
            assert (await send(runtime, "寻仙问道")).ok
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE players SET spirit_stones=?, total_cultivation=? WHERE platform_user_id='gatherer'",
                    (str(huge).encode("ascii"), str(huge).encode("ascii")),
                )
            assert (await send(runtime, "开始挂机 镇中行旅", "old-start")).ok
            with sqlite3.connect(runtime.settings.database_path) as connection:
                snapshot = json.loads(connection.execute("SELECT snapshot_json FROM idle_assignments").fetchone()[0])
                for field in ("gathering_journal", "reward_labels", "codex_entries"):
                    snapshot.pop(field)
                connection.execute("UPDATE idle_assignments SET snapshot_json=?", (json.dumps(snapshot),))
            await runtime.close()
            clock.advance(hours=2)
            runtime = create_runtime(data_dir=tmp_path, clock=clock)
            assert (await send(runtime, "挂机状态")).data["claimable"]
            claimed = await send(runtime, "领取挂机", "old-claim")
            assert claimed.ok and claimed.data["reward"] == snapshot["full_reward"]
            assert (await send(runtime, "采集行记")).data["journals"] == []
            with sqlite3.connect(runtime.settings.database_path) as connection:
                stones, cultivation = connection.execute("SELECT spirit_stones,total_cultivation FROM players").fetchone()
                assert int(stones) == huge + claimed.data["reward"]["spirit_stones"]
                assert int(cultivation) == huge
        finally:
            await runtime.close()
    asyncio.run(run())


def test_qq_entry_keyboard_prefix_and_onebot_text_fallback(tmp_path):
    from nonebot_plugin_xiuxian_3.adapters.message.markdown import send_markdown_message

    class Bot:
        __module__ = "nonebot.adapters.qq.bot"

        async def send(self, event, message, **kwargs):
            self.message = message
            return {"id": "reply"}

    class Event:
        __module__ = "nonebot.adapters.qq.event"

    async def run():
        clock = Clock()
        runtime = create_runtime(data_dir=tmp_path, clock=clock)
        try:
            for command in ("开始修仙", "寻仙问道", "前往近郊", "前往 百草坡"):
                assert (await send(runtime, command, adapter="qq.official")).ok
            clock.advance(minutes=3)
            assert (await send(runtime, "结算移动", adapter="qq.official")).ok
            before = state(runtime)
            for category in ("生活", "探索"):
                help_result = await send(runtime, f"修仙帮助 {category}", adapter="qq.official")
                assert help_result.ok and not help_result.actions
                assert all(name in help_result.message for _, name, *_ in ROUTES)
                assert "挂机状态" in help_result.message and "采集行记" in help_result.message
            preview = await send(runtime, "挂机预览 百草坡采药", adapter="qq.official")
            assert preview.ok and len(preview.actions) == 1
            assert "开始挂机" not in preview.message and "idle." not in preview.message
            assert state(runtime) == before
            bot = Bot()
            sent = await send_markdown_message(
                bot, Event(), preview.message, actions=preview.actions,
                capabilities=("markdown", "keyboard"), command_prefix="!",
            )
            assert sent.sent_format == "markdown+keyboard"
            assert "!开始挂机 百草坡采药" in str(bot.message)
            assert "mqqapi://aio/inlinecmd" in str(bot.message) and "command=%21" in str(bot.message)
            plain = Bot()
            sent = await send_markdown_message(plain, object(), preview.message, actions=preview.actions)
            assert sent.sent_format == "text" and "可发送：开始挂机 百草坡采药" in str(plain.message)
            assert "command:" not in str(plain.message) and "mqqapi:" not in str(plain.message)
            started = await send(runtime, preview.actions[0].command, "qq-start", adapter="qq.official")
            assert started.ok
            status = await send(runtime, "挂机状态", adapter="qq.official")
            assert status.data["cancellable"] and status.actions[0].command == "取消挂机"
            assert (await send(runtime, "查看挂机", adapter="qq.official")).code == "IDLE_PREVIEW"
        finally:
            await runtime.close()
    asyncio.run(run())


def test_cancel_late_daily_limit_and_owned_status_are_atomic(tmp_path):
    async def run():
        clock = Clock()
        runtime = create_runtime(data_dir=tmp_path, clock=clock)
        try:
            await starter(runtime)
            await move(runtime, clock, "百草坡")
            assert (await send(runtime, "开始挂机 百草坡采药", "start-cancel")).ok
            cancelled = await send(runtime, "取消挂机", "cancel")
            assert cancelled.ok and cancelled.data["refunded"] == {"stamina": 2, "energy": 1}
            before = state(runtime)
            assert (await send(runtime, "取消挂机", "cancel")).data["idempotent_replay"]
            assert state(runtime) == before
            started = await send(runtime, "开始挂机 百草坡采药", "start-late")
            assert started.ok
            for command in ("开始修仙", "寻仙问道"):
                assert (await send(runtime, command, user="other")).ok
            assert (await send(runtime, "挂机状态", user="other")).data["assignment"] is None
            before = state(runtime)
            denied = await send(runtime, f"领取挂机 {started.data['assignment_id']}", user="other")
            assert denied.code == "IDLE_NOT_FOUND" and state(runtime) == before
            clock.advance(hours=28, seconds=1)
            current = await send(runtime, "挂机状态")
            assert current.data["fallback"] and current.actions[0].label == "领取保底"
            late = await send(runtime, "领取挂机", "claim-late")
            assert late.ok and late.data["reward"] == {"item.herb.blood_grass": 1}
            assert "受潮" in late.message and (await send(runtime, "采集行记")).data["journals"] == []
            # The late result counts against the starting business day, not the claim day.
            assert (await send(runtime, "开始挂机 百草坡采药", "start-today")).ok
            clock.advance(hours=4)
            assert (await send(runtime, "领取挂机", "claim-today")).ok
            before = state(runtime)
            denied = await send(runtime, "开始挂机 百草坡采药", "limited")
            assert denied.code == "IDLE_DAILY_LIMIT" and state(runtime) == before
        finally:
            await runtime.close()
    asyncio.run(run())


@pytest.mark.parametrize("fault", ["reward", "ledger", "snapshot"])
def test_restart_snapshot_and_fault_rollback_retry(tmp_path, monkeypatch, fault, caplog):
    async def run():
        clock = Clock()
        runtime = create_runtime(data_dir=tmp_path, clock=clock)
        await starter(runtime)
        await move(runtime, clock, "百草坡")
        assert (await send(runtime, "开始挂机 百草坡采药", "start")).ok
        with sqlite3.connect(runtime.settings.database_path) as connection:
            frozen = json.loads(connection.execute("SELECT snapshot_json FROM idle_assignments").fetchone()[0])
        await runtime.close()
        clock.advance(hours=4)
        runtime = create_runtime(data_dir=tmp_path, clock=clock)
        try:
            def close_content(records):
                records["livelihood", ROUTES[0][0]]["status"] = "locked"
                records["livelihood", ROUTES[0][0]]["gathering_journal"]["complete_text"] = "new text"
                records["recipe", "recipe.pill.healing_low"]["name"] = "new name"
                records["codex_entry", "codex.story.herb_vale_gather"]["status"] = "locked"
                records["codex_entry", "codex.story.herb_vale_gather"]["name"] = "new codex"
            runtime.repository.content = change_content(close_content)
            assert (await send(runtime, "挂机状态")).data["claimable"]
            original_ledger = runtime.repository._record_idle_operation
            from nonebot_plugin_xiuxian_3.xiuxian.specials import idle_repository
            original_grant = idle_repository.grant_player_reward
            if fault == "reward":
                def broken_grant(*args, **kwargs):
                    original_grant(*args, **kwargs)
                    raise RuntimeError("injected reward failure")
                monkeypatch.setattr(idle_repository, "grant_player_reward", broken_grant)
            elif fault == "ledger":
                def broken_ledger(*args, **kwargs):
                    raise RuntimeError("injected ledger failure")
                monkeypatch.setattr(runtime.repository, "_record_idle_operation", broken_ledger)
            else:
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    corrupted = copy.deepcopy(frozen)
                    corrupted["gathering_journal"]["uses"] = "bad"
                    connection.execute("UPDATE idle_assignments SET snapshot_json=?", (json.dumps(corrupted),))
            before = state(runtime)
            with pytest.raises((RuntimeError, ValueError), match="injected|gathering_journal"):
                await send(runtime, "领取挂机", "claim")
            assert state(runtime) == before
            assert "idle command failed" in caplog.text and "operation=claim" in caplog.text
            monkeypatch.setattr(idle_repository, "grant_player_reward", original_grant)
            monkeypatch.setattr(runtime.repository, "_record_idle_operation", original_ledger)
            if fault == "snapshot":
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute("UPDATE idle_assignments SET snapshot_json=?", (json.dumps(frozen),))
            claimed = await send(runtime, "领取挂机", "claim")
            assert claimed.ok and claimed.data["reward"] == frozen["full_reward"]
            assert frozen["gathering_journal"]["complete_text"] in claimed.message and "new" not in claimed.message
            journals = await send(runtime, "采集行记")
            assert journals.data["journals"][0]["complete_text"] == frozen["gathering_journal"]["complete_text"]
            before = state(runtime)
            assert (await send(runtime, "领取挂机", "claim")).message == claimed.message
            assert state(runtime) == before
        finally:
            await runtime.close()
    asyncio.run(run())
