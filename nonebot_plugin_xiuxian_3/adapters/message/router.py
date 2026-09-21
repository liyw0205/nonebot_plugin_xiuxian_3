"""Adapter selection for ordinary and capability-aware messages."""

from __future__ import annotations

from typing import Any

from .common import MessageSendResult, detect_adapter, send_text_message
from .onebot import send_onebot_v11_text_message
from .qq import send_qq_text_message


async def send_message_by_adapter(bot: Any, event: Any, text: str, **kwargs: Any) -> MessageSendResult:
    adapter = detect_adapter(bot, event)
    if adapter == "qq":
        return await send_qq_text_message(bot, event, text, **kwargs)
    if adapter == "onebot.v11":
        return await send_onebot_v11_text_message(bot, event, text, **kwargs)
    return await send_text_message(bot, event, text, **kwargs)
