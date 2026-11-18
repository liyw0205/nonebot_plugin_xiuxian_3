from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.production.rules import random_quality_bp


class MutableClock:
    def __init__(self, value: datetime):
        self.value = value

    def __call__(self) -> datetime:
        return self.value

    def advance(self, **kwargs: int) -> None:
        self.value += timedelta(**kwargs)


async def _send(runtime, adapter: str, user: str, operation_id: str, command: str):
    return await runtime.adapters.dispatch(
        adapter,
        CommandContext(adapter=adapter, user_id=user, operation_id=operation_id),
        command,
    )


async def _create_player(runtime, adapter: str, user: str) -> None:
    assert (await _send(runtime, adapter, user, f"{user}-create", "开始修仙")).ok
    assert (await _send(runtime, adapter, user, f"{user}-seek", "寻仙问道")).ok


def _prepare_alchemist(runtime, user: str) -> None:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            """
            UPDATE players SET stage='cultivator', realm_key='qi_sensing', realm_layer=1,
                subprofession_key='alchemy', energy=20, energy_max=20, inventory_json=?
            WHERE platform_user_id=?
            """,
            (
                json.dumps(
                    {
                        "item.herb.blood_grass": 10,
                        "item.food.coarse_spirit_rice": 10,
                        "item.tool.basic_furnace": 1,
                    },
                    ensure_ascii=False,
                ),
                user,
            ),
        )


def test_batch_commission_runs_from_qq_to_onebot_and_scales_assets() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 23, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            await _create_player(runtime, "qq.official", "publisher")
            await _create_player(runtime, "onebot.v11", "producer")
            _prepare_alchemist(runtime, "producer")

            preview = await _send(runtime, "qq.official", "publisher", "preview", "批量委托预览 疗伤丹 2")
            assert preview.code == "BATCH_COMMISSION_PREVIEW"
            assert preview.data["inputs"]["item.herb.blood_grass"] == 4
            assert preview.data["duration_seconds"] == 60

            created = await _send(
                runtime,
                "qq.official",
                "publisher",
                "create-batch",
                "发布批量生产委托 疗伤丹 2 30 生产者供料",
            )
            assert created.code == "BATCH_COMMISSION_CREATED"
            assert created.data["batch_count"] == 2
            assert created.data["reward_stones"] == 60
            commission_id = str(created.data["commission_id"])

            accepted_operation = next(
                f"accept-batch-{index}"
                for index in range(512)
                if random_quality_bp(f"accept-batch-{index}") >= 1000
            )
            accepted = await _send(
                runtime,
                "onebot.v11",
                "producer",
                accepted_operation,
                f"接取批量生产委托 {commission_id}",
            )
            assert accepted.code == "BATCH_COMMISSION_ACCEPT"
            assert accepted.data["ends_at"]

            clock.advance(seconds=61)
            delivered = await _send(
                runtime,
                "onebot.v11",
                "producer",
                "deliver-batch",
                f"交付批量生产委托 {commission_id}",
            )
            assert delivered.code == "BATCH_COMMISSION_DELIVER"
            assert delivered.data["outputs"]["item.pill.healing_low"] == 2

            settled = await _send(
                runtime,
                "qq.official",
                "publisher",
                "settle-batch",
                f"确认批量生产委托 {commission_id}",
            )
            assert settled.code == "BATCH_COMMISSION_SETTLE"
            assert settled.data["producer_payment"] == 59
            with sqlite3.connect(runtime.settings.database_path) as connection:
                producer = connection.execute(
                    "SELECT energy, durability_json FROM players WHERE platform_user_id='producer'"
                ).fetchone()
                assert producer[0] == 12
                assert json.loads(producer[1])["item.tool.basic_furnace"] == 1800
                publisher_inventory = json.loads(
                    connection.execute(
                        "SELECT inventory_json FROM players WHERE platform_user_id='publisher'"
                    ).fetchone()[0]
                )
                assert publisher_inventory["item.pill.healing_low"] == 2
                assert connection.execute(
                    "SELECT batch_count FROM production_commission_orders WHERE commission_id=?",
                    (commission_id,),
                ).fetchone()[0] == 2
            await runtime.close()

    asyncio.run(run())


def test_batch_commission_cancel_releases_scaled_publisher_materials() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            await _create_player(runtime, "qq.official", "publisher")
            await _create_player(runtime, "onebot.v11", "producer")
            _prepare_alchemist(runtime, "publisher")
            created = await _send(
                runtime,
                "qq.official",
                "publisher",
                "create-publisher-supplies",
                "发布批量生产委托 疗伤丹 3 20 委托人供料",
            )
            assert created.ok
            commission_id = str(created.data["commission_id"])
            with sqlite3.connect(runtime.settings.database_path) as connection:
                after_publish = json.loads(
                    connection.execute(
                        "SELECT inventory_json FROM players WHERE platform_user_id='publisher'"
                    ).fetchone()[0]
                )
            cancelled = await _send(
                runtime,
                "qq.official",
                "publisher",
                "cancel-publisher-supplies",
                f"取消批量生产委托 {commission_id}",
            )
            assert cancelled.code == "BATCH_COMMISSION_CANCEL"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                after = json.loads(
                    connection.execute(
                        "SELECT inventory_json FROM players WHERE platform_user_id='publisher'"
                    ).fetchone()[0]
                )
            assert after["item.herb.blood_grass"] == after_publish["item.herb.blood_grass"] + 6
            assert after["item.food.coarse_spirit_rice"] == after_publish["item.food.coarse_spirit_rice"] + 3
            await runtime.close()

    asyncio.run(run())
