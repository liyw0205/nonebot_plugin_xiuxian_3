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


def bonus_percent_label(bp: int) -> str:
    """Render a basis-point bonus as compact player-facing percentage copy."""

    whole, remainder = divmod(int(bp), 100)
    if remainder == 0:
        return f"{whole}%"
    return f"{whole}.{remainder:02d}".rstrip("0") + "%"


__all__ = ["bonus_percent_label", "escape_markdown", "command_link"]
