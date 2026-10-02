"""Player-facing labels for public event rewards."""

from __future__ import annotations

from ..content import ContentBundle, bundled_content


def public_event_reward_lines(
    rewards: dict[str, int],
    content: ContentBundle | None = None,
) -> tuple[str, ...]:
    bundle = content or bundled_content()
    lines: list[str] = []
    for key, quantity in rewards.items():
        if key.startswith("item."):
            label = bundle.label("item", key, fallback=None)
        elif key.startswith("faction_reputation."):
            label = bundle.label("resource", f"resource.{key}")
        elif key == "spirit_stones":
            label = bundle.label("resource", "currency.spirit_stone")
        else:
            resource_key = key if key.startswith("resource.") else f"resource.{key}"
            label = bundle.label("resource", resource_key)
        lines.append(f"- **{label}**：+{quantity}")
    return tuple(lines)


__all__ = ["public_event_reward_lines"]
