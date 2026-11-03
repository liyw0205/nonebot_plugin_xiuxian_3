"""Content-backed contract for 道统路线议事 (``dao.choose_route`` / ``dao.council_vote``).

Social v0.6 froze the decision: sect level 6, at least three 合道 voters, 1000
sect merit, one of ``guard_world``/``ascend``/``remain``, locked for seven days,
settled by majority with a tie carrying last week's route.  Nothing in the
package consumed any of it, so this loader owns parsing and validation and the
runtime owns cycles, votes and settlement.
"""

from __future__ import annotations

from typing import Any

from ..content import ContentBundle, ContentError, bundled_content

KIND = "dao_route"
DEFAULTS_KEY = "route.dao_settlement.defaults"
ROUTE_PREFIX = "route.dao_settlement."
ROUTE_KEYS = ("guard_world", "ascend", "remain")
BONUS_KEYS = {
    "defense_event_bonus_bp": 3_000,
    "dao_fruit_trial_bonus_bp": 3_000,
    "hall_construction_bonus_bp": 3_000,
}
DEFAULTS_FIELDS = {
    "key",
    "name",
    "desc",
    "status",
    "required_sect_level",
    "required_sect_merit",
    "required_voters",
    "required_realm",
    "required_layer",
    "vote_period_days",
    "lock_days",
    "allow_tie_carryover",
}
ROUTE_FIELDS = {"key", "name", "desc", "status", "bonus"}


def _bundle(content: ContentBundle | None) -> ContentBundle:
    return content if content is not None else bundled_content()


def _text(row: dict[str, Any], field: str, key: str) -> str:
    value = row.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ContentError(f"dao route {key} requires a {field}")
    return value.strip()


def _positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ContentError(f"dao route {label} must be a positive integer")
    return int(value)


def dao_route_defaults(content: ContentBundle | None = None) -> dict[str, Any]:
    """Return the validated council parameters."""

    bundle = _bundle(content)
    try:
        row = bundle.require(KIND, DEFAULTS_KEY, include_locked=True)
    except KeyError as exc:
        raise ContentError(f"missing dao_route content: {DEFAULTS_KEY}") from exc
    if row.get("status") != "active":
        raise ContentError(f"{DEFAULTS_KEY} is not active")
    missing = DEFAULTS_FIELDS - set(row)
    if missing:
        raise ContentError(f"dao route {DEFAULTS_KEY} is missing fields: {sorted(missing)}")

    realm_key = _text(row, "required_realm", DEFAULTS_KEY)
    realm = bundle.get("realm", realm_key, include_locked=False)
    if realm is None:
        raise ContentError(f"dao route {DEFAULTS_KEY} references an unknown realm: {realm_key!r}")
    layer = _positive_int(row.get("required_layer"), f"{DEFAULTS_KEY} required_layer")
    if not int(realm.get("layer_min", 1)) <= layer <= int(realm.get("layer_max", 1)):
        raise ContentError(f"dao route {DEFAULTS_KEY} required_layer is outside realm {realm_key}")

    carry = row.get("allow_tie_carryover")
    if not isinstance(carry, bool):
        raise ContentError(f"dao route {DEFAULTS_KEY} allow_tie_carryover must be a boolean")

    return {
        "key": DEFAULTS_KEY,
        "name": _text(row, "name", DEFAULTS_KEY),
        "description": _text(row, "desc", DEFAULTS_KEY),
        "required_sect_level": _positive_int(
            row.get("required_sect_level"), f"{DEFAULTS_KEY} required_sect_level"
        ),
        "required_sect_merit": _positive_int(
            row.get("required_sect_merit"), f"{DEFAULTS_KEY} required_sect_merit"
        ),
        "required_voters": _positive_int(
            row.get("required_voters"), f"{DEFAULTS_KEY} required_voters"
        ),
        "required_realm": realm_key,
        "required_layer": layer,
        "vote_period_days": _positive_int(
            row.get("vote_period_days"), f"{DEFAULTS_KEY} vote_period_days"
        ),
        "lock_days": _positive_int(row.get("lock_days"), f"{DEFAULTS_KEY} lock_days"),
        "allow_tie_carryover": carry,
    }


def dao_route_options(content: ContentBundle | None = None) -> dict[str, dict[str, Any]]:
    """Return the three validated routes keyed by their stable key."""

    bundle = _bundle(content)
    options: dict[str, dict[str, Any]] = {}
    aliases: dict[str, str] = {}
    for row in bundle.list(KIND):
        key = row.get("key")
        if key == DEFAULTS_KEY:
            continue
        if not isinstance(key, str) or not key.startswith(ROUTE_PREFIX):
            raise ContentError(f"dao route {key!r} must use the {ROUTE_PREFIX} prefix")
        missing = ROUTE_FIELDS - set(row)
        if missing:
            raise ContentError(f"dao route {key} is missing fields: {sorted(missing)}")
        if row.get("status") not in {"active", "open", "locked"}:
            raise ContentError(f"dao route {key} has an invalid status")
        bonus = row.get("bonus")
        if not isinstance(bonus, dict) or set(bonus) != {"key", "value_bp"}:
            raise ContentError(f"dao route {key} bonus is malformed")
        bonus_key = bonus.get("key")
        if bonus_key not in BONUS_KEYS:
            raise ContentError(f"dao route {key} has an unsupported bonus key: {bonus_key!r}")
        value_bp = _positive_int(bonus.get("value_bp"), f"{key} bonus.value_bp")
        if value_bp > BONUS_KEYS[bonus_key]:
            raise ContentError(f"dao route {key} bonus exceeds its cap")

        names = [_text(row, "name", key)]
        raw_aliases = row.get("aliases", [])
        if not isinstance(raw_aliases, list):
            raise ContentError(f"dao route {key} aliases must be a list")
        for alias in raw_aliases:
            if not isinstance(alias, str) or not alias.strip():
                raise ContentError(f"dao route {key} has a malformed alias")
            names.append(alias.strip())
        for label in names:
            owner = aliases.get(label)
            if owner is not None and owner != key:
                raise ContentError(f"dao route alias {label!r} is shared by {owner} and {key}")
            aliases[label] = key

        options[key] = {
            "key": key,
            "name": names[0],
            "description": _text(row, "desc", key),
            "aliases": tuple(names),
            "status": str(row["status"]),
            "bonus_key": str(bonus_key),
            "bonus_bp": value_bp,
        }

    if len(options) != len(ROUTE_KEYS) or set(options) != {
        f"{ROUTE_PREFIX}{suffix}" for suffix in ROUTE_KEYS
    }:
        raise ContentError("dao route options must be exactly guard_world, ascend and remain")
    return options


def dao_route_alias_map(content: ContentBundle | None = None) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for key, option in dao_route_options(content).items():
        for label in option["aliases"]:
            mapping[label] = key
    return mapping


def resolve_dao_route(value: str | None, content: ContentBundle | None = None) -> str | None:
    if value is None:
        return None
    options = dao_route_options(content)
    if value in options:
        return value
    return dao_route_alias_map(content).get(value.strip())