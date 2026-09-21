"""Adapter boundary for NoneBot, Web, CLI, and test transports."""

from .base import AdapterRegistry, CommandRouter
from .messaging import (
    ForwardNode,
    MessageSendResult,
    send_markdown_message,
    send_message_by_adapter,
    send_onebot_v11_forward_message,
    send_onebot_v11_text_message,
    send_qq_markdown_message,
    send_qq_text_message,
    send_text_message,
)
from .onebot import normalize_event as normalize_onebot_event
from .qq import normalize_event as normalize_qq_event

__all__ = [
    "AdapterRegistry",
    "CommandRouter",
    "ForwardNode",
    "MessageSendResult",
    "normalize_onebot_event",
    "normalize_qq_event",
    "send_markdown_message",
    "send_message_by_adapter",
    "send_onebot_v11_forward_message",
    "send_onebot_v11_text_message",
    "send_qq_markdown_message",
    "send_qq_text_message",
    "send_text_message",
]
