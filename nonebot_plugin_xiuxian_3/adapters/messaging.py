"""Compatibility facade for the type-specific message implementations."""

from .message import (
    ForwardNode,
    MessageSendResult,
    markdown_to_text,
    message_id_from_response,
    send_markdown_message,
    send_message_by_adapter,
    send_onebot_v11_forward_message,
    send_onebot_v11_text_message,
    send_qq_markdown_message,
    send_qq_text_message,
    send_text_message,
)
from .message.common import detect_adapter as _detect_adapter
from .message.common import require_adapter as _require_adapter
from .message.common import require_content as _require_content
from .message.common import value as _value
from .message.markdown import _supports_markdown, qq_markdown_segment as _qq_markdown_segment

__all__ = [
    "ForwardNode",
    "MessageSendResult",
    "markdown_to_text",
    "message_id_from_response",
    "send_markdown_message",
    "send_message_by_adapter",
    "send_onebot_v11_forward_message",
    "send_onebot_v11_text_message",
    "send_qq_markdown_message",
    "send_qq_text_message",
    "send_text_message",
]
