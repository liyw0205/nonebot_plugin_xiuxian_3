"""Versioned contract for the first clue-driven legacy manor."""

from __future__ import annotations


LEGACY_MANOR_KEY = "instance.legacy.demon_reliquary"
LEGACY_MANOR_LOCATION = "demon.fallen_ruins"
LEGACY_MANOR_PERMISSION = "access.demon.fallen_ruins"
LEGACY_MANOR_CLUE = "item.clue.demon_contract"
LEGACY_MANOR_EXPIRY_SECONDS = 60 * 60
LEGACY_MANOR_CONTENT_VERSION = "content-0.6"
LEGACY_MANOR_RULE_VERSION = "adventures-0.6.0"
LEGACY_MANOR_STORY_FLAG = "story.legacy.demon_reliquary"

LEGACY_MANOR_NODES = (
    "reliquary_seal",
    "pact_archive",
    "oath_chamber",
)
LEGACY_MANOR_NODE_LABELS = {
    "reliquary_seal": "遗府封印",
    "pact_archive": "契约档案",
    "oath_chamber": "旧誓密室",
}
LEGACY_MANOR_NODE_ALIASES = {
    **{key: key for key in LEGACY_MANOR_NODES},
    **{label: key for key, label in LEGACY_MANOR_NODE_LABELS.items()},
    **{str(index + 1): key for index, key in enumerate(LEGACY_MANOR_NODES)},
}


def resolve_legacy_manor_node(value: str) -> str | None:
    return LEGACY_MANOR_NODE_ALIASES.get(value.strip())


__all__ = [
    "LEGACY_MANOR_CLUE",
    "LEGACY_MANOR_CONTENT_VERSION",
    "LEGACY_MANOR_EXPIRY_SECONDS",
    "LEGACY_MANOR_KEY",
    "LEGACY_MANOR_LOCATION",
    "LEGACY_MANOR_NODE_LABELS",
    "LEGACY_MANOR_NODES",
    "LEGACY_MANOR_PERMISSION",
    "LEGACY_MANOR_RULE_VERSION",
    "LEGACY_MANOR_STORY_FLAG",
    "resolve_legacy_manor_node",
]
