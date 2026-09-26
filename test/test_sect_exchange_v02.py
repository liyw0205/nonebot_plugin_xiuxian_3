from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory

import pytest

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.persistence.sqlite_repository import SQLitePlayerRepository
from nonebot_plugin_xiuxian_3.xiuxian.exploration.rules import battle_roll_bp


def _context(user: str, operation_id: str = "") -> CommandContext:
    return CommandContext(adapter="web", user_id=user, request_id=operation_id or "request", operation_id=operation_id)


async def _create_sect(runtime, user: str = "leader") -> str:
    assert (await runtime.dispatch(_context(user, "create-player"), "开始修仙")).ok
    assert (await runtime.dispatch(_context(user, "seek"), "寻仙问道")).ok
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE players SET realm_key='foundation', realm_layer=1, spirit_stones=40000, location_key='xuantian.outskirts', stamina=100, inventory_json=? WHERE platform_user_id=?",
            (json.dumps({"item.herb.spirit_leaf": 40, "item.herb.blood_grass": 30, "item.mat.array_sand": 20, "item.material.cloud_iron": 10}), user),
        )
    created = await runtime.dispatch(_context(user, "create-sect"), "创建宗门 青云门")
    assert created.code == "SECT_CREATED"
    return created.data["sect_id"]


async def _stock(runtime, user: str, count: int, *, stones: int = 0) -> None:
    if stones:
        assert (await runtime.dispatch(_context(user, f"donate-stones-{stones}"), f"宗门捐献 灵石 {stones}")).code == "SECT_DONATED"
    for label, quantity in (("灵叶", 2 * count), ("止血草", count), ("阵砂", count)):
        assert (await runtime.dispatch(_context(user, f"donate-{label}"), f"宗门捐献 {label} {quantity}")).code == "SECT_DONATED"
    for index in range(count):
        assert (await runtime.dispatch(_context(user, f"procure-{index}"), "宗门补给 筑基护脉丹")).code == "SECT_STOCK_PROCURED"


def test_sect_exchange_is_atomic_idempotent_and_daily_limited() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            sect_id = await _create_sect(runtime)
            await _stock(runtime, "leader", 6, stones=9900)
            assert (await runtime.dispatch(_context("leader", "more-stones"), "宗门捐献 灵石 9900")).code == "SECT_DONATED"

            listed = await runtime.dispatch(_context("leader"), "宗门商店")
            assert listed.code == "SECT_SHOP"
            assert any(item["offer_key"] == "sect.exchange.foundation_guard" for item in listed.data["offers"])

            first = await runtime.dispatch(_context("leader", "exchange-1"), "宗门商店兑换 筑基护脉丹")
            replay = await runtime.dispatch(_context("leader", "exchange-1"), "宗门商店兑换 筑基护脉丹")
            assert first.code == "SECT_EXCHANGE_COMPLETED"
            assert replay.data["idempotent_replay"] is True
            with sqlite3.connect(runtime.settings.database_path) as connection:
                row = connection.execute(
                    "SELECT s.warehouse_json, m.contribution, p.inventory_json FROM sects s JOIN sect_members m ON m.sect_id=s.sect_id JOIN players p ON p.id=m.player_id WHERE s.sect_id=?",
                    (sect_id,),
                ).fetchone()
            assert json.loads(row[0]) == {"item.pill.foundation_guard": 5}
            assert row[1] == 198 + 24 - 30
            assert json.loads(row[2])["item.pill.foundation_guard"] == 1

            for index in range(2, 6):
                result = await runtime.dispatch(_context("leader", f"exchange-{index}"), "宗门商店兑换 筑基护脉丹")
                assert result.code == "SECT_EXCHANGE_COMPLETED"
            limited = await runtime.dispatch(_context("leader", "exchange-6"), "宗门商店兑换 筑基护脉丹")
            assert limited.code == "SECT_EXCHANGE_DAILY_CAP"
            await runtime.close()

    asyncio.run(run())


def test_sect_exchange_rejects_missing_stock_and_contribution_without_changes() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            sect_id = await _create_sect(runtime)
            assert (await runtime.dispatch(_context("leader", "donate-currency"), "宗门捐献 灵石 9900")).code == "SECT_DONATED"
            stock = await runtime.dispatch(_context("leader", "stock"), "宗门兑换 筑基护脉丹")
            assert stock.code == "SECT_STOCK_INSUFFICIENT"
            await _stock(runtime, "leader", 1)
            assert (await runtime.dispatch(_context("leader", "donate-more"), "宗门捐献 灵石 9900")).code == "SECT_DONATED"
            # Another member starts with zero contribution, even when stock exists.
            assert (await runtime.dispatch(_context("member", "member-player"), "开始修仙")).ok
            assert (await runtime.dispatch(_context("member", "member-seek"), "寻仙问道")).ok
            assert (await runtime.dispatch(_context("member", "member-apply"), f"申请入宗 {sect_id}")).ok
            with sqlite3.connect(runtime.settings.database_path) as connection:
                application_id = connection.execute("SELECT application_id FROM sect_applications WHERE sect_id=?", (sect_id,)).fetchone()[0]
            assert (await runtime.dispatch(_context("leader", "member-approve"), f"审批入宗 {application_id} 同意")).ok
            contribution = await runtime.dispatch(_context("member", "contribution"), "宗门兑换 筑基护脉丹")
            assert contribution.code == "SECT_CONTRIBUTION_INSUFFICIENT"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                row = connection.execute(
                    "SELECT warehouse_json FROM sects WHERE sect_id=?",
                    (sect_id,),
                ).fetchone()
            assert json.loads(row[0])["item.pill.foundation_guard"] == 1
            await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("kind", ["onebot", "qq"])
def test_real_adapters_reach_sect_exchange(kind: str) -> None:
    pytest.importorskip("nonebot")
    from nonebot_plugin_xiuxian_3.adapters.onebot import normalize_event
    from nonebot_plugin_xiuxian_3.adapters.qq import normalize_event as normalize_qq_event

    def onebot_event(content: str, message_id: int, user_id: int):
        from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message
        from nonebot.adapters.onebot.v11.event import Sender

        return GroupMessageEvent(
            time=1_735_689_600,
            self_id=9001,
            post_type="message",
            sub_type="normal",
            user_id=user_id,
            message_type="group",
            message_id=message_id,
            message=Message(content),
            original_message=Message(content),
            raw_message=content,
            font=0,
            sender=Sender(user_id=user_id, nickname="道友"),
            group_id=2002,
        )

    def qq_event(content: str, message_id: int, user_id: str):
        from nonebot.adapters.qq.event import GroupMessageCreateEvent
        from nonebot.adapters.qq.models.qq import GroupMemberAuthor

        return GroupMessageCreateEvent(
            id=str(message_id),
            content=content,
            timestamp="2026-01-01T00:00:00+00:00",
            author=GroupMemberAuthor(id="raw", bot=False, member_openid=user_id, username="道友"),
            group_id="raw-group",
            group_openid="group-openid",
        )

    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            platform = "onebot.v11" if kind == "onebot" else "qq.official"
            adapter_user = 7011 if kind == "onebot" else "qq-exchange-user"

            async def dispatch(content: str, message_id: int):
                raw = onebot_event(content, message_id, int(adapter_user)) if kind == "onebot" else qq_event(content, message_id, str(adapter_user))
                normalized = normalize_event(raw) if kind == "onebot" else normalize_qq_event(raw)
                return await runtime.dispatch(normalized.context, normalized.text)

            assert (await dispatch("开始修仙", 9100)).ok
            assert (await dispatch("寻仙问道", 9101)).ok
            uid = str(adapter_user)
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE players SET realm_key='foundation', realm_layer=1, spirit_stones=10000, inventory_json=? WHERE platform=? AND platform_user_id=?",
                    (json.dumps({"item.herb.spirit_leaf": 2, "item.herb.blood_grass": 1, "item.mat.array_sand": 1}), platform, uid),
                )
            created = await dispatch("创建宗门 归元阁", 9102)
            assert created.code == "SECT_CREATED"
            for index, command in enumerate(("宗门捐献 灵石 3000", "宗门捐献 灵叶 2", "宗门捐献 止血草 1", "宗门捐献 阵砂 1", "宗门补给 筑基护脉丹"), start=9103):
                assert (await dispatch(command, index)).ok
            exchanged = await dispatch("宗门商店兑换 筑基护脉丹", 9108)
            assert exchanged.code == "SECT_EXCHANGE_COMPLETED"
            assert exchanged.data["item_key"] == "item.pill.foundation_guard"
            await runtime.close()

    asyncio.run(run())


def test_daily_build_counts_unique_completed_sessions_and_replays() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            sect_id = await _create_sect(runtime)
            assert (await runtime.dispatch(_context("leader", "early"), "宗门每日建设")).code == "SECT_BUILD_NOT_READY"
            for index in range(3):
                start_op = next(f"gather-{index}-{candidate}" for candidate in range(1000) if battle_roll_bp(f"gather-{index}-{candidate}:battle") >= 1000)
                started = await runtime.dispatch(_context("leader", start_op), "开始探索 近郊采集")
                assert started.code == "EXPLORATION_STARTED"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute("UPDATE exploration_sessions SET ends_at=? WHERE exploration_id=?", ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(), started.data["exploration_id"]))
                settled = await runtime.dispatch(_context("leader", f"settle-{index}"), "结算探索")
                assert settled.code == "EXPLORATION_SETTLED"
                if index == 0:
                    duplicate = await runtime.dispatch(_context("leader", "settle-0"), "结算探索")
                    assert duplicate.code == "EXPLORATION_SETTLED"
                    assert duplicate.data["idempotent_replay"] is True
                    assert (await runtime.dispatch(_context("leader", "still-early"), "宗门每日建设")).code == "SECT_BUILD_NOT_READY"
            built = await runtime.dispatch(_context("leader", "build"), "宗门每日建设")
            assert built.code == "SECT_DAILY_BUILT"
            assert built.data["contribution"] == 5
            replay = await runtime.dispatch(_context("leader", "build"), "宗门每日建设")
            assert replay.data["idempotent_replay"] is True
            assert (await runtime.dispatch(_context("leader", "build-again"), "宗门每日建设")).code == "SECT_BUILD_ALREADY_COMPLETED"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute("SELECT construction FROM sects WHERE sect_id=?", (sect_id,)).fetchone()[0] == 1
            await runtime.close()

    asyncio.run(run())


def test_supply_rejects_bound_items_capacity_and_operation_conflicts() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            sect_id = await _create_sect(runtime)
            assert (await runtime.dispatch(_context("leader", "bound"), "宗门捐献 筑基护脉丹 1")).code == "INVALID_SECT_SUPPLY"
            assert (await runtime.dispatch(_context("leader", "bad-stones"), "宗门捐献 灵石 99")).code == "INVALID_SECT_SUPPLY"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute("UPDATE sects SET warehouse_capacity=1 WHERE sect_id=?", (sect_id,))
            donated = await runtime.dispatch(_context("leader", "first-item"), "宗门捐献 灵叶 2")
            assert donated.code == "SECT_DONATED"
            assert (await runtime.dispatch(_context("leader", "first-item"), "宗门捐献 灵叶 2")).data["idempotent_replay"] is True
            assert (await runtime.dispatch(_context("leader", "first-item"), "宗门捐献 灵叶 3")).code == "OPERATION_CONFLICT"
            assert (await runtime.dispatch(_context("leader", "full"), "宗门捐献 阵砂 1")).code == "SECT_WAREHOUSE_FULL"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                row = connection.execute("SELECT warehouse_json FROM sects WHERE sect_id=?", (sect_id,)).fetchone()
                assert json.loads(row[0]) == {"item.herb.spirit_leaf": 2}
                assert connection.execute("SELECT COUNT(*) FROM sect_warehouse_supply_events WHERE sect_id=?", (sect_id,)).fetchone()[0] == 1
            await runtime.close()

    asyncio.run(run())


def test_procure_permission_and_concurrent_exchange_do_not_overdraw() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            sect_id = await _create_sect(runtime)
            await _stock(runtime, "leader", 1, stones=9900)
            assert (await runtime.dispatch(_context("member", "member-player"), "开始修仙")).ok
            assert (await runtime.dispatch(_context("member", "member-seek"), "寻仙问道")).ok
            assert (await runtime.dispatch(_context("member", "member-apply"), f"申请入宗 {sect_id}")).ok
            with sqlite3.connect(runtime.settings.database_path) as connection:
                application_id = connection.execute("SELECT application_id FROM sect_applications WHERE sect_id=?", (sect_id,)).fetchone()[0]
            assert (await runtime.dispatch(_context("leader", "member-approve"), f"审批入宗 {application_id} 同意")).ok
            assert (await runtime.dispatch(_context("member", "no-procure"), "宗门补给 筑基护脉丹")).code == "SECT_PERMISSION_DENIED"
            results = await asyncio.gather(*(
                runtime.dispatch(_context("leader", f"concurrent-{index}"), "宗门兑换 筑基护脉丹") for index in range(2)
            ))
            assert sorted(result.code for result in results) == ["SECT_EXCHANGE_COMPLETED", "SECT_STOCK_INSUFFICIENT"]
            with sqlite3.connect(runtime.settings.database_path) as connection:
                row = connection.execute("SELECT warehouse_json FROM sects WHERE sect_id=?", (sect_id,)).fetchone()
                assert "item.pill.foundation_guard" not in json.loads(row[0])
                assert connection.execute("SELECT COUNT(*) FROM sect_warehouse_supply_events WHERE sect_id=? AND action_key='procure'", (sect_id,)).fetchone()[0] == 1
            await runtime.close()
            await SQLitePlayerRepository(runtime.settings).initialize()
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute("SELECT COUNT(*) FROM sect_warehouse_supply_events WHERE sect_id=?", (sect_id,)).fetchone()[0] == 5

    asyncio.run(run())
