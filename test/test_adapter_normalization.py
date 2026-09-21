from __future__ import annotations

import asyncio
from dataclasses import replace
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.adapters.base import EventDeduplicator
from nonebot_plugin_xiuxian_3.adapters.onebot import normalize_event
from nonebot_plugin_xiuxian_3.adapters.qq import normalize_event as normalize_qq_event
from nonebot_plugin_xiuxian_3.runtime import create_runtime


class FakeOneBotEvent:
    __module__ = "nonebot.adapters.onebot.v11.event"

    def __init__(self) -> None:
        self.post_type = "message"
        self.message_type = "group"
        self.user_id = "1001"
        self.group_id = "2002"
        self.message_id = "3003"
        self.raw_message = "寻仙问道"
        self.sender = {"nickname": "OneBot道友"}


def test_onebot_v11_message_is_normalized() -> None:
    normalized = normalize_event(FakeOneBotEvent())
    assert normalized.context.adapter == "onebot.v11"
    assert normalized.context.user_id == "1001"
    assert normalized.context.scene == "group"
    assert normalized.context.scene_id == "group:2002"
    assert normalized.context.nickname == "OneBot道友"
    assert normalized.text == "寻仙问道"


def test_qq_group_message_is_normalized() -> None:
    from nonebot.adapters.qq.event import GroupMessageCreateEvent
    from nonebot.adapters.qq.models.qq import GroupMemberAuthor

    event = GroupMessageCreateEvent(
        id="qq-message-1",
        content="寻仙问道",
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
    normalized = normalize_qq_event(event)
    assert normalized.context.adapter == "qq.official"
    assert normalized.context.user_id == "qq-user-1"
    assert normalized.context.scene == "group"
    assert normalized.context.scene_id == "group:qq-group-1"
    assert normalized.context.nickname == "QQ道友"
    assert normalized.text == "寻仙问道"


def test_event_deduplication_is_bounded_and_exact() -> None:
    dedup = EventDeduplicator(ttl_seconds=60, max_entries=2)
    assert dedup.accept("onebot.v11:bot:event-1") is True
    assert dedup.accept("onebot.v11:bot:event-1") is False
    assert dedup.accept("onebot.v11:bot:event-2") is True
    assert dedup.accept("onebot.v11:bot:event-3") is True
    assert dedup.accept("") is True


def test_normalized_qq_event_reaches_shared_application() -> None:
    from nonebot.adapters.qq.event import C2CMessageCreateEvent
    from nonebot.adapters.qq.models.qq import FriendAuthor

    event = C2CMessageCreateEvent(
        id="qq-c2c-message-1",
        content="寻仙问道",
        timestamp="2026-01-01T00:00:00+00:00",
        author=FriendAuthor(
            id="qq-user-raw",
            user_openid="qq-user-2",
            username="C2C道友",
        ),
    )
    normalized = normalize_qq_event(event)

    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            created = await runtime.dispatch(normalized.context, "开始修仙")
            assert created.code == "PLAYER_CREATED"
            result = await runtime.dispatch(
                replace(normalized.context, operation_id="qq-c2c-seek-1"), normalized.text
            )
            assert result.code == "SEEKING_STARTED"
            await runtime.close()

    asyncio.run(run())
