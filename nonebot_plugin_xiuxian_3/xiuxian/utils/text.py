"""Text helpers shared by player-facing messages."""

from __future__ import annotations


def escape_markdown(value: str) -> str:
    value = " ".join(value.split())
    special = set("\\`*_{}[]()#+-.!|>~")
    return "".join(f"\\{char}" if char in special else char for char in value)


__all__ = ["escape_markdown"]
