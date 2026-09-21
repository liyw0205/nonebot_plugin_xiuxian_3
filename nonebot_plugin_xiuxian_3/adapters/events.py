"""Small, dependency-free event normalization helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..contracts import CommandContext


def value(source: Any, *names: str, default: Any = None) -> Any:
    for name in names:
        if isinstance(source, dict):
            candidate = source.get(name)
        else:
            candidate = getattr(source, name, None)
        if candidate is not None and candidate != "":
            return candidate
    return default


def text_value(source: Any, *names: str, default: str = "") -> str:
    candidate = value(source, *names, default=None)
    return default if candidate is None else str(candidate)


def nested_value(source: Any, paths: tuple[tuple[str, ...], ...]) -> str:
    for path in paths:
        current = source
        for name in path:
            current = value(current, name, default=None)
            if current is None:
                break
        if current is not None and current != "":
            return str(current)
    return ""


def extract_plaintext(event: Any) -> str:
    getter = getattr(event, "get_message", None)
    if callable(getter):
        try:
            message = getter()
            extractor = getattr(message, "extract_plain_text", None)
            if callable(extractor):
                content = extractor()
                if content:
                    return str(content).strip()
            if isinstance(message, str) and message.strip():
                return message.strip()
        except Exception:
            pass
    for name in ("raw_message", "plaintext", "content", "text"):
        content = value(event, name, default=None)
        if content:
            return str(content).strip()
    return ""


@dataclass(frozen=True, slots=True)
class NormalizedMessage:
    context: CommandContext
    text: str
    message_id: str
    event_id: str
    reference_id: str = ""
    raw_event: Any = None


def author_name(event: Any, user_id: str) -> str:
    return nested_value(
        event,
        (
            ("sender", "card"),
            ("sender", "nickname"),
            ("author", "member_name"),
            ("author", "nickname"),
            ("author", "username"),
            ("author", "name"),
        ),
    ) or user_id
