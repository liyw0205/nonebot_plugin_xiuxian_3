"""QQ official message formats."""

from __future__ import annotations

from typing import Any

from .common import MessageSendResult, require_adapter, require_content, send_text_message, message_id_from_response
from .markdown import qq_markdown_segment


async def send_qq_text_message(bot: Any, event: Any, text: str, **kwargs: Any) -> MessageSendResult:
    require_adapter(bot, event, "qq")
    return await send_text_message(bot, event, text, **kwargs)


async def send_qq_markdown_message(
    bot: Any,
    event: Any,
    markdown: str,
    **kwargs: Any,
) -> MessageSendResult:
    require_content(markdown, "markdown")
    require_adapter(bot, event, "qq")
    segment = qq_markdown_segment(markdown)
    if segment is None:
        raise RuntimeError("QQ Markdown message segment is unavailable")
    response = await bot.send(event=event, message=segment, **kwargs)
    return MessageSendResult(
        requested_format="markdown",
        sent_format="markdown",
        degraded=False,
        response=response,
        message_id=message_id_from_response(response),
    )
