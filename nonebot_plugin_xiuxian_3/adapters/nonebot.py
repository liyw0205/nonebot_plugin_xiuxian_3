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


_COMMANDS = (
    "开始修仙",
    "寻仙问道",
    "我的状态",
    "我的修仙信息",
    "修仙改名",
    "改名",
    "完成引导",
    "前往近郊",
    "前往灵泉谷",
    "返回新手城",
    "选择道途",
    "开始修炼",
    "结算修炼",
    "恢复修炼",
    "取消修炼",
    "晋升境界",
    "境界晋升",
    "恢复状态",
    "突破预览",
    "开始突破",
    "结算突破",
    "恢复虚弱",
    "生产预览",
    "开始生产",
    "领取生产",
    "恢复生产",
    "移动预览",
    "前往",
    "前往雾隐洞天",
    "结算移动",
    "开始探索",
    "结算探索",
    "取消探索",
    "悬赏榜",
    "接取悬赏",
    "领取悬赏",
    "道历问安",
    "每日问安",
    "签到",
    "补录道历",
    "补签到",
    "浇灌灵木",
    "灵木浇灌",
    "浇水",
    "收获灵木",
    "灵木收获",
    "七日入道",
    "七日目标",
    "入道七日",
    "领取七日目标",
    "领取七日任务",
    "领取七日入道",
    "功业录",
    "我的功业",
    "我的称号",
    "领取功业",
    "领取成就",
    "佩戴称号",
    "装备称号",
)


def _canonical_command(text: str) -> str | None:
    """Return the registered command while preserving normalized arguments."""

    normalized = text.strip()
    if not normalized:
        return None

    candidates = (normalized,)
    try:
        from nonebot import get_driver

        configured = get_driver().config.command_start
    except (ImportError, AttributeError, ValueError):
        configured = ("/",)
    prefixes = (configured,) if isinstance(configured, str) else (configured or ())
    candidates += tuple(
        normalized[len(prefix) :].lstrip()
        for prefix in prefixes
        if prefix and normalized.startswith(prefix)
    )
    for candidate in candidates:
        for command in _COMMANDS:
            if candidate == command or candidate.startswith(f"{command} "):
                return candidate
    return None


def _matches_seek_command(text: str) -> bool:
    """Backward-compatible matcher name for the shared command rule."""

    return _canonical_command(text) is not None


def _is_seek_command(event: Any) -> bool:
    if not (is_onebot_v11_event(event) or is_qq_event(event)):
        return False
    try:
        return _matches_seek_command(normalize_event(event).text)
    except (TypeError, ValueError):
        return False


def _handler_for(runtime: XiuxianRuntime, matcher: Any, normalizer: Callable[[Any], NormalizedMessage], dedup: EventDeduplicator):
    async def handle(event: NoneBotEvent) -> None:
        normalized = normalizer(event)
        key = (
            f"{normalized.context.adapter}:{normalized.context.bot_id}:{normalized.event_id}"
            if normalized.event_id
            else ""
        )
        if not dedup.accept(key):
            return
        # Route the normalized command so prefixes do not reach the shared router.
        command = _canonical_command(normalized.text)
        if command is None:
            return
        result = await runtime.dispatch(normalized.context, command)
        try:
            from nonebot.matcher import current_bot, current_event

            bot = current_bot.get()
            current = current_event.get()
        except (ImportError, LookupError):
            await matcher.finish(result.message)
        else:
            await send_markdown_message(
                bot,
                current,
                result.message,
                capabilities=normalized.context.capabilities,
            )
            await matcher.finish()

    return handle


def install(runtime: XiuxianRuntime) -> tuple[Any, ...]:
    """Register one cross-adapter matcher for the player command family."""

    try:
        from nonebot import on_message
    except ImportError as exc:  # pragma: no cover - exercised only without NoneBot
        raise RuntimeError("NoneBot 2 is required for the NoneBot adapter") from exc

    dedup = EventDeduplicator()
    matchers: list[Any] = []
    matcher = on_message(
        rule=_rule_for(_is_seek_command),
        priority=10,
        block=True,
    )
    matcher.handle()(_handler_for(runtime, matcher, normalize_event, dedup))
    matchers.append(matcher)
    return tuple(matchers)
