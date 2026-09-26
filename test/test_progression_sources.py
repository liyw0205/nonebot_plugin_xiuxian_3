from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.exploration.rules import (
    battle_roll_bp,
    cloud_boat_storm_roll_bp,
    settlement_result,
)
from nonebot_plugin_xiuxian_3.xiuxian.progression.breakthrough.rules import breakthrough_roll_bp
from nonebot_plugin_xiuxian_3.xiuxian.progression.rules import next_layer_threshold
from nonebot_plugin_xiuxian_3.xiuxian.production.rules import random_quality_bp
from nonebot_plugin_xiuxian_3.xiuxian.world.void_rules import void_route_roll_bp


class MutableClock:
    def __init__(self) -> None:
        self.current = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.current

    def advance(self, **kwargs: int) -> None:
        self.current += timedelta(**kwargs)


def _context(adapter: str, user: str, request_id: str, operation_id: str = "") -> CommandContext:
    return CommandContext(
        adapter=adapter,
        user_id=user,
        request_id=request_id,
        operation_id=operation_id,
    )


async def _dispatch(
    runtime,
    adapter: str,
    user: str,
    index: int,
    command: str,
    *,
    operation_id: str = "",
):
    result = await runtime.adapters.dispatch(
        adapter, _context(adapter, user, f"{adapter}-{index}", operation_id), command
    )
    assert result.ok, (command, result.code, result.message)
    return result


def test_qq_and_onebot_can_produce_focus_pill_from_player_path() -> None:
    async def run() -> None:
        for adapter in ("qq.official", "onebot.v11"):
            with TemporaryDirectory() as data_dir:
                clock = MutableClock()
                runtime = create_runtime(data_dir=data_dir, clock=clock)
                user = f"focus-{adapter}"
                for index, command in enumerate(
                    (
                        "开始修仙",
                        "寻仙问道",
                        "完成引导 阅读",
                        "前往近郊",
                        "完成引导 采集",
                        "完成引导 炼丹",
                        "选择道途 辅修 炼丹",
                    )
                ):
                    await _dispatch(runtime, adapter, user, index, command)

                for index in range(2):
                    await _dispatch(runtime, adapter, user, 10 + index, "开始修炼")
                    clock.advance(minutes=10)
                    settled = await _dispatch(runtime, adapter, user, 20 + index, "结算修炼")
                    assert settled.code == "CULTIVATION_SETTLED"
                advanced = await _dispatch(runtime, adapter, user, 30, "晋升境界")
                assert advanced.data["realm_layer"] == 2

                await _dispatch(runtime, adapter, user, 31, "前往 灵泉谷")
                clock.advance(seconds=90)
                await _dispatch(runtime, adapter, user, 32, "结算移动")
                gather_operation = next(
                    f"{adapter}-spring-gather-{index}"
                    for index in range(100)
                    if settlement_result("explore.spring_gather", f"{adapter}-spring-gather-{index}")[
                        "item.herb.spirit_leaf"
                    ]
                    >= 2
                )
                await _dispatch(
                    runtime,
                    adapter,
                    user,
                    33,
                    "开始探索 灵泉采集",
                    operation_id=gather_operation,
                )
                clock.advance(seconds=90)
                explored = await _dispatch(runtime, adapter, user, 34, "结算探索")
                assert explored.data["result"]["item.herb.spirit_leaf"] >= 1
                extra_gather_operation = next(
                    f"{adapter}-spring-extra-{index}"
                    for index in range(100)
                    if settlement_result("explore.spring_gather", f"{adapter}-spring-extra-{index}")[
                        "item.herb.spirit_leaf"
                    ]
                    >= 2
                )
                await _dispatch(
                    runtime,
                    adapter,
                    user,
                    35,
                    "开始探索 灵泉采集",
                    operation_id=extra_gather_operation,
                )
                clock.advance(seconds=90)
                extra_explored = await _dispatch(runtime, adapter, user, 35, "结算探索")
                assert extra_explored.data["result"]["item.herb.spirit_leaf"] >= 2

                operation = next(
                    f"{adapter}-focus-{index}"
                    for index in range(100)
                    if random_quality_bp(f"{adapter}-focus-{index}") >= 500
                )
                started = await runtime.adapters.dispatch(
                    adapter, _context(adapter, user, "focus-start", operation),
                    "开始生产 焦点丹",
                )
                assert started.code == "PRODUCTION_STARTED"
                clock.advance(seconds=45)
                completed = await _dispatch(runtime, adapter, user, 36, "领取生产")
                assert completed.code == "PRODUCTION_COMPLETED"
                assert completed.data["outputs"] == {"item.pill.focus_low": 1}

                extra_guard_operation = next(
                    f"{adapter}-qi-guard-{index}"
                    for index in range(1000)
                    if random_quality_bp(f"{adapter}-qi-guard-{index}") >= 500
                )
                started_guard = await runtime.adapters.dispatch(
                    adapter, _context(adapter, user, "qi-guard-start", extra_guard_operation),
                    "开始生产 聚气护脉丹",
                )
                assert started_guard.code == "PRODUCTION_STARTED"
                clock.advance(seconds=60)
                completed_guard = await _dispatch(runtime, adapter, user, 37, "领取生产")
                assert completed_guard.data["outputs"] == {"item.pill.qi_guard": 1}
                await runtime.close()

    asyncio.run(run())


def test_qq_and_onebot_can_reach_soul_transformation_from_new_player() -> None:
    async def run() -> None:
        for adapter in ("qq.official", "onebot.v11"):
            with TemporaryDirectory() as data_dir:
                clock = MutableClock()
                runtime = create_runtime(data_dir=data_dir, clock=clock)
                user = f"foundation-source-{adapter}"
                for index, command in enumerate(
                    (
                        "开始修仙",
                        "寻仙问道",
                        "完成引导 阅读",
                        "前往近郊",
                        "完成引导 采集",
                        "完成引导 炼丹",
                        "选择道途 辅修 炼丹",
                    )
                ):
                    await _dispatch(runtime, adapter, user, index, command)

                for index in range(2):
                    await _dispatch(runtime, adapter, user, 10 + index, "开始修炼")
                    clock.advance(minutes=10)
                    settled = await _dispatch(runtime, adapter, user, 20 + index, "结算修炼")
                    assert settled.code == "CULTIVATION_SETTLED"
                advanced = await _dispatch(runtime, adapter, user, 30, "晋升境界")
                assert advanced.data["realm_layer"] == 2

                await _dispatch(runtime, adapter, user, 31, "前往 灵泉谷")
                clock.advance(seconds=90)
                await _dispatch(runtime, adapter, user, 32, "结算移动")

                spring_operations: list[str] = []
                for index in range(3):
                    operation = next(
                        f"{adapter}-spring-before-{index}-{candidate}"
                        for candidate in range(1000)
                        if (
                            settlement_result(
                                "explore.spring_gather",
                                f"{adapter}-spring-before-{index}-{candidate}",
                            )["item.herb.spirit_leaf"]
                            >= 2
                            and settlement_result(
                                "explore.spring_gather",
                                f"{adapter}-spring-before-{index}-{candidate}",
                            )["item.mat.array_sand"]
                            >= 1
                        )
                    )
                    spring_operations.append(operation)
                    await _dispatch(
                        runtime,
                        adapter,
                        user,
                        40 + index,
                        "开始探索 灵泉采集",
                        operation_id=operation,
                    )
                    clock.advance(seconds=90)
                    result = await _dispatch(runtime, adapter, user, 50 + index, "结算探索")
                    assert result.data["result"]["item.herb.spirit_leaf"] >= 2

                focus_operation = next(
                    f"{adapter}-focus-{index}"
                    for index in range(1000)
                    if random_quality_bp(f"{adapter}-focus-{index}") >= 500
                )
                started_focus = await runtime.adapters.dispatch(
                    adapter, _context(adapter, user, "foundation-focus-start", focus_operation),
                    "开始生产 焦点丹",
                )
                assert started_focus.code == "PRODUCTION_STARTED"
                clock.advance(seconds=45)
                completed_focus = await _dispatch(runtime, adapter, user, 60, "领取生产")
                assert completed_focus.data["outputs"] == {"item.pill.focus_low": 1}

                # Finish the documented L1 -> L10 cultivation path before the
                # cross-realm breakthrough. Recovery is also exercised through
                # the public command so the loop does not mutate player state.
                clock.advance(hours=13)
                await _dispatch(runtime, adapter, user, 62, "恢复状态")
                for cycle in range(45):
                    if cycle:
                        clock.advance(hours=1)
                        await _dispatch(runtime, adapter, user, 100 + cycle, "恢复状态")
                    await _dispatch(runtime, adapter, user, 150 + cycle, "开始修炼")
                    clock.advance(minutes=10)
                    settled_cultivation = await _dispatch(
                        runtime,
                        adapter,
                        user,
                        200 + cycle,
                        "结算修炼",
                    )
                    realm_key = settled_cultivation.data["realm_key"]
                    realm_layer = settled_cultivation.data["realm_layer"]
                    threshold = next_layer_threshold(realm_key, realm_layer)
                    if threshold is not None and settled_cultivation.data["cultivation"] >= threshold:
                        advanced_layer = await _dispatch(
                            runtime,
                            adapter,
                            user,
                            250 + cycle,
                            "晋升境界",
                        )
                        realm_layer = advanced_layer.data["realm_layer"]
                    if realm_key == "qi_sensing" and realm_layer == 10 and settled_cultivation.data["total_cultivation"] >= 1360:
                        break
                else:
                    raise AssertionError("player path did not reach qi-sensing L10")

                breakthrough_operation = next(
                    f"{adapter}-qi-breakthrough-{index}"
                    for index in range(1000)
                    if breakthrough_roll_bp(f"{adapter}-qi-breakthrough-{index}") < 8000
                )
                started_breakthrough = await runtime.adapters.dispatch(
                    adapter, _context(adapter, user, "qi-breakthrough-start", breakthrough_operation),
                    "开始突破 聚气",
                )
                assert started_breakthrough.code == "BREAKTHROUGH_STARTED"
                clock.advance(minutes=3)
                settled_breakthrough = await _dispatch(runtime, adapter, user, 61, "结算突破")
                assert settled_breakthrough.code == "BREAKTHROUGH_SUCCEEDED"
                assert settled_breakthrough.data["target_realm"] == "qi_gathering"

                # Recover stamina through the public command before the next route.
                clock.advance(hours=13)
                recovered = await _dispatch(runtime, adapter, user, 63, "恢复状态")
                assert recovered.code == "RESOURCES_RECOVERED"

                await _dispatch(runtime, adapter, user, 64, "前往 青石镇")
                clock.advance(seconds=30)
                await _dispatch(runtime, adapter, user, 65, "结算移动")
                await _dispatch(runtime, adapter, user, 66, "前往 近郊")
                clock.advance(seconds=30)
                await _dispatch(runtime, adapter, user, 67, "结算移动")

                outskirts_operation = next(
                    f"{adapter}-outskirts-iron-{index}"
                    for index in range(1000)
                    if (
                        settlement_result(
                            "explore.gather_outskirts",
                            f"{adapter}-outskirts-iron-{index}",
                        )["item.ore.ironstone"]
                        >= 2
                        and battle_roll_bp(f"{adapter}-outskirts-iron-{index}:battle") >= 1000
                    )
                )
                await _dispatch(
                    runtime,
                    adapter,
                    user,
                    68,
                    "开始探索 近郊采集",
                    operation_id=outskirts_operation,
                )
                clock.advance(seconds=30)
                iron_result = await _dispatch(runtime, adapter, user, 69, "结算探索")
                assert iron_result.data["result"]["item.ore.ironstone"] >= 2

                await _dispatch(runtime, adapter, user, 70, "前往 灵泉谷")
                clock.advance(seconds=90)
                await _dispatch(runtime, adapter, user, 71, "结算移动")

                for index in range(2):
                    operation = next(
                        f"{adapter}-spring-after-{index}-{candidate}"
                        for candidate in range(1000)
                        if settlement_result(
                            "explore.spring_gather",
                            f"{adapter}-spring-after-{index}-{candidate}",
                        )["item.herb.spirit_leaf"]
                        >= 2
                    )
                    await _dispatch(
                        runtime,
                        adapter,
                        user,
                        80 + index,
                        "开始探索 灵泉采集",
                        operation_id=operation,
                    )
                    clock.advance(seconds=90)
                    await _dispatch(runtime, adapter, user, 90 + index, "结算探索")

                started_draft = await runtime.adapters.dispatch(
                    adapter, _context(adapter, user, "foundation-draft-start", f"{adapter}-foundation-draft"),
                    "开始生产 筑基丹",
                )
                assert started_draft.code == "PRODUCTION_STARTED", started_draft.message
                clock.advance(seconds=120)
                completed_draft = await _dispatch(runtime, adapter, user, 94, "领取生产")
                assert completed_draft.code == "PRODUCTION_COMPLETED"
                assert completed_draft.data["success"] is True
                assert completed_draft.data["outputs"] == {"item.pill.foundation_draft": 1}
                started_guard = await runtime.adapters.dispatch(
                    adapter, _context(adapter, user, "foundation-guard-start", f"{adapter}-foundation-guard"),
                    "开始生产 筑基护脉丹",
                )
                assert started_guard.code == "PRODUCTION_STARTED", started_guard.message
                clock.advance(seconds=180)
                completed_guard = await _dispatch(runtime, adapter, user, 95, "领取生产")
                assert completed_guard.code == "PRODUCTION_COMPLETED"
                assert completed_guard.data["success"] is True
                assert completed_guard.data["outputs"] == {"item.pill.foundation_guard": 1}
                forbidden_market = await runtime.adapters.dispatch(
                    adapter, _context(adapter, user, "foundation-draft-market"),
                    "发布摆摊 筑基丹 1 1",
                )
                assert forbidden_market.code == "MARKET_ITEM_FORBIDDEN"

                clock.advance(days=1)
                await _dispatch(runtime, adapter, user, 299, "恢复状态")
                for index in range(3):
                    operation = next(
                        f"{adapter}-foundation-sand-{index}-{candidate}"
                        for candidate in range(1000)
                        if settlement_result(
                            "explore.spring_gather", f"{adapter}-foundation-sand-{index}-{candidate}"
                        )["item.mat.array_sand"] == 1
                    )
                    await _dispatch(runtime, adapter, user, 300 + index, "开始探索 灵泉采集", operation_id=operation)
                    clock.advance(seconds=90)
                    await _dispatch(runtime, adapter, user, 310 + index, "结算探索")

                await _dispatch(runtime, adapter, user, 320, "前往 青石镇")
                clock.advance(seconds=30)
                await _dispatch(runtime, adapter, user, 321, "结算移动")
                await _dispatch(runtime, adapter, user, 322, "前往 近郊")
                clock.advance(seconds=30)
                await _dispatch(runtime, adapter, user, 323, "结算移动")
                for index in range(2):
                    operation = next(
                        f"{adapter}-foundation-iron-{index}-{candidate}"
                        for candidate in range(1000)
                        if settlement_result(
                            "explore.gather_outskirts", f"{adapter}-foundation-iron-{index}-{candidate}"
                        )["item.ore.ironstone"] == 2
                        and battle_roll_bp(f"{adapter}-foundation-iron-{index}-{candidate}:battle") >= 1000
                    )
                    await _dispatch(runtime, adapter, user, 330 + index, "开始探索 近郊采集", operation_id=operation)
                    clock.advance(seconds=30)
                    await _dispatch(runtime, adapter, user, 340 + index, "结算探索")

                for index in range(15):
                    if index in (0, 6, 12):
                        clock.advance(days=1)
                        await _dispatch(runtime, adapter, user, 350 + index, "恢复状态")
                    operation = next(
                        f"{adapter}-foundation-stones-{index}-{candidate}"
                        for candidate in range(1000)
                        if settlement_result(
                            "explore.trial_outskirts", f"{adapter}-foundation-stones-{index}-{candidate}"
                        )["spirit_stones"] == 30
                        and battle_roll_bp(f"{adapter}-foundation-stones-{index}-{candidate}:battle") >= 2000
                    )
                    await _dispatch(runtime, adapter, user, 360 + index, "开始探索 短历练", operation_id=operation)
                    clock.advance(seconds=60)
                    await _dispatch(runtime, adapter, user, 380 + index, "结算探索")

                for cycle in range(90):
                    clock.advance(hours=1)
                    await _dispatch(runtime, adapter, user, 400 + cycle, "恢复状态")
                    await _dispatch(runtime, adapter, user, 500 + cycle, "开始修炼")
                    clock.advance(minutes=10)
                    cultivated = await _dispatch(runtime, adapter, user, 600 + cycle, "结算修炼")
                    assert cultivated.data["realm_key"] == "qi_gathering"
                    threshold = next_layer_threshold("qi_gathering", cultivated.data["realm_layer"])
                    if threshold is not None and cultivated.data["cultivation"] >= threshold:
                        advanced = await _dispatch(runtime, adapter, user, 700 + cycle, "晋升境界")
                        layer = advanced.data["realm_layer"]
                    else:
                        layer = cultivated.data["realm_layer"]
                    if layer == 10 and cultivated.data["total_cultivation"] >= 4260:
                        break
                else:
                    raise AssertionError("new player did not reach qi-gathering L10")

                breakthrough_operation = next(
                    f"{adapter}-foundation-break-{candidate}"
                    for candidate in range(1000)
                    if breakthrough_roll_bp(f"{adapter}-foundation-break-{candidate}") < 7500
                )
                started_foundation = await runtime.adapters.dispatch(
                    adapter, _context(adapter, user, "foundation-break-start", breakthrough_operation),
                    "开始突破 筑基",
                )
                assert started_foundation.code == "BREAKTHROUGH_STARTED", started_foundation.message
                clock.advance(minutes=5)
                founded = await _dispatch(runtime, adapter, user, 800, "结算突破")
                assert founded.code == "BREAKTHROUGH_SUCCEEDED"
                assert founded.data["target_realm"] == "foundation"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    assert connection.execute(
                        "SELECT foundation_quality FROM players WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    ).fetchone()[0] == 5500
                replay = await _dispatch(runtime, adapter, user, 800, "结算突破")
                assert replay.data["idempotent_replay"] is True

                for index in range(15):
                    if index in (0, 6, 12):
                        clock.advance(days=1)
                        await _dispatch(runtime, adapter, user, 801 + index, "恢复状态")
                    operation = next(
                        f"{adapter}-core-stones-{index}-{candidate}"
                        for candidate in range(1000)
                        if settlement_result(
                            "explore.trial_outskirts", f"{adapter}-core-stones-{index}-{candidate}"
                        )["spirit_stones"] == 30
                        and battle_roll_bp(f"{adapter}-core-stones-{index}-{candidate}:battle") >= 2000
                    )
                    await _dispatch(runtime, adapter, user, 830 + index, "开始探索 短历练", operation_id=operation)
                    clock.advance(seconds=60)
                    await _dispatch(runtime, adapter, user, 850 + index, "结算探索")

                for cycle in range(70):
                    if cycle % 2 == 0:
                        clock.advance(days=1)
                        await _dispatch(runtime, adapter, user, 900 + cycle, "恢复状态")
                        await _dispatch(runtime, adapter, user, 1000 + cycle, "道历问安")
                    await _dispatch(runtime, adapter, user, 1100 + cycle, "开始修炼 静修")
                    clock.advance(minutes=30)
                    cultivated = await _dispatch(runtime, adapter, user, 1200 + cycle, "结算修炼")
                    assert cultivated.data["realm_key"] == "foundation"
                    threshold = next_layer_threshold("foundation", cultivated.data["realm_layer"])
                    if threshold is not None and cultivated.data["cultivation"] >= threshold:
                        advanced = await _dispatch(runtime, adapter, user, 1300 + cycle, "晋升境界")
                        layer = advanced.data["realm_layer"]
                    else:
                        layer = cultivated.data["realm_layer"]
                    if layer == 10 and cultivated.data["total_cultivation"] >= 11960:
                        break
                else:
                    raise AssertionError("new player did not reach foundation L10")

                clock.advance(days=1)
                await _dispatch(runtime, adapter, user, 1399, "恢复状态")
                await _dispatch(runtime, adapter, user, 1400, "前往 灵泉谷")
                clock.advance(seconds=90)
                await _dispatch(runtime, adapter, user, 1401, "结算移动")
                for index in range(3):
                    operation = next(
                        f"{adapter}-core-spring-{index}-{candidate}"
                        for candidate in range(1000)
                        if settlement_result(
                            "explore.spring_gather", f"{adapter}-core-spring-{index}-{candidate}"
                        )["item.herb.spirit_leaf"] == 2
                        and settlement_result(
                            "explore.spring_gather", f"{adapter}-core-spring-{index}-{candidate}"
                        )["item.mat.array_sand"] == 1
                    )
                    await _dispatch(runtime, adapter, user, 1410 + index, "开始探索 灵泉采集", operation_id=operation)
                    clock.advance(seconds=90)
                    await _dispatch(runtime, adapter, user, 1420 + index, "结算探索")

                await _dispatch(runtime, adapter, user, 1430, "前往 青石镇")
                clock.advance(seconds=30)
                await _dispatch(runtime, adapter, user, 1431, "结算移动")
                clock.advance(days=1)
                await _dispatch(runtime, adapter, user, 1435, "恢复状态")
                await _dispatch(runtime, adapter, user, 1432, "前往 云铁矿区")
                clock.advance(seconds=120)
                await _dispatch(runtime, adapter, user, 1433, "结算移动")
                await _dispatch(runtime, adapter, user, 1434, "接取悬赏 云铁矿区悬赏")
                for index in range(2):
                    operation = next(
                        f"{adapter}-core-mine-{index}-{candidate}"
                        for candidate in range(1000)
                        if battle_roll_bp(f"{adapter}-core-mine-{index}-{candidate}:battle") >= 3000
                        and settlement_result(
                            "explore.cloud_mine", f"{adapter}-core-mine-{index}-{candidate}"
                        )["item.material.cloud_iron"] >= 3
                    )
                    await _dispatch(runtime, adapter, user, 1440 + index, "开始探索 云铁采集", operation_id=operation)
                    clock.advance(seconds=120)
                    await _dispatch(runtime, adapter, user, 1450 + index, "结算探索")
                await _dispatch(runtime, adapter, user, 1460, "领取悬赏")
                await _dispatch(runtime, adapter, user, 1461, "前往 青石镇")
                clock.advance(seconds=30)
                await _dispatch(runtime, adapter, user, 1462, "结算移动")
                production_operation = next(
                    f"{adapter}-core-pill-{candidate}"
                    for candidate in range(1000)
                    if random_quality_bp(f"{adapter}-core-pill-{candidate}") >= 1000
                )
                await _dispatch(runtime, adapter, user, 1463, "开始生产 凝核丹", operation_id=production_operation)
                clock.advance(seconds=180)
                produced = await _dispatch(runtime, adapter, user, 1464, "领取生产")
                assert produced.data["outputs"] == {"item.pill.core_condense": 1}
                core_operation = next(
                    f"{adapter}-core-break-{candidate}"
                    for candidate in range(1000)
                    if breakthrough_roll_bp(f"{adapter}-core-break-{candidate}") < 4800
                )
                await _dispatch(runtime, adapter, user, 1465, "开始突破 金丹", operation_id=core_operation)
                clock.advance(minutes=5)
                golden = await _dispatch(runtime, adapter, user, 1466, "结算突破")
                assert golden.code == "BREAKTHROUGH_SUCCEEDED"
                assert golden.data["target_realm"] == "golden_core"

                await _dispatch(runtime, adapter, user, 1500, "前往 近郊")
                clock.advance(seconds=30)
                await _dispatch(runtime, adapter, user, 1501, "结算移动")
                for day in range(28):
                    clock.advance(days=1)
                    await _dispatch(runtime, adapter, user, 1510 + day, "恢复状态")
                    await _dispatch(runtime, adapter, user, 1540 + day, "道历问安")
                    for index in range(8):
                        if index == 6:
                            clock.advance(hours=3)
                            await _dispatch(runtime, adapter, user, 1900 + day, "恢复状态")
                        elif index == 7:
                            clock.advance(hours=3)
                            await _dispatch(runtime, adapter, user, 1950 + day, "恢复状态")
                        operation = next(
                            f"{adapter}-nascent-money-{day}-{index}-{candidate}"
                            for candidate in range(1000)
                            if settlement_result(
                                "explore.trial_outskirts",
                                f"{adapter}-nascent-money-{day}-{index}-{candidate}",
                            )["spirit_stones"] == 30
                            and battle_roll_bp(
                                f"{adapter}-nascent-money-{day}-{index}-{candidate}:battle"
                            ) >= 2000
                        )
                        await _dispatch(
                            runtime,
                            adapter,
                            user,
                            1580 + day * 8 + index,
                            "开始探索 短历练",
                            operation_id=operation,
                        )
                        clock.advance(seconds=60)
                        await _dispatch(runtime, adapter, user, 1810 + day * 8 + index, "结算探索")

                await _dispatch(runtime, adapter, user, 2100, "前往 青石镇")
                clock.advance(seconds=30)
                await _dispatch(runtime, adapter, user, 2101, "结算移动")
                clock.advance(hours=4)
                await _dispatch(runtime, adapter, user, 2106, "恢复状态")
                await _dispatch(runtime, adapter, user, 2102, "前往 云城")
                clock.advance(minutes=3)
                await _dispatch(runtime, adapter, user, 2103, "结算移动")
                await _dispatch(runtime, adapter, user, 2104, "前往 云舟渡口")
                clock.advance(minutes=1)
                await _dispatch(runtime, adapter, user, 2105, "结算移动")
                clock.advance(hours=6)
                await _dispatch(runtime, adapter, user, 2107, "恢复状态")

                nascent_ready = False
                for day in range(35):
                    if day:
                        clock.advance(days=1)
                        await _dispatch(runtime, adapter, user, 2110 + day, "恢复状态")
                        await _dispatch(runtime, adapter, user, 2150 + day, "道历问安")
                    for index in range(3):
                        if index:
                            clock.advance(hours=6)
                            await _dispatch(runtime, adapter, user, 2180 + day * 3 + index, "恢复状态")
                        with sqlite3.connect(runtime.settings.database_path) as connection:
                            realm, layer, cultivation, total = connection.execute(
                                "SELECT realm_key, realm_layer, cultivation, total_cultivation FROM players "
                                "WHERE platform=? AND platform_user_id=?",
                                (adapter, user),
                            ).fetchone()
                        if realm == "golden_core" and layer == 10 and total >= 58960:
                            nascent_ready = True
                            break
                        operation = next(
                            f"{adapter}-gold-trial-{day}-{index}-{candidate}"
                            for candidate in range(1000)
                            if cloud_boat_storm_roll_bp(
                                f"{adapter}-gold-trial-{day}-{index}-{candidate}"
                            ) >= 2500
                        )
                        await _dispatch(
                            runtime,
                            adapter,
                            user,
                            2200 + day * 3 + index,
                            "开始探索 云舟试炼",
                            operation_id=operation,
                        )
                        clock.advance(minutes=5)
                        settled_trial = await _dispatch(runtime, adapter, user, 2300 + day * 3 + index, "结算探索")
                        assert settled_trial.data["result"]["cultivation"] > 0
                        threshold = next_layer_threshold("golden_core", int(layer))
                        if threshold is not None and int(cultivation) + int(settled_trial.data["result"]["cultivation"]) >= threshold:
                            advanced = await _dispatch(runtime, adapter, user, 2400 + day * 3 + index, "晋升境界")
                            layer = int(advanced.data["realm_layer"])
                    if nascent_ready:
                        break
                else:
                    raise AssertionError("new player did not reach golden-core L10 from cloud-boat trials")

                clock.advance(days=1)
                await _dispatch(runtime, adapter, user, 2499, "恢复状态")
                await _dispatch(runtime, adapter, user, 2500, "乘坐云舟 魔界引导")
                clock.advance(minutes=5)
                await _dispatch(runtime, adapter, user, 2501, "结算云舟")
                assert (await _dispatch(runtime, adapter, user, 2502, "接受魔界引导")).code == "DEMON_INTRO_ACCEPTED"
                await _dispatch(runtime, adapter, user, 2503, "恢复状态")
                for index in range(6):
                    if index == 3:
                        clock.advance(days=1)
                        await _dispatch(runtime, adapter, user, 2504, "恢复状态")
                    elif index == 2:
                        clock.advance(hours=2)
                        await _dispatch(runtime, adapter, user, 2505, "恢复状态")
                    started = await _dispatch(runtime, adapter, user, 2510 + index, "开始探索 深渊门备材")
                    assert started.code == "EXPLORATION_STARTED"
                    clock.advance(minutes=4)
                    settled = await _dispatch(runtime, adapter, user, 2520 + index, "结算探索")
                    assert settled.data["result"] == {"item.soul_crystal": 1, "item.demon_core": 1}

                await _dispatch(runtime, adapter, user, 2530, "乘坐云舟 返回云城")
                clock.advance(minutes=3)
                await _dispatch(runtime, adapter, user, 2531, "结算云舟")
                soul_pill_operation = next(
                    f"{adapter}-final-soul-pill-{candidate}"
                    for candidate in range(1000)
                    if random_quality_bp(f"{adapter}-final-soul-pill-{candidate}") >= 1000
                )
                pill = await _dispatch(
                    runtime, adapter, user, 2532, "开始生产 凝魂丹", operation_id=soul_pill_operation
                )
                assert pill.code == "PRODUCTION_STARTED", pill.message
                clock.advance(minutes=5)
                soul_pill = await _dispatch(runtime, adapter, user, 2533, "领取生产")
                assert soul_pill.data["outputs"] == {"item.pill.soul_condense": 1}
                prepared = await _dispatch(runtime, adapter, user, 2534, "准备元婴")
                assert prepared.code == "NASCENT_SOUL_PREPARED", prepared.message
                soul_break_operation = next(
                    f"{adapter}-final-nascent-break-{candidate}"
                    for candidate in range(1000)
                    if breakthrough_roll_bp(f"{adapter}-final-nascent-break-{candidate}") < 5500
                )
                started_soul = await _dispatch(
                    runtime, adapter, user, 2535, "开始突破 元婴", operation_id=soul_break_operation
                )
                assert started_soul.code == "BREAKTHROUGH_STARTED", started_soul.message
                clock.advance(minutes=30)
                soul_break = await _dispatch(runtime, adapter, user, 2536, "结算突破")
                assert soul_break.code == "BREAKTHROUGH_SUCCEEDED", soul_break.message
                assert soul_break.data["target_realm"] == "nascent_soul"

                # The post-nascent path is intentionally driven by public
                # commands.  Only the second adapter's helper is a controlled
                # combat collaborator; the primary player's progression is
                # never patched in SQL.
                for stage in range(1, 6):
                    started_mainline = await _dispatch(
                        runtime,
                        adapter,
                        user,
                        2600 + stage * 2,
                        f"开始三界主线 共生 {stage}",
                    )
                    assert started_mainline.code == "THREE_REALMS_STAGE_STARTED"
                    claimed_mainline = await _dispatch(
                        runtime,
                        adapter,
                        user,
                        2601 + stage * 2,
                        f"领取三界主线奖励 共生 {stage}",
                    )
                    assert claimed_mainline.code == "THREE_REALMS_STAGE_CLAIMED"
                assert claimed_mainline.data["reward"].get("faction_reputation.beast") == 1000

                for commission in range(3):
                    completed_commission = await _dispatch(
                        runtime,
                        adapter,
                        user,
                        2620 + commission,
                        "完成领域委托",
                    )
                    assert completed_commission.data["progress"]["completed"] == commission + 1

                # Travel to the beast realm before creating the helper party.
                clock.advance(hours=10)
                await _dispatch(runtime, adapter, user, 2639, "恢复状态")
                await _dispatch(runtime, adapter, user, 2640, "前往 云舟渡口")
                clock.advance(minutes=1)
                await _dispatch(runtime, adapter, user, 2641, "结算移动")
                await _dispatch(runtime, adapter, user, 2642, "前往 万兽山")
                clock.advance(minutes=5)
                await _dispatch(runtime, adapter, user, 2643, "结算移动")

                helper_adapter = "onebot.v11" if adapter == "qq.official" else "qq.official"
                helper = f"combat-helper-{adapter}"
                await _dispatch(runtime, helper_adapter, helper, 2650, "开始修仙")
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        """
                        UPDATE players
                        SET stage='cultivator', realm_key='nascent_soul', realm_layer=1,
                            location_key='beast.ten_thousand_hills', cultivation=190000,
                            total_cultivation=248960, max_hp=100000, initiative=100000,
                            stamina=100, stamina_max=100, energy=100, energy_max=100,
                            soul_power=300, soul_power_max=300,
                            carry_capacity=1000, spirit_stones=100000,
                            qualification_json=?, faction_reputation_json=?, intro_json=?, inventory_json=?
                        WHERE platform=? AND platform_user_id=?
                        """,
                        (
                            json.dumps({"body": 20000, "agility": 20000, "spirit": 30, "root": 30, "insight": 30, "fortune": 10}),
                            json.dumps({"beast": 200}),
                            json.dumps({"flags": ["story.mainline.three_realms"]}),
                            json.dumps({"item.soul_crystal": 100}),
                            helper_adapter,
                            helper,
                        ),
                    )

                clock.advance(hours=10)
                await _dispatch(runtime, adapter, user, 2660, "恢复状态")
                await _dispatch(runtime, helper_adapter, helper, 2661, "恢复状态")
                helper_party = await runtime.adapters.dispatch(
                    helper_adapter,
                    _context(helper_adapter, helper, "beast-party-create"),
                    "创建万兽队伍",
                )
                assert helper_party.code == "PARTY_CREATED"
                party_id = str(helper_party.data["party_id"])
                invited = await runtime.adapters.dispatch(
                    helper_adapter,
                    _context(helper_adapter, helper, "beast-party-invite"),
                    f"邀请入队 {adapter}:{user}",
                )
                assert invited.code == "PARTY_INVITED"
                joined = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "beast-party-accept"),
                    f"接受入队 {party_id}",
                )
                assert joined.code == "PARTY_JOINED"
                for member_adapter, member in ((helper_adapter, helper), (adapter, user)):
                    confirmed = await runtime.adapters.dispatch(
                        member_adapter,
                        _context(member_adapter, member, f"beast-party-confirm-{member_adapter}"),
                        f"确认入队 {party_id}",
                    )
                    assert confirmed.ok, confirmed

                # Each win contributes +15 beast reputation and +20 world
                # merit.  Server-settled party evidence closes both gates
                # without patching the primary player's progression state.
                # Recovery advances time beyond the party confirmation TTL,
                # so each battle uses a newly confirmed party.
                for battle_index in range(98):
                    if battle_index:
                        clock.advance(hours=10)
                        await _dispatch(runtime, adapter, user, 10000 + battle_index * 5, "恢复状态")
                        await _dispatch(runtime, helper_adapter, helper, 10001 + battle_index * 5, "恢复状态")
                        helper_party = await runtime.adapters.dispatch(
                            helper_adapter,
                            _context(helper_adapter, helper, f"beast-party-create-{battle_index}"),
                            "创建万兽队伍",
                        )
                        assert helper_party.code == "PARTY_CREATED"
                        party_id = str(helper_party.data["party_id"])
                        await _dispatch(
                            runtime,
                            helper_adapter,
                            helper,
                            11000 + battle_index * 5,
                            f"邀请入队 {adapter}:{user}",
                        )
                        await _dispatch(
                            runtime,
                            adapter,
                            user,
                            11001 + battle_index * 5,
                            f"接受入队 {party_id}",
                        )
                        for member_adapter, member, offset in (
                            (helper_adapter, helper, 2),
                            (adapter, user, 3),
                        ):
                            confirmed = await _dispatch(
                                runtime,
                                member_adapter,
                                member,
                                11000 + battle_index * 5 + offset,
                                f"确认入队 {party_id}",
                            )
                            assert confirmed.ok
                    battle = await runtime.adapters.dispatch(
                        helper_adapter,
                        _context(helper_adapter, helper, f"beast-battle-{battle_index}"),
                        f"开始队伍战斗 {party_id}",
                    )
                    assert battle.code == "PARTY_BATTLE_SETTLED", (battle_index, battle.code, battle.message)
                    assert battle.data["outcome"] == "won"

                await _dispatch(runtime, helper_adapter, helper, 2880, "退出队伍")
                await _dispatch(runtime, adapter, user, 2881, "退出队伍")

                # Put both players in the boundary realm for the three
                # personally participated victories used by the ancient-line
                # quest.  The normal movement command is used for the real
                # player; the helper uses the same public route as well.
                clock.advance(hours=10)
                await _dispatch(runtime, adapter, user, 2890, "恢复状态")
                await _dispatch(runtime, helper_adapter, helper, 2891, "恢复状态")
                for move_adapter, move_user, offset in (
                    (adapter, user, 2892),
                    (helper_adapter, helper, 2894),
                ):
                    await _dispatch(runtime, move_adapter, move_user, offset, "前往 界隙秘境")
                    clock.advance(minutes=10)
                    await _dispatch(runtime, move_adapter, move_user, offset + 1, "结算移动")
                clock.advance(hours=15)
                await _dispatch(runtime, adapter, user, 2896, "恢复状态")
                await _dispatch(runtime, helper_adapter, helper, 2897, "恢复状态")

                boundary_party = await runtime.adapters.dispatch(
                    helper_adapter,
                    _context(helper_adapter, helper, "boundary-party-create"),
                    "创建界隙队伍",
                )
                assert boundary_party.code == "PARTY_CREATED"
                boundary_id = str(boundary_party.data["party_id"])
                await _dispatch(
                    runtime,
                    helper_adapter,
                    helper,
                    2900,
                    f"邀请入队 {adapter}:{user}",
                )
                await _dispatch(runtime, adapter, user, 2901, f"接受入队 {boundary_id}")
                for member_adapter, member in ((helper_adapter, helper), (adapter, user)):
                    confirmed = await _dispatch(
                        runtime,
                        member_adapter,
                        member,
                        2902 if member_adapter == helper_adapter else 2903,
                        f"确认入队 {boundary_id}",
                    )
                    assert confirmed.ok
                assert confirmed.data["ready"] is True or confirmed.data["status"] == "ready"

                boundary_battles: list[str] = []
                for battle_index in range(3):
                    if battle_index:
                        await _dispatch(runtime, helper_adapter, helper, 2905 + battle_index * 8, "退出队伍")
                        await _dispatch(runtime, adapter, user, 2906 + battle_index * 8, "退出队伍")
                        clock.advance(hours=15)
                        await _dispatch(runtime, adapter, user, 2910 + battle_index * 2, "恢复状态")
                        await _dispatch(runtime, helper_adapter, helper, 2911 + battle_index * 2, "恢复状态")
                        boundary_party = await runtime.adapters.dispatch(
                            helper_adapter,
                            _context(helper_adapter, helper, f"boundary-party-create-{battle_index}"),
                            "创建界隙队伍",
                        )
                        assert boundary_party.code == "PARTY_CREATED"
                        boundary_id = str(boundary_party.data["party_id"])
                        await _dispatch(
                            runtime,
                            helper_adapter,
                            helper,
                            2912 + battle_index * 8,
                            f"邀请入队 {adapter}:{user}",
                        )
                        await _dispatch(runtime, adapter, user, 2913 + battle_index * 8, f"接受入队 {boundary_id}")
                        for member_adapter, member in ((helper_adapter, helper), (adapter, user)):
                            confirmed = await _dispatch(
                                runtime,
                                member_adapter,
                                member,
                                2914 + battle_index * 8 if member_adapter == helper_adapter else 2915 + battle_index * 8,
                                f"确认入队 {boundary_id}",
                            )
                            assert confirmed.ok
                    battle = await runtime.adapters.dispatch(
                        helper_adapter,
                        _context(helper_adapter, helper, f"boundary-battle-{battle_index}"),
                        f"开始队伍战斗 {boundary_id}",
                    )
                    assert battle.code == "PARTY_BATTLE_SETTLED", battle.message
                    assert battle.data["outcome"] == "won"
                    boundary_battles.append(str(battle.data["battle_id"]))
                    evidence = await _dispatch(
                        runtime,
                        adapter,
                        user,
                        2920 + battle_index,
                        f"完成远古洞天任务 {boundary_battles[-1]}",
                    )
                    assert evidence.data["progress"]["success"] == battle_index + 1

                await _dispatch(runtime, helper_adapter, helper, 2928, "退出队伍")
                await _dispatch(runtime, adapter, user, 2929, "退出队伍")
                cross_realm = await _dispatch(runtime, adapter, user, 2930, "开始跨界战")
                assert cross_realm.data["outcome"] == "won"
                permit = await _dispatch(runtime, adapter, user, 2931, "领取化神许可")
                assert permit.code == "QUEST_PERMIT_GRANTED"

                # Soul refinement is limited to two sessions per UTC day and
                # supplies +5,000 cultivation per session for this character.
                # Advance the injected clock between days and recover through
                # the same public command used by players.
                soul_ready = False
                for day in range(60):
                    if day:
                        clock.advance(days=1)
                    clock.advance(hours=10)
                    await _dispatch(runtime, adapter, user, 2940 + day, "恢复状态")
                    for slot in range(2):
                        started_refinement = await _dispatch(
                            runtime,
                            adapter,
                            user,
                            3000 + day * 2 + slot,
                            "开始修炼 神魂淬炼",
                        )
                        assert started_refinement.code == "CULTIVATION_STARTED"
                        clock.advance(minutes=30)
                        settled_refinement = await _dispatch(
                            runtime,
                            adapter,
                            user,
                            3100 + day * 2 + slot,
                            "结算修炼",
                        )
                        assert settled_refinement.data["soul_power_gain"] == 50
                    with sqlite3.connect(runtime.settings.database_path) as connection:
                        realm, layer, cultivation, total_cultivation = connection.execute(
                            "SELECT realm_key, realm_layer, cultivation, total_cultivation FROM players WHERE platform=? AND platform_user_id=?",
                            (adapter, user),
                        ).fetchone()
                    threshold = next_layer_threshold(realm, layer)
                    if threshold is not None and cultivation >= threshold:
                        await _dispatch(runtime, adapter, user, 5000 + day * 2, "晋升境界")
                        with sqlite3.connect(runtime.settings.database_path) as connection:
                            realm, layer, cultivation, total_cultivation = connection.execute(
                                "SELECT realm_key, realm_layer, cultivation, total_cultivation FROM players WHERE platform=? AND platform_user_id=?",
                                (adapter, user),
                            ).fetchone()
                    if realm == "nascent_soul" and layer == 10 and cultivation >= 190000 and total_cultivation >= 248960:
                        soul_ready = True
                        break
                assert soul_ready

                # The breakthrough also requires 20,000 spirit stones.  Daily
                # check-in is a real player-facing source; the clock makes the
                # long-running accumulation deterministic without wall time.
                stones_ready = False
                for day in range(1000):
                    clock.advance(days=1)
                    await _dispatch(runtime, adapter, user, 3200 + day, "道历问安")
                    with sqlite3.connect(runtime.settings.database_path) as connection:
                        spirit_stones = connection.execute(
                            "SELECT spirit_stones FROM players WHERE platform=? AND platform_user_id=?",
                            (adapter, user),
                        ).fetchone()[0]
                    if spirit_stones >= 20000:
                        stones_ready = True
                        break
                assert stones_ready

                soul_break_operation = next(
                    f"{adapter}-soul-break-{candidate}"
                    for candidate in range(1000)
                    if breakthrough_roll_bp(f"{adapter}-soul-break-{candidate}") < 6500
                )
                started_soul_transformation = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "soul-transformation-start", soul_break_operation),
                    "开始突破 化神",
                )
                assert started_soul_transformation.code == "BREAKTHROUGH_STARTED", started_soul_transformation.message
                clock.advance(minutes=10)
                transformed = await _dispatch(runtime, adapter, user, 4300, "结算突破")
                assert transformed.code == "BREAKTHROUGH_SUCCEEDED", transformed.message
                assert transformed.data["target_realm"] == "soul_transformation"

                # Continue the same public player path through the炼虚 gate.
                # Soul refinement is available at higher realms as well; the
                # daily limit and injected clock keep this long resource path
                # deterministic without changing the player's row directly.
                void_ready = False
                for day in range(120):
                    clock.advance(days=1)
                    await _dispatch(runtime, adapter, user, 4400 + day, "恢复状态")
                    for slot in range(2):
                        started_refinement = await _dispatch(
                            runtime,
                            adapter,
                            user,
                            4600 + day * 2 + slot,
                            "开始修炼 神魂淬炼",
                        )
                        assert started_refinement.code == "CULTIVATION_STARTED", started_refinement.message
                        clock.advance(minutes=30)
                        settled_refinement = await _dispatch(
                            runtime,
                            adapter,
                            user,
                            4700 + day * 2 + slot,
                            "结算修炼",
                        )
                        assert settled_refinement.data["cultivation_gain"] >= 5000
                        if slot == 0:
                            clock.advance(hours=8)
                            await _dispatch(runtime, adapter, user, 4800 + day, "恢复状态")
                        current_realm = settled_refinement.data["realm_key"]
                        current_layer = int(settled_refinement.data["realm_layer"])
                        threshold = next_layer_threshold(current_realm, current_layer)
                        if threshold is not None and int(settled_refinement.data["cultivation"]) >= threshold:
                            advanced = await _dispatch(
                                runtime,
                                adapter,
                                user,
                                4900 + day * 2 + slot,
                                "晋升境界",
                            )
                            current_layer = int(advanced.data["realm_layer"])
                    with sqlite3.connect(runtime.settings.database_path) as connection:
                        realm, layer, cultivation, total_cultivation, spirit_stones = connection.execute(
                            "SELECT realm_key, realm_layer, cultivation, total_cultivation, spirit_stones "
                            "FROM players WHERE platform=? AND platform_user_id=?",
                            (adapter, user),
                        ).fetchone()
                    if (
                        realm == "soul_transformation"
                        and int(layer) == 10
                        and int(cultivation) >= 600000
                        and int(total_cultivation) >= 848960
                    ):
                        void_ready = True
                        break
                assert void_ready

                # Earn the 80,000-stone fee through the public market path.
                # The collaborator wallet is seeded, while the main player
                # sells an item already obtained through public exploration.
                clock.advance(days=1)
                await _dispatch(runtime, adapter, user, 5998, "恢复状态")
                await _dispatch(runtime, adapter, user, 5999, "道历问安")
                listed = await _dispatch(
                    runtime,
                    adapter,
                    user,
                    6000,
                    "发布摆摊 灵叶 1 90000",
                )
                assert listed.code == "MARKET_ORDER_CREATED", listed.message
                order_id = str(listed.data["order_id"])
                purchased = await _dispatch(
                    runtime,
                    helper_adapter,
                    helper,
                    6001,
                    f"购买摆摊 {order_id}",
                )
                assert purchased.code == "MARKET_ORDER_PURCHASED", purchased.message
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    spirit_stones = connection.execute(
                        "SELECT spirit_stones FROM players WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    ).fetchone()[0]
                assert int(spirit_stones) >= 80000

                # Reach the published portal, complete all three server-settled
                # wall trials, and use their rewards to pay for the archive
                # route.  The route roll is selected only to avoid the
                # documented storm loss; no inventory or location is patched.
                clock.advance(hours=8)
                await _dispatch(runtime, adapter, user, 5099, "恢复状态")
                await _dispatch(runtime, adapter, user, 5100, "前往 虚空门户")
                clock.advance(minutes=5)
                await _dispatch(runtime, adapter, user, 5101, "结算移动")
                wall_battles: list[str] = []
                for index in range(3):
                    trial = await _dispatch(runtime, adapter, user, 5110 + index, "开始界壁试炼")
                    assert trial.data["outcome"] == "won"
                    wall_battles.append(str(trial.data["battle_id"]))
                    assert trial.data["progress"]["void_wall_trial"] == index + 1

                archive_operation = next(
                    f"{adapter}-new-archive-{candidate}"
                    for candidate in range(1000)
                    if void_route_roll_bp(f"{adapter}-new-archive-{candidate}") >= 1500
                )
                started_archive = await _dispatch(
                    runtime,
                    adapter,
                    user,
                    5120,
                    "进入虚空航道 档案遗迹",
                    operation_id=archive_operation,
                )
                assert started_archive.code == "VOID_ROUTE_STARTED"
                assert started_archive.data["anchor_cost"] == 4
                clock.advance(minutes=45)
                settled_archive = await _dispatch(runtime, adapter, user, 5121, "结算虚空航道")
                assert settled_archive.code == "VOID_ROUTE_SETTLED"
                assert settled_archive.data["route_key"] == "void.archive_ruins"
                archive_guard = await _dispatch(runtime, adapter, user, 5122, "探索档案遗迹")
                assert archive_guard.code == "ARCHIVE_RUN_SETTLED"
                assert archive_guard.data["outcome"] == "won"
                delivered_archive = await _dispatch(runtime, adapter, user, 5123, "交付虚空档案")
                assert delivered_archive.code == "QUEST_ACTION_RECORDED"
                void_permit = await _dispatch(runtime, adapter, user, 5124, "领取炼虚许可")
                assert void_permit.code == "QUEST_PERMIT_GRANTED"

                with sqlite3.connect(runtime.settings.database_path) as connection:
                    inventory = json.loads(
                        connection.execute(
                            "SELECT inventory_json FROM players WHERE platform=? AND platform_user_id=?",
                            (adapter, user),
                        ).fetchone()[0]
                    )
                    location = connection.execute(
                        "SELECT location_key FROM players WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    ).fetchone()[0]
                assert location == "void.archive_ruins"
                assert inventory.get("item.recipe.void_refinery") == 1
                assert inventory.get("item.void_anchor") == 2
                assert inventory.get("item.void_crystal") == 7

                void_breakthrough_operation = next(
                    f"{adapter}-new-void-break-{candidate}"
                    for candidate in range(1000)
                    if breakthrough_roll_bp(f"{adapter}-new-void-break-{candidate}") < 7710
                )
                started_void = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "new-void-breakthrough-start", void_breakthrough_operation),
                    "开始突破 炼虚",
                )
                assert started_void.code == "BREAKTHROUGH_STARTED", started_void.message
                clock.advance(minutes=15)
                settled_void = await _dispatch(runtime, adapter, user, 5125, "结算突破")
                assert settled_void.code == "BREAKTHROUGH_SUCCEEDED", settled_void.message
                assert settled_void.data["target_realm"] == "void_refining"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    final_state = connection.execute(
                        "SELECT realm_key, realm_layer, void_power, void_power_max, world_merit, domain_charge "
                        "FROM players WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    ).fetchone()
                assert final_state[:4] == ("void_refining", 1, 200, 200)
                assert final_state[4] >= 2_000, final_state
                assert final_state[5] == 50

                # Continue the new character through void-refining L10 using
                # the public daily refinement and advancement commands.
                void_l10_reached = False
                for day in range(260):
                    operation_base = 20000 + day * 10
                    clock.advance(days=1)
                    await _dispatch(runtime, adapter, user, operation_base, "恢复状态")
                    await _dispatch(runtime, adapter, user, operation_base + 1, "道历问安")
                    for slot in range(2):
                        started_refinement = await _dispatch(
                            runtime,
                            adapter,
                            user,
                            operation_base + 2 + slot * 2,
                            "开始修炼 神魂淬炼",
                        )
                        assert started_refinement.code == "CULTIVATION_STARTED", started_refinement.message
                        clock.advance(minutes=30)
                        settled_refinement = await _dispatch(
                            runtime,
                            adapter,
                            user,
                            operation_base + 3 + slot * 2,
                            "结算修炼",
                        )
                        assert settled_refinement.data["cultivation_gain"] >= 5_000
                    realm = str(settled_refinement.data["realm_key"])
                    layer = int(settled_refinement.data["realm_layer"])
                    threshold = next_layer_threshold(realm, layer)
                    if threshold is not None and int(settled_refinement.data["cultivation"]) >= threshold:
                        advanced = await _dispatch(
                            runtime,
                            adapter,
                            user,
                            operation_base + 6,
                            "晋升境界",
                        )
                        assert advanced.code == "REALM_LAYER_ADVANCED"
                    with sqlite3.connect(runtime.settings.database_path) as connection:
                        void_state = connection.execute(
                            "SELECT realm_key, realm_layer, cultivation, total_cultivation, world_merit, spirit_stones "
                            "FROM players WHERE platform=? AND platform_user_id=?",
                            (adapter, user),
                        ).fetchone()
                    if (
                        void_state[0] == "void_refining"
                        and int(void_state[1]) == 10
                        and int(void_state[2]) >= 2_150_000
                        and int(void_state[3]) >= 2_998_960
                    ):
                        void_l10_reached = True
                        break
                assert void_l10_reached, void_state
                assert int(void_state[4]) >= 2_000, void_state
                await runtime.close()

    asyncio.run(run())
