"""Message delivery implementations grouped by transport capability."""

from .common import ForwardNode, MessageSendResult, message_id_from_response, send_text_message
from .markdown import markdown_to_text, send_markdown_message
from .onebot import send_onebot_v11_forward_message, send_onebot_v11_text_message
from .qq import send_qq_markdown_message, send_qq_text_message
from .router import send_message_by_adapter

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
