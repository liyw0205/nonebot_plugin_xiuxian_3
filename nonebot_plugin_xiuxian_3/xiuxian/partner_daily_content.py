"""Strict content contract for repeatable partner fieldwork."""

from __future__ import annotations

from typing import Any

from .content import ContentBundle, ContentError, bundled_content
from .exploration.deposit_rules import deposit_definitions

KIND = "partner_daily_task"
DEFAULTS_KEY = "task.partner.daily.fieldwork"
SOURCE_KIND = "deposit.extract"
FORBIDDEN_REWARD_ITEMS = {
    "item.tribulation_token",
    "item.ascension_certificate",
    "item.tribulation_guard",
    "item.dao_fruit_fragment",
    "item.domain_core",
}
REQUIRED_FIELDS = {
    "key",
    "name",
    "desc",
    "aliases",
    "status",
    "source_kind",
    "deposit_keys",
    "target_each",
    "window_seconds",
    "daily_limit",
    "reward_world_merit",
    "reward_items",
}


def _bundle(content: ContentBundle | None) -> ContentBundle:
    return content if content is not None else bundled_content()


def _text(row: dict[str, Any], field: str) -> str:
    value = row.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ContentError(f"partner daily task requires {field}")
    return value.strip()


def _positive_int(value: Any, field: str, *, maximum: int) -> int:
    if type(value) is not int or not 1 <= value <= maximum:
        raise ContentError(f"partner daily task {field} is outside its valid range")
    return value


def partner_daily_definition(content: ContentBundle | None = None) -> dict[str, Any]:
    bundle = _bundle(content)
    try:
        row = bundle.require(KIND, DEFAULTS_KEY, include_locked=True)
    except KeyError as exc:
        raise ContentError(f"missing partner daily task content: {DEFAULTS_KEY}") from exc
    if row.get("status") != "active":
        raise ContentError(f"{DEFAULTS_KEY} is not active")
    missing = REQUIRED_FIELDS - set(row)
    if missing:
        raise ContentError(f"{DEFAULTS_KEY} is missing fields: {sorted(missing)}")
    if _text(row, "source_kind") != SOURCE_KIND:
        raise ContentError(f"{DEFAULTS_KEY} has an unsupported source kind")

    raw_deposits = row.get("deposit_keys")
    deposits = deposit_definitions(bundle)
    if (not isinstance(raw_deposits, list) or not raw_deposits
            or any(not isinstance(key, str) or key not in deposits
                   or deposits[key]["status"] not in {"active", "open"} for key in raw_deposits)
            or len(set(raw_deposits)) != len(raw_deposits)):
        raise ContentError(f"{DEFAULTS_KEY} has invalid resource deposit references")

    raw_aliases = row.get("aliases")
    if not isinstance(raw_aliases, list) or any(not isinstance(alias, str) or not alias.strip()
                                                for alias in raw_aliases):
        raise ContentError(f"{DEFAULTS_KEY} aliases are malformed")
    aliases = [_text(row, "name"), *(alias.strip() for alias in raw_aliases)]
    if len(set(aliases)) != len(aliases):
        raise ContentError(f"{DEFAULTS_KEY} aliases are not unique")

    rewards = row.get("reward_items")
    if not isinstance(rewards, dict) or not rewards:
        raise ContentError(f"{DEFAULTS_KEY} reward_items must be a non-empty object")
    normalized_rewards: dict[str, int] = {}
    for item_key, quantity in rewards.items():
        if (not isinstance(item_key, str)
                or bundle.get("item", item_key, include_locked=False) is None
                or item_key in FORBIDDEN_REWARD_ITEMS):
            raise ContentError(f"{DEFAULTS_KEY} has an invalid reward item: {item_key!r}")
        normalized_rewards[item_key] = _positive_int(
            quantity, f"reward_items[{item_key}]", maximum=1000
        )

    daily_limit = _positive_int(row.get("daily_limit"), "daily_limit", maximum=1)
    if daily_limit != 1:
        raise ContentError(f"{DEFAULTS_KEY} must be limited to one task per UTC day")
    return {
        "key": DEFAULTS_KEY,
        "name": aliases[0],
        "description": _text(row, "desc"),
        "aliases": tuple(aliases),
        "source_kind": SOURCE_KIND,
        "deposit_keys": tuple(raw_deposits),
        "target_each": _positive_int(row.get("target_each"), "target_each", maximum=10),
        "window_seconds": _positive_int(row.get("window_seconds"), "window_seconds", maximum=86400),
        "daily_limit": daily_limit,
        "reward_world_merit": _positive_int(row.get("reward_world_merit"), "reward_world_merit", maximum=1000),
        "reward_items": normalized_rewards,
    }
