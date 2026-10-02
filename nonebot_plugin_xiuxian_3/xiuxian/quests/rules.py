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
DAO_ORIGIN_TARGET = 3
# These values close the documented 1,000/1,000 endgame resource path.
DAO_ORIGIN_REWARDS = {
    DAO_ORIGIN_GUARD: {"dao_fruit_progress": 150, "ascension_merit": 150, "item.tribulation_token": 1},
    DAO_ORIGIN_BUILD: {"dao_fruit_progress": 160, "ascension_merit": 150, "item.tribulation_token": 1},
    DAO_ORIGIN_TEACH: {"dao_fruit_progress": 160, "ascension_merit": 150, "item.tribulation_token": 1},
}
DAO_ORIGIN_WORLD_MERIT = {
    DAO_ORIGIN_GUARD: 300,
    DAO_ORIGIN_BUILD: 300,
    DAO_ORIGIN_TEACH: 400,
}


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
    "DAO_ORIGIN_REWARDS",
    "DAO_ORIGIN_TARGET",
    "DAO_ORIGIN_TASKS",
    "DAO_ORIGIN_TEACH",
    "DAO_ORIGIN_WORLD_MERIT",
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
    "guidance_quest_definitions",
    "meets_realm",
    "utc_week_bounds",
]
