"""Optional NoneBot 2 integration.

Importing this module does not require NoneBot; ``install`` performs the
optional import so the core package remains usable in CLI/Web deployments.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..contracts import CommandContext
from ..runtime import XiuxianRuntime
from .base import EventDeduplicator
from .events import NormalizedMessage
from .messaging import send_markdown_message
from .onebot import is_onebot_v11_event, normalize_event as normalize_onebot_event
from .qq import is_qq_event, normalize_event as normalize_qq_event

try:
    from nonebot.adapters import Event as NoneBotEvent
except ImportError:  # pragma: no cover - only used when NoneBot is absent
    NoneBotEvent = Any  # type: ignore[misc,assignment]


def _value(event: Any, method: str, attribute: str, default: str = "") -> str:
    getter = getattr(event, method, None)
    if callable(getter):
        result = getter()
        return str(result) if result is not None else default
    result = getattr(event, attribute, default)
    return str(result) if result is not None else default


def context_from_event(event: Any) -> CommandContext:
    if is_onebot_v11_event(event):
        return normalize_onebot_event(event).context
    if is_qq_event(event):
        return normalize_qq_event(event).context
    return CommandContext(
        adapter="nonebot",
        user_id=_value(event, "get_user_id", "user_id"),
        scene_id=_value(event, "get_session_id", "session_id"),
        nickname=_value(event, "get_user_name", "nickname"),
    )


def normalize_event(event: Any) -> NormalizedMessage:
    if is_onebot_v11_event(event):
        return normalize_onebot_event(event)
    if is_qq_event(event):
        return normalize_qq_event(event)
    raise ValueError(f"不支持的 NoneBot 事件类型: {type(event)!r}")


def _rule_for(checker: Callable[[Any], bool]):
    async def rule(event: NoneBotEvent) -> bool:
        return checker(event)

    return rule


def _canonical_command(text: str, commands: tuple[str, ...]) -> str | None:
    """Return a command known by the shared router, preserving its arguments."""

    normalized = text.strip()
    if not normalized:
        return None

    candidates = (normalized,)
    try:
        from nonebot import get_driver

        configured = get_driver().config.command_start
    except (ImportError, AttributeError, ValueError):
        configured = ("/",)
    if isinstance(configured, str):
        prefixes = (configured,)
    else:
        # NoneBot exposes ``command_start`` as a tuple in configured drivers.
        # Keep the normalizer tolerant of list-like settings and ignore invalid
        # entries instead of passing a nested tuple to ``str.startswith``.
        prefixes = tuple(
            prefix for prefix in (configured or ()) if isinstance(prefix, str)
        )
    candidates += tuple(
        normalized[len(prefix) :].lstrip()
        for prefix in prefixes
        if prefix and normalized.startswith(prefix)
    )
    command_names = {command.strip().lower() for command in commands if command.strip()}
    for candidate in candidates:
        command = candidate.split(maxsplit=1)[0].lower()
        if command in command_names:
            return candidate
    return None


def _matches_seek_command(text: str, commands: tuple[str, ...]) -> bool:
    """Return whether text starts with a command registered by the router."""

    return _canonical_command(text, commands) is not None


def _is_seek_command(event: Any, commands: tuple[str, ...]) -> bool:
    if not (is_onebot_v11_event(event) or is_qq_event(event)):
        return False
    try:
        return _matches_seek_command(normalize_event(event).text, commands)
    except (TypeError, ValueError):
        return False


def _handler_for(
    runtime: XiuxianRuntime,
    matcher: Any,
    normalizer: Callable[[Any], NormalizedMessage],
    dedup: EventDeduplicator,
    commands: tuple[str, ...],
):
    async def handle(event: NoneBotEvent) -> None:
        normalized = normalizer(event)
        # Route the normalized command so prefixes do not reach the shared router.
        command = _canonical_command(normalized.text, commands)
        if command is None:
            return
        key = normalized.context.operation_id
        if not dedup.accept(key):
            return
        try:
            result = await runtime.dispatch(normalized.context, command)
        except Exception:
            dedup.release(key)
            raise
        if result.retryable:
            dedup.release(key)
        try:
            from nonebot.matcher import current_bot, current_event

            bot = current_bot.get()
            current = current_event.get()
        except (ImportError, LookupError):
            await matcher.finish(result.message)
        else:
            try:
                await send_markdown_message(
                    bot,
                    current,
                    result.message,
                    capabilities=normalized.context.capabilities,
                )
            except Exception:
                # A delivery failure leaves the event eligible for transport retry.
                dedup.release(key)
                raise
            await matcher.finish()

    return handle


def install(runtime: XiuxianRuntime) -> tuple[Any, ...]:
    """Register one cross-adapter matcher for the player command family."""

    try:
        from nonebot import on_message
    except ImportError as exc:  # pragma: no cover - exercised only without NoneBot
        raise RuntimeError("NoneBot 2 is required for the NoneBot adapter") from exc

    dedup = EventDeduplicator()
    commands = runtime.router.commands
    matchers: list[Any] = []
    matcher = on_message(
        rule=_rule_for(lambda event: _is_seek_command(event, commands)),
        priority=10,
        block=True,
    )
    matcher.handle()(_handler_for(runtime, matcher, normalize_event, dedup, commands))
    matchers.append(matcher)
    return tuple(matchers)
