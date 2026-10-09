"""Rules for the mist-trial tower, backed by the current content bundle."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from ..content import ContentBundle, ContentError, bundled_content
from ..rewards.rules import local_reputation_maximum
from ..utils.player import PLAYER_RESOURCE_FIELDS
from ..utils.randomness import deterministic_weighted_choice


TOWER_KEY = "tower.mist_trial"


@dataclass(frozen=True, slots=True)
class TowerFloorDefinition:
    floor_no: int
    required_realm: str
    required_layer: int
    stamina_cost: int
    daily_limit: int
    enemy_key: str


def _bundle(content: ContentBundle | None) -> ContentBundle:
    return content or bundled_content()


def _reward_map(value: Any, *, field: str, bundle: ContentBundle) -> dict[str, int]:
    if not isinstance(value, dict):
        raise ContentError(f"mist trial {field} must be an object")
    normalized: dict[str, int] = {}
    for key, amount in value.items():
        if (
            not isinstance(key, str)
            or not key
            or isinstance(amount, bool)
            or not isinstance(amount, int)
            or amount <= 0
        ):
            raise ContentError(f"mist trial {field} contains an invalid reward")
        if key.startswith("item."):
            bundle.require("item", key, include_locked=False)
        elif key.startswith("local."):
            local_reputation_maximum(key, bundle)
        elif key not in PLAYER_RESOURCE_FIELDS or key.endswith("_max"):
            raise ContentError(f"mist trial {field} contains unsupported reward {key}")
        normalized[key] = amount
    return normalized


def _reward_options(
    value: Any, *, field: str, bundle: ContentBundle
) -> tuple[tuple[int, dict[str, int]], ...]:
    if not isinstance(value, list) or not value:
        raise ContentError(f"mist trial {field} must be a non-empty list")
    options: list[tuple[int, dict[str, int]]] = []
    for index, option in enumerate(value):
        if (
            not isinstance(option, dict)
            or isinstance(option.get("weight"), bool)
            or not isinstance(option.get("weight"), int)
            or option["weight"] <= 0
        ):
            raise ContentError(f"mist trial {field}[{index}] has an invalid weight")
        if option.get("no_reward") is True:
            if set(option) != {"weight", "no_reward"}:
                raise ContentError(
                    f"mist trial {field}[{index}] no_reward cannot include rewards"
                )
            reward: dict[str, int] = {}
        else:
            reward = _reward_map(
                option.get("rewards"),
                field=f"{field}[{index}].rewards",
                bundle=bundle,
            )
        options.append((int(option["weight"]), reward))
    return tuple(options)


def _tower_record(content: ContentBundle | None = None) -> dict[str, Any]:
    bundle = _bundle(content)
    row = bundle.require("mist_trial_tower", TOWER_KEY, include_locked=False)
    max_floor = row.get("max_floor")
    practice_limit = row.get("practice_weekly_limit")
    codex_floors = row.get("codex_first_clear_floors")
    codex_prefix = row.get("codex_entry_prefix")
    if isinstance(max_floor, bool) or not isinstance(max_floor, int) or max_floor < 1:
        raise ContentError("mist trial max_floor is invalid")
    if (
        isinstance(practice_limit, bool)
        or not isinstance(practice_limit, int)
        or practice_limit < 1
    ):
        raise ContentError("mist trial practice_weekly_limit is invalid")
    if (
        not isinstance(codex_floors, list)
        or any(
            isinstance(floor, bool)
            or not isinstance(floor, int)
            or not 1 <= floor <= max_floor
            for floor in codex_floors
        )
        or len(set(codex_floors)) != len(codex_floors)
    ):
        raise ContentError("mist trial codex_first_clear_floors is invalid")
    if not isinstance(codex_prefix, str) or not codex_prefix:
        raise ContentError("mist trial codex_entry_prefix is invalid")
    for floor_no in range(1, max_floor + 1):
        bundle.require(
            "codex_entry",
            f"{codex_prefix}{floor_no}",
            include_locked=False,
        )
    raw_segments = row.get("segments")
    if not isinstance(raw_segments, list) or not raw_segments:
        raise ContentError("mist trial requires segments")
    segments: list[dict[str, Any]] = []
    for index, segment in enumerate(raw_segments):
        if not isinstance(segment, dict):
            raise ContentError(f"mist trial segment {index} must be an object")
        required = (
            "floor_min",
            "floor_max",
            "required_realm",
            "required_layer",
            "stamina_cost",
            "daily_limit",
            "enemy_key",
            "boss_enemy_key",
            "boss_floors",
            "first_clear_rewards",
            "repeat_rewards",
        )
        if any(field not in segment for field in required):
            raise ContentError(f"mist trial segment {index} is incomplete")
        numeric = (
            segment["floor_min"],
            segment["floor_max"],
            segment["required_layer"],
            segment["stamina_cost"],
            segment["daily_limit"],
        )
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 1
            for value in numeric
        ):
            raise ContentError(f"mist trial segment {index} has invalid numeric fields")
        if segment["floor_min"] > segment["floor_max"] or segment["floor_max"] > max_floor:
            raise ContentError(f"mist trial segment {index} has invalid floor range")
        if not isinstance(segment["required_realm"], str) or not segment["required_realm"]:
            raise ContentError(f"mist trial segment {index} has invalid realm")
        bundle.require("realm", segment["required_realm"], include_locked=False)
        for enemy_field in ("enemy_key", "boss_enemy_key"):
            if not isinstance(segment[enemy_field], str) or not segment[enemy_field]:
                raise ContentError(f"mist trial segment {index} has invalid enemy")
            bundle.require("enemy", segment[enemy_field], include_locked=False)
        boss_floors = segment["boss_floors"]
        if not isinstance(boss_floors, list) or any(
            isinstance(floor, bool)
            or not isinstance(floor, int)
            or floor < segment["floor_min"]
            or floor > segment["floor_max"]
            for floor in boss_floors
        ):
            raise ContentError(f"mist trial segment {index} has invalid boss floors")
        first_clear = _reward_options(
            segment["first_clear_rewards"],
            field=f"segments[{index}].first_clear_rewards",
            bundle=bundle,
        )
        repeat = _reward_options(
            segment["repeat_rewards"],
            field=f"segments[{index}].repeat_rewards",
            bundle=bundle,
        )
        segments.append(
            {
                **segment,
                "boss_floors": tuple(boss_floors),
                "first_clear_rewards": first_clear,
                "repeat_rewards": repeat,
            }
        )
    segments.sort(key=lambda value: int(value["floor_min"]))
    if (
        segments[0]["floor_min"] != 1
        or segments[-1]["floor_max"] != max_floor
        or any(
            left["floor_max"] + 1 != right["floor_min"]
            for left, right in zip(segments, segments[1:])
        )
    ):
        raise ContentError("mist trial segments must cover every floor")
    raw_special = row.get("special_rewards")
    if not isinstance(raw_special, dict):
        raise ContentError("mist trial special_rewards must be an object")
    special: dict[int, dict[str, int]] = {}
    for raw_floor, reward in raw_special.items():
        if (
            not isinstance(raw_floor, str)
            or not raw_floor.isdigit()
            or not 1 <= int(raw_floor) <= max_floor
        ):
            raise ContentError("mist trial special reward floor is invalid")
        special[int(raw_floor)] = _reward_map(
            reward,
            field=f"special_rewards.{raw_floor}",
            bundle=bundle,
        )
    return {
        "max_floor": max_floor,
        "practice_weekly_limit": practice_limit,
        "codex_first_clear_floors": frozenset(codex_floors),
        "codex_entry_prefix": codex_prefix,
        "segments": tuple(segments),
        "special_rewards": special,
    }


def max_floor(content: ContentBundle | None = None) -> int:
    return int(_tower_record(content)["max_floor"])


def practice_weekly_limit(content: ContentBundle | None = None) -> int:
    return int(_tower_record(content)["practice_weekly_limit"])


def codex_first_clear_floors(content: ContentBundle | None = None) -> frozenset[int]:
    return frozenset(_tower_record(content)["codex_first_clear_floors"])


def codex_entry_key(floor_no: int, content: ContentBundle | None = None) -> str:
    record = _tower_record(content)
    if not isinstance(floor_no, int) or floor_no < 1 or floor_no > int(record["max_floor"]):
        raise ValueError("mist trial floor is invalid")
    return f"{record['codex_entry_prefix']}{floor_no}"


def reward_local_reputation_maximums(
    reward: dict[str, int], content: ContentBundle | None = None
) -> dict[str, int]:
    bundle = _bundle(content)
    return {
        key: local_reputation_maximum(key, bundle)
        for key in reward
        if key.startswith("local.")
    }


def _segment_for_floor(floor_no: int, content: ContentBundle | None = None) -> dict[str, Any]:
    for segment in _tower_record(content)["segments"]:
        if int(segment["floor_min"]) <= floor_no <= int(segment["floor_max"]):
            return segment
    raise ValueError("mist trial floor is outside the current tower")


def floor_definition(floor_no: int, content: ContentBundle | None = None) -> TowerFloorDefinition:
    if not isinstance(floor_no, int) or isinstance(floor_no, bool) or not 1 <= floor_no <= max_floor(content):
        raise ValueError("mist trial floor is invalid")
    segment = _segment_for_floor(floor_no, content)
    enemy_key = (
        segment["boss_enemy_key"]
        if floor_no in segment["boss_floors"]
        else segment["enemy_key"]
    )
    return TowerFloorDefinition(
        floor_no=floor_no,
        required_realm=str(segment["required_realm"]),
        required_layer=int(segment["required_layer"]),
        stamina_cost=int(segment["stamina_cost"]),
        daily_limit=int(segment["daily_limit"]),
        enemy_key=str(enemy_key),
    )


def reward_for(
    floor_no: int,
    seed: str,
    *,
    first_clear: bool,
    content: ContentBundle | None = None,
) -> dict[str, int]:
    floor_definition(floor_no, content)
    record = _tower_record(content)
    segment = _segment_for_floor(floor_no, content)
    options = segment["first_clear_rewards"] if first_clear else segment["repeat_rewards"]
    reward = dict(deterministic_weighted_choice(options, seed))
    if first_clear:
        for key, amount in record["special_rewards"].get(floor_no, {}).items():
            reward[key] = reward.get(key, 0) + amount
    return reward


def attempt_band_for(floor_no: int, content: ContentBundle | None = None) -> tuple[int, int]:
    floor_definition(floor_no, content)
    segment = _segment_for_floor(floor_no, content)
    return int(segment["floor_min"]), int(segment["floor_max"])


def practice_week_start(value) -> str:
    return (value.date() - timedelta(days=value.weekday())).isoformat()


def reward_snapshot_digest(
    reward: dict[str, int], reward_maximums: dict[str, int]
) -> str:
    """Bind a run's frozen reward and reputation caps into one integrity hash."""

    payload = json.dumps(
        {"reward": reward, "reward_maximums": reward_maximums},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


__all__ = [
    "TOWER_KEY",
    "TowerFloorDefinition",
    "attempt_band_for",
    "codex_first_clear_floors",
    "codex_entry_key",
    "floor_definition",
    "max_floor",
    "practice_weekly_limit",
    "practice_week_start",
    "reward_local_reputation_maximums",
    "reward_for",
    "reward_snapshot_digest",
]
