"""QQ official message formats."""

from __future__ import annotations

from typing import Any, Iterable
from urllib.parse import quote

from ...contracts import CommandAction
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


def qq_command_link(label: str, command: str) -> str:
    """Build a QQ inline-command link (the familiar blue text)."""

    clean_label = str(label or " ").replace("[", "").replace("]", "").replace("\n", " ").strip() or " "
    clean_command = str(command or clean_label).replace("\r", " ").replace("\n", " ").strip()
    return (
        f"[{clean_label}](mqqapi://aio/inlinecmd?command={quote(clean_command, safe='')}"
        "&enter=false&reply=false)"
    )


def qq_keyboard(
    rows: Iterable[Iterable[tuple[str, str] | CommandAction]],
    *,
    command_prefix: str = "",
) -> Any:
    """Construct a QQ inline keyboard without importing SDK types at module load."""

    try:
        from nonebot.adapters.qq import MessageSegment
        from nonebot.adapters.qq.models import (
            Action,
            Button,
            InlineKeyboard,
            InlineKeyboardRow,
            MessageKeyboard,
            Permission,
            RenderData,
        )
    except ImportError as exc:  # pragma: no cover - depends on optional adapter
        raise RuntimeError("QQ adapter is required for keyboard messages") from exc

    keyboard_rows = []
    for row in rows:
        buttons = []
        for index, item in enumerate(row):
            if isinstance(item, CommandAction):
                label, command, enter = item.label, item.command, item.enter
            else:
                label, command = item
                enter = False
            text = str(label or " ").replace("\r", " ").replace("\n", " ").strip() or " "
            action_data = command_prefix + (str(command or text).replace("\r", " ").replace("\n", " ").strip() or text)
            buttons.append(
                Button(
                    id=f"xiuxian3:{len(keyboard_rows)}:{index}",
                    render_data=RenderData(label=text, visited_label=text, style=1),
                    action=Action(
                        type=2,
                        permission=Permission(type=2),
                        data=action_data,
                        enter=enter,
                        reply=False,
                    ),
                )
            )
        if buttons:
            keyboard_rows.append(InlineKeyboardRow(buttons=buttons))
    return MessageSegment.keyboard(MessageKeyboard(content=InlineKeyboard(rows=keyboard_rows)))


async def send_qq_blue_text_message(
    bot: Any,
    event: Any,
    label: str,
    command: str,
    **kwargs: Any,
) -> MessageSendResult:
    """Send one clickable QQ command link as native Markdown."""

    return await send_qq_markdown_message(bot, event, qq_command_link(label, command), **kwargs)


async def send_qq_markdown_keyboard_message(
    bot: Any,
    event: Any,
    markdown: str,
    rows: Iterable[Iterable[tuple[str, str]]],
    **kwargs: Any,
) -> MessageSendResult:
    """Send QQ Markdown and inline buttons as one message."""

    require_content(markdown, "markdown")
    require_adapter(bot, event, "qq")
    segment = qq_markdown_segment(markdown)
    if segment is None:
        raise RuntimeError("QQ Markdown message segment is unavailable")
    message = segment + qq_keyboard(rows)
    response = await bot.send(event=event, message=message, **kwargs)
    return MessageSendResult(
        requested_format="markdown+keyboard",
        sent_format="markdown+keyboard",
        degraded=False,
        response=response,
        message_id=message_id_from_response(response),
    )
