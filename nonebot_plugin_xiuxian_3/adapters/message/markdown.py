"""Markdown rendering with a plain-text fallback."""

from __future__ import annotations

import re
from typing import Any, Collection
from urllib.parse import unquote

from .common import MessageSendResult, message_id_from_response, require_content


async def send_markdown_message(
    bot: Any,
    event: Any,
    markdown: str,
    *,
    capabilities: Collection[str] = (),
    fallback_text: str | None = None,
    **kwargs: Any,
) -> MessageSendResult:
    require_content(markdown, "markdown")
    if _supports_markdown(bot, event, capabilities):
        segment = qq_markdown_segment(markdown)
        if segment is not None:
            response = await bot.send(event=event, message=segment, **kwargs)
            return MessageSendResult(
                requested_format="markdown",
                sent_format="markdown",
                degraded=False,
                response=response,
                message_id=message_id_from_response(response),
            )

    text = fallback_text if fallback_text is not None else markdown_to_text(markdown)
    require_content(text, "fallback_text")
    response = await bot.send(event=event, message=text, **kwargs)
    return MessageSendResult(
        requested_format="markdown",
        sent_format="text",
        degraded=True,
        response=response,
        message_id=message_id_from_response(response),
    )


def markdown_to_text(markdown: str) -> str:
    text = markdown.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"```[^\n]*\n?", "", text)
    text = text.replace("```", "")
    text = re.sub(r"(?<!`)`([^`\n]+)`(?!`)", r"\1", text)
    text = re.sub(r"!\[([^]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\[([^]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"^\s{0,3}#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s{0,3}>\s?", "", text, flags=re.MULTILINE)
    text = re.sub(r"(?<!\\)[*_~]", "", text)
    text = text.replace("\\*", "*").replace("\\_", "_").replace("\\~", "~")
    return text.strip()


def _supports_markdown(bot: Any, event: Any, capabilities: Collection[str]) -> bool:
    modules = f"{type(bot).__module__} {type(event).__module__}".lower()
    if "nonebot.adapters.onebot" in modules:
        return False
    return "markdown" in capabilities


def qq_markdown_segment(markdown: str) -> Any | None:
    try:
        from nonebot.adapters.qq import MessageSegment
    except ImportError:
        return None
    builder = getattr(MessageSegment, "markdown", None)
    if not callable(builder):
        return None
    try:
        return builder(_qq_command_links(markdown))
    except (TypeError, ValueError):
        return None


def _qq_command_links(markdown: str) -> str:
    pattern = re.compile(r"\[([^\]\n]+)\]\(command:([^)]+)\)")
    if not pattern.search(markdown):
        return markdown
    from .qq import qq_command_link

    return pattern.sub(
        lambda match: qq_command_link(match.group(1), unquote(match.group(2))),
        markdown,
    )
