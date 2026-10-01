"""Versioned contract for the void-ruins party secret realm."""

from __future__ import annotations


VOID_RUINS_KEY = "instance.secret_realm.void_ruins"
VOID_RUINS_LOCATION = "void.archive_ruins"
VOID_RUINS_PARTY_TYPE = "secret_realm_void_ruins"
VOID_RUINS_STAMINA_COST = 50
VOID_RUINS_ANCHOR_LOCK = 1
VOID_RUINS_MIN_MEMBERS = 2
VOID_RUINS_MAX_MEMBERS = 5
VOID_RUINS_WEEKLY_LIMIT = 1
VOID_RUINS_EXPIRY_SECONDS = 60 * 60
VOID_RUINS_ROUTE_PERMISSION = "access.void.time_fort"
VOID_RUINS_CODEX = "codex.void.route_ruins"
VOID_RUINS_REPEAT_REWARD = {"item.void_crystal": 1}

VOID_RUINS_NODES = (
    "ruins_entrance",
    "fractured_beacon",
    "void_corridor",
    "rift_sentinel",
    "archive_fringe",
    "unstable_storm",
    "anchor_field",
    "archive_keeper",
    "route_tablet",
    "exit_gate",
)

VOID_RUINS_NODE_LABELS = {
    "ruins_entrance": "遗迹入口",
    "fractured_beacon": "破碎信标",
    "void_corridor": "虚空回廊",
    "rift_sentinel": "裂隙哨卫",
    "archive_fringe": "档案外围",
    "unstable_storm": "虚空风暴",
    "anchor_field": "锚点原野",
    "archive_keeper": "档案守卫",
    "route_tablet": "航道石碑",
    "exit_gate": "归航之门",
}
VOID_RUINS_NODE_ALIASES = {
    **{key: key for key in VOID_RUINS_NODES},
    **{label: key for key, label in VOID_RUINS_NODE_LABELS.items()},
}
VOID_RUINS_ENEMIES = {
    ("rift_sentinel", False): "enemy.void_ruins_sentinel",
    ("rift_sentinel", True): "enemy.void_ruins_sentinel_unstable",
    ("archive_keeper", False): "enemy.void_ruins_keeper",
    ("archive_keeper", True): "enemy.void_ruins_keeper_unstable",
}


def resolve_void_ruins_node(value: str) -> str | None:
    return VOID_RUINS_NODE_ALIASES.get(value.strip())


__all__ = [
    "VOID_RUINS_ANCHOR_LOCK",
    "VOID_RUINS_CODEX",
    "VOID_RUINS_ENEMIES",
    "VOID_RUINS_EXPIRY_SECONDS",
    "VOID_RUINS_KEY",
    "VOID_RUINS_LOCATION",
    "VOID_RUINS_MAX_MEMBERS",
    "VOID_RUINS_MIN_MEMBERS",
    "VOID_RUINS_NODES",
    "VOID_RUINS_NODE_LABELS",
    "VOID_RUINS_PARTY_TYPE",
    "VOID_RUINS_REPEAT_REWARD",
    "VOID_RUINS_ROUTE_PERMISSION",
    "VOID_RUINS_STAMINA_COST",
    "VOID_RUINS_WEEKLY_LIMIT",
    "resolve_void_ruins_node",
]
