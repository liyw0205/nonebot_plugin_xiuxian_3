"""Content-backed rules shared by recurring public events."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from ..content import ContentBundle, ContentError, bundled_content
from ..rewards.rules import RewardGrant, reward_definition

_CONTRIBUTION_FIELDS = {
    "battle_damage": {"source", "damage_per_point"},
    "settled_transport": {"source", "quantity"},
    "paid_active_personal_maintenance": {"source", "quantity"},
    "completed_cross_realm_trade": {"source", "quantity", "trade_keys"},
    "consume_item": {"source", "item_key", "item_quantity", "quantity"},
    "settled_boundary_party_battle": {"source", "quantity", "party_types"},
    "completed_ancient_domain": {"source", "quantity"},
}


@dataclass(frozen=True, slots=True)
class PublicEventDefinition:
    key: str
    location_key: str
    schedule: dict[str, Any]
    target_quantity: int
    contributions: dict[str, dict[str, Any]]
    required_realm_key: str | None
    required_realm_layer: int
    minimum_contribution: int
    reward: RewardGrant

    def snapshot(self) -> dict[str, Any]:
        return {
            "event_key": self.key,
            "location_key": self.location_key,
            "schedule": copy.deepcopy(self.schedule),
            "target_quantity": self.target_quantity,
            "contributions": copy.deepcopy(self.contributions),
            "required_realm_key": self.required_realm_key,
            "required_realm_layer": self.required_realm_layer,
            "minimum_contribution": self.minimum_contribution,
            "reward": self.reward.snapshot(),
        }


def public_event_definition(
    event_key: str,
    content: ContentBundle | None = None,
) -> PublicEventDefinition:
    bundle = content or bundled_content()
    try:
        event = bundle.require("event", event_key, include_locked=False)
        raw = event["public_event"]
        if not isinstance(raw, dict):
            raise ContentError(f"event {event_key} public_event must be an object")
        expected_fields = {"location_key", "schedule", "target_quantity", "requirement", "contributions", "claim"}
        if set(raw) != expected_fields:
            raise ContentError(f"event {event_key} public_event fields are invalid")
        location_key = _string(raw.get("location_key"), f"{event_key}.location_key")
        bundle.require("location", location_key, include_locked=False)
        schedule = _schedule(raw.get("schedule"), event_key)
        target_quantity = _positive_int(raw.get("target_quantity"), f"{event_key}.target_quantity")
        contributions = _contributions(event_key, raw.get("contributions"), bundle)
        requirement = raw.get("requirement")
        if requirement is None:
            required_realm_key = None
            required_realm_layer = 0
        else:
            if not isinstance(requirement, dict) or set(requirement) != {"realm_key", "min_layer"}:
                raise ContentError(f"event {event_key} requirement must be an object")
            required_realm_key = _string(
                requirement.get("realm_key"), f"{event_key}.requirement.realm_key"
            )
            bundle.require("realm", required_realm_key, include_locked=False)
            required_realm_layer = _positive_int(
                requirement.get("min_layer"), f"{event_key}.requirement.min_layer"
            )
        claim = raw.get("claim")
        if not isinstance(claim, dict) or set(claim) != {"min_contribution", "reward_key"}:
            raise ContentError(f"event {event_key} claim must be an object")
        minimum_contribution = _positive_int(
            claim.get("min_contribution"), f"{event_key}.claim.min_contribution"
        )
        reward_key = _string(claim.get("reward_key"), f"{event_key}.claim.reward_key")
        reward = reward_definition(reward_key, bundle, operation=f"{event_key}.claim_reward")
        return PublicEventDefinition(
            event_key,
            location_key,
            schedule,
            target_quantity,
            contributions,
            required_realm_key,
            required_realm_layer,
            minimum_contribution,
            reward,
        )
    except KeyError as exc:
        raise ContentError(f"public event content is incomplete: {event_key}: {exc}") from exc


def public_event_snapshot(event_key: str, result_json: str) -> PublicEventDefinition:
    import json

    try:
        result = json.loads(result_json)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ContentError(f"public event result is invalid: {event_key}") from exc
    if not isinstance(result, dict):
        raise ContentError(f"public event result must be an object: {event_key}")
    snapshot = result.get("configuration")
    if not isinstance(snapshot, dict) or snapshot.get("event_key") != event_key:
        raise ContentError(f"public event configuration snapshot is missing: {event_key}")
    if set(snapshot) != {
        "event_key",
        "location_key",
        "schedule",
        "target_quantity",
        "contributions",
        "required_realm_key",
        "required_realm_layer",
        "minimum_contribution",
        "reward",
    }:
        raise ContentError(f"public event configuration snapshot has invalid fields: {event_key}")
    try:
        reward = _reward_snapshot(snapshot.get("reward"), event_key)
        schedule = _schedule(snapshot.get("schedule"), event_key)
        contributions = _contributions_from_snapshot(event_key, snapshot.get("contributions"))
        location_key = _string(snapshot.get("location_key"), f"{event_key}.location_key")
        target_quantity = _positive_int(
            snapshot.get("target_quantity"), f"{event_key}.target_quantity"
        )
        minimum_contribution = _positive_int(
            snapshot.get("minimum_contribution"), f"{event_key}.minimum_contribution"
        )
        required_realm_key = snapshot.get("required_realm_key")
        if required_realm_key is not None:
            required_realm_key = _string(
                required_realm_key, f"{event_key}.required_realm_key"
            )
        required_realm_layer = snapshot.get("required_realm_layer")
        if (
            isinstance(required_realm_layer, bool)
            or not isinstance(required_realm_layer, int)
            or required_realm_layer < 0
        ):
            raise ContentError(f"event {event_key} snapshot has invalid realm layer")
        if (required_realm_key is None) != (required_realm_layer == 0):
            raise ContentError(f"event {event_key} snapshot realm requirement is incomplete")
        return PublicEventDefinition(
            event_key,
            location_key,
            schedule,
            target_quantity,
            contributions,
            required_realm_key,
            required_realm_layer,
            minimum_contribution,
            reward,
        )
    except (KeyError, TypeError) as exc:
        raise ContentError(f"public event configuration snapshot is invalid: {event_key}") from exc


def public_event_window(
    definition: PublicEventDefinition,
    now: datetime,
) -> tuple[str, datetime, datetime, datetime] | None:
    value = now.astimezone(timezone.utc)
    schedule = definition.schedule
    if schedule["kind"] == "weekly":
        start = value.replace(
            hour=schedule["hour_utc"],
            minute=schedule["minute_utc"],
            second=0,
            microsecond=0,
        )
        start -= timedelta(days=(value.weekday() - schedule["weekday_utc"]) % 7)
        if start > value:
            start -= timedelta(days=7)
    else:
        block_hours = schedule["block_hours"]
        start = value.replace(minute=0, second=0, microsecond=0)
        start = start.replace(hour=(start.hour // block_hours) * block_hours)
    end = start + timedelta(seconds=schedule["duration_seconds"])
    if not start <= value < end:
        return None
    claim_expires_at = end + timedelta(seconds=schedule["claim_window_seconds"])
    return (
        f"{definition.key}:{start:%Y%m%d%H%M}",
        start,
        end,
        claim_expires_at,
    )


def public_event_is_open(
    event_key: str,
    now: datetime,
    content: ContentBundle | None = None,
) -> bool:
    return public_event_window(public_event_definition(event_key, content), now) is not None


def _schedule(value: Any, event_key: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContentError(f"event {event_key} schedule must be an object")
    kind = value.get("kind")
    duration = _positive_int(value.get("duration_seconds"), f"{event_key}.duration_seconds")
    claim_window = _positive_int(
        value.get("claim_window_seconds"), f"{event_key}.claim_window_seconds"
    )
    if kind == "weekly":
        allowed = {
            "kind",
            "weekday_utc",
            "hour_utc",
            "minute_utc",
            "duration_seconds",
            "claim_window_seconds",
        }
        if set(value) != allowed:
            raise ContentError(f"event {event_key} weekly schedule fields are invalid")
        weekday = _bounded_int(value.get("weekday_utc"), 0, 6, f"{event_key}.weekday_utc")
        hour = _bounded_int(value.get("hour_utc"), 0, 23, f"{event_key}.hour_utc")
        minute = _bounded_int(value.get("minute_utc"), 0, 59, f"{event_key}.minute_utc")
        return {
            "kind": kind,
            "weekday_utc": weekday,
            "hour_utc": hour,
            "minute_utc": minute,
            "duration_seconds": duration,
            "claim_window_seconds": claim_window,
        }
    if kind == "utc_block":
        if set(value) != {"kind", "block_hours", "duration_seconds", "claim_window_seconds"}:
            raise ContentError(f"event {event_key} UTC block schedule fields are invalid")
        block_hours = _bounded_int(value.get("block_hours"), 1, 24, f"{event_key}.block_hours")
        if 24 % block_hours or duration != block_hours * 3600:
            raise ContentError(f"event {event_key} UTC block duration is invalid")
        return {
            "kind": kind,
            "block_hours": block_hours,
            "duration_seconds": duration,
            "claim_window_seconds": claim_window,
        }
    raise ContentError(f"event {event_key} has unsupported schedule kind")


def _contributions(event_key: str, value: Any, content: ContentBundle) -> dict[str, dict[str, Any]]:
    if not isinstance(value, dict) or not value:
        raise ContentError(f"event {event_key} contributions must be a non-empty object")
    normalized: dict[str, dict[str, Any]] = {}
    for action_key, raw in value.items():
        normalized[action_key] = _contribution_entry(event_key, action_key, raw, content)
    return normalized


def _contributions_from_snapshot(event_key: str, value: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(value, dict):
        raise ContentError(f"event {event_key} snapshot contributions must be an object")
    normalized: dict[str, dict[str, Any]] = {}
    for action_key, entry in value.items():
        normalized[action_key] = _contribution_entry(event_key, action_key, entry)
    return normalized


def _contribution_entry(
    event_key: str,
    action_key: Any,
    value: Any,
    content: ContentBundle | None = None,
) -> dict[str, Any]:
    label = f"{event_key}.{action_key}"
    _string(action_key, f"{event_key}.contribution action")
    if not isinstance(value, dict):
        raise ContentError(f"{label} contribution must be an object")
    source = _string(value.get("source"), f"{label}.source")
    if set(value) != _CONTRIBUTION_FIELDS.get(source):
        raise ContentError(f"{label} contribution fields are invalid")
    entry: dict[str, Any] = {"source": source}
    if source == "battle_damage":
        entry["damage_per_point"] = _positive_int(value.get("damage_per_point"), label)
    elif source == "consume_item":
        item_key = _string(value.get("item_key"), f"{label}.item_key")
        if content is not None:
            content.require("item", item_key, include_locked=False)
        entry.update(
            {
                "item_key": item_key,
                "item_quantity": _positive_int(value.get("item_quantity"), label),
                "quantity": _positive_int(value.get("quantity"), label),
            }
        )
    elif source == "completed_cross_realm_trade":
        entry["quantity"] = _positive_int(value.get("quantity"), label)
        trade_keys = _string_list(value.get("trade_keys"), f"{label}.trade_keys")
        if content is not None:
            available_trades = {
                action.removeprefix("economy.")
                for location in content.list("location", include_locked=False)
                for action in location.get("actions", [])
                if isinstance(action, str) and action.startswith("economy.trade.")
            }
            missing = sorted(set(trade_keys) - available_trades)
            if missing:
                raise ContentError(f"{label}.trade_keys references unavailable trades: {missing!r}")
        entry["trade_keys"] = trade_keys
    elif source == "settled_boundary_party_battle":
        entry["quantity"] = _positive_int(value.get("quantity"), label)
        entry["party_types"] = _string_list(value.get("party_types"), f"{label}.party_types")
    else:
        entry["quantity"] = _positive_int(value.get("quantity"), label)
    return entry


def _string_list(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ContentError(f"{label} must be a non-empty string list")
    normalized = [_string(item, label) for item in value]
    if len(set(normalized)) != len(normalized):
        raise ContentError(f"{label} contains duplicates")
    return normalized


def _reward_snapshot(value: Any, event_key: str) -> RewardGrant:
    if not isinstance(value, dict):
        raise ContentError(f"event {event_key} reward snapshot must be an object")
    grant_key = _string(value.get("key"), f"{event_key}.reward.key")
    operation = _string(value.get("operation"), f"{event_key}.reward.operation")
    if operation != f"{event_key}.claim_reward":
        raise ContentError(f"event {event_key} reward snapshot operation is invalid")
    maps: dict[str, dict[str, int]] = {}
    for map_key in ("assets", "value_delta", "set_values", "reputation"):
        raw_map = value.get(map_key)
        if not isinstance(raw_map, dict):
            raise ContentError(f"event {event_key} reward snapshot {map_key} must be an object")
        normalized: dict[str, int] = {}
        for key, quantity in raw_map.items():
            if not isinstance(key, str) or isinstance(quantity, bool) or not isinstance(quantity, int):
                raise ContentError(f"event {event_key} reward snapshot contains an invalid value")
            if map_key in {"assets", "set_values"} and quantity <= 0:
                raise ContentError(f"event {event_key} reward snapshot quantity must be positive")
            normalized[key] = quantity
        maps[map_key] = normalized
    return RewardGrant(grant_key, operation, maps["assets"], maps["value_delta"], maps["set_values"], maps["reputation"])


def _string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ContentError(f"{label} must be a non-empty string")
    return value


def _positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ContentError(f"{label} must be a positive integer")
    return value


def _bounded_int(value: Any, minimum: int, maximum: int, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ContentError(f"{label} is outside the supported range")
    return value


__all__ = [
    "PublicEventDefinition",
    "public_event_definition",
    "public_event_is_open",
    "public_event_snapshot",
    "public_event_window",
]
