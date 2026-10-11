from __future__ import annotations

import asyncio
import copy
import json
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle, ContentError
from nonebot_plugin_xiuxian_3.xiuxian.exploration.rules import settlement_result
from nonebot_plugin_xiuxian_3.xiuxian.material_content import validate_material_content
from nonebot_plugin_xiuxian_3.xiuxian.rewards.rules import reward_pool_outcomes
from test_data_completion import Flow, _edit


DATA = Path(__file__).parents[1] / "data"
RICE = "item.food.coarse_spirit_rice"
SPRING_POOL = "reward_pool.exploration.spring_gather"
MATERIALS = {
    RICE, "item.herb.blood_grass", "item.herb.spirit_leaf", "item.ore.ironstone",
    "item.mat.wood", "item.mat.array_sand", "item.spirit_water", "item.material.cloud_iron",
    "item.soul_crystal", "item.demon_core", "item.beast_blood", "item.ancestral_blood",
}


def _with_record(bundle, kind, key, **changes):
    records = dict(bundle._records)
    row = copy.deepcopy(records[(kind, key)])
    row.update(changes)
    records[(kind, key)] = row
    return replace(bundle, _records=records)


def _frozen_result(flow, exploration_id):
    with flow.runtime.repository._connect() as db:
        row = db.execute("SELECT snapshot_json FROM exploration_sessions WHERE exploration_id=?",
                         (exploration_id,)).fetchone()
    return json.loads(row["snapshot_json"])["frozen_result"]


def test_declared_material_sources_close_actual_reward_and_recipe_references():
    bundle = ContentBundle.load(DATA)
    summary = validate_material_content(bundle)
    assert {row["key"] for row in bundle.list("item") if "gathering_sources" in row} == MATERIALS
    assert summary["materials"] == 12
    assert summary["gathering_sources"] == 17
    assert summary["modes"] == 9
    assert summary["recipe_consumers"] == 29


@pytest.mark.parametrize("sources, message", [
    (None, "non-empty list"),
    ([], "non-empty list"),
    (["explore.spring_gather"], "malformed"),
    ([{"mode_key": True, "reward_pool_key": SPRING_POOL}], "non-empty strings"),
    ([{"mode_key": "explore.missing", "reward_pool_key": SPRING_POOL}], "unavailable mode"),
    ([{"mode_key": "explore.spring_gather", "reward_pool_key": "reward_pool.missing"}], "unavailable reward"),
    ([{"mode_key": "explore.spring_gather", "reward_pool_key": "reward_pool.exploration.cloud_mine"}], "not consumed"),
    ([{"mode_key": "explore.spring_gather", "reward_pool_key": SPRING_POOL}] * 2, "duplicate"),
])
def test_material_content_rejects_false_or_malformed_sources(sources, message):
    bundle = _with_record(ContentBundle.load(DATA), "item", RICE, gathering_sources=sources)
    with pytest.raises(ContentError, match=message):
        validate_material_content(bundle)


def test_material_content_rejects_a_pool_that_does_not_produce_the_material():
    bundle = _with_record(ContentBundle.load(DATA), "reward", SPRING_POOL,
                          outcomes=[{"weight": 1, "rewards": {"item.spirit_water": 1}}])
    with pytest.raises(ContentError, match="not produced"):
        validate_material_content(bundle)


@pytest.mark.parametrize("kind,key,field,value", [
    ("item", RICE, "name", ""),
    ("item", RICE, "desc", " "),
    ("reward", SPRING_POOL, "name", None),
    ("reward", SPRING_POOL, "desc", None),
])
def test_material_content_requires_player_names_and_descriptions(kind, key, field, value):
    bundle = _with_record(ContentBundle.load(DATA), kind, key, **{field: value})
    with pytest.raises(ContentError, match=f"requires non-empty {field}"):
        validate_material_content(bundle)


@pytest.mark.parametrize("quantity", [True, 1.5, 0, -1])
def test_material_content_rejects_invalid_source_quantities(quantity):
    bundle = _with_record(ContentBundle.load(DATA), "reward", SPRING_POOL,
                          outcomes=[{"weight": 1, "rewards": {RICE: quantity}}])
    with pytest.raises(ContentError):
        validate_material_content(bundle)


def test_material_content_rejects_items_without_a_real_consumer():
    bundle = _with_record(ContentBundle.load(DATA), "item", "item.seed.spirit_tree",
                          gathering_sources=[{"mode_key": "explore.spring_gather", "reward_pool_key": SPRING_POOL}])
    with pytest.raises(ContentError, match="no active production consumer"):
        validate_material_content(bundle)


def test_rice_acquisition_preserves_the_original_spring_distribution():
    bundle = ContentBundle.load(DATA)
    outcomes = reward_pool_outcomes(SPRING_POOL, bundle)
    assert tuple((weight, {key: value for key, value in rewards.items() if key != RICE})
                 for weight, rewards in outcomes) == (
        (3600, {"item.herb.spirit_leaf": 1, "item.spirit_water": 1}),
        (2400, {"item.herb.spirit_leaf": 1, "item.mat.array_sand": 1, "item.spirit_water": 1}),
        (2400, {"item.herb.spirit_leaf": 2, "item.spirit_water": 1}),
        (1600, {"item.herb.spirit_leaf": 2, "item.mat.array_sand": 1, "item.spirit_water": 1}),
    )
    assert all(rewards[RICE] == 1 for _, rewards in outcomes)


def test_public_spring_acquisition_funds_cooking_and_survives_failure_restart_and_replay(tmp_path):
    async def run():
        flow = Flow(tmp_path)
        try:
            await flow.enter("辅修 烹饪")
            # Only accumulated realm progress is shortened; all travel and items use public commands.
            flow.context(realm_key="qi_sensing", realm_layer=2)
            await flow.send("返回新手城")
            travel = await flow.send("前往 灵泉谷")
            assert travel.code == "TRAVEL_STARTED"
            flow.now = datetime.fromisoformat(travel.data["ends_at"]) + timedelta(seconds=1)
            await flow.send("结算移动")
            before_inventory = flow.inventory()
            before_stamina = flow.player()["stamina"]
            first = await flow.send("开始探索 灵泉采集", "spring-first")
            frozen = _frozen_result(flow, first.data["exploration_id"])
            assert frozen == settlement_result("explore.spring_gather", "spring-first", content=flow.runtime.content)
            assert frozen[RICE] == 1
            flow.now += timedelta(seconds=91)
            before = flow.dump()
            flow.trigger("exploration.settle")
            rejected = await flow.send("结算探索", "spring-first-settle", ok=False)
            assert rejected.code == "PERSISTENCE_ERROR"
            flow.trigger("exploration.settle", drop=True)
            assert flow.dump() == before
            changed_outcomes = flow.runtime.content.require("reward", SPRING_POOL)["outcomes"]
            for outcome in changed_outcomes:
                outcome["rewards"][RICE] = 2
            _edit(flow.root, "奖励/奖励.json", SPRING_POOL, outcomes=changed_outcomes)
            await flow.runtime.close()
            flow.runtime = create_runtime(data_dir=flow.root, clock=lambda: flow.now, adapters=("onebot.v11",))
            settled = await flow.send("结算探索", "spring-first-settle")
            assert settled.data["result"][RICE] == 1
            after = flow.dump()
            replay = await flow.send("结算探索", "spring-first-settle")
            assert replay.data["idempotent_replay"] is True
            assert flow.dump() == after
            second = await flow.send("开始探索 灵泉采集", "spring-second")
            flow.now += timedelta(seconds=91)
            await flow.send("结算探索", "spring-second-settle")
            assert flow.inventory()[RICE] == before_inventory.get(RICE, 0) + 3
            assert flow.player()["stamina"] == before_stamina - 12
            assert _frozen_result(flow, second.data["exploration_id"])[RICE] == 2
            before_inventory = flow.inventory()
            cooking_operation = "cook-acquired-rice"
            started, cooked = await flow.produce("灵米饭", operation=cooking_operation)
            assert cooked.data["outputs"] == {"item.food.spirit_rice": 2}
            assert flow.inventory()[RICE] == before_inventory[RICE] - 2
            assert flow.inventory()["item.food.spirit_rice"] == before_inventory.get("item.food.spirit_rice", 0) + 2
            before = flow.dump()
            replay = await flow.send("开始生产 灵米饭", cooking_operation)
            assert replay.data["idempotent_replay"] is True
            assert replay.data["order_id"] == started.data["order_id"]
            assert flow.dump() == before
            consumed = await flow.send("使用物品 灵米饭 精力", "use-cooked-rice")
            assert consumed.data["effect"]["restored"] > 0
            before = flow.dump()
            assert (await flow.send("使用物品 灵米饭 精力", "use-cooked-rice")).data["idempotent_replay"] is True
            assert flow.dump() == before
        finally:
            await flow.runtime.close()
    asyncio.run(run())
