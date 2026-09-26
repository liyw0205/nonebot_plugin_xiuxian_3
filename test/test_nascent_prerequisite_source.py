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


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs: int) -> None:
        self.now += timedelta(**kwargs)


def test_qq_onebot_golden_core_player_gets_nascent_breakthrough_materials() -> None:
    async def run() -> None:
        for adapter in ("qq.official", "onebot.v11"):
            with TemporaryDirectory() as directory:
                clock = Clock()
                runtime = create_runtime(data_dir=directory, clock=clock)
                user = f"nascent-prerequisite-{adapter}"

                async def send(command: str, request: str, operation: str = ""):
                    context = CommandContext(adapter=adapter, user_id=user, request_id=request, operation_id=operation)
                    return await runtime.adapters.dispatch(adapter, context, command)

                for index, command in enumerate((
                    "开始修仙", "寻仙问道", "完成引导 阅读", "前往近郊",
                    "完成引导 采集", "完成引导 炼丹", "选择道途 辅修 炼丹",
                )):
                    assert (await send(command, f"intro-{index}")).ok
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE players SET realm_key='golden_core', realm_layer=10, cultivation=47000, total_cultivation=58960, foundation_quality=5500, world_merit=100, spirit_stones=9000, stamina=100, energy=40, energy_max=40, inventory_json=? WHERE platform=? AND platform_user_id=?",
                        (json.dumps({"item.herb.spirit_leaf": 3, "item.mat.array_sand": 2, "item.tool.basic_furnace": 1}), adapter, user),
                    )
                for destination, duration, index in (("青石镇", 30, 0), ("云城", 180, 1)):
                    started = await send(f"前往 {destination}", f"travel-{index}")
                    assert started.code == "TRAVEL_STARTED", started.message
                    clock.advance(seconds=duration)
                    assert (await send("结算移动", f"arrive-{index}")).code == "TRAVEL_COMPLETED"
                assert (await send("乘坐云舟 魔界引导", "board-gate")).code == "CLOUD_BOAT_STARTED"
                clock.advance(minutes=5)
                assert (await send("结算云舟", "arrive-gate")).ok
                assert (await send("开始探索 深渊门备材", "before-intro")).code == "EXPLORATION_LOCATION_FORBIDDEN"
                assert (await send("接受魔界引导", "intro-gate")).code == "DEMON_INTRO_ACCEPTED"
                for index in range(6):
                    started = await send("开始探索 深渊门备材", f"gather-{index}")
                    assert started.code == "EXPLORATION_STARTED", started.message
                    clock.advance(minutes=4)
                    settled = await send("结算探索", f"settle-gather-{index}")
                    assert settled.code == "EXPLORATION_SETTLED", settled.message
                    assert settled.data["result"] == {"item.soul_crystal": 1, "item.demon_core": 1}
                    if index == 0:
                        replay = await send("结算探索", "settle-gather-0")
                        assert replay.data["idempotent_replay"] is True
                        with sqlite3.connect(runtime.settings.database_path) as connection:
                            snapshot = json.loads(connection.execute("SELECT snapshot_json FROM exploration_sessions WHERE exploration_id=?", (started.data["exploration_id"],)).fetchone()[0])
                            assert snapshot["rule_version"] == "exploration-0.3.1"
                            assert connection.execute("SELECT COUNT(*) FROM exploration_item_bindings WHERE player_id=(SELECT id FROM players WHERE platform=? AND platform_user_id=?)", (adapter, user)).fetchone()[0] == 1
                        assert (await send("发布摆摊 魔核 1 100", "bound-market")).code == "ITEM_BINDING_ACTIVE"
                        assert (await send("发布拍卖 魔核 1 100", "bound-auction")).code == "ITEM_BINDING_ACTIVE"
                        buyer = f"buyer-{adapter}"
                        buyer_context = CommandContext(adapter=adapter, user_id=buyer, request_id="buyer-create")
                        assert (await runtime.adapters.dispatch(adapter, buyer_context, "开始修仙")).ok
                        with sqlite3.connect(runtime.settings.database_path) as connection:
                            connection.execute("UPDATE players SET spirit_stones=500 WHERE platform=? AND platform_user_id=?", (adapter, buyer))
                        purchase_context = CommandContext(adapter=adapter, user_id=buyer, request_id="buyer-order")
                        purchase = await runtime.adapters.dispatch(adapter, purchase_context, "发布求购 item.demon_core 1 100")
                        assert purchase.code == "PURCHASE_ORDER_CREATED", purchase.message
                        assert (await send(f"匹配求购 {purchase.data['order_id']}", "bound-purchase")).code == "ITEM_BINDING_ACTIVE"
                assert (await send("开始探索 深渊门备材", "over-limit")).code == "EXPLORATION_QUOTA_EXHAUSTED"
                assert (await send("乘坐云舟 返回云城", "board-return")).code == "CLOUD_BOAT_STARTED"
                clock.advance(minutes=3)
                assert (await send("结算云舟", "arrive-return")).ok
                operation = next(f"soul-pill-{adapter}-{index}" for index in range(1000) if random_quality_bp(f"soul-pill-{adapter}-{index}") >= 1000)
                produced = await send("开始生产 凝魂丹", "produce", operation)
                assert produced.code == "PRODUCTION_STARTED", produced.message
                clock.advance(minutes=5)
                settled_pill = await send("领取生产", "collect")
                assert settled_pill.code == "PRODUCTION_COMPLETED" and settled_pill.data["success"]
                assert settled_pill.data["outputs"] == {"item.pill.soul_condense": 1}
                assert (await send("发布摆摊 item.pill.soul_condense 1 1", "market-bound")).code == "MARKET_ITEM_FORBIDDEN"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    snapshot = json.loads(connection.execute("SELECT snapshot_json FROM production_orders WHERE order_id=?", (produced.data["order_id"],)).fetchone()[0])
                    assert snapshot["rule_version"] == "production-0.3.1"
                    inventory = json.loads(connection.execute("SELECT inventory_json FROM players WHERE platform=? AND platform_user_id=?", (adapter, user)).fetchone()[0])
                    assert inventory["item.soul_crystal"] == 5
                    assert inventory["item.demon_core"] == 6
                    assert inventory["item.pill.soul_condense"] == 1
                assert (await send("准备元婴", "prepare")).code == "NASCENT_SOUL_PREPARED"
                breakthrough = next(f"soul-break-{adapter}-{index}" for index in range(1000) if breakthrough_roll_bp(f"soul-break-{adapter}-{index}") < 5500)
                started_break = await send("开始突破 元婴", "start-break", breakthrough)
                assert started_break.code == "BREAKTHROUGH_STARTED", started_break.message
                clock.advance(minutes=30)
                finished = await send("结算突破", "settle-break")
                assert finished.code == "BREAKTHROUGH_SUCCEEDED", finished.message
                assert finished.data["target_realm"] == "nascent_soul"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    assert connection.execute("SELECT COUNT(*) FROM exploration_item_bindings WHERE player_id=(SELECT id FROM players WHERE platform=? AND platform_user_id=?)", (adapter, user)).fetchone()[0] == 6
                await runtime.close()
                runtime = create_runtime(data_dir=directory, clock=clock)
                assert (await send("发布摆摊 魔核 1 100", "reopened-bound")).code == "ITEM_BINDING_ACTIVE"
                clock.advance(days=1)
                assert (await send("发布摆摊 魔核 1 100", "unbound-market")).code == "MARKET_ORDER_CREATED"
                await runtime.close()

    asyncio.run(run())
