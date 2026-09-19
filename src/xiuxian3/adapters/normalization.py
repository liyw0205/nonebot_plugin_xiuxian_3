"""Normalize supported adapter events into platform-neutral DTOs."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from .contracts import CommandContext, MessageCapability, Scene


def _string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _digest(event: Mapping[str, Any]) -> str:
    encoded = json.dumps(event, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _capabilities(source: str, event: Mapping[str, Any]) -> frozenset[MessageCapability]:
    values = event.get("capabilities")
    if isinstance(values, (list, tuple, set, frozenset)):
        result = {MessageCapability.TEXT}
        for value in values:
            try:
                result.add(MessageCapability(str(value)))
            except ValueError:
                continue
        return frozenset(result)
    if source == "onebot.v11":
        return frozenset({MessageCapability.TEXT, MessageCapability.IMAGE, MessageCapability.REFERENCE})
    if source == "qq":
        return frozenset({MessageCapability.TEXT, MessageCapability.REFERENCE})
    return frozenset({MessageCapability.TEXT})


def normalize_event(source: str, event: Mapping[str, Any]) -> CommandContext:
    """Build a safe DTO; unknown or incomplete events are read-only."""

    actor_id = _string(event.get("user_id" if source == "onebot.v11" else "author_id"))
    message_id = _string(event.get("message_id" if source == "onebot.v11" else "id"))
    text = _string(event.get("raw_message" if source == "onebot.v11" else "content")) or ""
    group_id: str | None = None
    scene = Scene.UNKNOWN

    if source == "onebot.v11":
        group_id = _string(event.get("group_id"))
        scene = Scene.GROUP if group_id is not None else Scene.PRIVATE
    elif source == "qq":
        channel_id = _string(event.get("channel_id"))
        if channel_id is not None:
            group_id = channel_id
            scene = Scene.CHANNEL_PRIVATE if bool(event.get("direct")) else Scene.CHANNEL_GROUP
        elif bool(event.get("direct")):
            scene = Scene.PRIVATE

    writable = actor_id is not None and message_id is not None and scene is not Scene.UNKNOWN
    return CommandContext(
        actor_id=actor_id,
        scene=scene,
        group_id=group_id,
        message_id=message_id,
        text=text,
        raw_text_digest=_digest(event),
        reply_to_message_id=_string(event.get("reply_to" if source == "onebot.v11" else "reply_to_id")),
        capabilities=_capabilities(source, event),
        can_write_assets=writable,
    )