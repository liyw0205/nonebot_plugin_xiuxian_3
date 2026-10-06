"""Stable keys and thresholds for breakthrough permits."""

from __future__ import annotations


from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

from ..content import ContentBundle, ContentError, bundled_content


GUIDANCE_CLAIM_OPERATION = "quest.claim_guidance_reward"


@dataclass(frozen=True, slots=True)
class GuidanceQuestDefinition:
    key: str
    name: str
    description: str
    reward_key: str
    operations: tuple[str, ...]
    result: dict[str, Any]


@dataclass(frozen=True, slots=True)
class DaoOriginTaskDefinition:
    key: str
    name: str
    status: str
    target: int
    reward: dict[str, int]
    codex_entry_key: str | None
    reward_labels: dict[str, str]
    codex_label: str | None

    def snapshot(self, season_id: str) -> dict[str, Any]:
        return {
            "key": self.key,
            "name": self.name,
            "status": self.status,
            "target": self.target,
            "reward": dict(self.reward),
            "codex_entry_key": self.codex_entry_key,
            "reward_labels": dict(self.reward_labels),
            "codex_label": self.codex_label,
            "season_id": season_id,
        }


def guidance_quest_definitions(
    content: ContentBundle | None = None,
) -> tuple[GuidanceQuestDefinition, ...]:
    bundle = content or bundled_content()
    rows = [
        row
        for row in bundle.list("quest", include_locked=False)
        if row.get("claim_group") == "guidance"
    ]
    definitions: list[GuidanceQuestDefinition] = []
    names: set[str] = set()
    for row in rows:
        key = row.get("key")
        name = row.get("name")
        description = row.get("desc")
        reward_key = row.get("reward_key")
        trigger = row.get("trigger")
        operations = trigger.get("operations") if isinstance(trigger, dict) else None
        result = trigger.get("result") if isinstance(trigger, dict) else None
        if (
            not isinstance(key, str)
            or not key.startswith("quest.")
            or not isinstance(name, str)
            or not name.strip()
            or name in names
            or not isinstance(description, str)
            or not isinstance(reward_key, str)
            or not reward_key.startswith("reward.")
            or row.get("claim_policy") != "once_per_player"
            or row.get("expires") is not False
            or not isinstance(operations, list)
            or not operations
            or any(not isinstance(operation, str) or not operation for operation in operations)
            or len(set(operations)) != len(operations)
            or not isinstance(result, dict)
            or not result
        ):
            raise ContentError(f"guidance quest definition is invalid: {key!r}")
        for field, expected in result.items():
            if not isinstance(field, str) or not field:
                raise ContentError(f"guidance quest result field is invalid: {key}")
            if isinstance(expected, dict):
                allowed = expected.get("one_of")
                if (
                    set(expected) != {"one_of"}
                    or not isinstance(allowed, list)
                    or not allowed
                    or any(not _is_json_scalar(value) for value in allowed)
                ):
                    raise ContentError(f"guidance quest result condition is invalid: {key}:{field}")
            elif not _is_json_scalar(expected):
                raise ContentError(f"guidance quest result value is invalid: {key}:{field}")
        names.add(name)
        definitions.append(
            GuidanceQuestDefinition(
                key=key,
                name=name.strip(),
                description=description.strip(),
                reward_key=reward_key,
                operations=tuple(operations),
                result=dict(result),
            )
        )
    if not definitions:
        raise ContentError("no active guidance quests are registered")
    return tuple(definitions)


def _is_json_scalar(value: Any) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


SOUL_QUEST = "quest.soul_transformation"
DOMAIN_COMMISSION = "quest.domain_material_commission"
ANCIENT_DOMAIN_LINE = "quest.ancient_domain_line"
CROSS_REALM_VICTORY = "event.cross_realm_victory"

VOID_QUEST = "quest.break_void"
VOID_WALL_TRIAL = "void_wall_trial"
VOID_ARCHIVE_DELIVERY = "void_archive_delivery"

DOMAIN_COMMISSION_TARGET = 3
ANCIENT_DOMAIN_TARGET = 3
VOID_TRIAL_TARGET = 3
VOID_TRIAL_WEEKLY_LIMIT = 5


def utc_week_bounds(value: datetime) -> tuple[date, date]:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    utc_date = value.astimezone(timezone.utc).date()
    start = utc_date - timedelta(days=utc_date.weekday())
    return start, start + timedelta(days=7)

DAO_UNION_QUEST = "quest.dao_union"
DAO_UNION_FRAGMENT_REWARD = 12
DAO_UNION_TRIBULATION_TOKEN_REWARD = 1
DAO_UNION_MAINLINE = "three_realm_mainline"
DAO_UNION_CHALLENGE = "cross_server_challenge"
DAO_UNION_WORK = "endgame_work"
DAO_UNION_MAINLINE_STORY_KEY = "story.mainline.dao_echoes"
DAO_UNION_MAINLINE_LANES = ("builder", "witness", "traveler")
DAO_UNION_MAINLINE_STAGE_KEYS = {
    lane: tuple(f"lane.{lane}.chapter.{chapter:02d}" for chapter in range(1, 11))
    for lane in DAO_UNION_MAINLINE_LANES
}
DAO_ORIGIN_GUARD = "task.dao_origin.guard"
DAO_ORIGIN_BUILD = "task.dao_origin.build"
DAO_ORIGIN_TEACH = "task.dao_origin.teach"
DAO_ORIGIN_TASKS = (DAO_ORIGIN_GUARD, DAO_ORIGIN_BUILD, DAO_ORIGIN_TEACH)
_DAO_ORIGIN_VALUE_REWARDS = frozenset(
    {"dao_fruit_progress", "ascension_merit", "world_merit"}
)
_DAO_ORIGIN_REQUIRED_REWARDS = _DAO_ORIGIN_VALUE_REWARDS | {"item.tribulation_token"}


def dao_origin_task_definition(
    task_key: str, content: ContentBundle | None = None
) -> DaoOriginTaskDefinition:
    if task_key not in DAO_ORIGIN_TASKS:
        raise ContentError(f"unknown dao-origin task: {task_key}")
    bundle = content or bundled_content()
    row = bundle.get("quest", task_key, include_locked=False)
    if row is None:
        raise ContentError(f"dao-origin task is missing: {task_key}")
    name = row.get("name")
    status = row.get("status")
    target = row.get("target")
    codex_entry_key = row.get("codex_entry_key")
    if (
        not isinstance(name, str)
        or not name.strip()
        or not isinstance(status, str)
        or not status.strip()
        or isinstance(target, bool)
        or not isinstance(target, int)
        or target <= 0
    ):
        raise ContentError(f"dao-origin task definition is invalid: {task_key}")
    reward = _dao_origin_reward_map(task_key, row.get("reward"), bundle)
    if row.get("claim_policy") != "once_per_season" or row.get("expires") is not False:
        raise ContentError(f"dao-origin task claim policy is invalid: {task_key}")
    if task_key == DAO_ORIGIN_BUILD:
        if not isinstance(codex_entry_key, str) or not codex_entry_key.strip():
            raise ContentError(f"dao-origin task {task_key} requires codex_entry_key")
        dao_origin_codex_entry_key(task_key, bundle)
    elif codex_entry_key is not None:
        raise ContentError(f"dao-origin task {task_key} cannot reference a codex entry")
    return DaoOriginTaskDefinition(
        key=task_key,
        name=name.strip(),
        status=status,
        target=target,
        reward=reward,
        codex_entry_key=codex_entry_key,
        reward_labels={key: bundle.label("item", key) for key in reward if key.startswith("item.")},
        codex_label=bundle.label("codex_entry", codex_entry_key) if codex_entry_key else None,
    )


def parse_dao_origin_task_snapshot(
    task_key: str, value: Any
) -> dict[str, Any]:
    expected = {
        "key", "name", "status", "target", "reward", "codex_entry_key",
        "season_id", "reward_labels", "codex_label",
    }
    if (
        task_key not in DAO_ORIGIN_TASKS
        or not isinstance(value, dict)
        or set(value) != expected
        or value.get("key") != task_key
    ):
        raise ContentError(f"dao-origin task snapshot is invalid: {task_key}")
    name = value.get("name")
    status = value.get("status")
    target = value.get("target")
    season_id = value.get("season_id")
    codex_entry_key = value.get("codex_entry_key")
    if (
        not isinstance(name, str)
        or not name.strip()
        or not isinstance(status, str)
        or status not in {"active", "open"}
        or isinstance(target, bool)
        or not isinstance(target, int)
        or target <= 0
        or not isinstance(season_id, str)
        or not season_id.strip()
        or (task_key == DAO_ORIGIN_BUILD and (not isinstance(codex_entry_key, str) or not codex_entry_key))
        or (task_key != DAO_ORIGIN_BUILD and codex_entry_key is not None)
    ):
        raise ContentError(f"dao-origin task snapshot is invalid: {task_key}")
    reward = _dao_origin_reward_map(task_key, value.get("reward"), None)
    reward_labels = value["reward_labels"]
    if (
        not isinstance(reward_labels, dict)
        or set(reward_labels) != {key for key in reward if key.startswith("item.")}
        or any(not isinstance(label, str) or not label.strip() for label in reward_labels.values())
        or (codex_entry_key is not None and (
            not isinstance(value["codex_label"], str) or not value["codex_label"].strip()
        ))
        or (codex_entry_key is None and value["codex_label"] is not None)
    ):
        raise ContentError(f"dao-origin task snapshot labels are invalid: {task_key}")
    return {
        "key": task_key,
        "name": name.strip(),
        "status": status,
        "target": target,
        "reward": reward,
        "codex_entry_key": codex_entry_key,
        "reward_labels": dict(reward_labels),
        "codex_label": value["codex_label"],
        "season_id": season_id,
    }


def dao_origin_task_snapshot_from_event(
    task_key: str, payload: Any
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ContentError(f"dao-origin task event is invalid: {task_key}")
    snapshot = parse_dao_origin_task_snapshot(task_key, payload.get("task_snapshot"))
    if payload.get("season_id") != snapshot["season_id"]:
        raise ContentError(f"dao-origin task event season differs from its snapshot: {task_key}")
    return snapshot


def _dao_origin_reward_map(
    task_key: str, value: Any, content: ContentBundle | None
) -> dict[str, int]:
    if not isinstance(value, dict) or not _DAO_ORIGIN_REQUIRED_REWARDS.issubset(value):
        raise ContentError(f"dao-origin task reward is incomplete: {task_key}")
    result: dict[str, int] = {}
    for key, amount in value.items():
        if (
            not isinstance(key, str)
            or (key not in _DAO_ORIGIN_VALUE_REWARDS and not key.startswith("item."))
            or key == "item."
            or isinstance(amount, bool)
            or not isinstance(amount, int)
            or amount < 0
        ):
            raise ContentError(f"dao-origin task reward is invalid: {task_key}:{key}")
        if key.startswith("item.") and content is not None and not content.has(
            "item", key, include_locked=False
        ):
            raise ContentError(f"dao-origin task reward references an inactive item: {task_key}:{key}")
        result[key] = amount
    return result


def dao_origin_codex_entry_key(
    task_key: str, content: ContentBundle | None = None
) -> str | None:
    """Resolve the optional service discovery declared by an origin task."""

    if task_key != DAO_ORIGIN_BUILD:
        return None
    bundle = content or bundled_content()
    task = bundle.get("quest", task_key, include_locked=False)
    entry_key = task.get("codex_entry_key") if task is not None else None
    if not isinstance(entry_key, str) or not entry_key.strip():
        raise ContentError(f"dao-origin task {task_key} requires codex_entry_key")
    entry = bundle.get("codex_entry", entry_key, include_locked=False)
    if entry is None or entry.get("status") != "active" or entry.get("category") != "service":
        raise ContentError(
            f"dao-origin task {task_key} references an inactive service codex entry: {entry_key}"
        )
    return entry_key


def realm_rank(realm_key: str) -> int:
    return {
        "mortal": 0,
        "qi_sensing": 1,
        "qi_gathering": 2,
        "foundation": 3,
        "golden_core": 4,
        "nascent_soul": 5,
        "soul_transformation": 6,
        "void_refining": 7,
        "dao_union": 8,
        "tribulation": 9,
    }.get(realm_key, -1)


def meets_realm(realm_key: str, layer: int, required_realm: str, required_layer: int = 1) -> bool:
    return (realm_rank(realm_key), int(layer)) >= (realm_rank(required_realm), required_layer)


__all__ = [
    "ANCIENT_DOMAIN_LINE",
    "ANCIENT_DOMAIN_TARGET",
    "CROSS_REALM_VICTORY",
    "DOMAIN_COMMISSION",
    "DOMAIN_COMMISSION_TARGET",
    "SOUL_QUEST",
    "VOID_ARCHIVE_DELIVERY",
    "VOID_QUEST",
    "VOID_TRIAL_TARGET",
    "VOID_TRIAL_WEEKLY_LIMIT",
    "VOID_WALL_TRIAL",
    "DAO_ORIGIN_BUILD",
    "DAO_ORIGIN_GUARD",
    "DAO_ORIGIN_TASKS",
    "DAO_ORIGIN_TEACH",
    "dao_origin_codex_entry_key",
    "dao_origin_task_definition",
    "dao_origin_task_snapshot_from_event",
    "DAO_UNION_CHALLENGE",
    "DAO_UNION_FRAGMENT_REWARD",
    "DAO_UNION_MAINLINE",
    "DAO_UNION_MAINLINE_LANES",
    "DAO_UNION_MAINLINE_STAGE_KEYS",
    "DAO_UNION_MAINLINE_STORY_KEY",
    "DAO_UNION_QUEST",
    "DAO_UNION_TRIBULATION_TOKEN_REWARD",
    "DAO_UNION_WORK",
    "GUIDANCE_CLAIM_OPERATION",
    "GuidanceQuestDefinition",
    "DaoOriginTaskDefinition",
    "guidance_quest_definitions",
    "parse_dao_origin_task_snapshot",
    "meets_realm",
    "utc_week_bounds",
]
