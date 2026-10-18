"""Rules for the first cross-realm player quest (content-backed)."""

from __future__ import annotations

from ..content import ContentBundle, bundled_content
from .cross_realm_quest_content import quest_record

DEMON_MAINLINE = "quest.demon_main_1"

_RECORD = quest_record(DEMON_MAINLINE)

DEMON_MAINLINE_EXPLORATION = str(_RECORD["exploration_mode"])
DEMON_MAINLINE_EXPLORATION_TARGET = int(_RECORD["exploration_target"])
DEMON_MAINLINE_REQUIRED_REPUTATION = int(_RECORD["required_reputation"])
DEMON_MAINLINE_ACCESS_FLAG = str(_RECORD["access_flag"])
DEMON_MAINLINE_REQUIRED_REALM = str(_RECORD["required_realm"])
DEMON_MAINLINE_REQUIRED_LAYER = int(_RECORD["required_layer"])


def realm_rank(realm_key: str, content: ContentBundle | None = None) -> int:
    """Rank of an open realm, read from the realm content instead of a table."""

    bundle = content if content is not None else bundled_content()
    try:
        row = bundle.require("realm", realm_key, include_locked=False)
    except KeyError:
        return -1
    rank = row.get("rank")
    if isinstance(rank, bool) or not isinstance(rank, int):
        raise ValueError(f"realm {realm_key} has no integer rank")
    return int(rank)


def demon_mainline_realm_ready(
    realm_key: str, layer: int, content: ContentBundle | None = None
) -> bool:
    master_rank = realm_rank(DEMON_MAINLINE_REQUIRED_REALM, content)
    rank = realm_rank(realm_key, content)
    return (rank, int(layer)) >= (master_rank, DEMON_MAINLINE_REQUIRED_LAYER)


__all__ = [
    "DEMON_MAINLINE",
    "DEMON_MAINLINE_ACCESS_FLAG",
    "DEMON_MAINLINE_EXPLORATION",
    "DEMON_MAINLINE_EXPLORATION_TARGET",
    "DEMON_MAINLINE_REQUIRED_LAYER",
    "DEMON_MAINLINE_REQUIRED_REALM",
    "DEMON_MAINLINE_REQUIRED_REPUTATION",
    "demon_mainline_realm_ready",
    "realm_rank",
]
