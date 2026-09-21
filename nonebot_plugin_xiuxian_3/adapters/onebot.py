"""OneBot V11 event normalization and matcher-facing helpers."""

from __future__ import annotations

from typing import Any

from ..contracts import CommandContext
from .events import NormalizedMessage, author_name, extract_plaintext, text_value, value


ADAPTER_NAME = "onebot.v11"


def is_onebot_v11_event(event: Any) -> bool:
    module = type(event).__module__.lower()
    if "nonebot.adapters.onebot.v11" in module:
        return True
    return (
        value(event, "post_type", default=None) == "message"
        and value(event, "user_id", default=None) is not None
        and value(event, "message_type", default=None) in {"group", "private"}
    )


def normalize_event(event: Any) -> NormalizedMessage:
    if not is_onebot_v11_event(event):
        raise ValueError(f"不是 OneBot V11 消息事件: {type(event)!r}")
    user_id = text_value(event, "user_id", default="")
    message_type = text_value(event, "message_type", default="private")
    group_id = text_value(event, "group_id", default="") if message_type == "group" else ""
    scene_id = f"group:{group_id}" if group_id else "private"
    message_id = text_value(event, "message_id", default="")
    event_id = text_value(event, "event_id", default="") or message_id
    context = CommandContext(
        adapter=ADAPTER_NAME,
        user_id=user_id,
        scene_id=scene_id,
        nickname=author_name(event, user_id),
        message_id=message_id,
        scene=message_type if message_type in {"group", "private"} else "unknown",
        group_id=group_id,
        bot_id=text_value(event, "self_id", "bot_id", default=""),
        capabilities=("text", "reference"),
        can_write_assets=bool(user_id and message_id),
        operation_id=event_id,
    )
    return NormalizedMessage(
        context=context,
        text=extract_plaintext(event),
        message_id=message_id,
        event_id=event_id,
        reference_id=text_value(event, "message_reference_id", "reference_id", default=""),
        raw_event=event,
    )


__all__ = ["ADAPTER_NAME", "is_onebot_v11_event", "normalize_event"]
