"""Contract for the time-fort party secret realm."""

from __future__ import annotations


TIME_FORT_KEY = "instance.secret_realm.time_fort"
TIME_FORT_LOCATION = "void.archive_ruins"
TIME_FORT_PARTY_TYPE = "secret_realm_time_fort"
TIME_FORT_STAMINA_COST = 40
TIME_FORT_MIN_MEMBERS = 2
TIME_FORT_MAX_MEMBERS = 5
TIME_FORT_WEEKLY_LIMIT = 1
TIME_FORT_EXPIRY_SECONDS = 60 * 60
TIME_FORT_OPEN = True
TIME_FORT_PERMISSION = "access.void.time_fort"
TIME_FORT_STORY_FLAG = "story.mainline.void_archive.time_fort"
TIME_FORT_FIRST_REWARD = {"item.mat.array_sand": 2}
TIME_FORT_REPEAT_REWARD = {"item.mat.array_sand": 1}
TIME_FORT_STORM_INTERVAL = 3
TIME_FORT_STORM_DAMAGE_BP = 500
TIME_FORT_ENEMY = "enemy.time_fort_keeper"

TIME_FORT_NODES = (
    "fort_gate",
    "clock_gallery",
    "time_storm",
    "broken_hourglass",
    "time_keeper",
    "chronicle_exit",
)

TIME_FORT_NODE_LABELS = {
    "fort_gate": "堡垒门庭",
    "clock_gallery": "星时回廊",
    "time_storm": "时间风暴",
    "broken_hourglass": "残破沙漏",
    "time_keeper": "守时者",
    "chronicle_exit": "编年出口",
}

TIME_FORT_NODE_ALIASES = {
    **{key: key for key in TIME_FORT_NODES},
    **{label: key for key, label in TIME_FORT_NODE_LABELS.items()},
}


def resolve_time_fort_node(value: str) -> str | None:
    return TIME_FORT_NODE_ALIASES.get(value.strip())


__all__ = [
    "TIME_FORT_ENEMY",
    "TIME_FORT_EXPIRY_SECONDS",
    "TIME_FORT_FIRST_REWARD",
    "TIME_FORT_KEY",
    "TIME_FORT_LOCATION",
    "TIME_FORT_MAX_MEMBERS",
    "TIME_FORT_MIN_MEMBERS",
    "TIME_FORT_NODE_LABELS",
    "TIME_FORT_NODES",
    "TIME_FORT_OPEN",
    "TIME_FORT_PARTY_TYPE",
    "TIME_FORT_PERMISSION",
    "TIME_FORT_REPEAT_REWARD",
    "TIME_FORT_STAMINA_COST",
    "TIME_FORT_STORM_DAMAGE_BP",
    "TIME_FORT_STORM_INTERVAL",
    "TIME_FORT_STORY_FLAG",
    "TIME_FORT_WEEKLY_LIMIT",
    "resolve_time_fort_node",
]
