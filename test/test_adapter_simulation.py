from __future__ import annotations

import asyncio
import json
import sqlite3
from dataclasses import replace
from datetime import datetime, timezone
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import pytest

nonebot = pytest.importorskip("nonebot")

from nonebot_plugin_xiuxian_3.adapters.base import EventDeduplicator
from nonebot_plugin_xiuxian_3.adapters.nonebot import _canonical_command
from nonebot_plugin_xiuxian_3.adapters.onebot import is_onebot_v11_event, normalize_event
from nonebot_plugin_xiuxian_3.adapters.qq import is_qq_event, normalize_event as normalize_qq_event
from nonebot_plugin_xiuxian_3.runtime import create_runtime


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
