"""Rules for the open floors of the void spire tower."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from ..content import ContentBundle, ContentError, bundled_content


TOWER_KEY = "tower.void_spire"
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


def _segment_records(content: ContentBundle | None = None) -> tuple[dict[str, Any], ...]:
    bundle = content or bundled_content()
    rows = bundle.list("void_spire", include_locked=False)
    if not rows:
        raise ContentError("void spire has no active route segments")
    normalized: list[dict[str, Any]] = []
    for row in rows:
        required = ("floor_min", "floor_max", "required_realm", "required_layer", "stamina_cost", "weekly_limit", "route_no", "route_key", "enemy_ranges", "boss_floors", "first_clear_reward", "boss_reward", "repeat_reward", "story_codex_key", "title_key")
        if any(field not in row for field in required):
            raise ContentError(f"void spire segment {row.get('key')} is incomplete")
        floor_min, floor_max = row["floor_min"], row["floor_max"]
        if any(isinstance(value, bool) or not isinstance(value, int) for value in (floor_min, floor_max, row["required_layer"], row["stamina_cost"], row["weekly_limit"], row["route_no"])):
            raise ContentError(f"void spire segment {row.get('key')} has invalid numeric fields")
        if floor_min < MID_ROUTE_END + 1 or floor_max < floor_min or floor_max > MAX_FLOOR:
            raise ContentError(f"void spire segment {row.get('key')} has invalid floor range")
        if not isinstance(row["required_realm"], str) or not isinstance(row["route_key"], str) or not row["route_key"]:
            raise ContentError(f"void spire segment {row.get('key')} has invalid admission fields")
        ranges = row["enemy_ranges"]
        if not isinstance(ranges, list) or not ranges:
            raise ContentError(f"void spire segment {row.get('key')} has no enemy ranges")
        previous = floor_min - 1
        for enemy_range in ranges:
            if not isinstance(enemy_range, dict) or not isinstance(enemy_range.get("max_floor"), int) or not isinstance(enemy_range.get("enemy_key"), str):
                raise ContentError(f"void spire segment {row.get('key')} has an invalid enemy range")
            if enemy_range["max_floor"] <= previous or enemy_range["max_floor"] > floor_max:
                raise ContentError(f"void spire segment {row.get('key')} has unordered enemy ranges")
            bundle.require("enemy", enemy_range["enemy_key"], include_locked=False)
            previous = enemy_range["max_floor"]
        if previous != floor_max or not isinstance(row["boss_floors"], list) or any(floor not in range(floor_min, floor_max + 1) for floor in row["boss_floors"]):
            raise ContentError(f"void spire segment {row.get('key')} has invalid boss floors")
        for field in ("first_clear_reward", "boss_reward", "repeat_reward"):
            reward = row[field]
            if not isinstance(reward, dict) or any(not isinstance(key, str) or isinstance(value, bool) or not isinstance(value, int) or value < 0 for key, value in reward.items()):
                raise ContentError(f"void spire segment {row.get('key')} has invalid {field}")
            for key in reward:
                if key.startswith("item."):
                    bundle.require("item", key, include_locked=False)
        for field in ("story_codex_key",):
            if not isinstance(row[field], str) or not bundle.has("codex_entry", row[field], include_locked=False):
                raise ContentError(f"void spire segment {row.get('key')} has an invalid {field}")
        if not isinstance(row["title_key"], str) or not row["title_key"]:
            raise ContentError(f"void spire segment {row.get('key')} has no title key")
        normalized.append(row)
    normalized.sort(key=lambda row: int(row["floor_min"]))
    if normalized[0]["floor_min"] != MID_ROUTE_END + 1 or normalized[-1]["floor_max"] != MAX_FLOOR or any(left["floor_max"] + 1 != right["floor_min"] for left, right in zip(normalized, normalized[1:])):
        raise ContentError("void spire route segments must cover every upper floor")
    return tuple(normalized)


def _segment_for_floor(floor_no: int, content: ContentBundle | None = None) -> dict[str, Any]:
    for row in _segment_records(content):
        if int(row["floor_min"]) <= floor_no <= int(row["floor_max"]):
            return row
    raise ValueError(f"void spire floor must be between 1 and {MAX_FLOOR}")


def floor_definition(floor_no: int, content: ContentBundle | None = None) -> VoidSpireFloorDefinition:
    if not isinstance(floor_no, int) or isinstance(floor_no, bool) or not 1 <= floor_no <= MAX_FLOOR:
        raise ValueError(f"void spire floor must be between 1 and {MAX_FLOOR}")
    if floor_no <= LOWER_ROUTE_END:
        route_no = 1 if floor_no <= 15 else 2
        route_key = "storm" if route_no == 1 else "echo"
        if floor_no == 15:
            enemy_key, boss = "enemy.void_spire.route_storm_boss", True
        elif floor_no == 30:
            enemy_key, boss = "enemy.void_spire.route_echo_boss", True
        elif floor_no <= 7:
            enemy_key, boss = "enemy.void_spire.scout", False
        elif floor_no <= 14:
            enemy_key, boss = "enemy.void_spire.sentinel", False
        elif floor_no <= 22:
            enemy_key, boss = "enemy.void_spire.watcher", False
        else:
            enemy_key, boss = "enemy.void_spire.warlord", False
    elif floor_no <= MID_ROUTE_END:
        route_no = 3 if floor_no <= 45 else 4
        route_key = "inscription" if route_no == 3 else "witness"
        if floor_no == 45:
            enemy_key, boss = "enemy.void_spire.route_inscription_boss", True
        elif floor_no == 60:
            enemy_key, boss = "enemy.void_spire.route_witness_boss", True
        elif floor_no <= 37:
            enemy_key, boss = "enemy.void_spire.scribe", False
        elif floor_no <= 44:
            enemy_key, boss = "enemy.void_spire.keeper", False
        elif floor_no <= 52:
            enemy_key, boss = "enemy.void_spire.echo_warden", False
        else:
            enemy_key, boss = "enemy.void_spire.origin_guard", False
    else:
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
            enemy_key=str(enemy_key),
            boss=floor_no in {int(value) for value in segment["boss_floors"]},
            title_key=str(segment["title_key"]),
        )
    return VoidSpireFloorDefinition(
        floor_no=floor_no,
        required_realm=REQUIRED_REALM if floor_no <= LOWER_ROUTE_END else UPPER_REQUIRED_REALM,
        required_layer=REQUIRED_LAYER,
        stamina_cost=STAMINA_COST,
        weekly_limit=WEEKLY_ATTEMPT_LIMIT if floor_no <= LOWER_ROUTE_END else UPPER_WEEKLY_ATTEMPT_LIMIT,
        route_no=route_no,
        route_key=route_key,
        enemy_key=enemy_key,
        boss=boss,
    )


def quota_floor_range(floor_no: int, content: ContentBundle | None = None) -> tuple[int, int]:
    floor_definition(floor_no, content)
    if floor_no <= LOWER_ROUTE_END:
        return (1, LOWER_ROUTE_END)
    if floor_no <= MID_ROUTE_END:
        return (LOWER_ROUTE_END + 1, MID_ROUTE_END)
    segment = _segment_for_floor(floor_no, content)
    return int(segment["floor_min"]), int(segment["floor_max"])


def story_codex_for_floor(floor_no: int, content: ContentBundle | None = None) -> str | None:
    if floor_no == 45:
        return "codex.story.void_spire.inscription"
    if floor_no == 60:
        return "codex.story.void_spire.witness"
    if floor_no > MID_ROUTE_END:
        segment = _segment_for_floor(floor_no, content)
        if floor_no in {int(value) for value in segment["boss_floors"]}:
            return str(segment["story_codex_key"])
    return None


def title_for_floor(floor_no: int, content: ContentBundle | None = None) -> str | None:
    if floor_no == 60:
        return "title.void_spire.witness"
    if floor_no > MID_ROUTE_END:
        segment = _segment_for_floor(floor_no, content)
        if floor_no in {int(value) for value in segment["boss_floors"]}:
            return str(segment["title_key"])
    return None


def week_start(value) -> str:
    return (value.date() - timedelta(days=value.weekday())).isoformat()


def reward_for(floor_no: int, seed: str, *, first_clear: bool, content: ContentBundle | None = None) -> dict[str, int]:
    definition = floor_definition(floor_no, content)
    if floor_no > MID_ROUTE_END:
        segment = _segment_for_floor(floor_no, content)
        if first_clear:
            reward = {str(key): int(value) for key, value in segment["first_clear_reward"].items()}
            if definition.boss:
                for key, value in segment["boss_reward"].items():
                    reward[str(key)] = reward.get(str(key), 0) + int(value)
            return reward
        roll = int.from_bytes(hashlib.blake2b(seed.encode("utf-8"), digest_size=8).digest(), "big")
        return dict(segment["repeat_reward"]) if roll % 2 == 0 else {}
    if floor_no > LOWER_ROUTE_END:
        return {}
    if first_clear:
        reward = {"spirit_stones": 120, "item.mat.array_sand": 3}
        if definition.boss:
            reward["local.void_supply"] = 30
        return reward
    roll = int.from_bytes(hashlib.blake2b(seed.encode("utf-8"), digest_size=8).digest(), "big")
    return {"item.mat.array_sand": 1} if roll % 2 else {}


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
    "story_codex_for_floor",
    "title_for_floor",
    "week_start",
]
