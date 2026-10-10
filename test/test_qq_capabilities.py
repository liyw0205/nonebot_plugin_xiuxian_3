from __future__ import annotations

import asyncio
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest

from nonebot_plugin_xiuxian_3.adapters.message.markdown import send_markdown_message
from nonebot_plugin_xiuxian_3.adapters.nonebot import _normalizer_for_runtime
from nonebot_plugin_xiuxian_3.xiuxian.config import XiuxianSettings
from nonebot_plugin_xiuxian_3.contracts import CommandAction, CommandResult
from nonebot_plugin_xiuxian_3.adapters.base import EventDeduplicator
from nonebot_plugin_xiuxian_3.adapters.nonebot import _canonical_command, _handler_for
from nonebot_plugin_xiuxian_3.xiuxian.utils.text import command_link


def qq_message_event():
    from nonebot.adapters.qq.event import GroupMessageCreateEvent
    from nonebot.adapters.qq.models.qq import GroupMemberAuthor

    return GroupMessageCreateEvent(
        id="message-1",
        content="# 修行\n\n下一步发送 `寻仙问道`。",
        timestamp="2026-01-01T00:00:00+00:00",
        author=GroupMemberAuthor(
            id="player-1",
            bot=False,
            member_openid="player-1",
            member_role="member",
            username="道友",
        ),
        group_id="group-raw",
        group_openid="group-1",
    )


class FakeQQBot:
    __module__ = "nonebot.adapters.qq.bot"

    def __init__(self, app_id: str = "") -> None:
        self.self_id = app_id
        self.sent: list[object] = []

    async def send(self, *, event: object, message: object, **kwargs: object) -> dict[str, str]:
        self.sent.append(message)
        return {"message_id": "reply-1"}


def test_app_id_capabilities_control_qq_markdown_fallback(monkeypatch) -> None:
    monkeypatch.setenv(
        "XIUXIAN3_QQ_CAPABILITIES",
        '{"markdown-app":["markdown","keyboard"],"text-app":["text"]}',
    )
    settings = XiuxianSettings.from_env()
    normalizer = _normalizer_for_runtime(SimpleNamespace(settings=settings))

    async def send(app_id: str):
        from nonebot.matcher import current_bot

        event = qq_message_event()
        bot = FakeQQBot(app_id)
        token = current_bot.set(bot)
        try:
            normalized = normalizer(event)
        finally:
            current_bot.reset(token)
        assert normalized.context.bot_id == app_id
        result = await send_markdown_message(
            bot,
            event,
            "# 修行\n\n下一步发送 `寻仙问道`。",
            capabilities=normalized.context.capabilities,
        )
        return normalized, bot, result

    async def run() -> None:
        from nonebot.adapters.qq import MessageSegment

        markdown, markdown_bot, markdown_result = await send("markdown-app")
        assert markdown.context.capabilities == ("text", "markdown", "keyboard")
        assert markdown_result.sent_format == "markdown"
        assert markdown_result.degraded is False
        assert isinstance(markdown_bot.sent[0], MessageSegment)

        plain, plain_bot, plain_result = await send("text-app")
        assert plain.context.capabilities == ("text",)
        assert plain_result.sent_format == "text"
        assert plain_result.degraded is True
        assert plain_bot.sent == ["修行\n\n下一步发送 寻仙问道。"]

        unknown, unknown_bot, unknown_result = await send("unlisted-app")
        assert unknown.context.capabilities == ("text",)
        assert unknown_result.degraded is True
        assert unknown_bot.sent == ["修行\n\n下一步发送 寻仙问道。"]

    asyncio.run(run())


def test_qq_capabilities_default_and_invalid_values(monkeypatch) -> None:
    monkeypatch.delenv("XIUXIAN3_QQ_CAPABILITIES", raising=False)
    settings = XiuxianSettings.from_env()
    assert settings.qq_capabilities_for("app-id") is None
    normalized = _normalizer_for_runtime(SimpleNamespace(settings=settings))(
        qq_message_event()
    )
    assert normalized.context.capabilities == ("text", "reference", "markdown", "keyboard")

    monkeypatch.setenv("XIUXIAN3_QQ_CAPABILITIES", '{"app-id":["unknown"]}')
    with pytest.raises(ValueError, match="unknown capabilities"):
        XiuxianSettings.from_env()


def test_qq_capability_map_enables_markdown_only_for_listed_app_ids(monkeypatch) -> None:
    monkeypatch.setenv(
        "XIUXIAN3_QQ_CAPABILITIES",
        '{"markdown-app":["markdown","keyboard"]}',
    )
    settings = XiuxianSettings.from_env()

    assert settings.qq_capabilities_for("markdown-app") == (
        "text",
        "markdown",
        "keyboard",
    )
    assert settings.qq_capabilities_for("unlisted-app") == ("text",)


@pytest.mark.parametrize("prefix", ("", "/", "!"))
def test_handler_sends_native_controls_with_configured_prefix_and_event_identity(monkeypatch, prefix) -> None:
    import re

    from nonebot.matcher import current_bot, current_event

    monkeypatch.setattr("nonebot.get_driver", lambda: SimpleNamespace(config=SimpleNamespace(command_start={prefix, "/"})))
    monkeypatch.setenv("XIUXIAN3_QQ_CAPABILITIES", '{"controls-app":["markdown","keyboard"]}')
    actions = (
        CommandAction("查看图鉴", "我的图鉴", enter=True),
        CommandAction("悬赏篇", "修仙帮助 悬赏", enter=True),
        CommandAction("取新道号", "修仙改名"),
    )
    calls = []

    async def dispatch(context, text):
        calls.append((context, text))
        return CommandResult(
            True, "PROFILE_READ", "道号：青云 · " + command_link("改名", "修仙改名"),
            context.request_id, actions=actions,
        )

    class Matcher:
        async def finish(self, *args):
            return None

    runtime = SimpleNamespace(settings=XiuxianSettings.from_env(), dispatch=dispatch)

    async def run() -> None:
        event = qq_message_event()
        event.content = prefix + "我的状态"
        bot = FakeQQBot("controls-app")
        bot_token = current_bot.set(bot)
        event_token = current_event.set(event)
        commands = ("我的状态", "修仙改名", "我的图鉴", "修仙帮助")
        try:
            handler = _handler_for(runtime, Matcher(), _normalizer_for_runtime(runtime), EventDeduplicator(), commands)
            await handler(event)
            await handler(event)
        finally:
            current_event.reset(event_token)
            current_bot.reset(bot_token)
        assert len(calls) == len(bot.sent) == 1
        context, text = calls[0]
        assert text == "我的状态"
        assert context.adapter == "qq.official" and context.user_id == "player-1"
        assert context.bot_id == "controls-app" and context.group_id == "group-1"
        assert context.message_id == event.id and context.operation_id
        segments = list(bot.sent[0])
        assert [segment.type for segment in segments] == ["markdown", "keyboard"]
        markdown = segments[0].data["markdown"].content
        assert "command:" not in markdown
        assert "[改名]" in markdown
        if prefix:
            assert "[" + prefix + "改名]" not in markdown
        query = parse_qs(urlparse(re.search(r"\[改名\]\(([^)]+)\)", markdown).group(1)).query)
        assert query == {"command": [prefix + "修仙改名"], "enter": ["false"], "reply": ["false"]}
        buttons = segments[1].data["keyboard"].content.rows[0].buttons
        assert len({button.id for button in buttons}) == 3
        assert [button.action.enter for button in buttons] == [True, True, False]
        for button, action in zip(buttons, actions):
            assert button.action.type == 2 and button.action.reply is False
            assert button.action.data == prefix + action.command
            assert button.render_data.label == action.label
            assert _canonical_command(button.action.data, commands) == action.command

    asyncio.run(run())


@pytest.mark.parametrize("capabilities", (("text",), ("text", "markdown")))
def test_missing_keyboard_keeps_contextual_action_without_native_buttons(capabilities) -> None:
    async def run() -> None:
        bot = FakeQQBot("limited-app")
        action = CommandAction("阅读世界说明", "完成引导 阅读", enter=True)
        result = await send_markdown_message(
            bot, qq_message_event(), "先读世界说明，再继续修行。", capabilities=capabilities,
            actions=(action,), command_prefix="!",
        )
        if "markdown" in capabilities:
            assert result.sent_format == "markdown"
            segment = bot.sent[0]
            assert segment.type == "markdown"
            content = segment.data["markdown"].content
            assert "[阅读世界说明](mqqapi://aio/inlinecmd" in content
            assert parse_qs(urlparse(content.split("](")[1].rstrip(")")).query)["command"] == ["!完成引导 阅读"]
            assert "keyboard" not in str(segment)
        else:
            assert result.sent_format == "text"
            assert bot.sent == ["先读世界说明，再继续修行。\n\n可发送：完成引导 阅读"]
            assert "!" not in bot.sent[0]

    asyncio.run(run())
