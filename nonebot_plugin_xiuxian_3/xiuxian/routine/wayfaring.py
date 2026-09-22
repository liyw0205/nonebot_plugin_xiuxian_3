"""Deterministic rules for the v0.1 wayfaring pass.

The pass is deliberately a pure content module.  Persistence, entitlement
checks and point-event idempotency belong to the repository layer; this file
only defines stable keys, caps and reward/source snapshots.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Mapping


WAYFARING_PASS_KEY = "pass.wayfaring.v0.1"
WAYFARING_CONTENT_VERSION = "content-0.1"
WAYFARING_RULE_VERSION = "wayfaring-0.1.0"
WAYFARING_CYCLE_DAYS = 28
WAYFARING_MAX_LEVEL = 30
WAYFARING_LEVEL_COUNT = WAYFARING_MAX_LEVEL
WAYFARING_POINTS_PER_LEVEL = 80
WAYFARING_TOTAL_POINTS = WAYFARING_MAX_LEVEL * WAYFARING_POINTS_PER_LEVEL
WAYFARING_DAILY_POINT_CAP = 100
WAYFARING_WEEKLY_POINT_CAP = 500
WAYFARING_LEVELS: tuple[int, ...] = tuple(range(1, WAYFARING_MAX_LEVEL + 1))

# Display/title keys are lightweight inventory flags; the water coupon is a
# registered bound token. The paid track is gated by the verified monthly dao
# contract in the repository layer.
WAYFARING_TITLE_REWARD = "title.wayfaring.pathfinder"
WAYFARING_RECIPE_CLUE = "item.clue.recipe_basic"
WAYFARING_TREE_WATER_COUPON = "item.token.spirit_tree_water"


@dataclass(frozen=True, slots=True)
class WayfaringSourceDefinition:
    key: str
    label: str
    points: int


# Source values are intentionally small.  A caller may submit a quantity for
# batched events, while the daily and weekly caps are enforced by persistence.
WAYFARING_SOURCES: Mapping[str, WayfaringSourceDefinition] = {
    "player.start_seeking": WayfaringSourceDefinition("player.start_seeking", "寻仙问道", 10),
    "routine.checkin.daily": WayfaringSourceDefinition("routine.checkin.daily", "道历问安", 20),
    "routine.spirit_tree.water": WayfaringSourceDefinition("routine.spirit_tree.water", "浇灌灵木", 5),
    "routine.spirit_tree.harvest": WayfaringSourceDefinition("routine.spirit_tree.harvest", "收获灵木", 30),
    "explore.gather_outskirts": WayfaringSourceDefinition("explore.gather_outskirts", "近郊采集", 20),
    "exploration.settle": WayfaringSourceDefinition("exploration.settle", "完成探索", 20),
    "production.complete": WayfaringSourceDefinition("production.complete", "完成生产", 25),
    "bounty.accept": WayfaringSourceDefinition("bounty.accept", "接取悬赏", 15),
    "bounty.claim": WayfaringSourceDefinition("bounty.claim", "领取悬赏", 25),
    "dao_contract.daily": WayfaringSourceDefinition("dao_contract.daily", "领取道契", 10),
}


# Free rewards contain ordinary materials, local reputation and display-only
# title flags.  They never grant cultivation, breakthrough resources or a
# payment entitlement.
_FREE_REWARDS: tuple[dict[str, int], ...] = (
    {"item.herb.blood_grass": 2},
    {"item.herb.spirit_leaf": 2},
    {"item.mat.wood": 3},
    {"local_reputation": 2},
    {"item.mat.array_sand": 2},
    {"item.ore.ironstone": 2},
    {WAYFARING_TITLE_REWARD: 1},
    {"item.herb.blood_grass": 3},
    {"item.herb.spirit_leaf": 3},
    {"local_reputation": 3},
    {"item.mat.wood": 4},
    {"item.mat.array_sand": 3},
    {"item.ore.ironstone": 3},
    {"title.wayfaring.trailblazer": 1},
    {"local_reputation": 4},
    {"item.herb.blood_grass": 4},
    {"item.herb.spirit_leaf": 4},
    {"item.mat.wood": 5},
    {"item.mat.array_sand": 4},
    {"title.wayfaring.seeker": 1},
    {"local_reputation": 5},
    {"item.ore.ironstone": 4},
    {"item.herb.blood_grass": 5},
    {"item.herb.spirit_leaf": 5},
    {"item.mat.array_sand": 5},
    {"item.mat.wood": 6},
    {"local_reputation": 6},
    {"item.ore.ironstone": 5},
    {"item.herb.spirit_leaf": 6},
    {"title.wayfaring.wayfarer": 1},
)


# The paid line adds only display, recipe clues and a tree-watering token. It
# does not duplicate the free reward or grant ordinary payment credentials.
_PAID_REWARDS: tuple[dict[str, int], ...] = (
    {WAYFARING_TITLE_REWARD: 1},
    {WAYFARING_RECIPE_CLUE: 1},
    {WAYFARING_TREE_WATER_COUPON: 1},
    {WAYFARING_RECIPE_CLUE: 1},
    {"title.wayfaring.licensed": 1},
    {WAYFARING_TREE_WATER_COUPON: 1},
    {WAYFARING_RECIPE_CLUE: 1},
    {WAYFARING_TREE_WATER_COUPON: 1},
    {WAYFARING_RECIPE_CLUE: 1},
    {"title.wayfaring.licensed": 1},
    {WAYFARING_TREE_WATER_COUPON: 1},
    {WAYFARING_RECIPE_CLUE: 1},
    {WAYFARING_TREE_WATER_COUPON: 1},
    {WAYFARING_RECIPE_CLUE: 1},
    {"title.wayfaring.licensed": 1},
    {WAYFARING_TREE_WATER_COUPON: 1},
    {WAYFARING_RECIPE_CLUE: 1},
    {WAYFARING_TREE_WATER_COUPON: 1},
    {WAYFARING_RECIPE_CLUE: 1},
    {"title.wayfaring.licensed": 1},
    {WAYFARING_TREE_WATER_COUPON: 1},
    {WAYFARING_RECIPE_CLUE: 1},
    {WAYFARING_TREE_WATER_COUPON: 1},
    {WAYFARING_RECIPE_CLUE: 1},
    {"title.wayfaring.licensed": 1},
    {WAYFARING_TREE_WATER_COUPON: 1},
    {WAYFARING_RECIPE_CLUE: 1},
    {WAYFARING_TREE_WATER_COUPON: 1},
    {WAYFARING_RECIPE_CLUE: 1},
    {"title.wayfaring.licensed": 1},
)


def _level(level: int) -> int:
    if isinstance(level, bool):
        raise ValueError("level must be an integer between 1 and 30")
    try:
        value = int(level)
    except (TypeError, ValueError) as exc:
        raise ValueError("level must be an integer between 1 and 30") from exc
    if value != level or value not in WAYFARING_LEVELS:
        raise ValueError("level must be an integer between 1 and 30")
    return value


def wayfaring_level_for_points(points: int) -> int:
    """Return the earned level, with zero meaning no level is unlocked."""

    if isinstance(points, bool):
        raise ValueError("points must be a non-negative integer")
    try:
        value = int(points)
    except (TypeError, ValueError) as exc:
        raise ValueError("points must be a non-negative integer") from exc
    if value != points or value < 0:
        raise ValueError("points must be a non-negative integer")
    return min(WAYFARING_MAX_LEVEL, value // WAYFARING_POINTS_PER_LEVEL)


def wayfaring_points_for_level(level: int) -> int:
    """Return the cumulative points required to unlock ``level``."""

    return _level(level) * WAYFARING_POINTS_PER_LEVEL


def wayfaring_source_points(source_key: str, quantity: int = 1) -> int:
    """Resolve a registered source into points.

    Unknown sources are rejected so an operation cannot silently mint pass
    progress.  Daily and weekly limits are intentionally left to the caller,
    which has the persisted point-event snapshot available.
    """

    definition = WAYFARING_SOURCES.get(str(source_key))
    if definition is None:
        raise ValueError(f"unknown wayfaring source: {source_key}")
    try:
        amount = int(quantity)
    except (TypeError, ValueError) as exc:
        raise ValueError("quantity must be a positive integer") from exc
    if isinstance(quantity, bool) or amount != quantity or amount <= 0:
        raise ValueError("quantity must be a positive integer")
    return definition.points * amount


def wayfaring_free_reward(level: int) -> dict[str, int]:
    """Return a copy of the free-track reward for ``level``."""

    return dict(_FREE_REWARDS[_level(level) - 1])


def wayfaring_paid_reward(level: int) -> dict[str, int]:
    """Return a copy of the paid-track reward for ``level``."""

    return dict(_PAID_REWARDS[_level(level) - 1])


def wayfaring_level_reward(level: int, premium: bool = False) -> dict[str, int]:
    """Return the selected track's immutable reward snapshot."""

    return wayfaring_paid_reward(level) if premium else wayfaring_free_reward(level)


def _coerce_date(value: date | datetime | str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("business date must be ISO-8601") from exc
    raise TypeError("business date must be a date, datetime, or ISO string")


def wayfaring_week_start(value: date | datetime | str) -> date:
    """Return the Monday containing a business date."""

    current = _coerce_date(value)
    return current - timedelta(days=current.weekday())


def wayfaring_cycle_window(cycle_start: date | datetime | str) -> tuple[date, date]:
    """Return inclusive start/end dates for a 28-business-day calendar cycle."""

    start = _coerce_date(cycle_start)
    return start, start + timedelta(days=WAYFARING_CYCLE_DAYS - 1)


__all__ = [
    "WAYFARING_CONTENT_VERSION",
    "WAYFARING_CYCLE_DAYS",
    "WAYFARING_DAILY_POINT_CAP",
    "WAYFARING_LEVEL_COUNT",
    "WAYFARING_LEVELS",
    "WAYFARING_MAX_LEVEL",
    "WAYFARING_PASS_KEY",
    "WAYFARING_POINTS_PER_LEVEL",
    "WAYFARING_RECIPE_CLUE",
    "WAYFARING_RULE_VERSION",
    "WAYFARING_SOURCES",
    "WAYFARING_TITLE_REWARD",
    "WAYFARING_TOTAL_POINTS",
    "WAYFARING_TREE_WATER_COUPON",
    "WAYFARING_WEEKLY_POINT_CAP",
    "WayfaringSourceDefinition",
    "wayfaring_cycle_window",
    "wayfaring_free_reward",
    "wayfaring_level_for_points",
    "wayfaring_level_reward",
    "wayfaring_paid_reward",
    "wayfaring_points_for_level",
    "wayfaring_source_points",
    "wayfaring_week_start",
]
