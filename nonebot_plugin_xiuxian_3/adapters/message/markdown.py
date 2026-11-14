"""Markdown rendering with a plain-text fallback."""

from __future__ import annotations

import re
from typing import Any, Collection
from urllib.parse import unquote

from ...contracts import CommandAction
from .common import MessageSendResult, message_id_from_response, require_content


_COMMAND_LINK_PATTERN = re.compile(r"\[([^\]\n]+)\]\(command:([^)]+)\)")


def command_targets(markdown: str) -> tuple[str, ...]:
    """Return decoded internal command targets already present in Markdown."""

    return tuple(unquote(match.group(2)).strip() for match in _COMMAND_LINK_PATTERN.finditer(markdown))


def _actions_without_inline_links(
    markdown: str, actions: Collection[CommandAction]
) -> tuple[CommandAction, ...]:
    targets = {" ".join(command.split()) for command in command_targets(markdown)}
    return tuple(
        action
        for action in actions
        if " ".join(action.command.split()) not in targets
    )


async def send_markdown_message(
    bot: Any,
    event: Any,
    markdown: str,
    *,
    capabilities: Collection[str] = (),
    fallback_text: str | None = None,
    actions: tuple[CommandAction, ...] = (),
    command_prefix: str = "",
    **kwargs: Any,
) -> MessageSendResult:
    require_content(markdown, "markdown")
    effective_actions = _actions_without_inline_links(markdown, actions)
    if _supports_markdown(bot, event, capabilities):
        body = markdown
        keyboard_requested = bool(effective_actions and "keyboard" in capabilities)
        if effective_actions and not keyboard_requested:
            from ...xiuxian.utils.text import command_link

            body += "\n\n" + " · ".join(
                command_link(action.label, action.command) for action in effective_actions
            )
        segment = qq_markdown_segment(body, command_prefix=command_prefix)
        if segment is not None:
            sent_format = "markdown"
            degraded = False
            if keyboard_requested:
                from .qq import qq_keyboard

                try:
                    segment += qq_keyboard((effective_actions,), command_prefix=command_prefix)
                    sent_format = "markdown+keyboard"
                except (ImportError, RuntimeError, TypeError, ValueError):
                    from ...xiuxian.utils.text import command_link

                    body += "\n\n" + " · ".join(
                        command_link(action.label, action.command) for action in effective_actions
                    )
                    segment = qq_markdown_segment(body, command_prefix=command_prefix)
                    degraded = True
            if segment is not None:
                response = await bot.send(event=event, message=segment, **kwargs)
                return MessageSendResult(
                    requested_format="markdown+keyboard" if actions else "markdown",
                    sent_format=sent_format,
                    degraded=degraded,
                    response=response,
                    message_id=message_id_from_response(response),
                )

    text = fallback_text if fallback_text is not None else markdown_to_text(markdown)
    if effective_actions:
        text += "\n\n可发送：" + "；".join(action.command for action in effective_actions)
    require_content(text, "fallback_text")
    response = await bot.send(event=event, message=text, **kwargs)
    return MessageSendResult(
        requested_format="markdown+keyboard" if actions else "markdown",
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
    commands: list[str] = []

    def plain_command(match: re.Match[str]) -> str:
        label, command = markdown_to_text(match.group(1)), unquote(match.group(2))
        commands.append(label if label == command else f"{label}（{command}）")
        return f"\x00{len(commands) - 1}\x00"

    text = re.sub(r"\[([^]]+)\]\(command:([^)]+)\)", plain_command, text)
    text = re.sub(r"\[([^]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"^\s{0,3}#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s{0,3}>\s?", "", text, flags=re.MULTILINE)
    text = re.sub(r"(?<!\\)[*_~]", "", text)
    text = text.replace("\\*", "*").replace("\\_", "_").replace("\\~", "~")
    # Restore commands after removing Markdown so stable IDs retain underscores.
    for index, command in enumerate(commands):
        text = text.replace(f"\x00{index}\x00", command)
    return text.strip()


def _supports_markdown(bot: Any, event: Any, capabilities: Collection[str]) -> bool:
    modules = f"{type(bot).__module__} {type(event).__module__}".lower()
    if "nonebot.adapters.onebot" in modules:
        return False
    return "markdown" in capabilities


def qq_markdown_segment(markdown: str, *, command_prefix: str = "") -> Any | None:
    try:
        from nonebot.adapters.qq import MessageSegment
    except ImportError:
        return None
    builder = getattr(MessageSegment, "markdown", None)
    if not callable(builder):
        return None
    try:
        return builder(_qq_command_links(markdown, command_prefix=command_prefix))
    except (TypeError, ValueError):
        return None


def _qq_command_links(markdown: str, *, command_prefix: str = "") -> str:
    pattern = _COMMAND_LINK_PATTERN
    if not pattern.search(markdown):
        return markdown
    from .qq import qq_command_link

    return pattern.sub(
        lambda match: qq_command_link(match.group(1), command_prefix + unquote(match.group(2))),
        markdown,
    )
