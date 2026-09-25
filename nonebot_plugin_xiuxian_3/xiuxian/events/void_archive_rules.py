"""Versioned rules for the v0.5 void archive and weekly fragments."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

CONTENT_VERSION = "content-0.5"
RULE_VERSION = "events-0.5.0"
ARCHIVE_EVENT_KEY = "event.archive_unlock"
ARCHIVE_ROUTE_KEY = "void.archive_ruins"
ARCHIVE_ENEMY_KEY = "enemy.archive_keeper"
ARCHIVE_WEEKLY_CAP = 1
ARCHIVE_CONVERSION_REWARD = {"item.void_crystal": 3}
ARCHIVE_REWARD = {"item.void_archive": 1}
TASK_REWARDS = {
    "task.archive_fragment.alpha": {"item.archive_fragment.alpha": 1},
    "task.archive_fragment.beta": {"item.archive_fragment.beta": 1},
    "task.archive_fragment.gamma": {"item.archive_fragment.gamma": 1},
}
TASK_TARGETS = {
    "task.archive_fragment.alpha": 2,
    "task.archive_fragment.beta": 1,
    "task.archive_fragment.gamma": 1,
}
TASKS = tuple(TASK_TARGETS)
TASK_VOID_MERIT = 20
UNLOCK_VOID_MERIT = 50


def archive_week_window(value: datetime) -> tuple[str, datetime, datetime]:
    """Use a UTC Monday window so weekly projections are deterministic."""

    current = value.astimezone(timezone.utc)
    start = (current - timedelta(days=current.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return start.date().isoformat(), start, start + timedelta(days=7)


def task_target(task_key: str) -> int:
    return TASK_TARGETS[task_key]


__all__ = [
    "ARCHIVE_CONVERSION_REWARD",
    "ARCHIVE_ENEMY_KEY",
    "ARCHIVE_EVENT_KEY",
    "ARCHIVE_REWARD",
    "ARCHIVE_ROUTE_KEY",
    "ARCHIVE_WEEKLY_CAP",
    "CONTENT_VERSION",
    "RULE_VERSION",
    "TASK_REWARDS",
    "TASK_TARGETS",
    "TASKS",
    "TASK_VOID_MERIT",
    "UNLOCK_VOID_MERIT",
    "archive_week_window",
    "task_target",
]
