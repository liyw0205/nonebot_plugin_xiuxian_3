"""QQ official adapter event normalization for group/C2C/channel messages."""

from __future__ import annotations

from typing import Any

from ..contracts import CommandContext
from .events import NormalizedMessage, author_name, extract_plaintext, nested_value, text_value, value


ADAPTER_NAME = "qq.official"


def is_qq_event(event: Any) -> bool:
    module = type(event).__module__.lower()
    if "nonebot.adapters.qq" in module:
        # QQ exposes many non-message events in the same module namespace.
        # MessageCreate events carry content and an author; reject lifecycle
        # events before they can reach command matching or persistence.
        event_name = type(event).__name__.lower()
        if "message" in event_name:
            return value(event, "content", default=None) is not None or value(
                event, "author", default=None
            ) is not None
        return False
    return any(
        value(event, name, default=None) is not None
        for name in ("group_openid", "user_openid", "channel_id", "guild_id")
    )


def _scene(event: Any) -> tuple[str, str]:
    event_name = type(event).__name__.lower()
    if "c2c" in event_name or value(event, "user_openid", default=None) is not None:
        user_id = nested_value(
            event,
            (("user_openid",), ("author", "user_openid"), ("author", "openid"), ("author", "id")),
        )
        return "private", f"private:{user_id}" if user_id else "private"
    if "directmessage" in event_name:
        channel_id = text_value(event, "channel_id", "guild_id", default="")
        return "channel_private", f"channel_private:{channel_id}" if channel_id else "channel_private"
    group_id = text_value(event, "group_openid", "group_id", default="")
    if group_id:
        return "group", f"group:{group_id}"
    channel_id = text_value(event, "channel_id", "guild_id", default="")
    if channel_id:
        return "channel_group", f"channel_group:{channel_id}"
    return "unknown", "unknown"


def normalize_event(event: Any) -> NormalizedMessage:
    if not is_qq_event(event):
        raise ValueError(f"不是 QQ 官方消息事件: {type(event)!r}")
    scene, scene_id = _scene(event)
    user_id = nested_value(
        event,
        (
            ("member_openid",),
            ("group_member_openid",),
            ("user_openid",),
            ("author", "member_openid"),
            ("author", "user_openid"),
            ("author", "openid"),
            ("author", "id"),
        ),
    )
    message_id = text_value(event, "id", "message_id", default="")
    event_id = text_value(event, "event_id", default="") or message_id
    context = CommandContext(
        adapter=ADAPTER_NAME,
        user_id=user_id,
        scene_id=scene_id,
        nickname=author_name(event, user_id),
        message_id=message_id,
        scene=scene,
        group_id=text_value(event, "group_openid", "group_id", "channel_id", default=""),
        bot_id=text_value(event, "application_id", "self_id", "bot_id", default=""),
        capabilities=("text", "reference", "markdown", "keyboard"),
        can_write_assets=bool(user_id and message_id and scene != "unknown"),
        operation_id=event_id,
    )
    reference_id = nested_value(
        event,
        (("msg_idx",), ("message_reference_id",), ("reference_id",), ("message_scene", "msg_idx")),
    )
    return NormalizedMessage(
        context=context,
        text=extract_plaintext(event),
        message_id=message_id,
        event_id=event_id,
        reference_id=reference_id,
        raw_event=event,
    )


__all__ = ["ADAPTER_NAME", "is_qq_event", "normalize_event"]
