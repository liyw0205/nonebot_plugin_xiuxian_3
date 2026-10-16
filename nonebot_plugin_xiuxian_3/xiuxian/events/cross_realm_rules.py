"""Stable event keys and command vocabulary for cross-realm events (content-backed)."""

from __future__ import annotations

from ..content import ContentBundle, ContentError, bundled_content

BEAST_TRADE_EVENT_KEY = "event.beast_trade"
BOUNDARY_RIFT_EVENT_KEY = "event.boundary_rift"
ANCIENT_DOMAIN_OPEN_EVENT_KEY = "event.ancient_domain_open"


def cross_realm_action_values(
    event_key: str, content: ContentBundle | None = None
) -> dict[str, str]:
    """Chinese command labels mapped to the event's own contribution keys."""

    bundle = content if content is not None else bundled_content()
    try:
        row = bundle.require("event", event_key, include_locked=True)
    except KeyError as exc:
        raise ContentError(f"missing event content: {event_key}") from exc
    public_event = row.get("public_event")
    contributions = (
        public_event.get("contributions") if isinstance(public_event, dict) else None
    )
    if not isinstance(contributions, dict) or not contributions:
        raise ContentError(f"{event_key} public_event.contributions is required")
    aliases = row.get("action_aliases")
    if not isinstance(aliases, dict) or not aliases:
        raise ContentError(f"{event_key} action_aliases must be a non-empty object")
    values: dict[str, str] = {}
    for label, action_key in aliases.items():
        if not isinstance(label, str) or not label.strip():
            raise ContentError(f"{event_key} has an invalid action alias")
        if not isinstance(action_key, str) or action_key not in contributions:
            raise ContentError(
                f"{event_key} action alias {label} maps to unknown action {action_key}"
            )
        values[label] = action_key
    return values


BEAST_TRADE_ACTION_VALUES = cross_realm_action_values(BEAST_TRADE_EVENT_KEY)
BOUNDARY_RIFT_ACTION_VALUES = cross_realm_action_values(BOUNDARY_RIFT_EVENT_KEY)
ANCIENT_DOMAIN_OPEN_ACTION_VALUES = cross_realm_action_values(ANCIENT_DOMAIN_OPEN_EVENT_KEY)


__all__ = [
    "BEAST_TRADE_ACTION_VALUES",
    "BEAST_TRADE_EVENT_KEY",
    "BOUNDARY_RIFT_ACTION_VALUES",
    "BOUNDARY_RIFT_EVENT_KEY",
    "ANCIENT_DOMAIN_OPEN_ACTION_VALUES",
    "ANCIENT_DOMAIN_OPEN_EVENT_KEY",
    "cross_realm_action_values",
]
