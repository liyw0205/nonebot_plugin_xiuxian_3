"""Validated wayfaring rules and self-contained cycle snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from ..content import ContentBundle, ContentError, bundled_content
from ..rewards.rules import local_reputation_maximum
from .rules import honor_title

WAYFARING_PASS_KEY = "pass.wayfaring"

_SOURCE_OPERATIONS = {
    "player.start_seeking": "player.start_seeking",
    "routine.checkin.daily": "routine.checkin.daily",
    "routine.spirit_tree.water": "routine.spirit_tree.water",
    "routine.spirit_tree.harvest": "routine.spirit_tree.harvest",
    "production.complete": "production.complete",
    "bounty.claim": "bounty.claim",
    "exploration.settle": "exploration.settle",
    "routine.claim_dao_contract": "dao_contract.daily",
}
_PAID_ITEM_KEYS = frozenset({"item.clue.recipe_basic", "item.token.spirit_tree_water"})
_SNAPSHOT_FIELDS = frozenset(
    {
        "key",
        "name",
        "cycle_days",
        "max_level",
        "points_per_level",
        "daily_point_cap",
        "weekly_point_cap",
        "sources",
        "free_rewards",
        "paid_rewards",
        "local_reputation_key",
        "local_reputation_maximum",
        "reward_labels",
    }
)


@dataclass(frozen=True, slots=True)
class WayfaringDefinition:
    key: str
    name: str
    cycle_days: int
    max_level: int
    points_per_level: int
    daily_point_cap: int
    weekly_point_cap: int
    sources: dict[str, dict[str, Any]]
    free_rewards: tuple[dict[str, int], ...]
    paid_rewards: tuple[dict[str, int], ...]
    local_reputation_key: str
    local_reputation_maximum: int
    reward_labels: dict[str, str]

    @property
    def total_points(self) -> int:
        return self.max_level * self.points_per_level

    def level_for_points(self, points: int) -> int:
        if isinstance(points, bool) or not isinstance(points, int) or points < 0:
            raise ContentError("wayfaring points must be a non-negative integer")
        return min(self.max_level, points // self.points_per_level)

    def reward(self, level: int, track: str) -> dict[str, int]:
        if (
            isinstance(level, bool)
            or not isinstance(level, int)
            or not 1 <= level <= self.max_level
            or not isinstance(track, str)
            or track not in {"free", "paid"}
        ):
            raise ContentError("invalid wayfaring reward level or track")
        rewards = self.free_rewards if track == "free" else self.paid_rewards
        return dict(rewards[level - 1])

    def snapshot(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "name": self.name,
            "cycle_days": self.cycle_days,
            "max_level": self.max_level,
            "points_per_level": self.points_per_level,
            "daily_point_cap": self.daily_point_cap,
            "weekly_point_cap": self.weekly_point_cap,
            "sources": {key: dict(value) for key, value in self.sources.items()},
            "free_rewards": [dict(reward) for reward in self.free_rewards],
            "paid_rewards": [dict(reward) for reward in self.paid_rewards],
            "local_reputation_key": self.local_reputation_key,
            "local_reputation_maximum": self.local_reputation_maximum,
            "reward_labels": dict(self.reward_labels),
        }


def wayfaring_definition(content: ContentBundle | None = None) -> WayfaringDefinition:
    bundle = content or bundled_content()
    row = bundle.get("wayfaring_pass", WAYFARING_PASS_KEY)
    if row is None or row.get("status") not in ("active", "open"):
        raise ContentError("wayfaring pass is missing or inactive")
    expected = (_SNAPSHOT_FIELDS - {"local_reputation_maximum", "reward_labels"}) | {
        "status",
        "desc",
    }
    if set(row) != expected:
        raise ContentError("wayfaring content fields are invalid")
    _text(row.get("desc"), "description")
    try:
        maximum = local_reputation_maximum(row.get("local_reputation_key"), bundle)
    except TypeError as exc:
        raise ContentError("wayfaring local reputation content is invalid") from exc
    rewards = _parse_rewards(row.get("free_rewards"), row.get("max_level"), "free")
    paid_rewards = _parse_rewards(row.get("paid_rewards"), row.get("max_level"), "paid")
    keys = {key for reward in (*rewards, *paid_rewards) for key in reward}
    labels: dict[str, str] = {}
    free_items = {
        key for reward in rewards for key in reward if key.startswith("item.")
    }
    for key in keys:
        if key == "local_reputation":
            location = bundle.get(
                "location", row["local_reputation_key"].removeprefix("local.")
            )
            labels[key] = (
                _text(location.get("name") if location else None, "location name")
                + "名望"
            )
        elif key.startswith("title."):
            labels[key] = _title_label(key)
        else:
            item = bundle.get("item", key)
            if item is None or item.get("status") not in ("active", "open"):
                raise ContentError(
                    f"wayfaring reward references an inactive item: {key}"
                )
            if key in free_items:
                effects = item.get("effects")
                if (
                    not isinstance(effects, list)
                    or not effects
                    or any(
                        not isinstance(effect, dict)
                        or effect.get("type") != "crafting_material"
                        for effect in effects
                    )
                ):
                    raise ContentError(
                        f"wayfaring free reward must be an ordinary material: {key}"
                    )
            labels[key] = _text(item.get("name"), f"reward label {key}")
    snapshot = {
        key: value for key, value in row.items() if key not in {"status", "desc"}
    }
    snapshot.update(local_reputation_maximum=maximum, reward_labels=labels)
    return parse_wayfaring_snapshot(snapshot)


def parse_wayfaring_snapshot(value: Any) -> WayfaringDefinition:
    if not isinstance(value, dict) or set(value) != _SNAPSHOT_FIELDS:
        raise ContentError("wayfaring snapshot fields are invalid")
    if value.get("key") != WAYFARING_PASS_KEY:
        raise ContentError("wayfaring snapshot identity is invalid")
    name = _text(value.get("name"), "name")
    numbers = {
        field: _positive_integer(value.get(field), field)
        for field in (
            "cycle_days",
            "max_level",
            "points_per_level",
            "daily_point_cap",
            "weekly_point_cap",
            "local_reputation_maximum",
        )
    }
    _require_reachable_cycle(
        numbers["cycle_days"],
        numbers["daily_point_cap"],
        numbers["weekly_point_cap"],
        numbers["max_level"] * numbers["points_per_level"],
    )
    sources = _parse_sources(value.get("sources"))
    free_rewards = _parse_rewards(
        value.get("free_rewards"), numbers["max_level"], "free"
    )
    paid_rewards = _parse_rewards(
        value.get("paid_rewards"), numbers["max_level"], "paid"
    )
    reputation_key = value.get("local_reputation_key")
    if (
        not isinstance(reputation_key, str)
        or not reputation_key.startswith("local.")
        or not reputation_key.removeprefix("local.").strip()
        or reputation_key != reputation_key.strip()
    ):
        raise ContentError("wayfaring local reputation key is invalid")
    reward_keys = {key for reward in (*free_rewards, *paid_rewards) for key in reward}
    labels = value.get("reward_labels")
    if not isinstance(labels, dict) or set(labels) != reward_keys:
        raise ContentError("wayfaring reward labels must match its rewards")
    return WayfaringDefinition(
        key=WAYFARING_PASS_KEY,
        name=name,
        **numbers,
        sources=sources,
        free_rewards=free_rewards,
        paid_rewards=paid_rewards,
        local_reputation_key=reputation_key,
        reward_labels={
            key: _text(label, f"reward label {key}") for key, label in labels.items()
        },
    )


def _parse_sources(value: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(value, dict) or set(value) != set(_SOURCE_OPERATIONS):
        raise ContentError("wayfaring sources must match settled source operations")
    result: dict[str, dict[str, Any]] = {}
    for operation, source_key in _SOURCE_OPERATIONS.items():
        source = value[operation]
        if (
            not isinstance(source, dict)
            or set(source) != {"key", "name", "points"}
            or source.get("key") != source_key
        ):
            raise ContentError(f"invalid wayfaring source: {operation}")
        result[operation] = {
            "key": source_key,
            "name": _text(source.get("name"), f"source name {operation}"),
            "points": _positive_integer(
                source.get("points"), f"source points {operation}"
            ),
        }
    return result


def _parse_rewards(
    value: Any, max_level: Any, track: str
) -> tuple[dict[str, int], ...]:
    levels = _positive_integer(max_level, "max_level")
    if not isinstance(value, list) or len(value) != levels:
        raise ContentError(f"wayfaring {track} rewards must cover every level")
    rewards: list[dict[str, int]] = []
    for level, reward in enumerate(value, start=1):
        if not isinstance(reward, dict) or not reward:
            raise ContentError(f"wayfaring {track} reward {level} must not be empty")
        normalized: dict[str, int] = {}
        for key, amount in reward.items():
            if not isinstance(key, str):
                raise ContentError("wayfaring reward keys must be strings")
            quantity = _positive_integer(amount, f"reward {key}")
            if key.startswith("title."):
                _title_label(key)
                if quantity != 1:
                    raise ContentError("wayfaring title reward quantity must be one")
            elif track == "paid":
                if key not in _PAID_ITEM_KEYS:
                    raise ContentError(f"unsupported wayfaring paid reward: {key}")
            elif key != "local_reputation" and not key.startswith(
                ("item.herb.", "item.mat.", "item.ore.")
            ):
                raise ContentError(f"unsupported wayfaring free reward: {key}")
            normalized[key] = quantity
        rewards.append(normalized)
    return tuple(rewards)


def _require_reachable_cycle(
    days: int, daily_cap: int, weekly_cap: int, target: int
) -> None:
    for weekday in range(7):
        first_week = min(days, 7 - weekday)
        full_weeks, last_week = divmod(days - first_week, 7)
        maximum = (
            min(first_week * daily_cap, weekly_cap)
            + full_weeks * min(7 * daily_cap, weekly_cap)
            + min(last_week * daily_cap, weekly_cap)
        )
        if maximum < target:
            raise ContentError(
                "wayfaring maximum level is unreachable within its cycle"
            )


def _positive_integer(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ContentError(f"wayfaring {field} must be a positive integer")
    return value


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContentError(f"wayfaring {field} must be a non-empty string")
    return value.strip()


def _title_label(key: str) -> str:
    try:
        definition = honor_title(key)
    except ValueError as exc:
        raise ContentError(
            f"wayfaring reward references an unknown title: {key}"
        ) from exc
    if definition.closed:
        raise ContentError(f"wayfaring reward references an inactive title: {key}")
    return definition.label


def wayfaring_week_start(value: date | datetime | str) -> date:
    if isinstance(value, datetime):
        current = value.date()
    elif isinstance(value, date):
        current = value
    elif isinstance(value, str):
        try:
            current = date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("business date must be ISO-8601") from exc
    else:
        raise TypeError("business date must be a date, datetime, or ISO string")
    return current - timedelta(days=current.weekday())


__all__ = [
    "WAYFARING_PASS_KEY",
    "WayfaringDefinition",
    "parse_wayfaring_snapshot",
    "wayfaring_definition",
    "wayfaring_week_start",
]
