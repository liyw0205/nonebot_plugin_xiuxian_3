"""Pure, versioned rules for the v0.1 routine slice."""

from __future__ import annotations

from datetime import date, timedelta
import hashlib


RULE_VERSION = "routine-0.1.0"
CONTENT_VERSION = "content-0.1"
CHECKIN_ACTIVITY = "ritual.checkin.daily"
MAKEUP_ACTIVITY = "ritual.makeup.daily"
TREE_WATER_ACTIVITY = "ritual.spirit_tree.water"
TREE_HARVEST_ACTIVITY = "ritual.spirit_tree.harvest"
FATE_TICKET = "item.ticket.fate_basic"
TREE_SEED = "item.seed.spirit_tree"


def parse_past_date(value: str, today: date) -> date:
    """Parse an ISO date and require a target in the previous three days."""

    try:
        target = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("invalid business date") from exc
    age = (today - target).days
    if age < 1 or age > 3:
        raise ValueError("date is outside the makeup window")
    if target.month != today.month or target.year != today.year:
        raise ValueError("date is outside the current business month")
    return target


def parse_iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("invalid business date") from exc


def checkin_reward(streak: int) -> dict[str, int]:
    reward = {"spirit_stones": 20, "energy": 3}
    if streak > 0 and streak % 7 == 0:
        reward[FATE_TICKET] = 1
    return reward


def makeup_reward() -> dict[str, int]:
    # The documented 80% reward is rounded down for integer assets.
    return {"spirit_stones": 16, "energy": 2}


def tree_harvest_reward(operation_id: str) -> dict[str, int]:
    digest = hashlib.blake2b(
        f"tree.harvest.v0.1:{operation_id}".encode("utf-8"), digest_size=16
    ).digest()
    bucket = int.from_bytes(digest[:8], "big") % 100
    stone_bucket = int.from_bytes(digest[8:], "big") % 100
    spirit_stones = 80 if stone_bucket < 25 else 120 if stone_bucket >= 75 else 100
    reward = {"spirit_stones": spirit_stones, "local_reputation": 2}
    if bucket < 30:
        reward[TREE_SEED] = 1
    return reward


def tree_status(water_count: int, cooldown_until: str | None, now_iso: str) -> str:
    if cooldown_until and now_iso < cooldown_until:
        return "cooldown"
    if water_count >= 7:
        return "ready"
    if water_count:
        return "watered"
    return "dormant"


def next_date(value: date) -> date:
    return value + timedelta(days=1)


__all__ = [
    "CHECKIN_ACTIVITY",
    "CONTENT_VERSION",
    "FATE_TICKET",
    "MAKEUP_ACTIVITY",
    "RULE_VERSION",
    "TREE_HARVEST_ACTIVITY",
    "TREE_SEED",
    "TREE_WATER_ACTIVITY",
    "checkin_reward",
    "makeup_reward",
    "next_date",
    "parse_iso_date",
    "parse_past_date",
    "tree_harvest_reward",
    "tree_status",
]
