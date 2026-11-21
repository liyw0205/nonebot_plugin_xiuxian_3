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
SNAPSHOT_FIELDS = {
    "key",
    "name",
    "description",
    "aliases",
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


def partner_daily_definition(content: ContentBundle | None = None, *, require_active: bool = True) -> dict[str, Any]:
    bundle = _bundle(content)
    if {row['key'] for row in bundle.list(KIND)} != {DEFAULTS_KEY}:
        raise ContentError("partner daily tasks must contain exactly the supported rule")
    try:
        row = bundle.require(KIND, DEFAULTS_KEY, include_locked=True)
    except KeyError as exc:
        raise ContentError(f"missing partner daily task content: {DEFAULTS_KEY}") from exc
    if row.get("status") not in {"active", "closed", "locked", "placeholder"}:
        raise ContentError("partner daily task status is invalid")
    if require_active and row.get("status") != "active":
        raise ContentError(f"{DEFAULTS_KEY} is not active")
    if set(row) != REQUIRED_FIELDS:
        missing = REQUIRED_FIELDS - set(row)
        unknown = set(row) - REQUIRED_FIELDS
        raise ContentError(
            f"{DEFAULTS_KEY} fields differ from contract: missing={sorted(missing)}, "
            f"unknown={sorted(unknown)}"
        )
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


def partner_daily_snapshot(snapshot: Any) -> dict[str, Any]:
    """Validate the frozen, normalized rule without consulting today's rule state."""
    if not isinstance(snapshot, dict) or set(snapshot) != SNAPSHOT_FIELDS:
        raise ContentError("partner daily snapshot fields differ from contract")
    if snapshot.get("key") != DEFAULTS_KEY or snapshot.get("source_kind") != SOURCE_KIND:
        raise ContentError("partner daily snapshot uses an unsupported task or source")
    name = _text(snapshot, "name")
    description = _text(snapshot, "description")
    raw_aliases = snapshot.get("aliases")
    raw_deposits = snapshot.get("deposit_keys")
    if (not isinstance(raw_aliases, (list, tuple))
            or any(not isinstance(alias, str) or not alias.strip() for alias in raw_aliases)
            or not isinstance(raw_deposits, (list, tuple))
            or not raw_deposits
            or any(not isinstance(key, str) or not key.startswith("deposit.") for key in raw_deposits)
            or len(set(raw_deposits)) != len(raw_deposits)):
        raise ContentError("partner daily snapshot references are malformed")
    aliases = [alias.strip() for alias in raw_aliases]
    if not aliases or aliases[0] != name or len(set(aliases)) != len(aliases):
        raise ContentError("partner daily snapshot aliases are not unique")
    rewards = snapshot.get("reward_items")
    if not isinstance(rewards, dict) or not rewards:
        raise ContentError("partner daily snapshot rewards are malformed")
    normalized_rewards: dict[str, int] = {}
    for item_key, quantity in rewards.items():
        if (not isinstance(item_key, str) or not item_key.startswith("item.")
                or item_key in FORBIDDEN_REWARD_ITEMS):
            raise ContentError("partner daily snapshot contains an invalid reward item")
        normalized_rewards[item_key] = _positive_int(
            quantity, f"reward_items[{item_key}]", maximum=1000
        )
    daily_limit = _positive_int(snapshot.get("daily_limit"), "daily_limit", maximum=1)
    if daily_limit != 1:
        raise ContentError("partner daily snapshot daily_limit is invalid")
    return {
        "key": DEFAULTS_KEY,
        "name": name,
        "description": description,
        "aliases": tuple(aliases),
        "source_kind": SOURCE_KIND,
        "deposit_keys": tuple(raw_deposits),
        "target_each": _positive_int(snapshot.get("target_each"), "target_each", maximum=10),
        "window_seconds": _positive_int(snapshot.get("window_seconds"), "window_seconds", maximum=86400),
        "daily_limit": daily_limit,
        "reward_world_merit": _positive_int(snapshot.get("reward_world_merit"), "reward_world_merit", maximum=1000),
        "reward_items": normalized_rewards,
    }
