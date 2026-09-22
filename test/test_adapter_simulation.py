from __future__ import annotations

import asyncio
from dataclasses import replace
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import pytest

nonebot = pytest.importorskip("nonebot")

from nonebot_plugin_xiuxian_3.adapters.base import EventDeduplicator
from nonebot_plugin_xiuxian_3.adapters.nonebot import _canonical_command
from nonebot_plugin_xiuxian_3.adapters.onebot import is_onebot_v11_event, normalize_event
from nonebot_plugin_xiuxian_3.adapters.qq import is_qq_event, normalize_event as normalize_qq_event
from nonebot_plugin_xiuxian_3.runtime import create_runtime


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
