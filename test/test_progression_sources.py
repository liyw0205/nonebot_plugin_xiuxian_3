from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.exploration.rules import battle_roll_bp, settlement_result
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
    result = await runtime.dispatch(
        _context(adapter, user, f"{adapter}-{index}", operation_id), command
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

                operation = next(
                    f"{adapter}-focus-{index}"
                    for index in range(100)
                    if random_quality_bp(f"{adapter}-focus-{index}") >= 500
                )
                started = await runtime.dispatch(
                    _context(adapter, user, "focus-start", operation),
                    "开始生产 焦点丹",
                )
                assert started.code == "PRODUCTION_STARTED"
                clock.advance(seconds=45)
                completed = await _dispatch(runtime, adapter, user, 36, "领取生产")
                assert completed.code == "PRODUCTION_COMPLETED"
                assert completed.data["outputs"] == {"item.pill.focus_low": 1}
                await runtime.close()

    asyncio.run(run())


def test_qq_and_onebot_can_produce_foundation_draft_from_player_path() -> None:
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
                started_focus = await runtime.dispatch(
                    _context(adapter, user, "foundation-focus-start", focus_operation),
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
                started_breakthrough = await runtime.dispatch(
                    _context(adapter, user, "qi-breakthrough-start", breakthrough_operation),
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

                started_draft = await runtime.dispatch(
                    _context(adapter, user, "foundation-draft-start", f"{adapter}-foundation-draft"),
                    "开始生产 筑基丹",
                )
                assert started_draft.code == "PRODUCTION_STARTED", started_draft.message
                clock.advance(seconds=120)
                completed_draft = await _dispatch(runtime, adapter, user, 94, "领取生产")
                assert completed_draft.code == "PRODUCTION_COMPLETED"
                assert completed_draft.data["success"] is True
                assert completed_draft.data["outputs"] == {"item.pill.foundation_draft": 1}
                forbidden_market = await runtime.dispatch(
                    _context(adapter, user, "foundation-draft-market"),
                    "发布摆摊 筑基丹 1 1",
                )
                assert forbidden_market.code == "MARKET_ITEM_FORBIDDEN"
                await runtime.close()

    asyncio.run(run())
