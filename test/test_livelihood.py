from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory

import pytest

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime


class MutableClock:
    def __init__(self, value: datetime):
        self.value = value

    def __call__(self) -> datetime:
        return self.value

    def advance(self, **kwargs: int) -> None:
        self.value += timedelta(**kwargs)


def _context(user: str, operation_id: str = "") -> CommandContext:
    return CommandContext(adapter="web", user_id=user, operation_id=operation_id)


def test_blood_grass_plot_is_idempotent_and_does_not_change_cultivation() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            user = "livelihood-user"
            context = _context(user)
            assert (await runtime.dispatch(context, "开始修仙")).ok
            assert (await runtime.dispatch(context, "寻仙问道")).ok
            leased = await runtime.dispatch(_context(user, "lease"), "租住居所")
            assert leased.code == "RESIDENCE_LEASED"
            planted = await runtime.dispatch(_context(user, "plant"), "灵田播种 止血草")
            assert planted.code == "FIELD_PLOT_PLANTED"
            replayed = await runtime.dispatch(_context(user, "plant"), "灵田播种 止血草")
            assert replayed.code == planted.code
            assert replayed.data["plot_id"] == planted.data["plot_id"]
            assert replayed.data["idempotent_replay"] is True

            busy = await runtime.dispatch(_context(user, "plant-2"), "灵田播种")
            assert busy.code == "FIELD_PLOT_BUSY"
            maintained = await runtime.dispatch(_context(user, "maintain"), "灵田维护")
            assert maintained.code == "FIELD_PLOT_MAINTAINED"
            clock.advance(hours=4)
            harvested = await runtime.dispatch(_context(user, "harvest"), "灵田收获")
            assert harvested.code == "FIELD_PLOT_HARVESTED"
            assert harvested.data["harvest"] == {"item.herb.blood_grass": 3}
            assert harvested.data["local_reputation_delta"] == 1
            harvest_replay = await runtime.dispatch(_context(user, "harvest"), "灵田收获")
            assert harvest_replay.data["harvest"] == harvested.data["harvest"]
            assert harvest_replay.data["idempotent_replay"] is True
            second = await runtime.dispatch(_context(user, "plant-3"), "灵田播种")
            assert second.code == "FIELD_PLOT_PLANTED"
            clock.advance(hours=4)
            unmaintained = await runtime.dispatch(_context(user, "harvest-2"), "灵田收获")
            assert unmaintained.data["harvest"] == {"item.herb.blood_grass": 1}
            daily_limit = await runtime.dispatch(_context(user, "plant-4"), "灵田播种")
            assert daily_limit.code == "CROP_DAILY_LIMIT"

            with sqlite3.connect(runtime.settings.database_path) as connection:
                player = connection.execute(
                    "SELECT cultivation, total_cultivation, energy, inventory_json FROM players WHERE platform_user_id = ?",
                    (user,),
                ).fetchone()
                assert player[0:2] == (0, 0)
                assert player[2] == 27
                inventory = json.loads(player[3])
                assert inventory["item.herb.blood_grass"] == 5
                reputation = connection.execute(
                    "SELECT local_json FROM player_reputations WHERE player_id = (SELECT id FROM players WHERE platform_user_id = ?)",
                    (user,),
                ).fetchone()
                assert json.loads(reputation[0])["local.xuantian.new_town"] == 2
            await runtime.close()

    asyncio.run(run())


def test_plot_expiry_marks_withered_without_refunding_assets() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            user = "withered-user"
            context = _context(user)
            await runtime.dispatch(context, "开始修仙")
            await runtime.dispatch(context, "寻仙问道")
            await runtime.dispatch(_context(user, "lease"), "租住居所")
            await runtime.dispatch(_context(user, "plant"), "灵田播种")
            clock.advance(hours=29)
            result = await runtime.dispatch(_context(user, "harvest"), "灵田收获")
            assert result.code == "PLOT_WITHERED"
            profile = await runtime.dispatch(_context(user), "我的灵田")
            assert profile.data["status"] == "withered"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                row = connection.execute(
                    "SELECT energy, inventory_json FROM players WHERE platform_user_id = ?", (user,)
                ).fetchone()
                assert row[0] == 29
                assert json.loads(row[1])["item.herb.blood_grass"] == 2
            await runtime.close()

    asyncio.run(run())


def test_town_commission_defers_materials_until_delivery_and_settles_once() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            user = "commission-user"
            context = _context(user)
            await runtime.dispatch(context, "开始修仙")
            await runtime.dispatch(context, "寻仙问道")
            listed = await runtime.dispatch(_context(user), "城镇委托")
            assert listed.code == "COMMISSION_LIST"
            assert len(listed.data["commissions"]) == 3
            accepted = await runtime.dispatch(
                _context(user, "accept-herb"), "接取委托 止血草供应"
            )
            assert accepted.code == "COMMISSION_ACCEPTED"
            assert accepted.data["claim_id"] != accepted.data["commission_id"]
            with sqlite3.connect(runtime.settings.database_path) as connection:
                before = connection.execute(
                    "SELECT spirit_stones, cultivation, total_cultivation, inventory_json FROM players WHERE platform_user_id = ?",
                    (user,),
                ).fetchone()
            inventory_before = json.loads(before[3])
            assert inventory_before["item.herb.blood_grass"] == 3
            assert before[:3] == (100, 0, 0)

            delivered = await runtime.dispatch(
                _context(user, "deliver-herb"), "交付委托 止血草供应"
            )
            assert delivered.code == "COMMISSION_DELIVERED"
            assert delivered.data["reward_stones"] == 18
            replay = await runtime.dispatch(
                _context(user, "deliver-herb"), "交付委托 止血草供应"
            )
            assert replay.code == delivered.code
            assert replay.data["idempotent_replay"] is True
            with sqlite3.connect(runtime.settings.database_path) as connection:
                after = connection.execute(
                    "SELECT spirit_stones, cultivation, total_cultivation, inventory_json FROM players WHERE platform_user_id = ?",
                    (user,),
                ).fetchone()
                reputation = connection.execute(
                    "SELECT local_json, service_reputation FROM player_reputations WHERE player_id = (SELECT id FROM players WHERE platform_user_id = ?)",
                    (user,),
                ).fetchone()
            assert after[:3] == (118, 0, 0)
            assert json.loads(after[3])["item.herb.blood_grass"] == 0
            assert json.loads(reputation[0])["local.xuantian.new_town"] == 3
            assert reputation[1] == 1
            await runtime.close()

    asyncio.run(run())


def test_town_commission_quota_material_failure_and_global_stock_are_atomic() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)

            async def create_user(user: str) -> None:
                context = _context(user)
                await runtime.dispatch(context, "开始修仙")
                await runtime.dispatch(context, "寻仙问道")

            await create_user("quota-user")
            assert (await runtime.dispatch(_context("quota-user", "q1"), "接取委托 止血草供应")).ok
            assert (await runtime.dispatch(_context("quota-user", "q2"), "接取委托 工具修缮")).ok
            quota = await runtime.dispatch(_context("quota-user", "q3"), "接取委托 灵米饭供应")
            assert quota.code == "COMMISSION_QUOTA_EXHAUSTED"
            missing = await runtime.dispatch(_context("quota-user", "missing"), "交付委托 工具修缮")
            assert missing.code == "RESOURCE_INSUFFICIENT"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                wallet = connection.execute(
                    "SELECT spirit_stones, cultivation, total_cultivation FROM players WHERE platform_user_id = ?",
                    ("quota-user",),
                ).fetchone()
            assert wallet == (100, 0, 0)

            await create_user("stock-a")
            await create_user("stock-b")
            await runtime.dispatch(_context("stock-a"), "城镇委托")
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE town_commissions SET stock_remaining = 1 WHERE commission_key = ? AND business_date = ?",
                    ("town_commission.meal_service", "2026-09-22"),
                )
            results = await asyncio.gather(
                runtime.dispatch(_context("stock-a", "stock-a-op"), "接取委托 灵米饭供应"),
                runtime.dispatch(_context("stock-b", "stock-b-op"), "接取委托 灵米饭供应"),
            )
            assert {result.code for result in results} == {"COMMISSION_ACCEPTED", "COMMISSION_STOCK_EXHAUSTED"}
            await runtime.close()

    asyncio.run(run())


def _onebot_event(content: str, message_id: int):
    from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message
    from nonebot.adapters.onebot.v11.event import Sender

    return GroupMessageEvent(
        time=1_735_689_600,
        self_id=9001,
        post_type="message",
        sub_type="normal",
        user_id=1001,
        message_type="group",
        message_id=message_id,
        message=Message(content),
        original_message=Message(content),
        raw_message=content,
        font=0,
        sender=Sender(user_id=1001, nickname="OneBot道友"),
        group_id=2002,
    )


def _qq_event(content: str, message_id: str):
    from nonebot.adapters.qq.event import GroupMessageCreateEvent
    from nonebot.adapters.qq.models.qq import GroupMemberAuthor

    return GroupMessageCreateEvent(
        id=message_id,
        content=content,
        timestamp="2026-01-01T00:00:00+00:00",
        author=GroupMemberAuthor(
            id="qq-user-raw",
            bot=False,
            member_openid="qq-user-1",
            username="QQ道友",
        ),
        group_id="qq-group-raw",
        group_openid="qq-group-1",
    )


@pytest.mark.parametrize("kind", ["onebot", "qq"])
def test_real_adapters_reach_livelihood_application(kind: str) -> None:
    pytest.importorskip("nonebot")
    from nonebot_plugin_xiuxian_3.adapters.onebot import normalize_event
    from nonebot_plugin_xiuxian_3.adapters.qq import normalize_event as normalize_qq_event

    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            clock = MutableClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            texts = [
                "开始修仙",
                "寻仙问道",
                "城镇委托",
                "接取委托 止血草供应",
                "交付委托 止血草供应",
            ]
            for index, text in enumerate(texts):
                event = _onebot_event(text, 4000 + index) if kind == "onebot" else _qq_event(text, f"qq-{index}")
                normalized = normalize_event(event) if kind == "onebot" else normalize_qq_event(event)
                result = await runtime.dispatch(normalized.context, normalized.text)
                assert result.ok, result
            await runtime.close()

    asyncio.run(run())
