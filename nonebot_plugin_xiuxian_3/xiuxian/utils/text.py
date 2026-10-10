"""Text helpers shared by player-facing messages."""

from __future__ import annotations

from urllib.parse import quote

def escape_markdown(value: str) -> str:
    value = " ".join(value.split())
    special = set("\\`*_{}[]()#+-.!|>~")
    return "".join(f"\\{char}" if char in special else char for char in value)


def command_link(label: str, command: str) -> str:
    """Keep transport prefixes out of player copy and domain commands."""

    return f"[{escape_markdown(label)}](command:{quote(command, safe='')})"


__all__ = ["escape_markdown", "command_link"]
