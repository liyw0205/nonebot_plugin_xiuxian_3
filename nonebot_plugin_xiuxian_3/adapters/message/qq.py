"""QQ official message formats."""

from __future__ import annotations

from typing import Any, Iterable
from urllib.parse import quote

from ...contracts import CommandAction
from .common import MessageSendResult, require_adapter, require_content, send_text_message, message_id_from_response
from .markdown import command_targets, markdown_to_text, qq_markdown_segment


def _clean_command_parts(label: str, command: str) -> tuple[str, str]:
    clean_label = str(label or " ").replace("[", "").replace("]", "").replace("\r", " ").replace("\n", " ").strip() or " "
    clean_command = str(command or clean_label).replace("\r", " ").replace("\n", " ").strip() or clean_label
    return clean_label, clean_command


def _button_rows(rows: Iterable[Iterable[tuple[str, str] | CommandAction]]) -> tuple[tuple[tuple[str, str, bool], ...], ...]:
    normalized: list[tuple[tuple[str, str, bool], ...]] = []
    for row in rows:
        items: list[tuple[str, str, bool]] = []
        for item in row:
            if isinstance(item, CommandAction):
                label, command, enter = item.label, item.command, item.enter
            else:
                label, command = item
                enter = False
            clean_label, clean_command = _clean_command_parts(label, command)
            items.append((clean_label, clean_command, enter))
        if items:
            normalized.append(tuple(items))
    return tuple(normalized)


def _keyboard_fallback_text(
    markdown: str,
    rows: tuple[tuple[tuple[str, str, bool], ...], ...],
    *,
    fallback_text: str | None = None,
) -> str:
    text = fallback_text if fallback_text is not None else markdown_to_text(markdown)
    commands = [command for row in rows for _, command, _ in row]
    if commands:
        text += "\n\n可发送：" + "；".join(commands)
    return text


def _rows_without_inline_links(
    markdown: str,
    rows: tuple[tuple[tuple[str, str, bool], ...], ...],
) -> tuple[tuple[tuple[str, str, bool], ...], ...]:
    targets = {" ".join(command.split()) for command in command_targets(markdown)}
    return tuple(
        tuple(item for item in row if " ".join(item[1].split()) not in targets)
        for row in rows
    )


async def send_qq_text_message(bot: Any, event: Any, text: str, **kwargs: Any) -> MessageSendResult:
    require_adapter(bot, event, "qq")
    return await send_text_message(bot, event, text, **kwargs)


async def send_qq_markdown_message(
    bot: Any,
    event: Any,
    markdown: str,
    *,
    fallback_text: str | None = None,
    **kwargs: Any,
) -> MessageSendResult:
    require_content(markdown, "markdown")
    require_adapter(bot, event, "qq")
    segment = qq_markdown_segment(markdown)
    if segment is None:
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

    clean_label, clean_command = _clean_command_parts(label, command)
    return (
        f"[{clean_label}](mqqapi://aio/inlinecmd?command={quote(clean_command, safe='')}"
        "&enter=false&reply=false)"
    )


def qq_keyboard(
    rows: Iterable[Iterable[tuple[str, str] | tuple[str, str, bool] | CommandAction]],
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
                if len(item) == 3:
                    label, command, enter = item
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

    clean_label, clean_command = _clean_command_parts(label, command)
    return await send_qq_markdown_message(
        bot,
        event,
        qq_command_link(clean_label, clean_command),
        fallback_text=f"{clean_label}（{clean_command}）",
        **kwargs,
    )


async def send_qq_markdown_keyboard_message(
    bot: Any,
    event: Any,
    markdown: str,
    rows: Iterable[Iterable[tuple[str, str] | CommandAction]],
    *,
    fallback_text: str | None = None,
    command_prefix: str = "",
    **kwargs: Any,
) -> MessageSendResult:
    """Send QQ Markdown and inline buttons as one message."""

    require_content(markdown, "markdown")
    require_adapter(bot, event, "qq")
    normalized_rows = _rows_without_inline_links(markdown, _button_rows(rows))
    if not any(normalized_rows):
        result = await send_qq_markdown_message(
            bot,
            event,
            markdown,
            fallback_text=fallback_text,
            **kwargs,
        )
        return MessageSendResult(
            requested_format="markdown+keyboard",
            sent_format=result.sent_format,
            degraded=result.degraded,
            response=result.response,
            message_id=result.message_id,
        )
    segment = qq_markdown_segment(markdown)
    if segment is None:
        text = _keyboard_fallback_text(markdown, normalized_rows, fallback_text=fallback_text)
        require_content(text, "fallback_text")
        response = await bot.send(event=event, message=text, **kwargs)
        return MessageSendResult(
            requested_format="markdown+keyboard",
            sent_format="text",
            degraded=True,
            response=response,
            message_id=message_id_from_response(response),
        )
    try:
        message = segment + qq_keyboard(normalized_rows, command_prefix=command_prefix)
    except (ImportError, RuntimeError, TypeError, ValueError):
        body = markdown
        links = [
            qq_command_link(label, command_prefix + command)
            for row in normalized_rows
            for label, command, _ in row
        ]
        if links:
            body += "\n\n" + " · ".join(links)
        result = await send_qq_markdown_message(
            bot,
            event,
            body,
            fallback_text=_keyboard_fallback_text(markdown, normalized_rows, fallback_text=fallback_text),
            **kwargs,
        )
        return MessageSendResult(
            requested_format="markdown+keyboard",
            sent_format=result.sent_format,
            degraded=True,
            response=result.response,
            message_id=result.message_id,
        )
    response = await bot.send(event=event, message=message, **kwargs)
    return MessageSendResult(
        requested_format="markdown+keyboard",
        sent_format="markdown+keyboard",
        degraded=False,
        response=response,
        message_id=message_id_from_response(response),
    )
