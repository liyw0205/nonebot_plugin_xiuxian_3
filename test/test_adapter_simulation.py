from __future__ import annotations

import asyncio
import json
import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import pytest

nonebot = pytest.importorskip("nonebot")

from nonebot_plugin_xiuxian_3.adapters.base import EventDeduplicator
from nonebot_plugin_xiuxian_3.adapters.nonebot import _canonical_command
from nonebot_plugin_xiuxian_3.adapters.onebot import is_onebot_v11_event, normalize_event
from nonebot_plugin_xiuxian_3.adapters.qq import is_qq_event, normalize_event as normalize_qq_event
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.world.void_rules import void_route_roll_bp


class MutableClock:
    def __init__(self, value: datetime):
        self.value = value

    def __call__(self) -> datetime:
        return self.value

    def advance(self, **kwargs: int) -> None:
        from datetime import timedelta

        self.value += timedelta(**kwargs)


def _onebot_group_event(content: str, *, message_id: int = 3003):
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


def _qq_group_event(content: str, *, message_id: str = "qq-message-1"):
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
            member_role="member",
            username="QQ道友",
        ),
        group_id="qq-group-raw",
        group_openid="qq-group-1",
    )


def test_real_onebot_v11_event_reaches_shared_application() -> None:
    event = _onebot_group_event("寻仙问道")
    normalized = normalize_event(event)

    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            created = await runtime.dispatch(
                replace(normalized.context, operation_id="onebot-create"), "开始修仙"
            )
            sought = await runtime.dispatch(
                replace(normalized.context, operation_id="onebot-seek"), normalized.text
            )
            assert created.code == "PLAYER_CREATED"
            assert sought.code == "SEEKING_STARTED"
            assert sought.data["player_id"] == created.data["player_id"]
            await runtime.close()

    asyncio.run(run())


def test_real_qq_group_event_reaches_shared_application() -> None:
    event = _qq_group_event("开始修仙 青云")
    normalized = normalize_qq_event(event)
    assert normalized.context.adapter == "qq.official"
    assert normalized.context.can_write_assets is True

    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            created = await runtime.dispatch(normalized.context, normalized.text)
            profile = await runtime.dispatch(
                replace(normalized.context, operation_id="qq-profile"), "我的状态"
            )
            assert created.code == "PLAYER_CREATED"
            assert profile.code == "PROFILE_READ"
            assert profile.data["dao_name"] == "青云"
            await runtime.close()

    asyncio.run(run())


def test_qq_and_onebot_normalized_events_reach_sky_terrace_flow() -> None:
    qq = normalize_qq_event(_qq_group_event("开始修仙", message_id="qq-sky-terrace"))
    onebot = normalize_event(_onebot_group_event("开始修仙", message_id=3050))

    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            for prefix, normalized in (("qq", qq), ("onebot", onebot)):
                base = normalized.context

                async def dispatch(operation: str, text: str):
                    context = replace(base, operation_id=f"{prefix}-{operation}")
                    return await runtime.adapters.dispatch(base.adapter, context, text)

                assert (await dispatch("create", "开始修仙")).code == "PLAYER_CREATED"
                assert (await dispatch("seek", "寻仙问道")).code == "SEEKING_STARTED"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE players SET stage='cultivator', realm_key='tribulation', realm_layer=3, "
                        "endgame_status='tribulation', location_key='dao.origin_gate', "
                        "inventory_json=? WHERE platform=? AND platform_user_id=?",
                        (json.dumps({"item.tribulation_token": 2}), base.adapter, base.user_id),
                    )

                started = await dispatch("travel", "前往 天劫台")
                assert started.code == "TRAVEL_STARTED"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE travel_sessions SET ends_at=? WHERE session_id=?",
                        ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(), started.data["session_id"]),
                    )
                arrived = await dispatch("travel-settle", "结算移动")
                assert arrived.code == "TRAVEL_COMPLETED"
                trial = await dispatch("trial", "开始天劫试炼 身心劫")
                assert trial.code == "TRIAL_STARTED"
                replay = await dispatch("trial", "开始天劫试炼 身心劫")
                assert replay.data["idempotent_replay"] is True
            await runtime.close()

    asyncio.run(run())


def test_qq_and_onebot_run_dao_echoes_mainline_commands() -> None:
    qq = normalize_qq_event(_qq_group_event("开始修仙", message_id="qq-dao-echoes"))
    onebot = normalize_event(_onebot_group_event("开始修仙", message_id=3060))

    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            for prefix, normalized in (("qq", qq), ("onebot", onebot)):
                base = normalized.context

                async def dispatch(operation: str, text: str):
                    context = replace(base, operation_id=f"{prefix}-{operation}")
                    return await runtime.adapters.dispatch(base.adapter, context, text)

                assert (await dispatch("create", "开始修仙")).code == "PLAYER_CREATED"
                assert (await dispatch("seek", "寻仙问道")).code == "SEEKING_STARTED"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE players SET stage='cultivator', realm_key='void_refining', realm_layer=10 "
                        "WHERE platform=? AND platform_user_id=?",
                        (base.adapter, base.user_id),
                    )

                started = await dispatch("start", "开始道源主线 建设者 1")
                assert started.code == "DAO_ECHOES_STAGE_STARTED"
                claimed = await dispatch("claim", "领取道源主线奖励 建设者 1")
                assert claimed.code == "DAO_ECHOES_STAGE_CLAIMED"
                assert claimed.data["stage_key"] == "lane.builder.chapter.01"
                status = await dispatch("status", "道源主线")
                assert status.code == "DAO_ECHOES_STATUS"
                assert status.data["lanes"][0]["completed"] == 1
            await runtime.close()

    asyncio.run(run())


def test_qq_and_onebot_normalization_reaches_automatic_training_battle() -> None:
    qq = normalize_qq_event(_qq_group_event("开始训练战", message_id="qq-training-battle"))
    onebot = normalize_event(_onebot_group_event("开始训练战", message_id=3020))

    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            for prefix, normalized in (("qq", qq), ("onebot", onebot)):
                base = normalized.context

                async def dispatch(operation: str, text: str):
                    return await runtime.adapters.dispatch(
                        base.adapter,
                        replace(base, operation_id=operation),
                        text,
                    )

                assert (await dispatch(f"{prefix}-create", "开始修仙")).ok
                assert (await dispatch(f"{prefix}-seek", "寻仙问道")).ok
                assert (await dispatch(f"{prefix}-read", "完成引导 阅读")).ok
                assert (await dispatch(f"{prefix}-travel", "前往近郊")).ok
                assert (await dispatch(f"{prefix}-gather", "完成引导 采集")).ok
                assert (await dispatch(f"{prefix}-service", "完成引导 炼丹")).ok
                assert (await dispatch(f"{prefix}-path", "选择道途 体修")).code == "CULTIVATION_ENTERED"
                assert (await dispatch(f"{prefix}-return", "返回新手城")).ok
                settled = await dispatch(f"{prefix}-battle", normalized.text)
                assert settled.code == "TRAINING_SPECTATOR"
                assert settled.data["status"] == "spectator"
                assert settled.data["actions"]
                claimed = await dispatch(f"{prefix}-claim", "领取战斗奖励")
                assert claimed.code == "BATTLE_REWARD_NOT_AVAILABLE"
                replay = await dispatch(f"{prefix}-replay", "战斗回放")
                assert replay.code == "BATTLE_NOT_FOUND"
            await runtime.close()

    asyncio.run(run())


def test_qq_and_onebot_spirit_leaf_field_flow_reaches_shared_application() -> None:
    qq = normalize_qq_event(_qq_group_event("开始修仙", message_id="qq-spirit-leaf"))
    onebot = normalize_event(_onebot_group_event("开始修仙", message_id=3010))

    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            for prefix, normalized in (("qq", qq), ("onebot", onebot)):
                context = replace(normalized.context, operation_id=f"{prefix}-create")
                assert (await runtime.adapters.dispatch(normalized.context.adapter, context, "开始修仙")).ok
                assert (
                    await runtime.adapters.dispatch(
                        normalized.context.adapter,
                        replace(context, operation_id=f"{prefix}-seek"),
                        "寻仙问道",
                    )
                ).ok
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    player_id = connection.execute(
                        "SELECT id FROM players WHERE platform = ? AND platform_user_id = ?",
                        (normalized.context.adapter, normalized.context.user_id),
                    ).fetchone()[0]
                    connection.execute(
                        "UPDATE players SET inventory_json = ?, spirit_stones = 100 WHERE id = ?",
                        (json.dumps({"item.herb.spirit_leaf": 1}), player_id),
                    )
                    connection.execute(
                        """
                        INSERT INTO player_reputations(player_id, local_json, service_reputation, updated_at)
                        VALUES (?, ?, 0, ?)
                        ON CONFLICT(player_id) DO UPDATE SET local_json = excluded.local_json
                        """,
                        (player_id, json.dumps({"local.xuantian.new_town": 40}), clock.value.isoformat()),
                    )
                dispatch = lambda operation, text: runtime.adapters.dispatch(
                    normalized.context.adapter,
                    replace(context, operation_id=operation),
                    text,
                )
                assert (await dispatch(f"{prefix}-lease", "租住居所 小院")).code == "RESIDENCE_LEASED"
                assert (await dispatch(f"{prefix}-plant", "灵田播种 灵叶")).code == "FIELD_PLOT_PLANTED"
                assert (await dispatch(f"{prefix}-maintain-1", "灵田维护")).ok
                assert (await dispatch(f"{prefix}-maintain-2", "灵田维护")).ok
                clock.advance(hours=8)
                harvested = await dispatch(f"{prefix}-harvest", "灵田收获")
                assert harvested.code == "FIELD_PLOT_HARVESTED"
                assert harvested.data["harvest"]["item.herb.spirit_leaf"] == 3
            await runtime.close()

    asyncio.run(run())


def test_qq_and_onebot_normalization_reaches_seclusion_cultivation() -> None:
    qq = normalize_qq_event(_qq_group_event("开始修炼 静修", message_id="qq-seclusion"))
    onebot = normalize_event(_onebot_group_event("开始修炼 静修", message_id=3012))

    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            for prefix, normalized in (("qq", qq), ("onebot", onebot)):
                base = normalized.context
                dispatch = lambda operation, text: runtime.adapters.dispatch(
                    base.adapter,
                    replace(base, operation_id=operation),
                    text,
                )
                assert (await dispatch(f"{prefix}-create", "开始修仙")).ok
                assert (await dispatch(f"{prefix}-seek", "寻仙问道")).ok
                assert (await dispatch(f"{prefix}-read", "完成引导 阅读")).ok
                assert (await dispatch(f"{prefix}-travel", "前往近郊")).ok
                assert (await dispatch(f"{prefix}-gather", "完成引导 采集")).ok
                assert (await dispatch(f"{prefix}-service", "完成引导 炼丹")).ok
                assert (await dispatch(f"{prefix}-path", "选择道途 体修")).code == "CULTIVATION_ENTERED"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        """
                        UPDATE players
                        SET realm_key = 'qi_gathering', realm_layer = 1, stamina = 30, energy = 30
                        WHERE platform = ? AND platform_user_id = ?
                        """,
                        (base.adapter, base.user_id),
                    )
                started = await runtime.adapters.dispatch(
                    base.adapter,
                    replace(base, operation_id=f"{prefix}-seclusion"),
                    normalized.text,
                )
                assert started.code == "CULTIVATION_STARTED"
                assert started.data["mode_key"] == "cultivate.seclusion"
                assert started.data["stamina_cost"] == 6
                assert started.data["energy_cost"] == 2
            await runtime.close()

    asyncio.run(run())


def test_qq_and_onebot_normalization_reaches_foundation_late_milestone() -> None:
    qq = normalize_qq_event(_qq_group_event("晋升境界", message_id="qq-foundation-late"))
    onebot = normalize_event(_onebot_group_event("晋升境界", message_id=3013))

    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            for prefix, normalized in (("qq", qq), ("onebot", onebot)):
                context = replace(normalized.context, operation_id=f"{prefix}-foundation-create")
                assert (await runtime.adapters.dispatch(context.adapter, context, "开始修仙")).ok
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        """
                        UPDATE players
                        SET stage = 'cultivator', realm_key = 'foundation', realm_layer = 8,
                            cultivation = 6300, total_cultivation = 10000
                        WHERE platform = ? AND platform_user_id = ?
                        """,
                        (normalized.context.adapter, normalized.context.user_id),
                    )
                advanced = await runtime.adapters.dispatch(
                    normalized.context.adapter,
                    replace(normalized.context, operation_id=f"{prefix}-foundation-advance"),
                    normalized.text,
                )
                assert advanced.code == "REALM_LAYER_ADVANCED"
                assert {item["key"] for item in advanced.data["unlocks"]} == {"milestone.foundation_late"}
            await runtime.close()

    asyncio.run(run())


def test_qq_and_onebot_normalization_reaches_nascent_soul_late_milestone() -> None:
    qq = normalize_qq_event(_qq_group_event("晋升境界", message_id="qq-nascent-late"))
    onebot = normalize_event(_onebot_group_event("晋升境界", message_id=3014))

    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            for prefix, normalized in (("qq", qq), ("onebot", onebot)):
                context = replace(normalized.context, operation_id=f"{prefix}-nascent-create")
                assert (await runtime.adapters.dispatch(context.adapter, context, "开始修仙")).ok
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        """
                        UPDATE players
                        SET stage = 'cultivator', realm_key = 'nascent_soul', realm_layer = 8,
                            cultivation = 153000, total_cultivation = 210000,
                            faction_reputation_json = ?
                        WHERE platform = ? AND platform_user_id = ?
                        """,
                        (json.dumps({"faction.abyss": 1000}), normalized.context.adapter, normalized.context.user_id),
                    )
                advanced = await runtime.adapters.dispatch(
                    normalized.context.adapter,
                    replace(normalized.context, operation_id=f"{prefix}-nascent-advance"),
                    normalized.text,
                )
                assert advanced.code == "REALM_LAYER_ADVANCED"
                assert {item["key"] for item in advanced.data["unlocks"]} == {"milestone.nascent_soul_late"}
            await runtime.close()

    asyncio.run(run())


def test_qq_and_onebot_normalization_reaches_soul_transformation_late_milestone() -> None:
    qq = normalize_qq_event(_qq_group_event("晋升境界", message_id="qq-soul-late"))
    onebot = normalize_event(_onebot_group_event("晋升境界", message_id=3015))

    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            for prefix, normalized in (("qq", qq), ("onebot", onebot)):
                context = replace(normalized.context, operation_id=f"{prefix}-soul-create")
                assert (await runtime.adapters.dispatch(context.adapter, context, "开始修仙")).ok
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        """
                        UPDATE players
                        SET stage = 'cultivator', realm_key = 'soul_transformation', realm_layer = 8,
                            cultivation = 480000, total_cultivation = 720000, domain_level = 3
                        WHERE platform = ? AND platform_user_id = ?
                        """,
                        (normalized.context.adapter, normalized.context.user_id),
                    )
                advanced = await runtime.adapters.dispatch(
                    normalized.context.adapter,
                    replace(normalized.context, operation_id=f"{prefix}-soul-advance"),
                    normalized.text,
                )
                assert advanced.code == "REALM_LAYER_ADVANCED"
                assert {item["key"] for item in advanced.data["unlocks"]} == {
                    "milestone.soul_transformation_late"
                }
            await runtime.close()

    asyncio.run(run())


def test_qq_and_onebot_normalization_reaches_void_refining_late_milestone() -> None:
    qq = normalize_qq_event(_qq_group_event("进入虚空航道 第一航道", message_id="qq-void-late"))
    onebot = normalize_event(_onebot_group_event("进入虚空航道 第一航道", message_id=3016))

    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            clock = MutableClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            for prefix, normalized in (("qq", qq), ("onebot", onebot)):
                context = replace(normalized.context, operation_id=f"{prefix}-void-create")
                assert (await runtime.adapters.dispatch(context.adapter, context, "开始修仙")).ok
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        """
                        UPDATE players
                        SET stage = 'cultivator', realm_key = 'void_refining', realm_layer = 8,
                            cultivation = 2150000, total_cultivation = 2500000,
                            stamina = 200, stamina_max = 200, space_resistance_bp = 1500,
                            inventory_json = ?
                        WHERE platform = ? AND platform_user_id = ?
                        """,
                        (
                            json.dumps({"item.void_anchor": 12}),
                            normalized.context.adapter,
                            normalized.context.user_id,
                        ),
                    )

                async def dispatch(operation: str, command: str):
                    event_context = replace(
                        normalized.context,
                        request_id=f"{operation}-request",
                        operation_id=operation,
                    )
                    return await runtime.adapters.dispatch(
                        normalized.context.adapter,
                        event_context,
                        command,
                    )

                async def travel(route_label: str, operation_prefix: str) -> None:
                    start_operation = next(
                        f"{prefix}-{operation_prefix}-start-{candidate}"
                        for candidate in range(1000)
                        if void_route_roll_bp(
                            f"{prefix}-{operation_prefix}-start-{candidate}"
                        ) >= 1500
                    )
                    started = await dispatch(
                        start_operation,
                        f"进入虚空航道 {route_label}",
                    )
                    assert started.code == "VOID_ROUTE_STARTED", started.message
                    clock.advance(minutes=46)
                    settled = await dispatch(
                        f"{prefix}-{operation_prefix}-settle",
                        "结算虚空航道",
                    )
                    assert settled.code == "VOID_ROUTE_SETTLED", settled.message

                await travel("第一航道", "first-a")
                await travel("第一航道", "first-b")
                await travel("档案遗迹", "archive")
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    count = connection.execute(
                        "SELECT void_route_count FROM players WHERE platform=? AND platform_user_id=?",
                        (normalized.context.adapter, normalized.context.user_id),
                    ).fetchone()[0]
                assert count == 2
                first_advance = await dispatch(f"{prefix}-void-l9", "晋升境界")
                assert first_advance.code == "REALM_LAYER_ADVANCED"
                assert first_advance.data["unlocks"] == []

                market_blocked = await dispatch(
                    f"{prefix}-void-market-blocked",
                    "进入虚空航道 虚空集市",
                )
                fortress_blocked = await dispatch(
                    f"{prefix}-void-fortress-blocked",
                    "进入虚空航道 虚空堡垒",
                )
                assert market_blocked.code == fortress_blocked.code == "VOID_ROUTE_LOCKED"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    row = connection.execute(
                        "SELECT stamina, inventory_json FROM players WHERE platform=? AND platform_user_id=?",
                        (normalized.context.adapter, normalized.context.user_id),
                    ).fetchone()
                assert row[0] == 90
                assert json.loads(row[1])["item.void_anchor"] == 2
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    player_id = connection.execute(
                        "SELECT id FROM players WHERE platform=? AND platform_user_id=?",
                        (normalized.context.adapter, normalized.context.user_id),
                    ).fetchone()[0]
                    sect_id = f"sect-{prefix}"
                    created_at = clock.value.isoformat()
                    connection.execute(
                        """
                        INSERT INTO sects(
                            sect_id, name, name_key, leader_id, status, level, max_members,
                            warehouse_capacity, construction, spirit_stones, sect_merit,
                            warehouse_json, created_at, updated_at, content_version, rule_version
                        ) VALUES (?, ?, ?, ?, 'active', 5, 120, 100, 0, 0, 0, '{}', ?, ?, '', '')
                        """,
                        (sect_id, f"{prefix} test sect", f"{prefix}-test-sect", player_id, created_at, created_at),
                    )
                    connection.execute(
                        """
                        INSERT INTO sect_members(
                            sect_id, player_id, role, status, contribution, joined_at,
                            last_action_at, created_at, updated_at
                        ) VALUES (?, ?, 'member', 'active', 0, ?, ?, ?, ?)
                        """,
                        (sect_id, player_id, created_at, created_at, created_at, created_at),
                    )

                await travel("虚空堡垒", "fortress")
                advanced = await dispatch(f"{prefix}-void-l10", "晋升境界")
                assert advanced.code == "REALM_LAYER_ADVANCED"
                assert {item["key"] for item in advanced.data["unlocks"]} == {
                    "milestone.void_refining_late"
                }
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    snapshot = json.loads(
                        connection.execute(
                            "SELECT snapshot_json FROM progression_milestones WHERE milestone_key = 'milestone.void_refining_late' AND player_id=(SELECT id FROM players WHERE platform=? AND platform_user_id=?)",
                            (normalized.context.adapter, normalized.context.user_id),
                        ).fetchone()[0]
                    )
                assert snapshot["void_route_count"] == snapshot["required_void_route_count"] == 3
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    row = connection.execute(
                        "SELECT inventory_json FROM players WHERE platform=? AND platform_user_id=?",
                        (normalized.context.adapter, normalized.context.user_id),
                    ).fetchone()
                    inventory = json.loads(row[0])
                    inventory["item.void_anchor"] = 2
                    connection.execute(
                        "UPDATE players SET void_merit=1000, inventory_json=? WHERE platform=? AND platform_user_id=?",
                        (
                            json.dumps(inventory),
                            normalized.context.adapter,
                            normalized.context.user_id,
                        ),
                    )
                await travel("虚空集市", "market")
            await runtime.close()

    asyncio.run(run())


def test_qq_and_onebot_public_project_flow_reaches_shared_application() -> None:
    qq = normalize_qq_event(_qq_group_event("开始修仙", message_id="qq-public-project"))
    onebot = normalize_event(_onebot_group_event("开始修仙", message_id=3011))

    async def run() -> None:
        clock = MutableClock(datetime(2026, 10, 12, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            for prefix, normalized in (("qq", qq), ("onebot", onebot)):
                base = normalized.context
                dispatch = lambda operation, text: runtime.adapters.dispatch(
                    base.adapter,
                    replace(base, operation_id=operation),
                    text,
                )
                assert (await dispatch(f"{prefix}-project-create", "开始修仙")).ok
                assert (await dispatch(f"{prefix}-project-seek", "寻仙问道")).ok
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    player_id = connection.execute(
                        "SELECT id FROM players WHERE platform = ? AND platform_user_id = ?",
                        (base.adapter, base.user_id),
                    ).fetchone()[0]
                    connection.execute(
                        "UPDATE players SET inventory_json = ? WHERE id = ?",
                        (json.dumps({"item.mat.wood": 10}), player_id),
                    )
                listing = await dispatch(f"{prefix}-project-list", "公共项目")
                assert listing.code == "PROJECT_LIST"
                contributed = await dispatch(
                    f"{prefix}-project-contribute",
                    "贡献公共项目 project.town_well 木材 10",
                )
                assert contributed.code == "PROJECT_CONTRIBUTED"
                assert contributed.data["contribution_points"] == 10
            await runtime.close()

    asyncio.run(run())


def test_qq_and_onebot_normalization_reaches_golden_core_preview() -> None:
    qq = normalize_qq_event(_qq_group_event("突破预览 金丹", message_id="qq-golden-preview"))
    onebot = normalize_event(_onebot_group_event("突破预览 金丹", message_id=3004))

    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            qq_user = replace(qq.context, operation_id="qq-golden-create")
            onebot_user = replace(onebot.context, operation_id="onebot-golden-create")
            assert (await runtime.dispatch(qq_user, "开始修仙")).code == "PLAYER_CREATED"
            assert (await runtime.dispatch(onebot_user, "开始修仙")).code == "PLAYER_CREATED"
            qq_preview = await runtime.dispatch(replace(qq.context, operation_id="qq-golden-preview"), qq.text)
            onebot_preview = await runtime.dispatch(replace(onebot.context, operation_id="onebot-golden-preview"), onebot.text)
            assert qq_preview.code == "BREAKTHROUGH_PREVIEW"
            assert onebot_preview.code == "BREAKTHROUGH_PREVIEW"
            assert qq_preview.data["target_realm"] == onebot_preview.data["target_realm"] == "golden_core"
            await runtime.close()

    asyncio.run(run())


def test_qq_and_onebot_normalization_reaches_nascent_soul_preview() -> None:
    qq = normalize_qq_event(_qq_group_event("突破预览 元婴", message_id="qq-nascent-preview"))
    onebot = normalize_event(_onebot_group_event("突破预览 元婴", message_id=3005))

    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            qq_context = replace(qq.context, operation_id="qq-nascent-create")
            onebot_context = replace(onebot.context, operation_id="onebot-nascent-create")
            assert (await runtime.dispatch(qq_context, "开始修仙")).code == "PLAYER_CREATED"
            assert (await runtime.dispatch(onebot_context, "开始修仙")).code == "PLAYER_CREATED"
            qq_preview = await runtime.dispatch(replace(qq.context, operation_id="qq-nascent-preview"), qq.text)
            onebot_preview = await runtime.dispatch(replace(onebot.context, operation_id="onebot-nascent-preview"), onebot.text)
            assert qq_preview.code == "BREAKTHROUGH_PREVIEW"
            assert onebot_preview.code == "BREAKTHROUGH_PREVIEW"
            assert qq_preview.data["target_realm"] == onebot_preview.data["target_realm"] == "nascent_soul"
            await runtime.close()

    asyncio.run(run())


def test_qq_and_onebot_normalization_reaches_soul_transformation_preview() -> None:
    qq = normalize_qq_event(_qq_group_event("突破预览 化神", message_id="qq-soul-preview"))
    onebot = normalize_event(_onebot_group_event("突破预览 化神", message_id=3006))

    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            qq_context = replace(qq.context, operation_id="qq-soul-create")
            onebot_context = replace(onebot.context, operation_id="onebot-soul-create")
            assert (await runtime.dispatch(qq_context, "开始修仙")).code == "PLAYER_CREATED"
            assert (await runtime.dispatch(onebot_context, "开始修仙")).code == "PLAYER_CREATED"
            qq_preview = await runtime.dispatch(replace(qq.context, operation_id="qq-soul-preview"), qq.text)
            onebot_preview = await runtime.dispatch(replace(onebot.context, operation_id="onebot-soul-preview"), onebot.text)
            assert qq_preview.code == "BREAKTHROUGH_PREVIEW"
            assert onebot_preview.code == "BREAKTHROUGH_PREVIEW"
            assert qq_preview.data["target_realm"] == onebot_preview.data["target_realm"] == "soul_transformation"
            await runtime.close()

    asyncio.run(run())


def test_qq_and_onebot_normalization_reaches_party_state_machine() -> None:
    qq = normalize_qq_event(_qq_group_event("创建双人队伍", message_id="qq-party-create"))
    onebot = normalize_event(_onebot_group_event("创建探索队伍", message_id=3007))
    assert _canonical_command(qq.text) == "创建双人队伍"
    assert _canonical_command(onebot.text) == "创建探索队伍"

    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            for normalized, adapter_user, operation in (
                (qq, qq.context.user_id, "qq-party-adapter"),
                (onebot, onebot.context.user_id, "onebot-party-adapter"),
            ):
                context = replace(normalized.context, operation_id=f"{operation}-create")
                assert (await runtime.dispatch(context, "开始修仙")).code == "PLAYER_CREATED"
                assert (await runtime.dispatch(replace(context, operation_id=f"{operation}-seek"), "寻仙问道")).code == "SEEKING_STARTED"
                result = await runtime.dispatch(replace(context, operation_id=operation), normalized.text)
                assert result.code == "PARTY_CREATED"
            await runtime.close()

    asyncio.run(run())


def test_adapter_message_guards_reject_non_message_events() -> None:
    class OneBotNotice:
        __module__ = "nonebot.adapters.onebot.v11.event"
        post_type = "notice"
        user_id = 1001
        message_type = "group"

    class QQGuildNotice:
        __module__ = "nonebot.adapters.qq.event"
        group_openid = "qq-group-1"

    assert is_onebot_v11_event(OneBotNotice()) is False
    assert is_qq_event(QQGuildNotice()) is False


def test_nonebot_tuple_command_start_is_flattened(monkeypatch) -> None:
    monkeypatch.setattr(
        nonebot,
        "get_driver",
        lambda: SimpleNamespace(config=SimpleNamespace(command_start=("/", "!"))),
    )
    assert _canonical_command("!开始修仙 青云") == "开始修仙 青云"
    assert _canonical_command("/我的状态") == "我的状态"


def test_normalized_event_identity_is_deduplicated_before_dispatch() -> None:
    onebot = normalize_event(_onebot_group_event("开始修仙", message_id=44))
    qq = normalize_qq_event(_qq_group_event("开始修仙", message_id="qq-44"))
    dedup = EventDeduplicator(ttl_seconds=60, max_entries=8)

    onebot_key = f"{onebot.context.adapter}:{onebot.context.bot_id}:{onebot.event_id}"
    qq_key = f"{qq.context.adapter}:{qq.context.bot_id}:{qq.event_id}"
    assert dedup.accept(onebot_key) is True
    assert dedup.accept(onebot_key) is False
    assert dedup.accept(qq_key) is True


def _seed_story_evidence(
    database_path,
    adapter: str,
    user: str,
    branch: str,
    *,
    first_index: int = 1,
    count: int | None = None,
    via_harvest: bool = False,
) -> list[str]:
    source_count = count or (3 if branch == "merchant" else 2)
    operation_ids = [
        f"evidence-{adapter}-{user}-{index}"
        for index in range(first_index, first_index + source_count)
    ]
    with sqlite3.connect(database_path) as connection:
        player_id = connection.execute(
            "SELECT id FROM players WHERE platform=? AND platform_user_id=?", (adapter, user)
        ).fetchone()[0]
        now = "2026-01-01T00:00:00+00:00"
        if branch == "merchant":
            for index, operation_id in zip(range(first_index, first_index + source_count), operation_ids):
                commission_id = f"story-test-commission-{adapter}-{user}-{index}"
                connection.execute(
                    "INSERT INTO town_commissions(commission_id,commission_key,business_date,status,"
                    "stock_total,stock_remaining,starts_at,expires_at,created_at,updated_at) "
                    "VALUES(?,?,?,'published',1,1,?,?,?,?)",
                    (commission_id, f"story.test.{adapter}.{user}.{index}", now[:10], now, now, now, now),
                )
                connection.execute(
                    "INSERT INTO town_commission_claims(claim_id,commission_id,player_id,business_date,"
                    "status,accept_operation_id,deliver_operation_id,accepted_at,delivered_at,created_at,updated_at) "
                    "VALUES(?,?,?,?,'delivered',?,?,?,?,?,?)",
                    (
                        f"story-test-claim-{adapter}-{user}-{index}", commission_id, player_id,
                        now[:10], f"accept-{operation_id}", operation_id, now, now, now, now,
                    ),
                )
        elif branch == "warden":
            for index, operation_id in zip(range(first_index, first_index + source_count), operation_ids):
                connection.execute(
                    "INSERT INTO battle_sessions(battle_id,player_id,start_operation_id,resolved_operation_id,"
                    "battle_type,enemy_key,location_key,status,reward_status,starts_at,turn_deadline,result_json,"
                    "created_at,updated_at) "
                    "VALUES(?,?,?,?,'pve','enemy.story.test','xuantian.new_town','settled','none',?,?,?,?,?)",
                    (
                        f"story-test-battle-{adapter}-{user}-{index}", player_id,
                        f"battle-start-{operation_id}", operation_id, now, now,
                        json.dumps({"outcome": "won"}), now, now,
                    ),
                )
        elif via_harvest:
            for index, operation_id in zip(range(first_index, first_index + source_count), operation_ids):
                connection.execute(
                    "INSERT INTO operations(operation_id,operation_name,player_id,request_hash,result_json,created_at) "
                    "VALUES(?,'livelihood.harvest',?,'story-test',?,?)",
                    (
                        operation_id,
                        player_id,
                        json.dumps({"plot_id": f"plot-{index}", "status": "harvested"}),
                        now,
                    ),
                )
        else:
            for index, operation_id in zip(range(first_index, first_index + source_count), operation_ids):
                connection.execute(
                    "INSERT INTO dispatch_assignments(assignment_id,player_id,operation_id,dispatch_key,status,"
                    "outcome,business_date,accepted_at,running_at,ends_at,cancel_until,result_json,"
                    "settle_operation_id,settled_at,created_at,updated_at) "
                    "VALUES(?,?,?,'dispatch.herb_search','settled','success',?,?,?,?,?,?,?, ?,?,?)",
                    (
                        f"story-test-dispatch-{adapter}-{user}-{index}", player_id,
                        f"dispatch-accept-{operation_id}", now[:10], now, now, now, now,
                        json.dumps({"outcome": "success"}), operation_id, now, now, now,
                    ),
                )
    return operation_ids


def test_story_endings_run_through_qq_and_onebot_v11_adapters() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            normalized_events = (
                ("qq.official", normalize_qq_event(_qq_group_event("剧情线", message_id="qq-story"))),
                ("onebot.v11", normalize_event(_onebot_group_event("剧情线", message_id=3099))),
            )
            for adapter, normalized in normalized_events:
                for branch, command_label in (("merchant", "商路"), ("warden", "守望"), ("gardener", "药圃")):
                    user = f"{normalized.context.user_id}-story-{branch}"
                    prefix = f"story-{adapter}-{branch}"
                    base = replace(normalized.context, user_id=user)

                    async def dispatch(suffix: str, command: str):
                        context = replace(base, operation_id=f"{prefix}-{suffix}")
                        return await runtime.adapters.dispatch(adapter, context, command)

                    created = await dispatch("create", "开始修仙")
                    premature = await dispatch("start-before-seek", "开始剧情")
                    sought = await dispatch("seek", "寻仙问道")
                    assert created.code == "PLAYER_CREATED"
                    assert premature.code == "STORY_REQUIREMENT_MISSING"
                    assert sought.code == "SEEKING_STARTED"
                    assert (await dispatch("status-before", "剧情线")).data["status"] == "available"
                    start = await dispatch("start", "开始剧情")
                    assert start.code == "STORY_STARTED"
                    assert (await dispatch("start", "开始剧情")).data["idempotent_replay"] is True

                    blocked = await dispatch("blocked-choice", f"选择剧情 {command_label}")
                    assert blocked.code == "STORY_CHOICE_NOT_READY"
                    evidence_ids = _seed_story_evidence(
                        runtime.settings.database_path,
                        adapter,
                        user,
                        branch,
                        via_harvest=(adapter == "qq.official" and branch == "gardener"),
                    )
                    chosen = await dispatch("choose", f"选择剧情 {command_label}")
                    assert chosen.code == "STORY_ROUTE_LOCKED"
                    assert chosen.data["source_operation_ids"] == list(reversed(evidence_ids))
                    assert (await dispatch("choose", f"选择剧情 {command_label}")).data["idempotent_replay"] is True
                    locked = await dispatch("wrong-choice", "选择剧情 药圃" if branch != "gardener" else "选择剧情 守望")
                    assert locked.code == "STORY_CHOICE_LOCKED"
                    later_evidence = _seed_story_evidence(
                        runtime.settings.database_path,
                        adapter,
                        user,
                        branch,
                        first_index=4 if branch == "merchant" else 3,
                        count=1,
                        via_harvest=(adapter == "qq.official" and branch == "gardener"),
                    )
                    if adapter == "onebot.v11" and branch == "warden":
                        await runtime.close()
                        runtime = create_runtime(data_dir=data_dir)
                        resumed = await dispatch("status-resumed", "剧情线")
                        assert resumed.data["status"] == "ending_pending"
                        assert resumed.data["selected_route"] == branch

                    claimed = await dispatch("claim", "领取剧情结局")
                    assert claimed.code == "STORY_ENDING_CLAIMED"
                    assert claimed.data["reward"] == {"local_reputation": 10}
                    assert claimed.data["idempotent_replay"] is False
                    replay = await dispatch("claim", "领取剧情结局")
                    assert replay.code == "STORY_ENDING_CLAIMED"
                    assert replay.data["idempotent_replay"] is True
                    status = await dispatch("status-ended", "剧情线")
                    assert status.data["status"] == "ended"
                    assert status.data["selected_route"] == branch
                    assert (await dispatch("claim-again", "领取剧情结局")).code == "STORY_ENDING_ALREADY_CLAIMED"

                    with sqlite3.connect(runtime.settings.database_path) as connection:
                        local_json, intro_json, cultivation, endgame_status = connection.execute(
                            "SELECT r.local_json,p.intro_json,p.cultivation,p.endgame_status "
                            "FROM players p LEFT JOIN player_reputations r ON r.player_id=p.id "
                            "WHERE p.platform=? AND p.platform_user_id=?",
                            (adapter, user),
                        ).fetchone()
                        assert json.loads(local_json)["local.xuantian.new_town"] >= 10
                        flags = json.loads(intro_json)["flags"]
                        assert f"flag.road.{branch}" in flags
                        assert f"appearance.home.{branch}" in flags
                        assert cultivation == 0 and endgame_status == "none"
                        assert connection.execute(
                            "SELECT COUNT(*) FROM story_ending_claims c JOIN players p ON p.id=c.player_id "
                            "WHERE p.platform=? AND p.platform_user_id=?",
                            (adapter, user),
                        ).fetchone()[0] == 1
                        snapshot_json, reward_json = connection.execute(
                            "SELECT c.snapshot_json,c.reward_json "
                            "FROM story_ending_claims c JOIN players p ON p.id=c.player_id "
                            "WHERE p.platform=? AND p.platform_user_id=?",
                            (adapter, user),
                        ).fetchone()
                        ending_snapshot = json.loads(snapshot_json)
                        assert ending_snapshot["choice"]["source_operation_ids"] == list(reversed(evidence_ids))
                        assert later_evidence[0] not in ending_snapshot["choice"]["source_operation_ids"]
                        assert json.loads(reward_json) == {"local_reputation": 10}
                        assert "content_version" not in ending_snapshot["choice"]
                        assert "rule_version" not in ending_snapshot["choice"]
                        story_columns = {
                            row[1] for row in connection.execute("PRAGMA table_info(story_ending_claims)")
                        }
                        assert not {"content_version", "rule_version"} & story_columns
                        assert connection.execute(
                            "SELECT COUNT(*) FROM codex_entries c JOIN players p ON p.id=c.player_id "
                            "WHERE p.platform=? AND p.platform_user_id=? AND c.entry_key=?",
                            (adapter, user, f"codex.story.xuantian.road.{branch}"),
                        ).fetchone()[0] == 1
            await runtime.close()

    asyncio.run(run())
