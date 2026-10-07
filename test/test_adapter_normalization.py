from __future__ import annotations

import asyncio
from dataclasses import replace
from tempfile import TemporaryDirectory

import pytest

from nonebot_plugin_xiuxian_3.adapters.base import EventDeduplicator
from nonebot_plugin_xiuxian_3.adapters.nonebot import (
    _canonical_command,
    _handler_for,
    _is_seek_command,
    normalize_event as normalize_nonebot_event,
)
from nonebot_plugin_xiuxian_3.adapters.onebot import normalize_event
from nonebot_plugin_xiuxian_3.adapters.qq import normalize_event as normalize_qq_event
from nonebot_plugin_xiuxian_3.contracts import CommandResult
from nonebot_plugin_xiuxian_3.runtime import create_runtime


class FakeOneBotEvent:
    __module__ = "nonebot.adapters.onebot.v11.event"

    def __init__(
        self,
        *,
        message_id: str = "3003",
        user_id: str = "1001",
        self_id: str = "onebot-bot",
        content: str = "寻仙问道",
    ) -> None:
        self.post_type = "message"
        self.message_type = "group"
        self.user_id = user_id
        self.group_id = "2002"
        self.message_id = message_id
        self.self_id = self_id
        self.raw_message = content
        self.sender = {"nickname": "OneBot道友", "user_id": user_id}


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
            member_role="member",
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


def test_event_operation_identity_is_stable_and_scoped() -> None:
    onebot = normalize_event(
        FakeOneBotEvent(
            message_id="shared-event",
            user_id="one-user",
            self_id="bot-a",
            content="开始修仙",
        )
    )
    onebot_other_bot = normalize_event(
        FakeOneBotEvent(message_id="shared-event", user_id="one-user", self_id="bot-b")
    )
    onebot_other_user = normalize_event(
        FakeOneBotEvent(message_id="shared-event", user_id="other-user", self_id="bot-a")
    )
    onebot_replay = normalize_event(
        FakeOneBotEvent(message_id="shared-event", user_id="one-user", self_id="bot-a")
    )
    assert onebot.context.operation_id == onebot_replay.context.operation_id
    assert onebot.context.operation_id != onebot_other_bot.context.operation_id
    assert onebot.context.operation_id != onebot_other_user.context.operation_id

    from nonebot.adapters.qq.event import GroupMessageCreateEvent
    from nonebot.adapters.qq.models.qq import GroupMemberAuthor

    qq = normalize_qq_event(
        GroupMessageCreateEvent(
            id="shared-event",
            content="开始修仙",
            timestamp="2026-01-01T00:00:00+00:00",
            author=GroupMemberAuthor(
                id="qq-user-raw",
                bot=False,
                member_openid="qq-user",
                member_role="member",
                username="QQ道友",
            ),
            group_id="qq-group-raw",
            group_openid="qq-group",
        )
    )
    assert onebot.context.operation_id != qq.context.operation_id
    assert '"onebot.v11"' in onebot.context.operation_id
    assert '"qq.official"' in qq.context.operation_id


def test_same_raw_event_id_does_not_conflict_between_adapters() -> None:
    onebot = normalize_event(
        FakeOneBotEvent(
            message_id="shared-event",
            user_id="one-user",
            self_id="bot-a",
            content="开始修仙",
        )
    )
    from nonebot.adapters.qq.event import GroupMessageCreateEvent
    from nonebot.adapters.qq.models.qq import GroupMemberAuthor

    qq = normalize_qq_event(
        GroupMessageCreateEvent(
            id="shared-event",
            content="开始修仙",
            timestamp="2026-01-01T00:00:00+00:00",
            author=GroupMemberAuthor(
                id="qq-user-raw",
                bot=False,
                member_openid="qq-user",
                member_role="member",
                username="QQ道友",
            ),
            group_id="qq-group-raw",
            group_openid="qq-group",
        )
    )

    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            first = await runtime.adapters.dispatch(onebot.context.adapter, onebot.context, onebot.text)
            second = await runtime.adapters.dispatch(qq.context.adapter, qq.context, qq.text)
            assert first.code == "PLAYER_CREATED"
            assert second.code == "PLAYER_CREATED"
            await runtime.close()

    asyncio.run(run())


def test_nonebot_handler_retries_retryable_event_then_deduplicates_success() -> None:
    event = FakeOneBotEvent(content="我的状态", message_id="retry-event")

    class Matcher:
        def __init__(self) -> None:
            self.finished: list[tuple[object, ...]] = []

        async def finish(self, *args: object) -> None:
            self.finished.append(args)

    class Runtime:
        def __init__(self) -> None:
            self.calls = 0

        async def dispatch(self, context, text):
            self.calls += 1
            if self.calls == 1:
                return CommandResult(
                    False,
                    "PERSISTENCE_ERROR",
                    "仙缘簿暂时不可用，请稍后再试。",
                    context.request_id,
                    context.operation_id,
                    retryable=True,
                )
            return CommandResult(True, "PROFILE_READ", "状态已阅。", context.request_id, context.operation_id)

    async def run() -> None:
        runtime = Runtime()
        matcher = Matcher()
        handler = _handler_for(
            runtime,
            matcher,
            normalize_event,
            EventDeduplicator(),
            ("我的状态",),
        )
        await handler(event)
        await handler(event)
        await handler(event)
        assert runtime.calls == 2
        assert len(matcher.finished) == 2

    asyncio.run(run())


def test_nonebot_handler_releases_event_after_dispatch_exception() -> None:
    event = FakeOneBotEvent(content="我的状态", message_id="exception-event")

    class Matcher:
        async def finish(self, *args: object) -> None:
            return None

    class Runtime:
        def __init__(self) -> None:
            self.calls = 0

        async def dispatch(self, context, text):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("temporary dispatch failure")
            return CommandResult(True, "PROFILE_READ", "状态已阅。", context.request_id, context.operation_id)

    async def run() -> None:
        runtime = Runtime()
        handler = _handler_for(
            runtime,
            Matcher(),
            normalize_nonebot_event,
            EventDeduplicator(),
            ("我的状态",),
        )
        with pytest.raises(RuntimeError, match="temporary dispatch failure"):
            await handler(event)
        await handler(event)
        assert runtime.calls == 2

    asyncio.run(run())


def test_event_deduplication_is_bounded_and_exact() -> None:
    dedup = EventDeduplicator(ttl_seconds=60, max_entries=2)
    assert dedup.accept("onebot.v11:bot:event-1") is True
    assert dedup.accept("onebot.v11:bot:event-1") is False
    assert dedup.accept("onebot.v11:bot:event-2") is True
    assert dedup.accept("onebot.v11:bot:event-3") is True
    assert dedup.accept("") is True
    dedup.release("onebot.v11:bot:event-3")
    assert dedup.accept("onebot.v11:bot:event-3") is True


def test_nonebot_command_gate_includes_shared_routine_commands() -> None:
    commands = ("七日入道", "领取七日目标", "七日目标")
    assert _canonical_command("七日入道", commands) == "七日入道"
    assert _canonical_command("领取七日目标 1", commands) == "领取七日目标 1"
    assert _canonical_command("/七日目标", commands) == "七日目标"


def test_nonebot_command_gate_uses_every_shared_router_command() -> None:
    with TemporaryDirectory() as data_dir:
        runtime = create_runtime(data_dir=data_dir)
        commands = runtime.router.commands
        assert len(commands) >= 500
        for command in commands:
            assert _canonical_command(command, commands) == command
        for text in ("属性说明", "我的属性", "发布服务", "交付委托", "使用道具", "公共项目"):
            assert _canonical_command(text, commands) == text
        assert _is_seek_command(FakeOneBotEvent(content="属性说明"), commands)


def test_both_real_adapters_pass_dynamic_gate_to_shared_handler() -> None:
    onebot_event = FakeOneBotEvent(content="属性说明", message_id="gate-onebot")
    from nonebot.adapters.qq.event import GroupMessageCreateEvent
    from nonebot.adapters.qq.models.qq import GroupMemberAuthor

    qq_event = GroupMessageCreateEvent(
        id="gate-qq",
        content="属性说明",
        timestamp="2026-01-01T00:00:00+00:00",
        author=GroupMemberAuthor(
            id="qq-user-raw",
            bot=False,
            member_openid="qq-user-gate",
            member_role="member",
            username="QQ道友",
        ),
        group_id="qq-group-raw",
        group_openid="qq-group-gate",
    )

    class Matcher:
        async def finish(self, *args: object) -> None:
            return None

    class Runtime:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str]] = []

        async def dispatch(self, context, text):
            self.calls.append((context.adapter, text))
            return CommandResult(True, "STATS_EXPLAINED", "属性已阅。", context.request_id, context.operation_id)

    async def run() -> None:
        runtime = Runtime()
        commands = ("属性说明",)
        onebot_handler = _handler_for(
            runtime,
            Matcher(),
            normalize_nonebot_event,
            EventDeduplicator(),
            commands,
        )
        qq_handler = _handler_for(
            runtime,
            Matcher(),
            normalize_qq_event,
            EventDeduplicator(),
            commands,
        )
        assert _is_seek_command(onebot_event, commands)
        assert _is_seek_command(qq_event, commands)
        await onebot_handler(onebot_event)
        await qq_handler(qq_event)
        assert runtime.calls == [("onebot.v11", "属性说明"), ("qq.official", "属性说明")]

    asyncio.run(run())


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
