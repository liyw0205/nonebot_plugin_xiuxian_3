from __future__ import annotations

import asyncio
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


def test_qq_and_onebot_can_reach_nascent_soul_from_new_player() -> None:
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
                await runtime.close()

    asyncio.run(run())
