from __future__ import annotations

import asyncio

import pytest

from nonebot_plugin_xiuxian_3.adapters.messaging import (
    ForwardNode,
    markdown_to_text,
    send_markdown_message,
    send_message_by_adapter,
    send_onebot_v11_forward_message,
    send_onebot_v11_text_message,
    send_qq_markdown_message,
    send_qq_text_message,
    send_text_message,
)


class FakeBot:
    def __init__(self) -> None:
        self.sent: list[tuple[object, object, dict[str, object]]] = []

    async def send(self, event: object, message: object, **kwargs: object) -> dict[str, str]:
        self.sent.append((event, message, kwargs))
        return {"message_id": "reply-1"}


def test_message_dispatch_selects_adapter_family() -> None:
    class FakeQQBot(FakeBot):
        __module__ = "nonebot.adapters.qq.bot"

    class FakeQQEvent:
        __module__ = "nonebot.adapters.qq.event"

    class FakeOneBot(FakeBot):
        __module__ = "nonebot.adapters.onebot.v11.bot"

    class FakeOneBotEvent:
        __module__ = "nonebot.adapters.onebot.v11.event"

    async def run() -> None:
        qq = FakeQQBot()
        onebot = FakeOneBot()
        assert (await send_message_by_adapter(qq, FakeQQEvent(), "QQ")).sent_format == "text"
        assert (await send_message_by_adapter(onebot, FakeOneBotEvent(), "OneBot")).sent_format == "text"

    asyncio.run(run())


def test_send_text_message_uses_plain_text() -> None:
    async def run() -> None:
        bot = FakeBot()
        result = await send_text_message(bot, "event", "寻仙问道", reply_to="m-1")
        assert result.sent_format == "text"
        assert result.degraded is False
        assert result.message_id == "reply-1"
        assert bot.sent == [("event", "寻仙问道", {"reply_to": "m-1"})]

    asyncio.run(run())


def test_qq_specific_senders_use_expected_formats() -> None:
    async def run() -> None:
        bot = FakeBot()
        plain = await send_qq_text_message(bot, "event", "QQ 普通消息")
        markdown = await send_qq_markdown_message(bot, "event", "**QQ Markdown**")
        assert plain.sent_format == "text"
        assert markdown.sent_format == "markdown"
        assert bot.sent[0][1] == "QQ 普通消息"

    asyncio.run(run())


def test_markdown_degrades_to_text_without_capability() -> None:
    async def run() -> None:
        bot = FakeBot()
        result = await send_markdown_message(
            bot,
            "event",
            "# 境界\n\n**感气**：见[资料](https://example.invalid/realm)",
        )
        assert result.sent_format == "text"
        assert result.degraded is True
        assert bot.sent[0][1] == "境界\n\n感气：见资料"

    asyncio.run(run())


def test_markdown_uses_qq_segment_when_capability_is_declared() -> None:
    from nonebot.adapters.qq import MessageSegment

    async def run() -> None:
        bot = FakeBot()
        result = await send_markdown_message(bot, "event", "**感气**", capabilities=("markdown",))
        assert result.sent_format == "markdown"
        assert result.degraded is False
        assert isinstance(bot.sent[0][1], MessageSegment)

    asyncio.run(run())


def test_markdown_to_text_preserves_code_content() -> None:
    assert markdown_to_text("```text\n灵石: 100\n```") == "灵石: 100"


def test_onebot_v11_specific_senders() -> None:
    onebot = pytest.importorskip("nonebot.adapters.onebot.v11")

    class FakeOneBot(FakeBot):
        __module__ = "nonebot.adapters.onebot.v11.bot"

        def __init__(self) -> None:
            super().__init__()
            self.self_id = "987"
            self.api_calls: list[tuple[str, dict[str, object]]] = []

        async def call_api(self, api: str, **data: object) -> dict[str, str]:
            self.api_calls.append((api, data))
            return {"message_id": "forward-1"}

    class FakeOneBotEvent:
        __module__ = "nonebot.adapters.onebot.v11.event"
        message_type = "group"
        group_id = "456"
        user_id = "123"

    async def run() -> None:
        bot = FakeOneBot()
        event = FakeOneBotEvent()
        plain = await send_onebot_v11_text_message(bot, event, "OneBot 普通消息")
        forward = await send_onebot_v11_forward_message(
            bot,
            event,
            ["第一段", ForwardNode("第二段", user_id="321", nickname="道友")],
        )
        assert plain.sent_format == "text"
        assert forward.sent_format == "forward"
        assert bot.sent[0][1] == "OneBot 普通消息"
        api, data = bot.api_calls[0]
        assert api == "send_group_forward_msg"
        assert data["group_id"] == 456
        nodes = data["messages"]
        assert len(nodes) == 2
        assert nodes[0].type == "node"
        assert nodes[0].data["content"].extract_plain_text() == "第一段"

    asyncio.run(run())
