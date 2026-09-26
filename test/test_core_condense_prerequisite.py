from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.production.rules import random_quality_bp
from nonebot_plugin_xiuxian_3.xiuxian.progression.breakthrough.rules import breakthrough_roll_bp
from nonebot_plugin_xiuxian_3.xiuxian.exploration.rules import battle_roll_bp, settlement_result


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs: int) -> None:
        self.now += timedelta(**kwargs)


def _context(adapter: str, user: str, request: str, operation: str = "") -> CommandContext:
    return CommandContext(adapter=adapter, user_id=user, request_id=request, operation_id=operation)


def test_foundation_player_produces_bound_core_condense_before_breakthrough() -> None:
    async def run() -> None:
        for adapter in ("qq.official", "onebot.v11"):
            with TemporaryDirectory() as directory:
                clock = Clock()
                runtime = create_runtime(data_dir=directory, clock=clock)
                user = f"foundation-source-{adapter}"

                async def send(command: str, request: str, operation: str = ""):
                    return await runtime.adapters.dispatch(adapter, _context(adapter, user, request, operation), command)

                for index, command in enumerate((
                    "开始修仙", "寻仙问道", "完成引导 阅读", "前往近郊",
                    "完成引导 采集", "完成引导 炼丹", "选择道途 辅修 炼丹",
                )):
                    assert (await send(command, f"onboard-{index}")).ok
                assert (await send("开始生产 凝核丹", "too-early")).code == "RECIPE_REQUIREMENT_MISSING"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE players SET realm_key='foundation', realm_layer=10, cultivation=7700, total_cultivation=11960, foundation_quality=4000, stamina=100, energy=30, spirit_stones=2000, inventory_json=? WHERE platform=? AND platform_user_id=?",
                        (json.dumps({
                            "item.herb.spirit_leaf": 5,
                            "item.mat.array_sand": 2, "item.tool.basic_furnace": 1,
                        }), adapter, user),
                    )
                assert (await send("前往 青石镇", "to-town")).code == "TRAVEL_STARTED"
                clock.advance(seconds=30)
                assert (await send("结算移动", "town-arrived")).code == "TRAVEL_COMPLETED"
                assert (await send("前往 云铁矿区", "to-mine")).code == "TRAVEL_STARTED"
                clock.advance(seconds=120)
                assert (await send("结算移动", "mine-arrived")).code == "TRAVEL_COMPLETED"
                assert (await send("开始探索 云铁采集", "no-permit")).code == "EXPLORATION_LOCATION_FORBIDDEN"
                assert (await send("接取悬赏 云铁矿区悬赏", "mine-bounty")).code == "BOUNTY_ACCEPTED"
                for index in range(2):
                    gather = next(
                        f"mine-{adapter}-{index}-{candidate}" for candidate in range(1000)
                        if battle_roll_bp(f"mine-{adapter}-{index}-{candidate}:battle") >= 3000
                        and settlement_result("explore.cloud_mine", f"mine-{adapter}-{index}-{candidate}")["item.material.cloud_iron"] >= 3
                    )
                    assert (await send("开始探索 云铁采集", f"mine-start-{index}", gather)).code == "EXPLORATION_STARTED"
                    clock.advance(seconds=120)
                    assert (await send("结算探索", f"mine-settle-{index}")).code == "EXPLORATION_SETTLED"
                assert (await send("领取悬赏", "claim-mine")).code == "BOUNTY_CLAIMED"
                assert (await send("开始探索 云铁采集", "claimed-no-permit")).code == "EXPLORATION_LOCATION_FORBIDDEN"
                assert (await send("前往 青石镇", "leave-mine")).code == "TRAVEL_STARTED"
                clock.advance(seconds=30)
                assert (await send("结算移动", "back-town")).code == "TRAVEL_COMPLETED"
                operation = next(f"core-{adapter}-{index}" for index in range(1000) if random_quality_bp(f"core-{adapter}-{index}") >= 1000)
                started = await send("开始生产 凝核丹", "produce", operation)
                assert started.code == "PRODUCTION_STARTED", started.message
                clock.advance(seconds=180)
                collected = await send("领取生产", "collect")
                assert collected.code == "PRODUCTION_COMPLETED", collected.message
                assert collected.data["outputs"] == {"item.pill.core_condense": 1}
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    snapshot = json.loads(connection.execute(
                        "SELECT snapshot_json FROM production_orders WHERE order_id=?", (started.data["order_id"],),
                    ).fetchone()[0])
                    assert snapshot["rule_version"] == "production-0.2.1"
                    inventory = json.loads(connection.execute(
                        "SELECT inventory_json FROM players WHERE platform=? AND platform_user_id=?", (adapter, user),
                    ).fetchone()[0])
                    assert inventory["item.pill.core_condense"] == 1
                breakthrough = next(f"golden-{adapter}-{index}" for index in range(1000) if breakthrough_roll_bp(f"golden-{adapter}-{index}") < 4800)
                begun = await send("开始突破 金丹", "breakthrough", breakthrough)
                assert begun.code == "BREAKTHROUGH_STARTED", begun.message
                clock.advance(minutes=5)
                settled = await send("结算突破", "settle")
                assert settled.code == "BREAKTHROUGH_SUCCEEDED", settled.message
                assert settled.data["target_realm"] == "golden_core"
                await runtime.close()

    asyncio.run(run())


def test_expired_mine_commission_cannot_grant_exploration_access() -> None:
    async def run() -> None:
        with TemporaryDirectory() as directory:
            clock = Clock()
            runtime = create_runtime(data_dir=directory, clock=clock)
            user = "expired-mine-commission"

            async def send(command: str, request: str):
                return await runtime.adapters.dispatch("qq.official", _context("qq.official", user, request), command)

            assert (await send("开始修仙", "create")).ok
            assert (await send("寻仙问道", "seek")).ok
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE players SET stage='cultivator', realm_key='foundation', realm_layer=4, location_key='xuantian.cloud_mine' WHERE platform_user_id=?",
                    (user,),
                )
            assert (await send("接取悬赏 云铁矿区悬赏", "accept")).code == "BOUNTY_ACCEPTED"
            clock.advance(hours=2, seconds=1)
            assert (await send("开始探索 云铁采集", "expired")).code == "EXPLORATION_LOCATION_FORBIDDEN"
            await runtime.close()

    asyncio.run(run())
