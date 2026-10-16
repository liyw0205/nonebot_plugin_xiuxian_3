"""Content-backed rules for every open floor of the void spire tower."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from ..content import ContentBundle, ContentError, bundled_content


TOWER_KEY = "tower.void_spire"
# Kept as compatibility exports for callers that display the established
# route bands.  Floor lookup and admission now use the content segments.
LOWER_ROUTE_END = 30
MID_ROUTE_END = 60
MAX_FLOOR = 90
WEEKLY_ATTEMPT_LIMIT = 2
UPPER_WEEKLY_ATTEMPT_LIMIT = 1
STAMINA_COST = 20
REQUIRED_REALM = "void_refining"
REQUIRED_LAYER = 1
UPPER_REQUIRED_REALM = "dao_union"
SUPPLY_REPUTATION_KEY = "local.void_supply"
SUPPLY_REPUTATION_REQUIRED = 600
DAO_SERVICE_REPUTATION_KEY = "local.dao_service"
DAO_SERVICE_REPUTATION_REQUIRED = 700


@dataclass(frozen=True, slots=True)
class VoidSpireFloorDefinition:
    floor_no: int
    required_realm: str
    required_layer: int
    stamina_cost: int
    weekly_limit: int
    route_no: int
    route_key: str
    enemy_key: str
    boss: bool
    title_key: str | None = None
    route_codex_key: str | None = None
    reputation_key: str = SUPPLY_REPUTATION_KEY
    reputation_required: int = SUPPLY_REPUTATION_REQUIRED


_SEGMENT_FIELDS = frozenset(
    {
        "key",
        "name",
        "desc",
        "status",
        "floor_min",
        "floor_max",
        "required_realm",
        "required_layer",
        "stamina_cost",
        "weekly_limit",
        "reputation_key",
        "reputation_required",
        "route_no",
        "route_key",
        "route_codex_key",
        "enemy_ranges",
        "boss_floors",
        "first_clear_reward",
        "boss_reward",
        "repeat_reward",
        "story_codex_key",
        "title_key",
    }
)


def _positive_int(value: Any, field: str, key: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ContentError(f"void spire {key} {field} must be a positive integer")
    return int(value)


def _reward_map(value: Any, *, field: str, key: str, bundle: ContentBundle) -> dict[str, int]:
    if not isinstance(value, dict):
        raise ContentError(f"void spire {key} {field} must be an object")
    rewards: dict[str, int] = {}
    for raw_key, raw_amount in value.items():
        if not isinstance(raw_key, str) or not raw_key.strip():
            raise ContentError(f"void spire {key} {field} has an invalid reward key")
        reward_key = raw_key
        amount = _positive_int(raw_amount, f"{field}.{reward_key}", key)
        if reward_key == "spirit_stones" or reward_key.startswith("local."):
            rewards[reward_key] = amount
        elif reward_key.startswith("item."):
            try:
                bundle.require("item", reward_key, include_locked=False)
            except KeyError as exc:
                raise ContentError(
                    f"void spire {key} {field} references unknown item {reward_key}"
                ) from exc
            rewards[reward_key] = amount
        else:
            raise ContentError(f"void spire {key} {field} has unsupported reward {reward_key}")
    return rewards


def _segment_records(content: ContentBundle | None = None) -> tuple[dict[str, Any], ...]:
    bundle = content or bundled_content()
    rows = bundle.list("void_spire", include_locked=False)
    if not rows:
        raise ContentError("void spire has no active route segments")
    normalized: list[dict[str, Any]] = []
    seen_routes: set[str] = set()
    seen_route_numbers: set[int] = set()
    for row in rows:
        key = str(row.get("key"))
        if set(row) != _SEGMENT_FIELDS:
            raise ContentError(f"void spire segment {key} has missing or unknown fields")
        if row.get("status") != "active":
            raise ContentError(f"void spire segment {key} is not active")
        for field in ("name", "desc"):
            if not isinstance(row[field], str) or not row[field].strip():
                raise ContentError(f"void spire segment {key} requires {field}")
        floor_min = _positive_int(row["floor_min"], "floor_min", key)
        floor_max = _positive_int(row["floor_max"], "floor_max", key)
        if floor_max < floor_min or floor_max > MAX_FLOOR:
            raise ContentError(f"void spire segment {key} has an invalid floor range")
        realm = row["required_realm"]
        if not isinstance(realm, str) or not realm.strip():
            raise ContentError(f"void spire segment {key} requires a realm")
        try:
            bundle.require("realm", realm, include_locked=False)
        except KeyError as exc:
            raise ContentError(f"void spire segment {key} references unknown realm {realm}") from exc
        required_layer = _positive_int(row["required_layer"], "required_layer", key)
        stamina_cost = _positive_int(row["stamina_cost"], "stamina_cost", key)
        weekly_limit = _positive_int(row["weekly_limit"], "weekly_limit", key)
        reputation_key = row["reputation_key"]
        if not isinstance(reputation_key, str) or not reputation_key.startswith("local."):
            raise ContentError(f"void spire segment {key} has an invalid reputation key")
        reputation_required = _positive_int(row["reputation_required"], "reputation_required", key)
        route_no = _positive_int(row["route_no"], "route_no", key)
        route_key = row["route_key"]
        route_codex_key = row["route_codex_key"]
        if not isinstance(route_key, str) or not route_key.strip() or route_key in seen_routes:
            raise ContentError(f"void spire segment {key} has a duplicate or invalid route key")
        if route_no in seen_route_numbers:
            raise ContentError(f"void spire segment {key} has a duplicate route number")
        if not isinstance(route_codex_key, str) or not bundle.has("codex_entry", route_codex_key, include_locked=False):
            raise ContentError(f"void spire segment {key} has an invalid route codex key")
        seen_routes.add(route_key)
        seen_route_numbers.add(route_no)
        ranges = row["enemy_ranges"]
        if not isinstance(ranges, list) or not ranges:
            raise ContentError(f"void spire segment {key} has no enemy ranges")
        normalized_ranges: list[dict[str, Any]] = []
        previous = floor_min - 1
        for enemy_range in ranges:
            if not isinstance(enemy_range, dict) or set(enemy_range) != {"max_floor", "enemy_key"}:
                raise ContentError(f"void spire segment {key} has an invalid enemy range")
            max_floor = enemy_range["max_floor"]
            enemy_key = enemy_range["enemy_key"]
            if isinstance(max_floor, bool) or not isinstance(max_floor, int) or max_floor <= previous or max_floor > floor_max:
                raise ContentError(f"void spire segment {key} has unordered enemy ranges")
            if not isinstance(enemy_key, str) or not enemy_key.strip():
                raise ContentError(f"void spire segment {key} has an invalid enemy range")
            try:
                bundle.require("enemy", enemy_key, include_locked=False)
            except KeyError as exc:
                raise ContentError(f"void spire segment {key} references unknown enemy {enemy_key}") from exc
            normalized_ranges.append({"max_floor": max_floor, "enemy_key": enemy_key})
            previous = max_floor
        if previous != floor_max:
            raise ContentError(f"void spire segment {key} enemy ranges do not cover its floor range")
        boss_floors = row["boss_floors"]
        if not isinstance(boss_floors, list) or not boss_floors:
            raise ContentError(f"void spire segment {key} has invalid boss floors")
        if any(isinstance(value, bool) or not isinstance(value, int) for value in boss_floors):
            raise ContentError(f"void spire segment {key} has invalid boss floors")
        if len(set(boss_floors)) != len(boss_floors):
            raise ContentError(f"void spire segment {key} has invalid boss floors")
        for boss_floor in boss_floors:
            if isinstance(boss_floor, bool) or not isinstance(boss_floor, int) or not floor_min <= boss_floor <= floor_max:
                raise ContentError(f"void spire segment {key} has a boss floor outside its range")
        boss_range_floors = {
            item["max_floor"] for item in normalized_ranges if item["enemy_key"].endswith("_boss")
        }
        if boss_range_floors != set(boss_floors):
            raise ContentError(f"void spire segment {key} has invalid boss floors")
        rewards = {
            field: _reward_map(row[field], field=field, key=key, bundle=bundle)
            for field in ("first_clear_reward", "boss_reward", "repeat_reward")
        }
        story_codex_key = row["story_codex_key"]
        if story_codex_key is not None and (not isinstance(story_codex_key, str) or not bundle.has("codex_entry", story_codex_key, include_locked=False)):
            raise ContentError(f"void spire segment {key} has an invalid story codex key")
        title_key = row["title_key"]
        if title_key is not None:
            if not isinstance(title_key, str) or not title_key.strip():
                raise ContentError(f"void spire segment {key} has an invalid title key")
            from ..routine.rules import HONOR_TITLES

            if title_key not in {title.key for title in HONOR_TITLES}:
                raise ContentError(f"void spire segment {key} references unknown title {title_key}")
        normalized.append(
            {
                "floor_min": floor_min,
                "floor_max": floor_max,
                "required_realm": realm,
                "required_layer": required_layer,
                "stamina_cost": stamina_cost,
                "weekly_limit": weekly_limit,
                "reputation_key": reputation_key,
                "reputation_required": reputation_required,
                "route_no": route_no,
                "route_key": route_key,
                "route_codex_key": route_codex_key,
                "enemy_ranges": tuple(normalized_ranges),
                "boss_floors": frozenset(boss_floors),
                **rewards,
                "story_codex_key": story_codex_key,
                "title_key": title_key,
            }
        )
    normalized.sort(key=lambda row: int(row["floor_min"]))
    if normalized[0]["floor_min"] != 1 or normalized[-1]["floor_max"] != MAX_FLOOR or any(left["floor_max"] + 1 != right["floor_min"] for left, right in zip(normalized, normalized[1:])):
        raise ContentError("void spire route segments must cover every floor")
    return tuple(normalized)


def _segment_for_floor(floor_no: int, content: ContentBundle | None = None) -> dict[str, Any]:
    if not isinstance(floor_no, int) or isinstance(floor_no, bool) or not 1 <= floor_no <= MAX_FLOOR:
        raise ValueError(f"void spire floor must be between 1 and {MAX_FLOOR}")
    for row in _segment_records(content):
        if int(row["floor_min"]) <= floor_no <= int(row["floor_max"]):
            return row
    raise ValueError(f"void spire floor must be between 1 and {MAX_FLOOR}")


def floor_definition(floor_no: int, content: ContentBundle | None = None) -> VoidSpireFloorDefinition:
    segment = _segment_for_floor(floor_no, content)
    enemy_key = next(item["enemy_key"] for item in segment["enemy_ranges"] if floor_no <= item["max_floor"])
    return VoidSpireFloorDefinition(
        floor_no=floor_no,
        required_realm=str(segment["required_realm"]),
        required_layer=int(segment["required_layer"]),
        stamina_cost=int(segment["stamina_cost"]),
        weekly_limit=int(segment["weekly_limit"]),
        route_no=int(segment["route_no"]),
        route_key=str(segment["route_key"]),
        enemy_key=enemy_key,
        boss=floor_no in segment["boss_floors"],
        title_key=segment["title_key"],
        route_codex_key=str(segment["route_codex_key"]),
        reputation_key=str(segment["reputation_key"]),
        reputation_required=int(segment["reputation_required"]),
    )


def quota_floor_range(floor_no: int, content: ContentBundle | None = None) -> tuple[int, int]:
    segment = _segment_for_floor(floor_no, content)
    return int(segment["floor_min"]), int(segment["floor_max"])


def story_codex_for_floor(floor_no: int, content: ContentBundle | None = None) -> str | None:
    segment = _segment_for_floor(floor_no, content)
    return segment["story_codex_key"] if floor_no in segment["boss_floors"] else None


def title_for_floor(floor_no: int, content: ContentBundle | None = None) -> str | None:
    segment = _segment_for_floor(floor_no, content)
    return segment["title_key"] if floor_no in segment["boss_floors"] else None


def route_codex_for_floor(floor_no: int, content: ContentBundle | None = None) -> str:
    return str(_segment_for_floor(floor_no, content)["route_codex_key"])


def week_start(value) -> str:
    return (value.date() - timedelta(days=value.weekday())).isoformat()


def reward_for(floor_no: int, seed: str, *, first_clear: bool, content: ContentBundle | None = None) -> dict[str, int]:
    definition = floor_definition(floor_no, content)
    segment = _segment_for_floor(floor_no, content)
    if first_clear:
        reward = dict(segment["first_clear_reward"])
        if definition.boss:
            for key, value in segment["boss_reward"].items():
                reward[str(key)] = reward.get(str(key), 0) + int(value)
        return reward
    roll = int.from_bytes(hashlib.blake2b(seed.encode("utf-8"), digest_size=8).digest(), "big")
    return dict(segment["repeat_reward"]) if roll % 2 == 0 else {}


__all__ = [
    "DAO_SERVICE_REPUTATION_KEY",
    "DAO_SERVICE_REPUTATION_REQUIRED",
    "LOWER_ROUTE_END",
    "MID_ROUTE_END",
    "MAX_FLOOR",
    "REQUIRED_LAYER",
    "REQUIRED_REALM",
    "STAMINA_COST",
    "SUPPLY_REPUTATION_KEY",
    "SUPPLY_REPUTATION_REQUIRED",
    "TOWER_KEY",
    "UPPER_REQUIRED_REALM",
    "UPPER_WEEKLY_ATTEMPT_LIMIT",
    "VoidSpireFloorDefinition",
    "WEEKLY_ATTEMPT_LIMIT",
    "floor_definition",
    "quota_floor_range",
    "reward_for",
    "route_codex_for_floor",
    "story_codex_for_floor",
    "title_for_floor",
    "week_start",
]
