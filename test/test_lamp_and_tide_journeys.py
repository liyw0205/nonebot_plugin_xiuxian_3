from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from datetime import timedelta
from urllib.parse import quote

import pytest

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.adventures.mainline import mainline_definitions
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle, ContentError
from nonebot_plugin_xiuxian_3.xiuxian.exploration.rules import (
    battle_roll_bp, cloud_boat_storm_roll_bp, settlement_result,
)
from nonebot_plugin_xiuxian_3.xiuxian.production.rules import random_quality_bp, recipe_definitions
from nonebot_plugin_xiuxian_3.xiuxian.rewards.rules import reward_pool_outcomes
from nonebot_plugin_xiuxian_3.xiuxian.specials.idle_rules import idle_route_definitions, select_wilderness_choice
from test_companion_old_trail_mainline import _database_state, _inventory
from test_mainline_vertical_slice import MutableClock, _copy_content
from test_wilderness_idle import starter


ARCS = {
    "mist_lamp": {
        "title": "雾隐守灯", "realm": "qi_gathering", "layer": 4,
        "route": "雾隐洞天守灯", "route_key": "idle.mist_lamp_watch", "hours": 6,
        "choices": ("固灯筛砂", "照壁辨叶"), "commission": "灯阵续灵",
        "mode": "explore.mist_grotto", "explore": "雾隐洞天探索", "proof": "item.mat.array_sand",
        "stages": ("验牌入雾", "长灯照壁", "归谷续灯"),
    },
    "cloud_tide": {
        "title": "云舟候潮", "realm": "golden_core", "layer": 1,
        "route": "云舟渡口候潮", "route_key": "idle.cloud_dock_tide", "hours": 8,
        "choices": ("扶舷搬铁", "护袋理砂"), "commission": "候潮备材",
        "mode": "explore.cloud_boat_trial", "explore": "云舟试炼", "proof": "item.ticket.cloud_boat_fragment",
        "stages": ("问潮登舟", "候潮交班", "航材归镇"),
    },
}


class Journey:
    def __init__(self, data, adapter):
        self.data = data
        self.adapter = adapter
        self.clock = MutableClock()
        self.runtime = create_runtime(data_dir=data, clock=self.clock, adapters=(adapter,))
        self.sequence = 0

    async def send(self, text, operation="", user="gatherer"):
        self.sequence += 1
        return await self.runtime.dispatch(CommandContext(
            adapter=self.adapter, user_id=user, operation_id=operation or f"journey-{self.sequence}",
            capabilities=("text", "markdown", "keyboard"),
        ), text)

    async def move(self, destination):
        started = await self.send(f"前往 {destination}")
        assert started.code == "TRAVEL_STARTED", (destination, started.message)
        self.clock.advance(minutes=3)
        result = await self.send("结算移动")
        assert result.code == "TRAVEL_COMPLETED", result.message
        return started

    async def restart(self):
        await self.runtime.close()
        self.runtime = create_runtime(data_dir=self.data, clock=self.clock, adapters=(self.adapter,))
        await self.runtime.repository.initialize()

    async def next_day(self):
        self.clock.value = (self.clock.value + timedelta(days=1)).replace(hour=0, minute=0, second=0)
        assert (await self.send("恢复状态")).ok

    async def gather(self, route, hours, operation):
        started = await self.send(f"开始挂机 {route}", operation)
        assert started.code == "IDLE_STARTED", started.message
        self.clock.advance(hours=hours)
        result = await self.send("领取挂机", f"{operation}-claim")
        assert result.code == "IDLE_CLAIMED" and not result.data["fallback"], result.message
        return result

    def fail_on(self, operation):
        with self.runtime.repository._connect() as connection:
            connection.execute(
                "CREATE TRIGGER fail_journey BEFORE INSERT ON operations "
                f"WHEN NEW.operation_id='{operation}' BEGIN SELECT RAISE(ABORT, 'forced journey failure'); END"
            )

    def repair(self):
        with self.runtime.repository._connect() as connection:
            connection.execute("DROP TRIGGER fail_journey")

    async def reject_corrupt_receipt(self, table, key, identifier, field, value, command, operation):
        with self.runtime.repository._connect() as connection:
            original = connection.execute(f"SELECT {field} FROM {table} WHERE {key}=?", (identifier,)).fetchone()[0]
            connection.execute(f"UPDATE {table} SET {field}=? WHERE {key}=?", (value, identifier))
        try:
            before = _database_state(self.runtime)
            result = await self.send(command, operation)
            assert result.code == "PERSISTENCE_ERROR", (operation, result.code, result.message)
            assert _database_state(self.runtime) == before
        finally:
            with self.runtime.repository._connect() as connection:
                connection.execute(f"UPDATE {table} SET {field}=? WHERE {key}=?", (original, identifier))


def good_order(prefix):
    return next(f"{prefix}-{i}" for i in range(200) if random_quality_bp(f"{prefix}-{i}") == 1000)


@pytest.mark.parametrize("arc", ARCS)
@pytest.mark.parametrize("adapter,choice_index", [("onebot.v11", 0), ("qq.official", 1)])
def test_public_journey_producers_choices_consumers_restart_and_zero_write(tmp_path, arc, adapter, choice_index):
    async def run():
        journey = Journey(_copy_content(tmp_path), adapter)
        spec = ARCS[arc]
        title, route = spec["title"], spec["route"]
        choice = spec["choices"][choice_index]

        async def story_start(index, operation):
            result = await journey.send(f"开始{title}主线 {spec['stages'][index - 1]}", operation)
            assert result.code == "MAINLINE_STARTED", result.message
            return result

        async def story_claim(index, operation):
            return await journey.send(f"领取{title}主线奖励 {spec['stages'][index - 1]}", operation)

        try:
            await starter(journey.runtime, adapter=adapter, path="辅修 布阵")
            before = _database_state(journey.runtime)
            assert (await journey.send(f"开始{title}主线 {spec['stages'][0]}", "denied")).code == "MAINLINE_REQUIREMENT_MISSING"
            assert _database_state(journey.runtime) == before
            # Only progression prerequisites are fixtures; all materials, passes,
            # journeys and evidence below come through public application calls.
            with journey.runtime.repository._connect() as connection:
                connection.execute(
                    "UPDATE players SET realm_key=?,realm_layer=?,stamina=100,stamina_max=100,"
                    "energy=100,energy_max=100,spirit_stones=1000",
                    (spec["realm"], spec["layer"]),
                )
            preview = await journey.send(f"挂机预览 {route}")
            assert preview.ok and not preview.data["routes"][0]["ready"]
            before = _database_state(journey.runtime)
            denied = await journey.send(f"开始挂机 {route} {choice}", "wrong-place")
            assert not denied.ok and denied.data["reason"]
            assert _database_state(journey.runtime) == before
            await story_start(1, "start-1")
            if arc == "mist_lamp":
                await journey.move("百草坡")
                await journey.gather("百草坡采药 扶徒归棚", 4, "herb-source")
                await journey.move("近郊")
                await journey.move("铁木林")
                await journey.gather("铁木林拾材 顺纹取材", 6, "wood-source")
                await journey.move("近郊")
                await journey.move("青石镇")
                original = _inventory(journey.runtime)
                pass_operation = good_order("make-pass")
                started = await journey.send("开始生产 洞天验行牌", pass_operation)
                assert started.code == "PRODUCTION_STARTED", started.message
                assert original["item.mat.wood"] - _inventory(journey.runtime)["item.mat.wood"] == 1
                assert original["item.herb.blood_grass"] - _inventory(journey.runtime)["item.herb.blood_grass"] == 2
                journey.clock.advance(seconds=30)
                made = await journey.send("领取生产", "pass-claim")
                assert made.ok and made.data["success"] and made.data["outputs"] == {"item.cave_pass_basic": 1}
                await journey.move("灵泉谷")
                pass_before = _inventory(journey.runtime)["item.cave_pass_basic"]
                await journey.move("雾隐洞天")
                assert pass_before - _inventory(journey.runtime).get("item.cave_pass_basic", 0) == 1
            else:
                await journey.move("青石镇")
                await journey.move("云城")
                await journey.move("云舟渡口")

            seed = next(
                f"survey-{i}" for i in range(1000)
                if battle_roll_bp(f"survey-{i}:battle") >= 2500
                and cloud_boat_storm_roll_bp(f"survey-{i}") >= 2000
                and settlement_result(spec["mode"], f"survey-{i}").get(spec["proof"], 0) > 0
            )
            started = await journey.send(f"开始探索 {spec['explore']}", seed)
            assert started.code == "EXPLORATION_STARTED", started.message
            before = _database_state(journey.runtime)
            assert (await story_claim(1, "before-survey")).code == "MAINLINE_OBJECTIVES_INCOMPLETE"
            assert _database_state(journey.runtime) == before
            journey.clock.advance(minutes=5)
            await journey.restart()
            explored = await journey.send("结算探索", "survey-claim")
            assert explored.ok, explored.message
            if arc == "mist_lamp":
                claim_command = f"领取{title}主线奖励 {spec['stages'][0]}"
                await journey.reject_corrupt_receipt(
                    "exploration_sessions", "exploration_id", explored.data["exploration_id"],
                    "operation_id", "missing-survey", claim_command, "missing-survey-start",
                )
                with journey.runtime.repository._connect() as connection:
                    receipt_json = connection.execute("SELECT result_json FROM operations WHERE operation_id='survey-claim'").fetchone()[0]
                foreign = json.loads(receipt_json)
                foreign["player"]["player_id"] = "another-cultivator"
                await journey.reject_corrupt_receipt(
                    "operations", "operation_id", "survey-claim", "result_json",
                    json.dumps(foreign), claim_command, "foreign-survey-receipt",
                )
                await journey.reject_corrupt_receipt(
                    "operations", "operation_id", "survey-claim", "result_json",
                    receipt_json.replace('"result":', '"result": {}, "result":', 1),
                    claim_command, "duplicate-survey-json",
                )
            first_claim = await story_claim(1, "claim-1")
            assert first_claim.code == "MAINLINE_REWARD_CLAIMED", first_claim.message
            assert first_claim.actions[0].command == f"开始{title}主线 {arc}.2"
            await journey.next_day()
            # An assignment made before the stage remains stale even if claimed later.
            assert (await journey.send(f"开始挂机 {route} {choice}", "old-idle")).ok
            second = await story_start(2, "start-2")
            journey.clock.advance(hours=spec["hours"])
            assert (await journey.send("领取挂机", "old-idle-claim")).ok
            before = _database_state(journey.runtime)
            assert (await story_claim(2, "stale-story")).code == "MAINLINE_OBJECTIVES_INCOMPLETE"
            assert _database_state(journey.runtime) == before
            await journey.next_day()
            assert (await journey.send(f"开始挂机 {route} {choice}", "cancel-start")).ok
            assert (await journey.send("取消挂机", "cancel")).code == "IDLE_CANCELLED"
            assert (await story_claim(2, "cancel-story")).code == "MAINLINE_OBJECTIVES_INCOMPLETE"
            assert (await journey.send(f"开始挂机 {route} {choice}", "late-start")).ok
            before = _database_state(journey.runtime)
            assert (await journey.send("领取挂机", "early")).code == "IDLE_CLAIM_TOO_EARLY"
            assert _database_state(journey.runtime) == before
            journey.clock.advance(hours=spec["hours"] + 25)
            late = await journey.send("领取挂机", "late")
            assert late.ok and late.data["fallback"]
            assert not any(key.startswith("codex.") for key in late.data["reward"])
            assert (await story_claim(2, "late-story")).code == "MAINLINE_OBJECTIVES_INCOMPLETE"
            await journey.next_day()
            before = _database_state(journey.runtime)
            assert not (await journey.send(f"开始挂机 {route} 错误选择", "bad-choice")).ok
            assert _database_state(journey.runtime) == before
            assert (await journey.send(f"开始挂机 {route} {choice}", "full-idle")).ok
            before = _database_state(journey.runtime)
            assert (await journey.send(f"开始挂机 {route} {choice}", "full-idle")).data["idempotent_replay"]
            other_choice = spec["choices"][1 - choice_index]
            assert (await journey.send(f"开始挂机 {route} {other_choice}", "full-idle")).code == "OPERATION_CONFLICT"
            assert _database_state(journey.runtime) == before
            with journey.runtime.repository._connect() as connection:
                frozen_json = connection.execute("SELECT snapshot_json FROM idle_assignments WHERE operation_id='full-idle'").fetchone()[0]
            frozen = json.loads(frozen_json)
            journey.clock.advance(hours=spec["hours"])
            await journey.restart()
            status = await journey.send("挂机状态")
            assert choice in status.message and status.data["claimable"]
            with journey.runtime.repository._connect() as connection:
                broken = {**frozen, "full_reward": {"item.missing": True}}
                connection.execute("UPDATE idle_assignments SET snapshot_json=? WHERE operation_id='full-idle'", (json.dumps(broken),))
            before = _database_state(journey.runtime)
            with pytest.raises(ValueError):
                await journey.send("领取挂机", "full-claim")
            assert _database_state(journey.runtime) == before
            with journey.runtime.repository._connect() as connection:
                connection.execute("UPDATE idle_assignments SET snapshot_json=? WHERE operation_id='full-idle'", (frozen_json,))
            journey.fail_on("full-claim")
            before = _database_state(journey.runtime)
            assert (await journey.send("领取挂机", "full-claim")).code == "PERSISTENCE_ERROR"
            assert _database_state(journey.runtime) == before
            journey.repair()
            original = _inventory(journey.runtime)
            full = await journey.send("领取挂机", "full-claim")
            assert full.ok and full.data["reward"] == frozen["full_reward"]
            after = _inventory(journey.runtime)
            assert all(after.get(key, 0) - original.get(key, 0) == amount for key, amount in full.data["reward"].items() if key.startswith("item."))
            assert (await story_claim(2, "claim-2")).code == "MAINLINE_REWARD_CLAIMED"
            if arc == "mist_lamp":
                await journey.move("灵泉谷")
                await journey.move("青石镇")
                await journey.next_day()
                assert (await journey.send("接取委托 灯阵续灵", "old-lamp-order")).code == "COMMISSION_ACCEPTED"
            await story_start(3, "start-3")
            if arc == "mist_lamp":
                await journey.move("灵泉谷")
                original = _inventory(journey.runtime)
                started = await journey.send("开始生产 基础聚灵阵", good_order("make-array"))
                assert started.code == "PRODUCTION_STARTED", started.message
                assert original["item.mat.array_sand"] - _inventory(journey.runtime)["item.mat.array_sand"] == 2
                journey.clock.advance(seconds=90)
                made = await journey.send("领取生产", "array-claim")
                assert made.ok and made.data["success"], made.message
            else:
                await journey.move("云城")
            await journey.move("青石镇")
            if arc == "mist_lamp":
                assert (await journey.send("交付委托 灯阵续灵", "old-lamp-delivery")).code == "COMMISSION_DELIVERED"
                before = _database_state(journey.runtime)
                assert (await story_claim(3, "old-lamp-story")).code == "MAINLINE_OBJECTIVES_INCOMPLETE"
                assert _database_state(journey.runtime) == before
                await journey.move("灵泉谷")
                assert (await journey.send("开始生产 基础聚灵阵", good_order("make-fresh-array"))).code == "PRODUCTION_STARTED"
                journey.clock.advance(seconds=90)
                fresh_array = await journey.send("领取生产", "fresh-array-claim")
                assert fresh_array.ok and fresh_array.data["success"]
                await journey.move("青石镇")
            await journey.next_day()
            accepted = await journey.send(f"接取委托 {spec['commission']}", "accept-final")
            assert accepted.code == "COMMISSION_ACCEPTED", accepted.message
            journey.fail_on("deliver-final")
            before = _database_state(journey.runtime)
            assert (await journey.send(f"交付委托 {spec['commission']}", "deliver-final")).code == "PERSISTENCE_ERROR"
            assert _database_state(journey.runtime) == before
            journey.repair()
            original = _inventory(journey.runtime)
            delivered = await journey.send(f"交付委托 {spec['commission']}", "deliver-final")
            assert delivered.code == "COMMISSION_DELIVERED", delivered.message
            spent = {"item.array.gathering_basic": 1} if arc == "mist_lamp" else {"item.material.cloud_iron": 2, "item.mat.array_sand": 1}
            assert all(original[key] - _inventory(journey.runtime).get(key, 0) == amount for key, amount in spent.items())
            if arc == "mist_lamp":
                await journey.reject_corrupt_receipt(
                    "town_commission_claims", "claim_id", accepted.data["claim_id"],
                    "deliver_operation_id", "missing-lamp-delivery", f"领取{title}主线奖励 {spec['stages'][2]}",
                    "missing-lamp-receipt",
                )
            await journey.restart()
            journey.fail_on("claim-3")
            before = _database_state(journey.runtime)
            assert (await story_claim(3, "claim-3")).code == "PERSISTENCE_ERROR"
            assert _database_state(journey.runtime) == before
            journey.repair()
            # Closing live content must not alter a frozen story or operation.
            bundle = journey.runtime.repository.content
            records = dict(bundle._records)
            for (kind, key), value in list(records.items()):
                if key.startswith(f"{arc}.") or key in {spec["route_key"], "codex.story.mist_lamp_handover"}:
                    records[kind, key] = {**value, "status": "locked"}
            journey.runtime.repository.content = replace(bundle, _records=records)
            if arc == "mist_lamp":
                concurrent = await asyncio.gather(
                    story_claim(3, "claim-3"), story_claim(3, "claim-3"),
                )
                assert all(item.code == "MAINLINE_REWARD_CLAIMED" for item in concurrent)
                assert sorted(item.data["idempotent_replay"] for item in concurrent) == [False, True]
                final = concurrent[0]
            else:
                final = await story_claim(3, "claim-3")
            assert final.code == "MAINLINE_REWARD_CLAIMED", final.message
            before = _database_state(journey.runtime)
            assert (await story_claim(3, "claim-3")).data["idempotent_replay"]
            assert (await journey.send("领取挂机", "full-claim")).data["idempotent_replay"]
            assert _database_state(journey.runtime) == before
            if arc == "mist_lamp":
                with journey.runtime.repository._connect() as connection:
                    assert connection.execute("SELECT COUNT(*) FROM codex_entries WHERE entry_key='codex.story.mist_lamp_handover'").fetchone()[0] == 1
                    assert connection.execute("SELECT COUNT(*) FROM activity_events WHERE event_key='story.mainline.mist_lamp:mist_lamp.3'").fetchone()[0] == 1
            from nonebot_plugin_xiuxian_3.adapters.message.markdown import _qq_command_links, markdown_to_text

            converted = _qq_command_links(second.message, command_prefix="!")
            assert quote(f"!开始挂机 {route} {choice}", safe="") in converted
            assert "enter=false" in converted and "command:" not in markdown_to_text(second.message)
            for category in ("探索", "生活"):
                assert f"{title}主线" in (await journey.send(f"修仙帮助 {category}")).message
        finally:
            await journey.runtime.close()
    asyncio.run(run())


@pytest.mark.parametrize("arc", ARCS)
@pytest.mark.parametrize("damage", ["body", "source", "weight", "journal", "recipe", "consumer", "location"])
def test_lamp_and_tide_content_rejects_broken_closed_loops(tmp_path, arc, damage):
    data = _copy_content(tmp_path)
    spec = ARCS[arc]
    if damage in {"body", "source"}:
        path = data / "剧情/主线.json"
        document = json.loads(path.read_text(encoding="utf-8"))
        row = next(row for row in document["records"] if row["key"] == f"{arc}.2")
        if damage == "body":
            row["body"] = "只有标题"
        else:
            row["objectives"][0]["route_key"] = "idle.missing"
    elif damage == "weight":
        path = data / "奖励/奖励.json"
        document = json.loads(path.read_text(encoding="utf-8"))
        pool = "reward_pool.idle.mist_lamp" if arc == "mist_lamp" else "reward_pool.idle.cloud_dock"
        next(row for row in document["records"] if row["key"] == pool)["outcomes"][0]["weight"] = 0
    else:
        path = data / "生活/生活.json"
        document = json.loads(path.read_text(encoding="utf-8"))
        row = next(row for row in document["records"] if row["key"] == spec["route_key"])
        if damage == "journal":
            row["gathering_journal"]["complete_text"] = " "
        elif damage == "recipe":
            row["wilderness_event"]["choices"][0]["recipe_keys"] = ["recipe.missing"]
        elif damage == "location":
            row["requirements"]["location_key"] = "location.missing"
        else:
            commission = "town_commission.lamp_array" if arc == "mist_lamp" else "town_commission.tide_supplies"
            next(row for row in document["records"] if row["key"] == commission)["inputs"][0]["item_key"] = "item.missing"
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ContentError):
        mainline_definitions(ContentBundle.load(data), story_key=f"story.mainline.{arc}")
        idle_route_definitions(ContentBundle.load(data))


@pytest.mark.parametrize("arc", ARCS)
def test_lamp_and_tide_choices_have_different_costs_and_guaranteed_consumable_yields(arc):
    spec = ARCS[arc]
    route = idle_route_definitions()[spec["route_key"]]
    choices = [select_wilderness_choice(route, name) for name in spec["choices"]]
    assert choices[0].stamina_cost > choices[1].stamina_cost
    assert choices[1].energy_cost > choices[0].energy_cost
    assert choices[0].pool_key != choices[1].pool_key
    for choice in choices:
        for _, reward in reward_pool_outcomes(choice.pool_key):
            if arc == "mist_lamp":
                assert reward["item.mat.array_sand"] >= 2
            else:
                assert reward["item.material.cloud_iron"] >= 2 and reward["item.mat.array_sand"] >= 1


@pytest.mark.parametrize("damage", ["false_receipts", "numeric_receipts", "stale_order", "wrong_input", "missing_handover"])
def test_mist_lamp_rejects_invalid_owned_evidence_contract(tmp_path, damage):
    data = _copy_content(tmp_path)
    path = data / "剧情/主线.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    stages = {row["key"]: row for row in document["records"] if row.get("story_key") == "story.mainline.mist_lamp"}
    if damage in {"false_receipts", "numeric_receipts"}:
        stages["mist_lamp.1"]["objectives"][-1]["owned_receipts"] = False if damage == "false_receipts" else 1
    elif damage == "stale_order":
        stages["mist_lamp.3"]["objectives"][-1]["delivery_evidence"]["fresh_acceptance"] = False
    elif damage == "wrong_input":
        stages["mist_lamp.3"]["objectives"][-1]["delivery_evidence"]["inputs"] = {"item.mat.array_sand": 2}
    else:
        stages["mist_lamp.3"]["first_clear_reward"]["codex.story.missing"] = 1
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ContentError):
        mainline_definitions(ContentBundle.load(data), story_key="story.mainline.mist_lamp")


@pytest.mark.parametrize("outcome", ["won", "lost"])
def test_mist_lamp_owned_evidence_follows_the_actual_exploration_battle(tmp_path, outcome):
    from test_exploration_mist_content import (
        FROZEN_REWARDS, _operation_for_encounter, _prepare_player, _set_guardian_stats, _set_pool,
    )
    from nonebot_plugin_xiuxian_3.xiuxian.adventures.exploration_evidence import has_owned_exploration_reward

    async def run():
        data = _copy_content(tmp_path)
        _set_pool(data, FROZEN_REWARDS)
        _set_guardian_stats(data, outcome=outcome)
        path = data / "战斗/遭遇池.json"
        document = json.loads(path.read_text(encoding="utf-8"))
        next(row for row in document["records"] if row["key"] == "encounter.cave.mist_grotto")["candidates"] = [{"enemy_key": "enemy.mist_guardian", "weight": 1}]
        path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
        journey = Journey(data, "onebot.v11")
        objective = dict(mainline_definitions(ContentBundle.load(data), story_key="story.mainline.mist_lamp")[0].objectives[-1])
        try:
            await _prepare_player(journey.runtime, "onebot.v11", "gatherer", max_hp=20000 if outcome == "won" else 1, initiative=20000 if outcome == "won" else 1)
            started_at = journey.clock.value.isoformat()
            with journey.runtime.repository._connect() as connection:
                player_id = connection.execute("SELECT id FROM players").fetchone()[0]
                baseline = connection.execute("SELECT COALESCE(MAX(rowid),0) FROM operations").fetchone()[0]
            operation = _operation_for_encounter("lamp-owned", 2500)
            assert (await journey.send("开始探索 雾隐洞天探索", operation)).code == "EXPLORATION_STARTED"
            journey.clock.advance(minutes=5)
            result = await journey.send("结算探索", "battle-survey-claim")
            assert result.code == "EXPLORATION_SETTLED" and result.data["battle_outcome"] == outcome
            before = _database_state(journey.runtime)
            with journey.runtime.repository._connect() as connection:
                assert has_owned_exploration_reward(connection, player_id, objective, baseline, started_at) is (outcome == "won")
                battle = connection.execute("SELECT result_json FROM battle_sessions WHERE battle_id=?", (result.data["battle_id"],)).fetchone()[0]
                connection.execute("UPDATE battle_sessions SET result_json='{}' WHERE battle_id=?", (result.data["battle_id"],))
                with pytest.raises(ValueError, match="matching settled battle"):
                    has_owned_exploration_reward(connection, player_id, objective, baseline, started_at)
                connection.execute("UPDATE battle_sessions SET result_json=? WHERE battle_id=?", (battle, result.data["battle_id"]))
            assert _database_state(journey.runtime) == before
        finally:
            await journey.runtime.close()
    asyncio.run(run())


@pytest.mark.parametrize("adapter", ["qq.official", "onebot.v11"])
def test_mist_lamp_help_exposes_each_stage_and_delivery_without_asset_operations(tmp_path, adapter):
    async def run():
        journey = Journey(_copy_content(tmp_path), adapter)
        try:
            assert (await journey.send("开始修仙")).ok
            before = _database_state(journey.runtime)
            for category in ("生活", "探索"):
                result = await journey.send(f"修仙帮助 {category}")
                assert result.ok
                for command in (
                    "开始雾隐守灯主线 验牌入雾", "开始雾隐守灯主线 长灯照壁",
                    "开始雾隐守灯主线 归谷续灯", "生产预览 洞天验行牌",
                    "挂机预览 雾隐洞天守灯", "接取委托 灯阵续灵", "交付委托 灯阵续灵",
                ):
                    assert command in result.message
                assert "关前接单" in result.message and "归谷续灯录" in result.message
            assert _database_state(journey.runtime) == before
        finally:
            await journey.runtime.close()
    asyncio.run(run())


def test_basic_cave_pass_declares_its_real_public_producer_and_travel_consumer():
    from nonebot_plugin_xiuxian_3.xiuxian.content import bundled_content
    from nonebot_plugin_xiuxian_3.xiuxian.world.rules import destination_definition

    bundle = bundled_content()
    sources = bundle.sources_for("item.cave_pass_basic")
    assert any(
        channel == {"operation": "production.complete", "reference": "recipe.permit.mist_grotto"}
        for source in sources for channel in source["channels"]
    )
    recipe = recipe_definitions(bundle)["recipe.permit.mist_grotto"]
    assert recipe.outputs == {"item.cave_pass_basic": 1}
    destination = destination_definition("cave.mist_grotto", bundle, source="xuantian.spirit_field")
    assert destination.pass_key == "item.cave_pass_basic" and destination.pass_quantity == 1
