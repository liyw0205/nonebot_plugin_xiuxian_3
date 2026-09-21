"""Transport-neutral message result and text primitives."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class MessageSendResult:
    requested_format: str
    sent_format: str
    degraded: bool
    response: Any = None
    message_id: str = ""


@dataclass(frozen=True, slots=True)
class ForwardNode:
    """One custom node in an OneBot V11 merged-forward message."""

    content: str
    user_id: str = ""
    nickname: str = "修仙3"


async def send_text_message(bot: Any, event: Any, text: str, **kwargs: Any) -> MessageSendResult:
    require_content(text, "text")
    response = await bot.send(event=event, message=text, **kwargs)
    return MessageSendResult(
        requested_format="text",
        sent_format="text",
        degraded=False,
        response=response,
        message_id=message_id_from_response(response),
    )


def message_id_from_response(response: Any) -> str:
    if response is None:
        return ""
    if isinstance(response, dict):
        value = response.get("message_id", response.get("id", ""))
    else:
        value = getattr(response, "message_id", getattr(response, "id", ""))
    return "" if value is None else str(value)


def detect_adapter(bot: Any, event: Any) -> str:
    modules = f"{type(bot).__module__} {type(event).__module__}".lower()
    if "nonebot.adapters.qq" in modules:
        return "qq"
    if "nonebot.adapters.onebot.v11" in modules:
        return "onebot.v11"
    return "unknown"


def require_adapter(bot: Any, event: Any, expected: str) -> None:
    detected = detect_adapter(bot, event)
    if detected not in {expected, "unknown"}:
        raise TypeError(f"expected {expected} adapter, got {detected}")


def require_content(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


def value(source: Any, name: str, *, default: Any = None) -> Any:
    result = source.get(name, default) if isinstance(source, dict) else getattr(source, name, default)
    return default if result is None else result
