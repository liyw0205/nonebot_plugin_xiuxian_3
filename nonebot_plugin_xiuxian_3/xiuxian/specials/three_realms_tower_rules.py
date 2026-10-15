"""Content-backed rules for the single-player three-realms tower."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from ..content import ContentBundle, ContentError, bundled_content

TOWER_KEY = "tower.three_realms"
MAX_FLOOR = 40
NASCENT_SOUL_MAX_FLOOR = 20
WEEKLY_ATTEMPT_LIMIT = 2
FACTIONS = ("xuantian", "demon", "beast")
REBUILD_REPUTATION_KEYS = (
    "local.xuantian.domain_front",
    "local.demon.abyss_market",
    "local.beast.three_realms_trade_port",
)

_SEGMENT_FIELDS = (
    "floor_min",
    "floor_max",
    "required_realm",
    "required_layer",
    "stamina_cost",
    "weekly_limit",
    "encounter_key",
    "boss_encounter_key",
    "boss_floors",
    "permit_flag",
    "rebuild_reputation_threshold",
    "first_clear_reward",
    "repeat_reward",
)


@dataclass(frozen=True, slots=True)
class ThreeRealmsTowerFloorDefinition:
    floor_no: int
    required_realm: str
    required_layer: int
    stamina_cost: int
    weekly_limit: int
    enemy_key: str
    boss: bool


def _bundle(content: ContentBundle | None) -> ContentBundle:
    return content if content is not None else bundled_content()


def _positive_int(value: Any, field: str, key: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ContentError(f"three-realms tower {key} {field} must be a positive integer")
    return int(value)


def _reward_map(value: Any, *, field: str, key: str, bundle: ContentBundle) -> dict[str, int]:
    if not isinstance(value, dict):
        raise ContentError(f"three-realms tower {key} {field} must be an object")
    rewards: dict[str, int] = {}
    for reward_key, raw_amount in value.items():
        reward_key = str(reward_key)
        amount = _positive_int(raw_amount, f"{field}.{reward_key}", key)
        if reward_key == "spirit_stones":
            rewards[reward_key] = amount
            continue
        if not reward_key.startswith("item."):
            raise ContentError(f"three-realms tower {key} {field} has an unsupported reward {reward_key}")
        try:
            bundle.require("item", reward_key, include_locked=False)
        except KeyError as exc:
            raise ContentError(
                f"three-realms tower {key} {field} references unknown item {reward_key}"
            ) from exc
        rewards[reward_key] = amount
    return rewards


def _tower_record(content: ContentBundle | None = None) -> dict[str, Any]:
    bundle = _bundle(content)
    row = bundle.require("three_realms_tower", TOWER_KEY, include_locked=False)
    if row.get("status") != "active":
        raise ContentError(f"three-realms tower {TOWER_KEY} is not active")
    if not isinstance(row.get("name"), str) or not row["name"].strip():
        raise ContentError(f"three-realms tower {TOWER_KEY} requires a name")
    if not isinstance(row.get("desc"), str) or not row["desc"].strip():
        raise ContentError(f"three-realms tower {TOWER_KEY} requires a description")
    if _positive_int(row.get("max_floor"), "max_floor", TOWER_KEY) != MAX_FLOOR:
        raise ContentError(f"three-realms tower {TOWER_KEY} max_floor must match the open floor bound")
    if _positive_int(row.get("weekly_attempt_limit"), "weekly_attempt_limit", TOWER_KEY) != WEEKLY_ATTEMPT_LIMIT:
        raise ContentError(f"three-realms tower {TOWER_KEY} weekly_attempt_limit must match the weekly cap")
    if tuple(row.get("factions") or ()) != FACTIONS:
        raise ContentError(f"three-realms tower {TOWER_KEY} factions must be the three open factions")
    if tuple(row.get("rebuild_reputation_keys") or ()) != REBUILD_REPUTATION_KEYS:
        raise ContentError(f"three-realms tower {TOWER_KEY} rebuild reputation keys must match the open keys")
    if not isinstance(row.get("enemy_prefix"), str) or not row["enemy_prefix"].strip():
        raise ContentError(f"three-realms tower {TOWER_KEY} requires an enemy prefix")
    return row


def _segments(content: ContentBundle | None = None) -> tuple[dict[str, Any], ...]:
    bundle = _bundle(content)
    row = _tower_record(bundle)
    rows = row.get("segments")
    if not isinstance(rows, list) or not rows:
        raise ContentError(f"three-realms tower {TOWER_KEY} requires floor segments")
    normalized: list[dict[str, Any]] = []
    for index, segment in enumerate(rows):
        if not isinstance(segment, dict):
            raise ContentError(f"three-realms tower segment {index} must be an object")
        if set(segment) != set(_SEGMENT_FIELDS):
            raise ContentError(f"three-realms tower segment {index} has missing or unknown fields")
        floor_min = _positive_int(segment["floor_min"], "floor_min", f"segment {index}")
        floor_max = _positive_int(segment["floor_max"], "floor_max", f"segment {index}")
        if floor_max < floor_min or floor_max > MAX_FLOOR:
            raise ContentError(f"three-realms tower segment {index} has an invalid floor range")
        realm = segment["required_realm"]
        if not isinstance(realm, str) or not realm:
            raise ContentError(f"three-realms tower segment {index} requires a realm")
        try:
            bundle.require("realm", realm, include_locked=False)
        except KeyError as exc:
            raise ContentError(
                f"three-realms tower segment {index} references unknown realm {realm}"
            ) from exc
        _positive_int(segment["required_layer"], "required_layer", f"segment {index}")
        _positive_int(segment["stamina_cost"], "stamina_cost", f"segment {index}")
        _positive_int(segment["weekly_limit"], "weekly_limit", f"segment {index}")
        for field in ("encounter_key", "boss_encounter_key"):
            if not isinstance(segment[field], str) or not segment[field].strip():
                raise ContentError(f"three-realms tower segment {index} requires {field}")
        boss_floors = segment["boss_floors"]
        if not isinstance(boss_floors, list) or not boss_floors:
            raise ContentError(f"three-realms tower segment {index} requires boss floors")
        for boss_floor in boss_floors:
            if (
                isinstance(boss_floor, bool)
                or not isinstance(boss_floor, int)
                or not floor_min <= boss_floor <= floor_max
            ):
                raise ContentError(f"three-realms tower segment {index} has a boss floor outside its range")
        permit_flag = segment["permit_flag"]
        if permit_flag is not None and (not isinstance(permit_flag, str) or not permit_flag.strip()):
            raise ContentError(f"three-realms tower segment {index} has an invalid permit flag")
        threshold = segment["rebuild_reputation_threshold"]
        if isinstance(threshold, bool) or not isinstance(threshold, int) or threshold < 0:
            raise ContentError(f"three-realms tower segment {index} has an invalid rebuild threshold")
        normalized.append(
            {
                "floor_min": floor_min,
                "floor_max": floor_max,
                "required_realm": realm,
                "required_layer": int(segment["required_layer"]),
                "stamina_cost": int(segment["stamina_cost"]),
                "weekly_limit": int(segment["weekly_limit"]),
                "encounter_key": segment["encounter_key"],
                "boss_encounter_key": segment["boss_encounter_key"],
                "boss_floors": frozenset(int(value) for value in boss_floors),
                "permit_flag": permit_flag,
                "rebuild_reputation_threshold": int(threshold),
                "first_clear_reward": _reward_map(
                    segment["first_clear_reward"],
                    field="first_clear_reward",
                    key=f"segment {index}",
                    bundle=bundle,
                ),
                "repeat_reward": _reward_map(
                    segment["repeat_reward"],
                    field="repeat_reward",
                    key=f"segment {index}",
                    bundle=bundle,
                ),
            }
        )
    ordered = sorted(normalized, key=lambda item: item["floor_min"])
    if ordered[0]["floor_min"] != 1 or ordered[-1]["floor_max"] != MAX_FLOOR:
        raise ContentError(f"three-realms tower {TOWER_KEY} segments must cover every floor")
    for left, right in zip(ordered, ordered[1:]):
        if left["floor_max"] + 1 != right["floor_min"]:
            raise ContentError(f"three-realms tower {TOWER_KEY} segments must be contiguous")
    return tuple(ordered)


def _segment_for_floor(floor_no: int, content: ContentBundle | None = None) -> dict[str, Any]:
    if not isinstance(floor_no, int) or isinstance(floor_no, bool) or not 1 <= floor_no <= MAX_FLOOR:
        raise ValueError(f"three-realms tower floor must be between 1 and {MAX_FLOOR}")
    for segment in _segments(content):
        if segment["floor_min"] <= floor_no <= segment["floor_max"]:
            return segment
    raise ContentError(f"three-realms tower has no segment for floor {floor_no}")


def _enemy_key(
    segment: dict[str, Any], floor_no: int, faction: str, content: ContentBundle | None = None
) -> str:
    if faction not in FACTIONS:
        raise ValueError(f"unsupported three-realms faction: {faction}")
    prefix = _tower_record(content)["enemy_prefix"]
    encounter = (
        segment["boss_encounter_key"] if floor_no in segment["boss_floors"] else segment["encounter_key"]
    )
    return f"{prefix}.{faction}.{encounter}"


def floor_definition(floor_no: int, content: ContentBundle | None = None) -> ThreeRealmsTowerFloorDefinition:
    segment = _segment_for_floor(floor_no, content)
    return ThreeRealmsTowerFloorDefinition(
        floor_no=floor_no,
        required_realm=str(segment["required_realm"]),
        required_layer=int(segment["required_layer"]),
        stamina_cost=int(segment["stamina_cost"]),
        weekly_limit=int(segment["weekly_limit"]),
        enemy_key=_enemy_key(segment, floor_no, FACTIONS[0], content),
        boss=floor_no in segment["boss_floors"],
    )


def enemy_key_for(floor_no: int, faction: str, content: ContentBundle | None = None) -> str:
    segment = _segment_for_floor(floor_no, content)
    return _enemy_key(segment, floor_no, faction, content)


def floor_gate(floor_no: int, content: ContentBundle | None = None) -> tuple[str | None, int]:
    """Return the segment's (permit flag, rebuild reputation threshold) for this floor."""

    segment = _segment_for_floor(floor_no, content)
    return segment["permit_flag"], int(segment["rebuild_reputation_threshold"])


def rebuild_reputation_total(values: dict[str, object]) -> int:
    total = 0
    for key in REBUILD_REPUTATION_KEYS:
        try:
            total += max(0, int(values.get(key, 0)))
        except (TypeError, ValueError):
            continue
    return total


def reward_for(
    floor_no: int,
    seed: str,
    *,
    first_clear: bool,
    content: ContentBundle | None = None,
) -> dict[str, int]:
    segment = _segment_for_floor(floor_no, content)
    if first_clear:
        return dict(segment["first_clear_reward"])
    roll = int.from_bytes(hashlib.blake2b(seed.encode("utf-8"), digest_size=8).digest(), "big")
    return dict(segment["repeat_reward"]) if roll % 2 == 0 else {}


def week_start(value) -> str:
    return (value.date() - timedelta(days=value.weekday())).isoformat()


__all__ = [
    "FACTIONS",
    "MAX_FLOOR",
    "REBUILD_REPUTATION_KEYS",
    "TOWER_KEY",
    "WEEKLY_ATTEMPT_LIMIT",
    "NASCENT_SOUL_MAX_FLOOR",
    "ThreeRealmsTowerFloorDefinition",
    "enemy_key_for",
    "floor_definition",
    "floor_gate",
    "rebuild_reputation_total",
    "reward_for",
    "week_start",
]
