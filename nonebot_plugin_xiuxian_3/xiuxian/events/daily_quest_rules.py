"""Content-backed rules for a player's daily cultivation tasks."""

from __future__ import annotations

from dataclasses import dataclass
import random
from typing import Any

from ..content import ContentBundle, ContentError, bundled_content
from ..rewards.rules import RewardGrant, local_reputation_maximum, reward_definition


@dataclass(frozen=True, slots=True)
class DailyTaskSource:
    operation: str
    result: dict[str, Any]
    required_fields: tuple[str, ...]
    battle_types: tuple[str, ...]

    def snapshot(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "operation": self.operation,
            "result": self.result,
            "required_fields": list(self.required_fields),
        }
        if self.battle_types:
            result["battle_types"] = list(self.battle_types)
        return result


@dataclass(frozen=True, slots=True)
class DailyTaskDefinition:
    key: str
    name: str
    description: str
    group: str
    weight: int
    target: int
    sources: tuple[DailyTaskSource, ...]

    def snapshot(self) -> dict[str, Any]:
        return {
            "task_key": self.key,
            "name": self.name,
            "description": self.description,
            "group": self.group,
            "target": self.target,
            "sources": [source.snapshot() for source in self.sources],
        }


@dataclass(frozen=True, slots=True)
class DailyQuestRules:
    timezone: str
    claim_window_seconds: int
    completion_threshold: int
    selection: tuple[tuple[str, int], ...]
    reward: RewardGrant
    local_reputation_maximums: dict[str, int]

    @property
    def task_count(self) -> int:
        return sum(count for _, count in self.selection)


def daily_quest_rules(content: ContentBundle | None = None) -> DailyQuestRules:
    bundle = content or bundled_content()
    try:
        event = bundle.require("event", "event.daily_tasks", include_locked=False)
        raw = event.get("daily_tasks")
        if not isinstance(raw, dict) or set(raw) != {
            "timezone", "claim_window_seconds", "completion_threshold", "selection", "reward_key"
        }:
            raise ContentError("daily task event fields are invalid")
        timezone_name = _string(raw.get("timezone"), "event.daily_tasks.timezone")
        if timezone_name != "UTC":
            raise ContentError("daily task timezone must be UTC")
        claim_window = _positive_int(raw.get("claim_window_seconds"), "event.daily_tasks.claim_window_seconds")
        threshold = _positive_int(raw.get("completion_threshold"), "event.daily_tasks.completion_threshold")
        selection_raw = raw.get("selection")
        if not isinstance(selection_raw, list) or not selection_raw:
            raise ContentError("daily task selection must be a non-empty list")
        selection: list[tuple[str, int]] = []
        groups: set[str] = set()
        for index, record in enumerate(selection_raw):
            if not isinstance(record, dict) or set(record) != {"group", "count"}:
                raise ContentError(f"daily task selection {index} is invalid")
            group = _string(record.get("group"), f"event.daily_tasks.selection[{index}].group")
            count = _positive_int(record.get("count"), f"event.daily_tasks.selection[{index}].count")
            if group in groups:
                raise ContentError(f"daily task group is selected more than once: {group}")
            groups.add(group)
            selection.append((group, count))
        reward_key = _string(raw.get("reward_key"), "event.daily_tasks.reward_key")
        reward = reward_definition(reward_key, bundle, operation="event.claim_daily_tasks")
        local_maximums = {
            reputation_key: local_reputation_maximum(reputation_key, bundle)
            for reputation_key in reward.local_reputation
        }
        definitions = daily_task_definitions(bundle)
        if threshold > sum(count for _, count in selection):
            raise ContentError("daily task completion threshold exceeds the selected task count")
        for group, count in selection:
            if sum(definition.group == group for definition in definitions) < count:
                raise ContentError(f"daily task group {group} has too few candidates")
        return DailyQuestRules(
            timezone=timezone_name,
            claim_window_seconds=claim_window,
            completion_threshold=threshold,
            selection=tuple(selection),
            reward=reward,
            local_reputation_maximums=local_maximums,
        )
    except KeyError as exc:
        raise ContentError(f"daily task content is incomplete: {exc}") from exc


def daily_task_definitions(content: ContentBundle | None = None) -> tuple[DailyTaskDefinition, ...]:
    bundle = content or bundled_content()
    definitions: list[DailyTaskDefinition] = []
    names: set[str] = set()
    operation_owners: dict[str, str] = {}
    for row in bundle.list("quest", include_locked=False):
        if row.get("claim_group") != "daily":
            continue
        key = _string(row.get("key"), "daily task key")
        name = _string(row.get("name"), f"{key}.name")
        description = _string(row.get("desc"), f"{key}.desc")
        if not key.startswith("task.daily.") or name in names:
            raise ContentError(f"daily task key or name is invalid: {key}")
        raw = row.get("daily_task")
        if not isinstance(raw, dict) or set(raw) != {"group", "weight", "target", "sources"}:
            raise ContentError(f"daily task fields are invalid: {key}")
        group = _string(raw.get("group"), f"{key}.group")
        weight = _positive_int(raw.get("weight"), f"{key}.weight")
        target = _positive_int(raw.get("target"), f"{key}.target")
        raw_sources = raw.get("sources")
        if not isinstance(raw_sources, list) or not raw_sources:
            raise ContentError(f"daily task sources are invalid: {key}")
        sources: list[DailyTaskSource] = []
        for index, raw_source in enumerate(raw_sources):
            label = f"{key}.sources[{index}]"
            if (
                not isinstance(raw_source, dict)
                or not {"operation", "result", "required_fields"} <= set(raw_source)
                or set(raw_source)
                - {"operation", "result", "required_fields", "battle_types"}
            ):
                raise ContentError(f"daily task source fields are invalid: {label}")
            operation = _string(raw_source.get("operation"), f"{label}.operation")
            owner = operation_owners.get(operation)
            if owner is not None and owner != key:
                raise ContentError(f"daily source operation belongs to multiple tasks: {operation}")
            operation_owners[operation] = key
            result = raw_source.get("result")
            if not isinstance(result, dict):
                raise ContentError(f"daily task source result must be an object: {label}")
            for field, expected in result.items():
                if not isinstance(field, str) or not field or not _valid_condition(expected):
                    raise ContentError(f"daily task source result condition is invalid: {label}.{field}")
            required = raw_source.get("required_fields")
            if (
                not isinstance(required, list)
                or not required
                or any(not isinstance(value, str) or not value for value in required)
                or len(set(required)) != len(required)
            ):
                raise ContentError(f"daily task source required_fields are invalid: {label}")
            battle_types_raw = raw_source.get("battle_types", [])
            if not isinstance(battle_types_raw, list) or any(not isinstance(value, str) or not value.startswith("pve.") for value in battle_types_raw) or len(set(battle_types_raw)) != len(battle_types_raw):
                raise ContentError(f"daily task source battle_types are invalid: {label}")
            if battle_types_raw and operation != "battle.resolve":
                raise ContentError(f"daily task battle_types require battle.resolve: {label}")
            sources.append(DailyTaskSource(operation, dict(result), tuple(required), tuple(battle_types_raw)))
        definitions.append(DailyTaskDefinition(key, name, description, group, weight, target, tuple(sources)))
        names.add(name)
    if not definitions:
        raise ContentError("no active daily tasks are registered")
    return tuple(definitions)


def select_daily_tasks(
    rules: DailyQuestRules,
    definitions: tuple[DailyTaskDefinition, ...],
    seed: str,
) -> tuple[DailyTaskDefinition, ...]:
    rng = random.Random(seed)
    selected: list[DailyTaskDefinition] = []
    for group, count in rules.selection:
        candidates = [definition for definition in definitions if definition.group == group]
        for _ in range(count):
            total = sum(candidate.weight for candidate in candidates)
            roll = rng.randrange(total)
            for index, candidate in enumerate(candidates):
                roll -= candidate.weight
                if roll < 0:
                    selected.append(candidate)
                    candidates.pop(index)
                    break
    return tuple(selected)


def source_matches(source: DailyTaskSource, operation: str, result: dict[str, Any]) -> bool:
    if source.operation != operation or any(field not in result for field in source.required_fields):
        return False
    for field, expected in source.result.items():
        actual = result.get(field)
        if isinstance(expected, dict):
            if actual not in expected["one_of"]:
                return False
        elif actual != expected:
            return False
    return True


def _valid_condition(value: Any) -> bool:
    if isinstance(value, dict):
        values = value.get("one_of")
        return set(value) == {"one_of"} and isinstance(values, list) and bool(values) and all(
            item is None or isinstance(item, (str, int, float, bool)) for item in values
        )
    return value is None or isinstance(value, (str, int, float, bool))


def _positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ContentError(f"{field} must be a positive integer")
    return value


def _string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContentError(f"{field} must be a non-empty string")
    return value.strip()


__all__ = [
    "DailyQuestRules",
    "DailyTaskDefinition",
    "DailyTaskSource",
    "daily_quest_rules",
    "daily_task_definitions",
    "select_daily_tasks",
    "source_matches",
]
