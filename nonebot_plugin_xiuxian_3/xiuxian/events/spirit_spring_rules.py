"""Content-backed rules for the spirit-spring world event."""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from ..content import ContentBundle, ContentError, bundled_content
from ..rewards.rules import RewardGrant, reward_definition, reward_grant_from_snapshot
from ..utils.json_cache import decode_json_strict

SPIRIT_SPRING_EVENT_KEY = "event.spirit_spring"


@dataclass(frozen=True, slots=True)
class SpiritSpringDefinition:
    key: str
    name: str
    description: str
    location_key: str
    schedule: dict[str, Any]
    required_realm_key: str
    required_realm_layer: int
    source_item_key: str
    source_item_name: str
    contribution_per_quantity: int
    contribution_cap: int
    target_item_key: str
    target_quantity: int
    minimum_contribution: int
    claim_window_seconds: int
    base_reward: RewardGrant
    completion_reward: RewardGrant

    def snapshot(self) -> dict[str, Any]:
        return {
            "event_key": self.key,
            "name": self.name,
            "description": self.description,
            "location_key": self.location_key,
            "schedule": copy.deepcopy(self.schedule),
            "required_realm_key": self.required_realm_key,
            "required_realm_layer": self.required_realm_layer,
            "source_item_key": self.source_item_key,
            "source_item_name": self.source_item_name,
            "contribution_per_quantity": self.contribution_per_quantity,
            "contribution_cap": self.contribution_cap,
            "target_item_key": self.target_item_key,
            "target_quantity": self.target_quantity,
            "minimum_contribution": self.minimum_contribution,
            "claim_window_seconds": self.claim_window_seconds,
            "base_reward": self.base_reward.snapshot(),
            "completion_reward": self.completion_reward.snapshot(),
        }


def spirit_spring_definition(
    content: ContentBundle | None = None,
) -> SpiritSpringDefinition:
    bundle = content or bundled_content()
    try:
        event = bundle.require("event", SPIRIT_SPRING_EVENT_KEY, include_locked=False)
        expected = {
            "name", "desc", "status", "location_key", "duration_seconds", "schedule",
            "requirements", "contribution", "global_goal", "claim", "key",
        }
        if set(event) != expected or event.get("key") != SPIRIT_SPRING_EVENT_KEY:
            raise ContentError("spirit spring event fields are invalid")
        name = _string(event["name"], "event.spirit_spring.name")
        description = _string(event["desc"], "event.spirit_spring.desc")
        location_key = _string(event["location_key"], "event.spirit_spring.location_key")
        bundle.require("location", location_key, include_locked=False)
        duration_seconds = _positive_int(event["duration_seconds"], "event.spirit_spring.duration_seconds")
        schedule = _schedule(event["schedule"], duration_seconds)
        required_realm_key, required_realm_layer = _requirement(event["requirements"], bundle)
        contribution = event["contribution"]
        if not isinstance(contribution, dict) or set(contribution) != {
            "source_item_key", "per_quantity", "max_per_player"
        }:
            raise ContentError("event.spirit_spring.contribution fields are invalid")
        source_item_key = _string(contribution["source_item_key"], "event.spirit_spring.contribution.source_item_key")
        source_item = bundle.require("item", source_item_key, include_locked=False)
        per_quantity = _positive_int(
            contribution["per_quantity"], "event.spirit_spring.contribution.per_quantity"
        )
        contribution_cap = _positive_int(
            contribution["max_per_player"], "event.spirit_spring.contribution.max_per_player"
        )
        global_goal = event["global_goal"]
        if not isinstance(global_goal, dict) or set(global_goal) != {"item_key", "quantity"}:
            raise ContentError("event.spirit_spring.global_goal fields are invalid")
        target_item_key = _string(global_goal["item_key"], "event.spirit_spring.global_goal.item_key")
        if target_item_key != source_item_key:
            raise ContentError("spirit spring global goal must use the contribution item")
        target_quantity = _positive_int(global_goal["quantity"], "event.spirit_spring.global_goal.quantity")
        claim = event["claim"]
        if not isinstance(claim, dict) or set(claim) != {
            "min_contribution", "window_seconds", "reward_key", "completion_bonus_key"
        }:
            raise ContentError("event.spirit_spring.claim fields are invalid")
        minimum = _positive_int(claim["min_contribution"], "event.spirit_spring.claim.min_contribution")
        window = _positive_int(claim["window_seconds"], "event.spirit_spring.claim.window_seconds")
        if minimum > contribution_cap:
            raise ContentError("event.spirit_spring.claim.min_contribution exceeds contribution cap")
        base_reward = reward_definition(
            _string(claim["reward_key"], "event.spirit_spring.claim.reward_key"),
            bundle,
            operation="event.claim_reward",
        )
        completion_reward = reward_definition(
            _string(claim["completion_bonus_key"], "event.spirit_spring.claim.completion_bonus_key"),
            bundle,
            operation="event.claim_reward",
        )
        return SpiritSpringDefinition(
            key=SPIRIT_SPRING_EVENT_KEY,
            name=name,
            description=description,
            location_key=location_key,
            schedule={
                **schedule,
                "duration_seconds": duration_seconds,
            },
            required_realm_key=required_realm_key,
            required_realm_layer=required_realm_layer,
            source_item_key=source_item_key,
            source_item_name=_string(source_item.get("name"), f"item {source_item_key}.name"),
            contribution_per_quantity=per_quantity,
            contribution_cap=contribution_cap,
            target_item_key=target_item_key,
            target_quantity=target_quantity,
            minimum_contribution=minimum,
            claim_window_seconds=window,
            base_reward=base_reward,
            completion_reward=completion_reward,
        )
    except KeyError as exc:
        raise ContentError(f"spirit spring event content is incomplete: {exc}") from exc


def spirit_spring_result(
    result_json: str | dict[str, Any],
) -> tuple[dict[str, Any], SpiritSpringDefinition]:
    """Decode and validate a persisted round result and its frozen definition."""

    try:
        result = decode_json_strict(result_json) if isinstance(result_json, str) else result_json
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ContentError("spirit spring round result is invalid") from exc
    if not isinstance(result, dict):
        raise ContentError("spirit spring round result must be an object")
    allowed_fields = {"success", "configuration", "settled_at"}
    if not set(result).issubset(allowed_fields):
        raise ContentError("spirit spring round result has invalid fields")
    if not isinstance(result.get("success"), bool):
        raise ContentError("spirit spring round result success is invalid")
    if "settled_at" in result:
        settled_at = result["settled_at"]
        if not isinstance(settled_at, str) or not settled_at.strip():
            raise ContentError("spirit spring round result settled_at is invalid")
        try:
            settled_time = datetime.fromisoformat(settled_at)
        except ValueError as exc:
            raise ContentError("spirit spring round result settled_at is invalid") from exc
        if settled_time.tzinfo is None or settled_time.utcoffset() is None:
            raise ContentError("spirit spring round result settled_at must include timezone")
    return dict(result), _spirit_spring_snapshot_from_result(result)


def spirit_spring_snapshot(result_json: str | dict[str, Any]) -> SpiritSpringDefinition:
    """Return the frozen definition stored in a persisted round result."""

    _, definition = spirit_spring_result(result_json)
    return definition


def _spirit_spring_snapshot_from_result(result: dict[str, Any]) -> SpiritSpringDefinition:
    snapshot = result.get("configuration")
    if not isinstance(snapshot, dict):
        raise ContentError("spirit spring configuration snapshot is missing")
    expected = {
        "event_key", "name", "description", "location_key", "schedule",
        "required_realm_key", "required_realm_layer", "source_item_key", "source_item_name",
        "contribution_per_quantity", "contribution_cap", "target_item_key", "target_quantity",
        "minimum_contribution", "claim_window_seconds", "base_reward", "completion_reward",
    }
    if set(snapshot) != expected or snapshot.get("event_key") != SPIRIT_SPRING_EVENT_KEY:
        raise ContentError("spirit spring configuration snapshot has invalid fields")
    schedule = _snapshot_schedule(snapshot["schedule"])
    required_realm_key = _string(snapshot["required_realm_key"], "spirit spring snapshot.required_realm_key")
    required_realm_layer = _positive_int(
        snapshot["required_realm_layer"], "spirit spring snapshot.required_realm_layer"
    )
    source_item_key = _string(snapshot["source_item_key"], "spirit spring snapshot.source_item_key")
    target_item_key = _string(snapshot["target_item_key"], "spirit spring snapshot.target_item_key")
    if source_item_key != target_item_key:
        raise ContentError("spirit spring snapshot goal item differs from source item")
    contribution_per_quantity = _positive_int(
        snapshot["contribution_per_quantity"], "spirit spring snapshot.contribution_per_quantity"
    )
    contribution_cap = _positive_int(
        snapshot["contribution_cap"], "spirit spring snapshot.contribution_cap"
    )
    minimum_contribution = _positive_int(
        snapshot["minimum_contribution"], "spirit spring snapshot.minimum_contribution"
    )
    if minimum_contribution > contribution_cap:
        raise ContentError("spirit spring snapshot minimum contribution exceeds contribution cap")
    return SpiritSpringDefinition(
        key=SPIRIT_SPRING_EVENT_KEY,
        name=_string(snapshot["name"], "spirit spring snapshot.name"),
        description=_string(snapshot["description"], "spirit spring snapshot.description"),
        location_key=_string(snapshot["location_key"], "spirit spring snapshot.location_key"),
        schedule=schedule,
        required_realm_key=required_realm_key,
        required_realm_layer=required_realm_layer,
        source_item_key=source_item_key,
        source_item_name=_string(snapshot["source_item_name"], "spirit spring snapshot.source_item_name"),
        contribution_per_quantity=contribution_per_quantity,
        contribution_cap=contribution_cap,
        target_item_key=target_item_key,
        target_quantity=_positive_int(snapshot["target_quantity"], "spirit spring snapshot.target_quantity"),
        minimum_contribution=minimum_contribution,
        claim_window_seconds=_positive_int(snapshot["claim_window_seconds"], "spirit spring snapshot.claim_window_seconds"),
        base_reward=reward_grant_from_snapshot(snapshot["base_reward"], operation="event.claim_reward"),
        completion_reward=reward_grant_from_snapshot(snapshot["completion_reward"], operation="event.claim_reward"),
    )


def spirit_spring_window(
    definition: SpiritSpringDefinition,
    now: datetime,
) -> tuple[str, datetime, datetime, datetime] | None:
    value = now.astimezone(timezone.utc)
    schedule = definition.schedule
    for weekday in schedule["weekdays_utc"]:
        start = value.replace(
            hour=schedule["hour_utc"],
            minute=schedule["minute_utc"],
            second=0,
            microsecond=0,
        )
        start -= timedelta(days=(value.weekday() - weekday) % 7)
        end = start + timedelta(seconds=schedule["duration_seconds"])
        if start <= value < end:
            return round_id_for(start), start, end, end + timedelta(seconds=definition.claim_window_seconds)
    return None


def round_id_for(start: datetime) -> str:
    return start.astimezone(timezone.utc).strftime("%Y%m%d")


def _schedule(value: Any, duration_seconds: int) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"weekdays", "local_time"}:
        raise ContentError("event.spirit_spring.schedule fields are invalid")
    weekdays = value["weekdays"]
    if not isinstance(weekdays, list) or not weekdays:
        raise ContentError("event.spirit_spring.schedule.weekdays must be non-empty")
    if any(isinstance(day, bool) or not isinstance(day, int) or not 1 <= day <= 7 for day in weekdays):
        raise ContentError("event.spirit_spring.schedule.weekdays contains an invalid day")
    if len(set(weekdays)) != len(weekdays):
        raise ContentError("event.spirit_spring.schedule.weekdays contains duplicates")
    local_time = value["local_time"]
    if not isinstance(local_time, str) or len(local_time) != 5 or local_time[2] != ":":
        raise ContentError("event.spirit_spring.schedule.local_time is invalid")
    try:
        hour, minute = (int(part) for part in local_time.split(":"))
    except ValueError as exc:
        raise ContentError("event.spirit_spring.schedule.local_time is invalid") from exc
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise ContentError("event.spirit_spring.schedule.local_time is invalid")
    if duration_seconds <= 0:
        raise ContentError("event.spirit_spring.duration_seconds must be positive")
    return {
        "weekdays_utc": [day - 1 for day in weekdays],
        "hour_utc": hour,
        "minute_utc": minute,
        "duration_seconds": duration_seconds,
    }


def _snapshot_schedule(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {
        "weekdays_utc", "hour_utc", "minute_utc", "duration_seconds"
    }:
        raise ContentError("spirit spring snapshot schedule is invalid")
    weekdays = value["weekdays_utc"]
    if not isinstance(weekdays, list) or not weekdays or any(
        isinstance(day, bool) or not isinstance(day, int) or not 0 <= day <= 6 for day in weekdays
    ):
        raise ContentError("spirit spring snapshot weekdays are invalid")
    if len(set(weekdays)) != len(weekdays):
        raise ContentError("spirit spring snapshot weekdays contain duplicates")
    hour = _bounded_int(value["hour_utc"], 0, 23, "spirit spring snapshot.hour_utc")
    minute = _bounded_int(value["minute_utc"], 0, 59, "spirit spring snapshot.minute_utc")
    duration = _positive_int(value["duration_seconds"], "spirit spring snapshot.duration_seconds")
    return {
        "weekdays_utc": list(weekdays),
        "hour_utc": hour,
        "minute_utc": minute,
        "duration_seconds": duration,
    }


def _requirement(value: Any, content: ContentBundle) -> tuple[str, int]:
    if not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], dict):
        raise ContentError("event.spirit_spring.requirements must contain one realm requirement")
    requirement = value[0]
    if set(requirement) != {"type", "realm_key", "min_layer"} or requirement.get("type") != "realm":
        raise ContentError("event.spirit_spring.requirement is invalid")
    realm_key = _string(requirement["realm_key"], "event.spirit_spring.requirement.realm_key")
    content.require("realm", realm_key, include_locked=False)
    return realm_key, _positive_int(requirement["min_layer"], "event.spirit_spring.requirement.min_layer")


def _string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContentError(f"{label} must be a non-empty string")
    return value.strip()


def _positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ContentError(f"{label} must be a positive integer")
    return value


def _bounded_int(value: Any, minimum: int, maximum: int, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ContentError(f"{label} is outside supported range")
    return value


__all__ = [
    "SPIRIT_SPRING_EVENT_KEY",
    "SpiritSpringDefinition",
    "round_id_for",
    "spirit_spring_definition",
    "spirit_spring_result",
    "spirit_spring_snapshot",
    "spirit_spring_window",
]
