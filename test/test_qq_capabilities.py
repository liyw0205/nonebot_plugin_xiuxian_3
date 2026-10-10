from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from nonebot_plugin_xiuxian_3.adapters.message.markdown import send_markdown_message
from nonebot_plugin_xiuxian_3.adapters.nonebot import _normalizer_for_runtime
from nonebot_plugin_xiuxian_3.xiuxian.config import XiuxianSettings


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
