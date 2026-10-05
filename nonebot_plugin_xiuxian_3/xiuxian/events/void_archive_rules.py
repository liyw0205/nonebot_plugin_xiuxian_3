"""Content-backed rules for the void archive and weekly fragments."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from ..content import ContentBundle, ContentError, bundled_content
from ..rewards.rules import RewardGrant, reward_definition

ARCHIVE_EVENT_KEY = "event.archive_unlock"
ARCHIVE_ROUTE_KEY = "void.archive_ruins"
ARCHIVE_ENEMY_KEY = "enemy.archive_keeper"


@dataclass(frozen=True, slots=True)
class ArchiveTaskDefinition:
    key: str
    name: str
    target: int
    reward_key: str
    reward: RewardGrant


@dataclass(frozen=True, slots=True)
class VoidArchiveDefinition:
    event_key: str
    route_key: str
    enemy_key: str
    weekly_cap: int
    unlock_duration_seconds: int
    first_reward_key: str
    repeat_reward_key: str
    unlock_reward_key: str
    first_reward: RewardGrant
    repeat_reward: RewardGrant
    unlock_reward: RewardGrant
    tasks: tuple[ArchiveTaskDefinition, ...]


def void_archive_definition(content: ContentBundle | None = None) -> VoidArchiveDefinition:
    """Parse the complete archive contract without keeping a parallel table."""

    bundle = content or bundled_content()
    try:
        row = bundle.require("event", ARCHIVE_EVENT_KEY, include_locked=False)
    except KeyError as exc:
        raise ContentError(f"archive event is not active: {ARCHIVE_EVENT_KEY}") from exc
    if not isinstance(row.get("name"), str) or not row["name"].strip():
        raise ContentError(f"archive event {ARCHIVE_EVENT_KEY} requires a name")
    if not isinstance(row.get("desc"), str) or not row["desc"].strip():
        raise ContentError(f"archive event {ARCHIVE_EVENT_KEY} requires a description")
    archive = row.get("archive")
    if not isinstance(archive, dict):
        raise ContentError(f"archive event {ARCHIVE_EVENT_KEY} requires archive settings")
    expected_fields = {
        "unlock_duration_seconds", "route_key", "enemy_key", "weekly_cap",
        "first_reward_key", "repeat_reward_key", "unlock_reward_key", "tasks",
    }
    if set(archive) != expected_fields:
        raise ContentError("archive settings have missing or unknown fields")
    route_key = archive.get("route_key")
    enemy_key = archive.get("enemy_key")
    weekly_cap = archive.get("weekly_cap")
    if not isinstance(route_key, str) or not route_key:
        raise ContentError("archive route_key must be a non-empty string")
    if not isinstance(enemy_key, str) or not enemy_key:
        raise ContentError("archive enemy_key must be a non-empty string")
    if not bundle.has("location", route_key, include_locked=False):
        raise ContentError(f"archive route references inactive location: {route_key}")
    if isinstance(weekly_cap, bool) or not isinstance(weekly_cap, int) or weekly_cap <= 0:
        raise ContentError("archive weekly_cap must be a positive integer")
    unlock_duration = archive.get("unlock_duration_seconds")
    if isinstance(unlock_duration, bool) or not isinstance(unlock_duration, int) or unlock_duration <= 0:
        raise ContentError("archive unlock_duration_seconds must be a positive integer")

    first_reward_key = _required_key(archive, "first_reward_key")
    repeat_reward_key = _required_key(archive, "repeat_reward_key")
    unlock_reward_key = _required_key(archive, "unlock_reward_key")
    first_reward = reward_definition(first_reward_key, bundle, operation="event.archive_ruins")
    repeat_reward = reward_definition(repeat_reward_key, bundle, operation="event.archive_ruins")
    unlock_reward = reward_definition(unlock_reward_key, bundle, operation="event.archive_unlock")

    raw_tasks = archive.get("tasks")
    if not isinstance(raw_tasks, list):
        raise ContentError("archive tasks must be a list")
    tasks: list[ArchiveTaskDefinition] = []
    seen: set[str] = set()
    for index, raw_task in enumerate(raw_tasks):
        if not isinstance(raw_task, dict):
            raise ContentError(f"archive task {index} must be an object")
        if set(raw_task) != {"key", "name", "target", "reward_key"}:
            raise ContentError(f"archive task {index} has missing or unknown fields")
        task_key = raw_task.get("key")
        task_name = raw_task.get("name")
        target = raw_task.get("target")
        reward_key = raw_task.get("reward_key")
        if not isinstance(task_key, str) or not task_key or task_key in seen:
            raise ContentError(f"archive task {index} has a duplicate or invalid key")
        if not isinstance(task_name, str) or not task_name.strip():
            raise ContentError(f"archive task {task_key} requires a name")
        if not task_key.startswith("task.archive_fragment."):
            raise ContentError(f"archive task {task_key} is outside the archive namespace")
        if isinstance(target, bool) or not isinstance(target, int) or target <= 0:
            raise ContentError(f"archive task {task_key} target must be positive")
        if not isinstance(reward_key, str) or not reward_key:
            raise ContentError(f"archive task {task_key} requires reward_key")
        reward = reward_definition(reward_key, bundle, operation=f"{task_key}.claim")
        seen.add(task_key)
        tasks.append(ArchiveTaskDefinition(task_key, task_name.strip(), target, reward_key, reward))
    if {task.key for task in tasks} != {
        "task.archive_fragment.alpha",
        "task.archive_fragment.beta",
        "task.archive_fragment.gamma",
    }:
        raise ContentError("archive tasks must define alpha, beta and gamma")
    return VoidArchiveDefinition(
        event_key=ARCHIVE_EVENT_KEY,
        route_key=route_key,
        enemy_key=enemy_key,
        weekly_cap=weekly_cap,
        unlock_duration_seconds=unlock_duration,
        first_reward_key=first_reward_key,
        repeat_reward_key=repeat_reward_key,
        unlock_reward_key=unlock_reward_key,
        first_reward=first_reward,
        repeat_reward=repeat_reward,
        unlock_reward=unlock_reward,
        tasks=tuple(tasks),
    )


def archive_task_keys(content: ContentBundle | None = None) -> tuple[str, ...]:
    return tuple(task.key for task in void_archive_definition(content).tasks)


def archive_task_definition(
    task_key: str, content: ContentBundle | None = None
) -> ArchiveTaskDefinition:
    definition = void_archive_definition(content)
    for task in definition.tasks:
        if task.key == task_key:
            return task
    raise KeyError(task_key)


def resolve_archive_task(
    value: str, content: ContentBundle | None = None
) -> ArchiveTaskDefinition:
    """Resolve a task by its stable key or the name shown to players."""

    normalized = (value or "").strip()
    if not normalized:
        raise KeyError(value)
    definition = void_archive_definition(content)
    matches = [
        task for task in definition.tasks
        if normalized == task.key or normalized == task.name
    ]
    if len(matches) != 1:
        raise KeyError(value)
    return matches[0]


def archive_week_window(value: datetime) -> tuple[str, datetime, datetime]:
    """Use a UTC Monday window so weekly projections are deterministic."""

    current = value.astimezone(timezone.utc)
    start = (current - timedelta(days=current.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return start.date().isoformat(), start, start + timedelta(days=7)


def _required_key(settings: dict[str, Any], field: str) -> str:
    value = settings.get(field)
    if not isinstance(value, str) or not value:
        raise ContentError(f"archive {field} must be a non-empty string")
    return value


__all__ = [
    "ARCHIVE_ENEMY_KEY",
    "ARCHIVE_EVENT_KEY",
    "ARCHIVE_ROUTE_KEY",
    "ArchiveTaskDefinition",
    "VoidArchiveDefinition",
    "archive_task_definition",
    "archive_task_keys",
    "archive_week_window",
    "resolve_archive_task",
    "void_archive_definition",
]
