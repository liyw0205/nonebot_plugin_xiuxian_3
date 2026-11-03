"""Content-backed contract for the endgame final arena (``location.final_arena``).

World v0.6 froze the location row (渡劫 L6, activity-round gated, 15 minutes /
15 stamina, display-only ladder, no effect on ascension).  This loader owns
parsing and validation only; the window, quota and ladder progression live in
``final_arena_rules`` and the repository.

The arena is a map location (unlike the void market, which is an anchor-route
terminal), so the loader validates the location record, the region edge that
carries the round gate, the enemy references and the ladder shape.
"""

from __future__ import annotations

from typing import Any

from ..content import ContentBundle, ContentError, bundled_content

KIND = "final_arena"
DEFAULTS_KEY = "arena.final_heaven.defaults"
TIER_PREFIX = "tier."
SCHEDULE_KINDS = {"utc_block"}


def _bundle(content: ContentBundle | None) -> ContentBundle:
    return content if content is not None else bundled_content()


def _positive_int(value: Any, field: str, key: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ContentError(f"final arena {key} {field} must be a positive integer")
    return int(value)


def _non_negative_int(value: Any, field: str, key: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ContentError(f"final arena {key} {field} must be a non-negative integer")
    return int(value)


def _text(row: dict[str, Any], field: str, key: str) -> str:
    value = row.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ContentError(f"final arena {key} requires a {field}")
    return value.strip()


def _schedule(value: Any, key: str) -> dict[str, Any]:
    """Validate the UTC block schedule shared with the public-event windows."""

    if not isinstance(value, dict):
        raise ContentError(f"final arena {key} schedule must be an object")
    if set(value) != {"kind", "block_hours", "duration_seconds", "claim_window_seconds"}:
        raise ContentError(f"final arena {key} schedule fields are invalid")
    if value.get("kind") not in SCHEDULE_KINDS:
        raise ContentError(f"final arena {key} has unsupported schedule kind")
    block_hours = value.get("block_hours")
    if isinstance(block_hours, bool) or not isinstance(block_hours, int) or not 1 <= block_hours <= 24:
        raise ContentError(f"final arena {key} block_hours must be within 1-24")
    duration = _positive_int(value.get("duration_seconds"), "schedule.duration_seconds", key)
    claim = _positive_int(value.get("claim_window_seconds"), "schedule.claim_window_seconds", key)
    # The round is the whole UTC block (that is what rotates the quota), but the
    # open window is a whole number of hours inside it, so a closed period
    # really exists between rounds.
    if 24 % block_hours or duration % 3600 or duration > block_hours * 3600:
        raise ContentError(f"final arena {key} utc door window is invalid")
    return {
        "kind": str(value["kind"]),
        "block_hours": int(block_hours),
        "duration_seconds": duration,
        "claim_window_seconds": claim,
    }


def final_arena_defaults(content: ContentBundle | None = None) -> dict[str, Any]:
    """Return the validated shared arena parameters."""

    bundle = _bundle(content)
    try:
        row = bundle.require(KIND, DEFAULTS_KEY, include_locked=True)
    except KeyError as exc:
        raise ContentError(f"missing final_arena content: {DEFAULTS_KEY}") from exc
    if row.get("status") != "active":
        raise ContentError(f"{DEFAULTS_KEY} is not active")
    _text(row, "name", DEFAULTS_KEY)
    _text(row, "desc", DEFAULTS_KEY)

    location_key = _text(row, "location_key", DEFAULTS_KEY)
    location = bundle.get("location", location_key, include_locked=True)
    if location is None:
        raise ContentError(f"{DEFAULTS_KEY} references unknown location {location_key}")
    if location.get("status") not in {"active", "open"}:
        raise ContentError(f"{DEFAULTS_KEY} references closed location {location_key}")

    realm_key = _text(row, "required_realm", DEFAULTS_KEY)
    realm = bundle.get("realm", realm_key, include_locked=True)
    if realm is None:
        raise ContentError(f"{DEFAULTS_KEY} references unknown realm {realm_key}")
    if realm.get("status") not in {"active", "open"}:
        raise ContentError(f"{DEFAULTS_KEY} references closed realm {realm_key}")
    layer = _positive_int(row.get("required_layer"), "required_layer", DEFAULTS_KEY)

    # The arena gate must be the location's own gate: a mismatch would let the
    # arena admit characters the map location refuses (or vice versa).
    location_requirements = [
        entry
        for entry in (location.get("requirements") or [])
        if isinstance(entry, dict) and entry.get("type") == "realm"
    ]
    if len(location_requirements) != 1:
        raise ContentError(f"{DEFAULTS_KEY} location must declare exactly one realm requirement")
    location_requirement = location_requirements[0]
    if (
        str(location_requirement.get("realm_key")) != realm_key
        or int(location_requirement.get("min_layer", 0)) != layer
    ):
        raise ContentError(f"{DEFAULTS_KEY} realm gate differs from its location record")

    return {
        "location_key": location_key,
        "schedule": _schedule(row.get("schedule"), DEFAULTS_KEY),
        "attempt_limit_per_round": _positive_int(
            row.get("attempt_limit_per_round"), "attempt_limit_per_round", DEFAULTS_KEY
        ),
        "stamina_cost": _positive_int(row.get("stamina_cost"), "stamina_cost", DEFAULTS_KEY),
        "required_realm": realm_key,
        "required_layer": layer,
    }


def final_arena_tiers(content: ContentBundle | None = None) -> tuple[dict[str, Any], ...]:
    """Return validated ladder tiers, guaranteeing a contiguous 0-based ladder."""

    bundle = _bundle(content)
    rows = [
        row
        for row in bundle.list(KIND, include_locked=True)
        if str(row.get("key")) != DEFAULTS_KEY
    ]
    if not rows:
        raise ContentError("no final arena tier content is active")

    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    aliases: dict[str, str] = {}
    for row in sorted(rows, key=lambda item: str(item.get("key"))):
        key = str(row.get("key"))
        if not key.startswith(TIER_PREFIX):
            raise ContentError(f"final arena tier key must start with {TIER_PREFIX!r}: {key!r}")
        if key in seen:
            raise ContentError(f"final arena has a duplicate tier key {key!r}")
        seen.add(key)
        if row.get("status") != "active":
            raise ContentError(f"final arena {key} is not active")
        label = _text(row, "label", key)
        _text(row, "name", key)
        _text(row, "desc", key)

        enemy_key = _text(row, "enemy_key", key)
        if not enemy_key.startswith("enemy."):
            raise ContentError(f"final arena {key} enemy_key must be an enemy key")
        enemy = bundle.get("enemy", enemy_key, include_locked=False)
        if enemy is None:
            raise ContentError(f"final arena {key} references unknown enemy {enemy_key}")

        required_best = _non_negative_int(row.get("required_best_tier"), "required_best_tier", key)
        title_key = row.get("title_key")
        if title_key is not None:
            title_key = _text(row, "title_key", key)
            if not title_key.startswith("title."):
                raise ContentError(f"final arena {key} title_key must use the title namespace")
            if bundle.get("honor_title", title_key, include_locked=False) is None:
                raise ContentError(f"final arena {key} references unknown title {title_key}")

        row_aliases = row.get("aliases")
        if not isinstance(row_aliases, list) or not row_aliases:
            raise ContentError(f"final arena {key} aliases must be a non-empty list")
        for alias in row_aliases:
            if not isinstance(alias, str) or not alias.strip():
                raise ContentError(f"final arena {key} has an invalid alias")
            alias = alias.strip()
            owner = aliases.get(alias)
            if owner is not None and owner != key:
                raise ContentError(f"final arena alias {alias} is already owned by {owner}")
            aliases[alias] = key

        record: dict[str, Any] = {
            "key": key,
            "label": label,
            "enemy_key": enemy_key,
            "required_best_tier": required_best,
            "aliases": tuple(str(alias).strip() for alias in row_aliases),
        }
        if title_key is not None:
            record["title_key"] = title_key
        records.append(record)

    expected = list(range(len(records)))
    if [record["required_best_tier"] for record in records] != expected:
        raise ContentError(
            "final arena tiers must form a contiguous ladder from zero "
            f"({[record['required_best_tier'] for record in records]} != {expected})"
        )
    return tuple(records)


def final_arena_alias_map(content: ContentBundle | None = None) -> dict[str, str]:
    """Map every stable key and Chinese alias to its tier key."""

    bundle = _bundle(content)
    aliases: dict[str, str] = {}
    for record in final_arena_tiers(bundle):
        aliases[record["key"]] = record["key"]
        for alias in record["aliases"]:
            aliases[alias] = record["key"]
    return aliases


__all__ = [
    "DEFAULTS_KEY",
    "KIND",
    "SCHEDULE_KINDS",
    "TIER_PREFIX",
    "final_arena_alias_map",
    "final_arena_defaults",
    "final_arena_tiers",
]
