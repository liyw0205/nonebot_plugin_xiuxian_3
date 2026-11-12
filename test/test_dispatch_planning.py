from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from unittest.mock import patch
from urllib.parse import unquote

import pytest

from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentError, bundled_content
from nonebot_plugin_xiuxian_3.xiuxian.exploration.rules import battle_roll_bp, settlement_result
from nonebot_plugin_xiuxian_3.xiuxian.persistence.errors import OperationResultMalformedError
from nonebot_plugin_xiuxian_3.xiuxian.production.rules import random_quality_bp
from nonebot_plugin_xiuxian_3.xiuxian.specials.dispatch_planning import freeze_planning, select_preparation
from nonebot_plugin_xiuxian_3.xiuxian.specials.dispatch_rules import choose_outcome, dispatch_definitions
from nonebot_plugin_xiuxian_3.xiuxian.utils.player import player_integer
from test_dispatch import _force_uuid
from test_wilderness_idle import Clock, change_content, move, send, starter

HERB = "dispatch.herb_spring_works"
BRIDGE = "dispatch.ironwood_bridge_works"
BASALT = "dispatch.basalt_watermark_works"


def state(runtime):
    with runtime.repository._connect() as db:
        return {table: tuple(tuple(row) for row in db.execute(f"SELECT * FROM {table} ORDER BY rowid"))
                for table in ("players", "dispatch_assignments", "operations", "codex_entries", "activity_events", "player_reputations", "economy_ledger_entries")}


def player(runtime):
    with runtime.repository._connect() as db:
        return dict(db.execute("SELECT * FROM players WHERE platform_user_id='gatherer'").fetchone())


async def prepare(runtime):
    await starter(runtime, path="辅修 布阵")
    # Reuse the delivered growth baseline, never inject materials or source evidence.
    with runtime.repository._connect() as db:
        db.execute("UPDATE players SET realm_key='qi_gathering', realm_layer=1, "
                   "stamina=300, stamina_max=300, energy=100, energy_max=100")


async def gather(runtime, clock, key, wanted, op):
    mode = runtime.repository.content or bundled_content()
    row = mode.require("exploration_mode", key)
    seed = next(f"{op}-{i}" for i in range(10000)
                if all(settlement_result(key, f"{op}-{i}", content=mode).get(item, 0) >= count for item, count in wanted.items())
                and battle_roll_bp(f"{op}-{i}:battle") >= 5000)
    result = await send(runtime, "开始探索 " + row["name"], seed)
    assert result.ok, (result.code, result.message)
    clock.advance(seconds=row["duration_seconds"])
    result = await send(runtime, "结算探索", op + "-claim")
    assert result.ok, (result.code, result.message)
    assert all(result.data["result"].get(item, 0) >= count for item, count in wanted.items())


async def herb_supplies(runtime, clock):
    await gather(runtime, clock, "explore.gather_outskirts", {"item.mat.wood": 1}, "wood")
    await move(runtime, clock, "百草坡")
    await gather(runtime, clock, "explore.gather_herb_vale", {"item.herb.blood_grass": 3}, "herbs")


def force(definition, outcome, assignment):
    seed = next(f"planning-{i}" for i in range(10000) if choose_outcome(definition, f"planning-{i}") == outcome)
    return _force_uuid(seed, assignment)


def test_three_sites_six_preparations_have_twenty_four_frozen_results():
    bundle = bundled_content()
    definitions = dispatch_definitions(bundle)
    planned = [definition for definition in definitions.values() if definition.planning]
    assert {definition.key for definition in planned} == {HERB, BRIDGE, BASALT}
    texts = set()
    for definition in planned:
        assert definition.required_location and len(definition.planning["plans"]) == 2
        survey = select_preparation(definition, None, bundle)
        repair = select_preparation(definition, "整治", bundle)
        assert survey.duration_seconds < repair.duration_seconds
        assert sum(dict(survey.costs).values()) < sum(dict(repair.costs).values())
        assert dict(survey.risk_weights)["success"] < dict(repair.risk_weights)["success"]
        for selected in (survey, repair):
            for outcome in ("success", "delayed", "partial", "failed"):
                frozen = freeze_planning(selected, outcome, bundle)
                assert frozen["uses"] and frozen["asset_labels"]
                texts.add(frozen["result_text"])
                assert frozen["npc"] in selected.planning["scene"]
    assert len(texts) == 24


@pytest.mark.parametrize("damage", ["boolean", "duplicate", "blank", "outcome", "source", "missing_source", "consumer", "worksite", "refund", "default"])
def test_invalid_planning_content_fails_without_defaults(damage):
    def mutate(records):
        row = records["livelihood", HERB]
        plan = row["planning"]["plans"][1]
        if damage == "boolean":
            plan["duration_seconds"] = True
        elif damage == "duplicate":
            plan["name"] = "踏勘"
        elif damage == "blank":
            plan["start_text"] = " "
        elif damage == "outcome":
            del plan["outcome_texts"]["failed"]
        elif damage == "source":
            row["planning"]["sources"][0]["exploration_key"] = "explore.gather_ironwood"
        elif damage == "missing_source":
            row["planning"]["sources"].pop()
        elif damage == "consumer":
            row["planning"]["recipe_keys"] = ["recipe.array.gathering_basic"]
        elif damage == "worksite":
            row["requirements"]["location_key"] = "location.missing"
        elif damage == "refund":
            plan["failure_refunds"]["item.mat.wood"] = 999
        else:
            row["duration_seconds"] += 1
    with pytest.raises(ContentError):
        dispatch_definitions(change_content(mutate))


def test_public_six_preparations_restart_receipts_and_real_consumption(tmp_path):
    async def run():
        clock = Clock()
        runtime = create_runtime(data_dir=tmp_path, clock=clock)
        try:
            await prepare(runtime)
            await herb_supplies(runtime, clock)
            for key, destination in ((HERB, "百草坡"), (BRIDGE, "铁木林"), (BASALT, "玄武岩径")):
                if key != HERB:
                    await move(runtime, clock, "近郊")
                    await move(runtime, clock, destination)
                    await gather(runtime, clock, "explore.gather_ironwood" if key == BRIDGE else "explore.gather_basalt_pass",
                                 {"item.mat.wood": 3, "item.ore.ironstone": 1} if key == BRIDGE else {"item.ore.ironstone": 2, "item.mat.array_sand": 1},
                                 key + "-gather")
                definition = dispatch_definitions()[key]
                before = state(runtime)
                preview = await send(runtime, f"派遣预览 {definition.label}")
                assert preview.ok and len(preview.actions) == 2, preview.message
                assert state(runtime) == before
                assert "备料" in preview.message and "用途" in preview.message
                for index, action in enumerate(preview.actions):
                    selected = select_preparation(definition, ("survey", "repair")[index], bundled_content())
                    op = f"{key}-{index}"
                    original = player(runtime)
                    with force(selected, "success", op):
                        result = await send(runtime, action.command, op)
                    assert result.code == "DISPATCH_ACCEPTED", result.message
                    changed = player(runtime)
                    old_inv, new_inv = json.loads(original["inventory_json"]), json.loads(changed["inventory_json"])
                    for asset, cost in selected.costs:
                        assert (old_inv.get(asset, 0) - new_inv.get(asset, 0) if asset.startswith("item.") else original[asset] - changed[asset]) == cost
                    frozen = result.data["planning"]
                    before = state(runtime)
                    status = await send(runtime, "派遣状态")
                    assert status.data["assignment"]["remaining_seconds"] == selected.duration_seconds
                    assert state(runtime) == before
                    replay = await send(runtime, action.command, op)
                    assert replay.data["idempotent_replay"] and replay.data["planning"] == frozen
                    assert replay.message == result.message
                    assert state(runtime) == before
                    conflict = await send(runtime, f"接受派遣 {definition.label} " + ("整治" if index == 0 else "踏勘"), op)
                    assert conflict.code == "OPERATION_CONFLICT" and conflict.data["reason"]
                    assert state(runtime) == before
                    await runtime.close()
                    clock.advance(seconds=selected.duration_seconds)
                    runtime = create_runtime(data_dir=tmp_path, clock=clock)
                    status = await send(runtime, "派遣状态")
                    assert status.data["assignment"]["planning"] == frozen
                    assert len(status.actions) == 1 and status.actions[0].command.startswith("结算派遣 ")
                    original = player(runtime)
                    settled = await send(runtime, status.actions[0].command, op + "-settle")
                    assert settled.code == "DISPATCH_SETTLED", settled.message
                    changed = player(runtime)
                    for asset, amount in settled.data["reward"].items():
                        delta = json.loads(changed["inventory_json"]).get(asset, 0) - json.loads(original["inventory_json"]).get(asset, 0) if asset.startswith("item.") else changed[asset] - original[asset]
                        assert delta == amount
                    assert frozen["result_text"] in settled.message
                    before = state(runtime)
                    replay = await send(runtime, status.actions[0].command, op + "-settle")
                    assert replay.data["idempotent_replay"] and replay.message == settled.message
                    assert state(runtime) == before
                    last = await send(runtime, "我的派遣")
                    assert last.data["assignment"]["result"]["reward"] == settled.data["reward"]
                    assert state(runtime) == before
            await move(runtime, clock, "近郊")
            await move(runtime, clock, "青石镇")
            # Daily town offers expire at noon; wait for the next public board window.
            clock.advance(seconds=24 * 3600 - (clock.value.hour * 3600 + clock.value.minute * 60 + clock.value.second))
            for commission, inputs in (("草药供应", {"item.herb.blood_grass": 3}), ("工具修缮", {"item.mat.wood": 2, "item.ore.ironstone": 1})):
                accepted = await send(runtime, "接取委托 " + commission, "commission-" + commission)
                assert accepted.ok, accepted.message
                original = json.loads(player(runtime)["inventory_json"])
                done = await send(runtime, "交付委托 " + commission, "delivery-" + commission)
                assert done.ok, done.message
                current = json.loads(player(runtime)["inventory_json"])
                assert all(original[item] - current.get(item, 0) == count for item, count in inputs.items())
            await move(runtime, clock, "灵泉谷")
            original = json.loads(player(runtime)["inventory_json"])["item.mat.array_sand"]
            op = next(f"array-start-{i}" for i in range(100) if random_quality_bp(f"array-start-{i}") >= 500)
            produced = await send(runtime, "开始生产 基础聚灵阵", op)
            assert produced.ok, produced.message
            assert original - json.loads(player(runtime)["inventory_json"])["item.mat.array_sand"] == 2
            clock.advance(seconds=90)
            done = await send(runtime, "领取生产", "array-claim")
            assert done.ok and done.data["success"], done.message
            assert json.loads(player(runtime)["inventory_json"])["item.array.gathering_basic"] >= 1
        finally:
            await runtime.close()
    asyncio.run(run())


@pytest.mark.parametrize("outcome", ["partial", "failed", "delayed"])
def test_outcome_refunds_and_closed_content_auto_recovery(tmp_path, outcome):
    async def run():
        clock = Clock()
        runtime = create_runtime(data_dir=tmp_path, clock=clock)
        try:
            await prepare(runtime)
            await herb_supplies(runtime, clock)
            definition = select_preparation(dispatch_definitions()[HERB], "整治", bundled_content())
            with force(definition, outcome, "risk"):
                accepted = await send(runtime, "接受派遣 百草坡药泉勘务 整治", "accept")
            assert accepted.ok, accepted.message
            assert (await send(runtime, "派遣状态")).data["assignment"]["remaining_seconds"] == definition.duration_seconds * (3 if outcome == "delayed" else 2) // 2
            def close(records):
                records["livelihood", HERB]["status"] = "locked"
            runtime.repository.content = change_content(close)
            before = state(runtime)
            replay = await send(runtime, "接受派遣 百草坡药泉勘务 整治", "accept")
            assert replay.data["planning"] == accepted.data["planning"] and replay.data["idempotent_replay"]
            assert state(runtime) == before
            original = player(runtime)
            clock.advance(hours=32)
            assert await runtime.repository.recover_expired_dispatches(batch_size=1) == 1
            assert await runtime.repository.recover_expired_dispatches(batch_size=1) == 0
            status = await send(runtime, "派遣状态")
            result = status.data["assignment"]["result"]
            assert result["outcome"] == outcome
            assert accepted.data["planning"]["result_text"] in status.message
            now = player(runtime)
            if outcome == "failed":
                assert result["reward"] == {}
                assert result["refunded"] == dict(definition.failure_refunds)
                assert now["stamina"] - original["stamina"] == 2
                assert json.loads(now["inventory_json"])["item.mat.wood"] - json.loads(original["inventory_json"]).get("item.mat.wood", 0) == 1
            else:
                assert result["reward"] == dict(definition.reward_specs(outcome))
            with runtime.repository._connect() as db:
                assert db.execute("SELECT count(*) FROM activity_events WHERE event_key='specials.dispatch.settled'").fetchone()[0] == 1
        finally:
            await runtime.close()
    asyncio.run(run())


def test_missing_conditions_cancel_quota_and_parallel_exactly_once(tmp_path):
    async def run():
        clock = Clock()
        runtime = create_runtime(data_dir=tmp_path, clock=clock)
        try:
            await prepare(runtime)
            before = state(runtime)
            denied = await send(runtime, f"接受派遣 {HERB} 整治", "wrong-place")
            assert not denied.ok and "百草坡" in denied.data["reason"]
            assert state(runtime) == before
            invalid = await send(runtime, f"接受派遣 {HERB} 疾行", "invalid")
            assert "疾行" in invalid.data["reason"] and invalid.data["subject"]
            assert state(runtime) == before
            await move(runtime, clock, "百草坡")
            denied = await send(runtime, f"接受派遣 {HERB} 整治", "no-wood")
            assert "木材" in denied.data["reason"]
            await move(runtime, clock, "近郊")
            await herb_supplies(runtime, clock)
            original = player(runtime)
            results = await asyncio.gather(*(send(runtime, f"接受派遣 {HERB} 整治", "same") for _ in range(2)))
            assert all(r.ok for r in results) and sum(r.data["idempotent_replay"] for r in results) == 1
            cancelled = await send(runtime, "取消派遣", "cancel")
            assert cancelled.ok and json.loads(player(runtime)["inventory_json"]) == json.loads(original["inventory_json"])
            replay = await send(runtime, "取消派遣", "cancel")
            assert replay.data["idempotent_replay"]
            accepted = await send(runtime, f"接受派遣 {HERB} 踏勘", "second")
            assert accepted.ok
            clock.advance(seconds=61)
            before = state(runtime)
            denied = await send(runtime, "取消派遣", "too-late")
            assert denied.code == "DISPATCH_CANCEL_WINDOW_EXPIRED" and state(runtime) == before
            clock.advance(hours=2)
            outcomes = await asyncio.gather(*(send(runtime, "结算派遣", "settle") for _ in range(2)))
            assert all(r.ok for r in outcomes) and sum(r.data["idempotent_replay"] for r in outcomes) == 1
            before = state(runtime)
            limited = await send(runtime, f"接受派遣 {HERB} 踏勘", "third")
            assert limited.code == "DISPATCH_DAILY_LIMIT" and state(runtime) == before
        finally:
            await runtime.close()
    asyncio.run(run())


@pytest.mark.parametrize("stage", ["accept", "settle", "cancel"])
def test_faults_fully_rollback_then_same_operation_retries(tmp_path, stage, caplog):
    async def run():
        clock = Clock()
        runtime = create_runtime(data_dir=tmp_path, clock=clock)
        try:
            await prepare(runtime)
            await herb_supplies(runtime, clock)
            command = f"接受派遣 {HERB} 整治"
            if stage != "accept":
                assert (await send(runtime, command, "prepare")).ok
                command = "结算派遣" if stage == "settle" else "取消派遣"
                if stage == "settle":
                    clock.advance(hours=8)
            before = state(runtime)
            with patch.object(runtime.repository, "_record_dispatch_operation", side_effect=RuntimeError("dispatch ledger write failed")):
                with pytest.raises(RuntimeError, match="dispatch ledger write failed"):
                    await send(runtime, command, "fault")
            assert state(runtime) == before
            assert "operation=fault" in caplog.text and "dispatch command failed command=" in caplog.text
            assert (await send(runtime, command, "fault")).ok
            before = state(runtime)
            assert (await send(runtime, command, "fault")).data["idempotent_replay"]
            assert state(runtime) == before
        finally:
            await runtime.close()
    asyncio.run(run())


@pytest.mark.parametrize("damage", ["null", "refund", "outcome", "cost", "operation"])
def test_bad_snapshots_and_operations_fail_with_context(tmp_path, damage, caplog):
    async def run():
        clock = Clock()
        runtime = create_runtime(data_dir=tmp_path, clock=clock)
        try:
            await prepare(runtime)
            await herb_supplies(runtime, clock)
            assert (await send(runtime, f"接受派遣 {HERB} 整治", "prepare")).ok
            with runtime.repository._connect() as db:
                if damage == "operation":
                    db.execute("UPDATE operations SET result_json='[]' WHERE operation_id='prepare'")
                else:
                    frozen = json.loads(db.execute("SELECT snapshot_json FROM dispatch_assignments").fetchone()[0])
                    if damage == "null":
                        frozen["planning"] = None
                    elif damage == "refund":
                        frozen["failure_refunds"]["item.mat.wood"] = 999
                    elif damage == "outcome":
                        frozen["outcome"] = "unknown"
                    else:
                        frozen["costs"]["stamina"] = 0
                    db.execute("UPDATE dispatch_assignments SET snapshot_json=?", (json.dumps(frozen),))
            clock.advance(hours=8)
            before = state(runtime)
            command = f"接受派遣 {HERB} 整治" if damage == "operation" else "结算派遣"
            with pytest.raises(OperationResultMalformedError if damage == "operation" else ContentError):
                await send(runtime, command, "prepare" if damage == "operation" else "broken")
            assert state(runtime) == before
            assert "dispatch command failed" in caplog.text and "Traceback" in caplog.text
        finally:
            await runtime.close()
    asyncio.run(run())


def test_huge_assets_and_old_snapshot_remain_exact(tmp_path):
    async def run():
        clock = Clock()
        runtime = create_runtime(data_dir=tmp_path, clock=clock)
        try:
            await prepare(runtime)
            await herb_supplies(runtime, clock)
            huge = 10 ** 150 + 71
            with runtime.repository._connect() as db:
                db.execute("UPDATE players SET spirit_stones=?, cultivation=?, total_cultivation=?", (str(huge).encode(), str(huge).encode(), str(huge).encode()))
            definition = select_preparation(dispatch_definitions()[HERB], None, bundled_content())
            with force(definition, "success", "big"):
                assert (await send(runtime, f"接受派遣 {HERB}", "accept")).ok
            # A pre-preparation snapshot must not receive a new plan after upgrade.
            with runtime.repository._connect() as db:
                snapshot = json.loads(db.execute("SELECT snapshot_json FROM dispatch_assignments").fetchone()[0])
                del snapshot["planning"]
                db.execute("UPDATE dispatch_assignments SET snapshot_json=?", (json.dumps(snapshot),))
            status = await send(runtime, "派遣状态")
            assert status.data["assignment"]["planning"] is None
            clock.advance(hours=2)
            result = await send(runtime, "结算派遣", "settle")
            assert result.ok and result.data["planning"] is None
            assert player_integer(player(runtime), "spirit_stones") == huge + 20
            assert player_integer(player(runtime), "cultivation") == huge
            assert player_integer(player(runtime), "total_cultivation") == huge
        finally:
            await runtime.close()
    asyncio.run(run())


def test_native_qq_planning_markdown_prefix_and_plain_text(tmp_path):
    from test_adapter_simulation import _qq_group_event
    from test_messaging import FakeBot
    from nonebot_plugin_xiuxian_3.adapters.qq import normalize_event
    from nonebot_plugin_xiuxian_3.adapters.messaging import send_markdown_message, markdown_to_text

    class QQBot(FakeBot):
        __module__ = "nonebot.adapters.qq.bot"

    async def run():
        runtime = create_runtime(data_dir=tmp_path)
        try:
            for text in ("开始修仙", "寻仙问道"):
                initial = normalize_event(_qq_group_event(text, message_id="initial-" + text))
                assert (await runtime.adapters.dispatch("qq.official", initial.context, initial.text)).ok
            event = _qq_group_event("派遣预览 百草坡药泉勘务")
            message = normalize_event(event)
            result = await runtime.adapters.dispatch("qq.official", replace(message.context, operation_id="qq-preview"), message.text)
            assert result.ok and "沈蘅" in result.message and "踏勘" in result.message and "整治" in result.message
            assert not result.actions and not result.message.startswith("#") and "\n>" not in result.message
            bot = QQBot()
            sent = await send_markdown_message(bot, event, result.message, capabilities=("markdown", "keyboard"), command_prefix="!")
            assert sent.sent_format == "markdown"
            actual = unquote(str(bot.sent[0][1]))
            assert "!开始探索 百草坡采集" in actual and "enter=false" in actual
            assert "command:" not in actual and "keyboard" not in actual
            plain = markdown_to_text(result.message)
            assert "沈蘅" in plain and "开始探索 百草坡采集" in plain and "mqqapi" not in plain
            helped = normalize_event(_qq_group_event("修仙帮助 生活"))
            help_result = await runtime.adapters.dispatch("qq.official", helped.context, helped.text)
            assert "派遣状态" in help_result.message and "药泉" in help_result.message and not help_result.actions
        finally:
            await runtime.close()
    asyncio.run(run())


@pytest.mark.parametrize("method,args", [("preview", ("任务", "踏勘", "多余")),
                                        ("accept", ("任务", "踏勘", "多余")),
                                        ("settle", ("编号", "多余")),
                                        ("cancel", ("编号", "多余")),
                                        ("status", ("多余",))])
def test_invalid_dispatch_parameters_keep_reason_and_subject(method, args):
    from nonebot_plugin_xiuxian_3.contracts import CommandContext
    from nonebot_plugin_xiuxian_3.xiuxian.specials.dispatch_use_cases import DispatchApplication

    context = CommandContext(adapter="onebot.v11", user_id="invalid-args", command_args=args)
    result = asyncio.run(getattr(DispatchApplication(None), method)(context))
    assert not result.ok and result.code == "INVALID_DISPATCH_COMMAND"
    assert result.data["reason"] == result.message
    assert result.data["subject"] == " ".join(args)


def test_qq_ready_preparations_keyboard_and_action_fallback():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from test_adapter_simulation import _qq_group_event
    from test_messaging import FakeBot
    from nonebot_plugin_xiuxian_3.adapters.qq import normalize_event
    from nonebot_plugin_xiuxian_3.adapters.messaging import send_markdown_message
    from nonebot_plugin_xiuxian_3.xiuxian.specials.dispatch_models import DispatchPreviewRecord
    from nonebot_plugin_xiuxian_3.xiuxian.specials.dispatch_use_cases import DispatchApplication

    class QQBot(FakeBot):
        __module__ = "nonebot.adapters.qq.bot"

    async def run():
        bundle = bundled_content()
        definition = dispatch_definitions(bundle)[HERB]
        # Only presentation differs here; the real six-plan asset chain is covered above.
        records = tuple(
            DispatchPreviewRecord(
                selected.key, selected.label, selected.description, selected.duration_seconds,
                selected.daily_limit, 0, dict(selected.costs), True,
                planning=freeze_planning(selected, "success", bundle),
            )
            for selected in (select_preparation(definition, name, bundle) for name in ("踏勘", "整治"))
        )
        repository = SimpleNamespace(content=bundle, preview_dispatch=AsyncMock(return_value=records))
        event = _qq_group_event("派遣预览 百草坡药泉勘务")
        context = replace(normalize_event(event).context, command_args=(definition.label,))
        result = await DispatchApplication(repository).preview(context)
        assert result.ok and len(result.actions) == 2
        assert all(action.enter for action in result.actions)
        assert "接受派遣" not in unquote(result.message)
        for capabilities, expected in ((('markdown', 'keyboard'), 'markdown+keyboard'),
                                       (('markdown',), 'markdown'), ((), 'text')):
            bot = QQBot()
            sent = await send_markdown_message(bot, event, result.message, capabilities=capabilities,
                                               actions=result.actions, command_prefix="!")
            assert sent.sent_format == expected
            actual = unquote(str(bot.sent[0][1]))
            for name in ("踏勘", "整治"):
                command = "接受派遣 百草坡药泉勘务 " + name
                assert actual.count(command) == 1
                assert ("!" + command in actual) == bool(capabilities)
            assert "command:" not in actual and "/接受派遣" not in actual
            if expected == 'markdown+keyboard':
                assert "keyboard" in actual and "enter=false" in actual
            elif expected == 'markdown':
                assert "keyboard" not in actual and "enter=false" in actual
            else:
                assert "mqqapi" not in actual and "keyboard" not in actual
    asyncio.run(run())


def test_source_entry_candidate_and_real_exception_are_not_hidden(tmp_path, caplog):
    from nonebot_plugin_xiuxian_3.xiuxian.exploration.rules import exploration_encounter_selection
    selected, candidates = exploration_encounter_selection("explore.gather_basalt_pass", seed="entry",
                                                          realm_key="qi_gathering", realm_layer=1)
    assert selected == "enemy.basalt_young_mole"
    assert candidates == [{"enemy_key": selected, "weight": 20}]

    async def run():
        clock = Clock()
        runtime = create_runtime(data_dir=tmp_path, clock=clock)
        try:
            await prepare(runtime)
            await move(runtime, clock, "玄武岩径")
            before = state(runtime)
            with patch("nonebot_plugin_xiuxian_3.xiuxian.exploration.repository.exploration_encounter_selection",
                       side_effect=ContentError("basalt encounter candidates corrupted")):
                with pytest.raises(ContentError, match="basalt encounter candidates corrupted"):
                    await send(runtime, "开始探索 玄武岩径采集", "source-fault")
            assert state(runtime) == before
            assert "command=开始探索" in caplog.text and "operation=source-fault" in caplog.text and "Traceback" in caplog.text
        finally:
            await runtime.close()
    asyncio.run(run())
