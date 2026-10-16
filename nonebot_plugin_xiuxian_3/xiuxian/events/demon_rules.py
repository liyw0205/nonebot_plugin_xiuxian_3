"""Command vocabulary for the demon invasion event (content-backed)."""

from __future__ import annotations

from ..content import ContentBundle, ContentError, bundled_content

DEMON_EVENT_KEY = "event.demon_invasion"


def demon_action_values(content: ContentBundle | None = None) -> dict[str, str]:
    """Chinese command labels mapped to the event's own contribution keys."""

    bundle = content if content is not None else bundled_content()
    try:
        row = bundle.require("event", DEMON_EVENT_KEY, include_locked=True)
    except KeyError as exc:
        raise ContentError(f"missing event content: {DEMON_EVENT_KEY}") from exc
    public_event = row.get("public_event")
    contributions = (
        public_event.get("contributions") if isinstance(public_event, dict) else None
    )
    if not isinstance(contributions, dict) or not contributions:
        raise ContentError(f"{DEMON_EVENT_KEY} public_event.contributions is required")
    aliases = row.get("action_aliases")
    if not isinstance(aliases, dict) or not aliases:
        raise ContentError(f"{DEMON_EVENT_KEY} action_aliases must be a non-empty object")
    values: dict[str, str] = {}
    for label, action_key in aliases.items():
        if not isinstance(label, str) or not label.strip():
            raise ContentError(f"{DEMON_EVENT_KEY} has an invalid action alias")
        if not isinstance(action_key, str) or action_key not in contributions:
            raise ContentError(
                f"{DEMON_EVENT_KEY} action alias {label} maps to unknown action {action_key}"
            )
        values[label] = action_key
    return values


DEMON_ACTION_VALUES = demon_action_values()


__all__ = ["DEMON_ACTION_VALUES", "DEMON_EVENT_KEY", "demon_action_values"]
