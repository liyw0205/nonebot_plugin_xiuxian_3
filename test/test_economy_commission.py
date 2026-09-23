from __future__ import annotations

import asyncio
import json
import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.adapters.onebot import normalize_event as normalize_onebot_event
from nonebot_plugin_xiuxian_3.adapters.qq import normalize_event as normalize_qq_event
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


def _context(user_id: str, operation_id: str = "") -> CommandContext:
    return CommandContext(adapter="web", user_id=user_id, operation_id=operation_id)


async def _create_player(runtime, user_id: str, operation_prefix: str) -> None:
    assert (await runtime.dispatch(_context(user_id, operation_prefix + "-create"), "开始修仙")).ok
    assert (await runtime.dispatch(_context(user_id, operation_prefix + "-seek"), "寻仙问道")).ok


def _prepare_alchemist(runtime, user_id: str, *, energy: int = 20) -> None:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            """
            UPDATE players SET stage = 'cultivator', realm_key = 'qi_sensing', realm_layer = 1,
                subprofession_key = 'alchemy', energy = ?, energy_max = ?,
                inventory_json = ?
            WHERE platform_user_id = ?
            """,
            (
                energy,
                energy,
                json.dumps(
                    {
                        "item.herb.blood_grass": 3,
                        "item.food.coarse_spirit_rice": 2,
                        "item.tool.basic_furnace": 1,
                    },
                    ensure_ascii=False,
                ),
                user_id,
            ),
        )


def test_production_commission_happy_path_uses_qq_and_onebot_contexts() -> None:
    from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message
    from nonebot.adapters.onebot.v11.event import Sender
    from nonebot.adapters.qq.event import GroupMessageCreateEvent
    from nonebot.adapters.qq.models.qq import GroupMemberAuthor

    qq_event = GroupMessageCreateEvent(
        id="commission-qq-1",
        content="开始修仙",
        timestamp="2026-01-01T00:00:00+00:00",
        author=GroupMemberAuthor(id="qq-raw", bot=False, member_openid="publisher", username="委托人"),
        group_id="qq-raw-group",
        group_openid="commission-group",
    )
    onebot_event = GroupMessageEvent(
        time=1_735_689_600,
        self_id=9001,
        post_type="message",
        sub_type="normal",
        user_id=2001,
        message_type="group",
        message_id=9002,
        message=Message("开始修仙"),
        original_message=Message("开始修仙"),
        raw_message="开始修仙",
        font=0,
        sender=Sender(user_id=2001, nickname="生产者"),
        group_id=3001,
    )
    qq = normalize_qq_event(qq_event).context
    onebot = normalize_onebot_event(onebot_event).context
    assert qq.adapter == "qq.official"
    assert onebot.adapter == "onebot.v11"

    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 23, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            assert (await runtime.adapters.dispatch("qq.official", replace(qq, operation_id="qq-create"), "开始修仙")).ok
            assert (await runtime.adapters.dispatch("qq.official", replace(qq, operation_id="qq-seek"), "寻仙问道")).ok
            assert (await runtime.adapters.dispatch("onebot.v11", replace(onebot, operation_id="ob-create"), "开始修仙")).ok
            assert (await runtime.adapters.dispatch("onebot.v11", replace(onebot, operation_id="ob-seek"), "寻仙问道")).ok
            _prepare_alchemist(runtime, "2001")

            created = await runtime.adapters.dispatch(
                "qq.official",
                replace(qq, operation_id="qq-commission"),
                "发布生产委托 疗伤丹 50 生产者供料",
            )
            assert created.code == "COMMISSION_CREATED"
            commission_id = created.data["commission_id"]
            accept_operation = next(
                f"ob-accept-{index}"
                for index in range(256)
                if random_quality_bp(f"ob-accept-{index}") >= 1000
            )
            accepted = await runtime.adapters.dispatch(
                "onebot.v11",
                replace(onebot, operation_id=accept_operation),
                f"接取生产委托 {commission_id}",
            )
            assert accepted.code == "COMMISSION_ACCEPTED"
            clock.advance(seconds=31)
            delivered = await runtime.adapters.dispatch(
                "onebot.v11",
                replace(onebot, operation_id="ob-deliver"),
                f"交付生产委托 {commission_id}",
            )
            assert delivered.code == "COMMISSION_DELIVERED"
            assert delivered.data["status"] == "delivered"
            settled = await runtime.adapters.dispatch(
                "qq.official",
                replace(qq, operation_id="qq-settle"),
                f"确认生产委托 {commission_id}",
            )
            assert settled.code == "COMMISSION_SETTLED"
            assert settled.data["producer_payment"] == 49
            replay = await runtime.adapters.dispatch(
                "qq.official",
                replace(qq, operation_id="qq-settle"),
                f"确认生产委托 {commission_id}",
            )
            assert replay.data["idempotent_replay"] is True
            with sqlite3.connect(runtime.settings.database_path) as connection:
                producer = connection.execute(
                    "SELECT spirit_stones, inventory_json, energy FROM players WHERE platform_user_id = '2001'"
                ).fetchone()
                assert producer[0] == 149
                assert "item.pill.healing_low" not in json.loads(producer[1])
                assert producer[2] == 16
                publisher_inventory = json.loads(
                    connection.execute(
                        "SELECT inventory_json FROM players WHERE platform_user_id = 'publisher'"
                    ).fetchone()[0]
                )
                assert publisher_inventory["item.pill.healing_low"] == 1
                assert connection.execute(
                    "SELECT status FROM production_commission_orders WHERE commission_id = ?", (commission_id,)
                ).fetchone()[0] == "settled"
            await runtime.close()

    asyncio.run(run())


def test_production_commission_failure_cancel_and_expiry_are_atomic() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 23, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            for user in ("publisher", "producer"):
                await _create_player(runtime, user, user)
            _prepare_alchemist(runtime, "producer")
            create = await runtime.dispatch(_context("publisher", "create"), "发布生产委托 疗伤丹 100 生产者供料")
            commission_id = create.data["commission_id"]
            failure_operation = next(
                f"accept-failure-{index}" for index in range(256) if random_quality_bp(f"accept-failure-{index}") == 0
            )
            accept = await runtime.dispatch(_context("producer", failure_operation), f"接取生产委托 {commission_id}")
            assert accept.code == "COMMISSION_ACCEPTED"
            clock.advance(seconds=31)
            failed = await runtime.dispatch(_context("producer", "deliver-failed"), f"交付生产委托 {commission_id}")
            assert failed.data["status"] == "failed"
            assert failed.data["publisher_refund"] == 80
            with sqlite3.connect(runtime.settings.database_path) as connection:
                publisher_stones = connection.execute(
                    "SELECT spirit_stones FROM players WHERE platform_user_id = 'publisher'"
                ).fetchone()[0]
                assert publisher_stones == 80

            _prepare_alchemist(runtime, "producer")
            second = await runtime.dispatch(_context("publisher", "create-2"), "发布生产委托 疗伤丹 40 生产者供料")
            second_id = second.data["commission_id"]
            accepted = await runtime.dispatch(_context("producer", "accept-2"), f"接取生产委托 {second_id}")
            assert accepted.ok
            cancelled = await runtime.dispatch(_context("producer", "cancel-2"), f"取消生产委托 {second_id}")
            assert cancelled.code == "COMMISSION_CANCELLED"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                producer = connection.execute(
                    "SELECT spirit_stones, energy, inventory_json, durability_json FROM players WHERE platform_user_id = 'producer'"
                ).fetchone()
                assert producer[1] == 20
                assert json.loads(producer[2])["item.herb.blood_grass"] == 3
                assert json.loads(producer[3]).get("item.tool.basic_furnace", 2000) == 1900

            third = await runtime.dispatch(_context("publisher", "create-3"), "发布生产委托 疗伤丹 20 委托人供料")
            third_id = third.data["commission_id"]
            with sqlite3.connect(runtime.settings.database_path) as connection:
                before = connection.execute(
                    "SELECT spirit_stones, inventory_json FROM players WHERE platform_user_id = 'publisher'"
                ).fetchone()
            clock.advance(hours=25)
            expired = await runtime.dispatch(_context("publisher", "expire-3"), f"清理生产委托 {third_id}")
            assert expired.code == "COMMISSION_EXPIRED"
            again = await runtime.dispatch(_context("publisher", "expire-3-replay"), f"清理生产委托 {third_id}")
            assert again.code == "COMMISSION_EXPIRED"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                after = connection.execute(
                    "SELECT spirit_stones, inventory_json FROM players WHERE platform_user_id = 'publisher'"
                ).fetchone()
                assert after[0] == before[0] + 20
                assert json.loads(after[1])["item.herb.blood_grass"] == json.loads(before[1])["item.herb.blood_grass"] + 2
                assert connection.execute(
                    "SELECT COUNT(*) FROM economy_ledger_entries WHERE reason = 'commission.expiry_refund' AND source_id = ?",
                    (third_id,),
                ).fetchone()[0] == 1
            await runtime.close()

    asyncio.run(run())


def test_production_commission_accept_is_single_winner() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            for user in ("publisher", "one", "two"):
                await _create_player(runtime, user, user)
            _prepare_alchemist(runtime, "one")
            _prepare_alchemist(runtime, "two")
            created = await runtime.dispatch(_context("publisher", "create"), "发布生产委托 疗伤丹 20 生产者供料")
            commission_id = created.data["commission_id"]
            results = await asyncio.gather(
                runtime.dispatch(_context("one", "accept-one"), f"接取生产委托 {commission_id}"),
                runtime.dispatch(_context("two", "accept-two"), f"接取生产委托 {commission_id}"),
            )
            assert sum(result.ok for result in results) == 1
            assert sorted(result.code for result in results) == ["COMMISSION_ACCEPTED", "COMMISSION_STATE_CONFLICT"]
            await runtime.close()

    asyncio.run(run())
