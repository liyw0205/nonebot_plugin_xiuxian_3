from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.exploration.rules import settlement_result
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
