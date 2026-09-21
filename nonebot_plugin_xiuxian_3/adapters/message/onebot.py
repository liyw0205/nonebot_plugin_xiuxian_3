"""OneBot V11 message formats, including merged forwarding."""

from __future__ import annotations

from typing import Any, Iterable

from .common import ForwardNode, MessageSendResult, message_id_from_response, require_adapter, require_content, send_text_message, value


async def send_onebot_v11_text_message(bot: Any, event: Any, text: str, **kwargs: Any) -> MessageSendResult:
    require_content(text, "text")
    require_adapter(bot, event, "onebot.v11")
    return await send_text_message(bot, event, text, **kwargs)


async def send_onebot_v11_forward_message(
    bot: Any,
    event: Any,
    messages: Iterable[str | ForwardNode],
    *,
    group_id: str | int | None = None,
    user_id: str | int | None = None,
    node_user_id: str | int | None = None,
    node_nickname: str = "修仙3",
    **kwargs: Any,
) -> MessageSendResult:
    require_adapter(bot, event, "onebot.v11")
    rows = tuple(messages)
    if not rows:
        raise ValueError("messages must contain at least one node")
    try:
        from nonebot.adapters.onebot.v11 import Message, MessageSegment
    except ImportError as exc:
        raise RuntimeError("OneBot V11 adapter is required for merged forwarding") from exc

    event_message_type = str(value(event, "message_type", default=""))
    resolved_group_id = str(group_id) if group_id is not None else str(value(event, "group_id", default=""))
    resolved_user_id = str(user_id) if user_id is not None else str(value(event, "user_id", default=""))
    if event_message_type == "group" or resolved_group_id:
        if not resolved_group_id:
            raise ValueError("group_id is required for group forward messages")
        api = "send_group_forward_msg"
        target = {"group_id": int(resolved_group_id) if resolved_group_id.isdigit() else resolved_group_id}
    elif event_message_type == "private" or resolved_user_id:
        if not resolved_user_id:
            raise ValueError("user_id is required for private forward messages")
        api = "send_private_forward_msg"
        target = {"user_id": int(resolved_user_id) if resolved_user_id.isdigit() else resolved_user_id}
    else:
        raise ValueError("cannot determine OneBot V11 forward target")

    default_node_user_id = str(node_user_id) if node_user_id is not None else str(
        value(bot, "self_id", default="") or value(event, "self_id", default="") or "0"
    )
    node_payload = []
    for row in rows:
        node = row if isinstance(row, ForwardNode) else ForwardNode(content=row)
        require_content(node.content, "forward node content")
        node_payload.append(
            MessageSegment.node_custom(
                int(node.user_id or default_node_user_id) if (node.user_id or default_node_user_id).isdigit() else 0,
                node.nickname or node_nickname,
                Message(node.content),
            )
        )

    response = await bot.call_api(api, **target, messages=node_payload, **kwargs)
    return MessageSendResult(
        requested_format="forward",
        sent_format="forward",
        degraded=False,
        response=response,
        message_id=message_id_from_response(response),
    )
