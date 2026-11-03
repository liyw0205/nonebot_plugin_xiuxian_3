"""Content-backed contract for the 留界据点 (``settlement.dao_hall``).

Social v0.6 froze the row: founded only by a player who chose ``remain_in_world``,
2000 world merit plus 5000 spirit stones, thirty core seats, a weekly 5000
maintenance bill and a 72-hour rebuild window.  Economy v0.6 froze the
construction currency as world merit (never spirit stones).  Nothing in the
package consumed any of it, so this loader owns parsing and validation and the
runtime owns founding, membership, construction and maintenance.
"""

from __future__ import annotations

from typing import Any

from ..content import ContentBundle, ContentError, bundled_content

KIND = "dao_hall"
DEFAULTS_KEY = "hall.dao_settlement.defaults"
PROJECT_PREFIX = "project.dao_hall."
ALLOWED_ENDINGS = {"remain_in_world"}
PROJECT_EFFECTS = {
    "core_capacity_bonus": 30,
    "maintenance_discount_bp": 5_000,
    "rebuild_hours_reduction": 48,
}
DEFAULTS_FIELDS = {
    "key",
    "name",
    "desc",
    "status",
    "required_ending",
    "required_world_merit",
    "spirit_stones",
    "core_capacity",
    "maintenance_spirit_stones",
    "maintenance_period_days",
    "rebuild_hours",
    "core_required_realms",
}
PROJECT_FIELDS = {
    "key",
    "name",
    "desc",
    "status",
    "world_merit",
    "required_project_keys",
    "effects",
}


def _bundle(content: ContentBundle | None) -> ContentBundle:
    return content if content is not None else bundled_content()


def _text(row: dict[str, Any], field: str, key: str) -> str:
    value = row.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ContentError(f"dao hall {key} requires a {field}")
    return value.strip()


def _positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ContentError(f"dao hall {label} must be a positive integer")
    return int(value)


def _bounded_int(value: Any, label: str, *, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ContentError(f"dao hall {label} must be between {low} and {high}")
    return int(value)


def _aliases(row: dict[str, Any], key: str, seen: dict[str, str]) -> tuple[str, ...]:
    names = [_text(row, "name", key)]
    raw = row.get("aliases", [])
    if not isinstance(raw, list):
        raise ContentError(f"dao hall {key} aliases must be a list")
    for alias in raw:
        if not isinstance(alias, str) or not alias.strip():
            raise ContentError(f"dao hall {key} has a malformed alias")
        names.append(alias.strip())
    for label in names:
        owner = seen.get(label)
        if owner is not None and owner != key:
            raise ContentError(f"dao hall alias {label!r} is shared by {owner} and {key}")
        seen[label] = key
    return tuple(names)


def dao_hall_defaults(content: ContentBundle | None = None) -> dict[str, Any]:
    """Return the validated hall parameters."""

    bundle = _bundle(content)
    try:
        row = bundle.require(KIND, DEFAULTS_KEY, include_locked=True)
    except KeyError as exc:
        raise ContentError(f"missing dao_hall content: {DEFAULTS_KEY}") from exc
    if row.get("status") != "active":
        raise ContentError(f"{DEFAULTS_KEY} is not active")
    missing = DEFAULTS_FIELDS - set(row)
    if missing:
        raise ContentError(f"dao hall {DEFAULTS_KEY} is missing fields: {sorted(missing)}")

    ending = _text(row, "required_ending", DEFAULTS_KEY)
    if ending not in ALLOWED_ENDINGS:
        raise ContentError(f"dao hall {DEFAULTS_KEY} has an unsupported ending requirement")

    core_realms = row.get("core_required_realms")
    if not isinstance(core_realms, list) or not core_realms:
        raise ContentError(f"dao hall {DEFAULTS_KEY} core_required_realms must be a non-empty list")
    for realm_key in core_realms:
        if not isinstance(realm_key, str) or bundle.get("realm", realm_key, include_locked=False) is None:
            raise ContentError(f"dao hall {DEFAULTS_KEY} references an unknown realm: {realm_key!r}")

    return {
        "key": DEFAULTS_KEY,
        "name": _text(row, "name", DEFAULTS_KEY),
        "description": _text(row, "desc", DEFAULTS_KEY),
        "required_ending": ending,
        "required_world_merit": _positive_int(
            row.get("required_world_merit"), f"{DEFAULTS_KEY} required_world_merit"
        ),
        "spirit_stones": _positive_int(row.get("spirit_stones"), f"{DEFAULTS_KEY} spirit_stones"),
        "core_capacity": _positive_int(row.get("core_capacity"), f"{DEFAULTS_KEY} core_capacity"),
        "maintenance_spirit_stones": _positive_int(
            row.get("maintenance_spirit_stones"), f"{DEFAULTS_KEY} maintenance_spirit_stones"
        ),
        "maintenance_period_days": _positive_int(
            row.get("maintenance_period_days"), f"{DEFAULTS_KEY} maintenance_period_days"
        ),
        "rebuild_hours": _bounded_int(
            row.get("rebuild_hours"), f"{DEFAULTS_KEY} rebuild_hours", low=1, high=720
        ),
        "core_required_realms": tuple(str(value) for value in core_realms),
    }


def dao_hall_projects(content: ContentBundle | None = None) -> dict[str, dict[str, Any]]:
    """Return every validated construction project keyed by its stable key."""

    bundle = _bundle(content)
    projects: dict[str, dict[str, Any]] = {}
    for row in bundle.list(KIND):
        key = row.get("key")
        if key == DEFAULTS_KEY:
            continue
        if not isinstance(key, str) or not key.startswith(PROJECT_PREFIX):
            raise ContentError(f"dao hall project {key!r} must use the {PROJECT_PREFIX} prefix")
        missing = PROJECT_FIELDS - set(row)
        if missing:
            raise ContentError(f"dao hall project {key} is missing fields: {sorted(missing)}")
        if row.get("status") not in {"active", "open", "locked"}:
            raise ContentError(f"dao hall project {key} has an invalid status")

        effects = row.get("effects")
        if not isinstance(effects, dict) or not effects:
            raise ContentError(f"dao hall project {key} effects must be a non-empty object")
        unknown = set(effects) - set(PROJECT_EFFECTS)
        if unknown:
            raise ContentError(f"dao hall project {key} has unknown effects: {sorted(unknown)}")
        normalised_effects: dict[str, int] = {}
        for field, value in effects.items():
            cap = PROJECT_EFFECTS[field]
            normalised_effects[field] = _bounded_int(
                value, f"{key} effects.{field}", low=1, high=cap
            )

        requires = row.get("required_project_keys")
        if not isinstance(requires, list):
            raise ContentError(f"dao hall project {key} required_project_keys must be a list")
        normalised_requires = []
        for prerequisite in requires:
            if not isinstance(prerequisite, str) or not prerequisite.startswith(PROJECT_PREFIX):
                raise ContentError(f"dao hall project {key} has a malformed prerequisite")
            if prerequisite == key:
                raise ContentError(f"dao hall project {key} cannot require itself")
            normalised_requires.append(prerequisite)

        projects[key] = {
            "key": key,
            "name": _text(row, "name", key),
            "description": _text(row, "desc", key),
            "status": str(row["status"]),
            "world_merit": _positive_int(row.get("world_merit"), f"{key} world_merit"),
            "required_project_keys": tuple(normalised_requires),
            "effects": normalised_effects,
        }

    # Every prerequisite must exist and the graph must be acyclic, otherwise a
    # project could never be built.
    for key, project in projects.items():
        for prerequisite in project["required_project_keys"]:
            if prerequisite not in projects:
                raise ContentError(f"dao hall project {key} references an unknown project: {prerequisite}")
    for key in projects:
        seen: set[str] = set()
        current = key
        while current is not None:
            if current in seen:
                raise ContentError(f"dao hall project {key} has a circular prerequisite")
            seen.add(current)
            required = projects[current]["required_project_keys"]
            current = required[0] if required else None
    return projects


def dao_hall_alias_map(content: ContentBundle | None = None) -> dict[str, str]:
    """Return ``label -> key`` for the hall and every project."""

    bundle = _bundle(content)
    seen: dict[str, str] = {}
    rows = [
        row
        for row in bundle.list(KIND)
        if isinstance(row.get("key"), str)
    ]
    for row in rows:
        key = str(row["key"])
        for label in _aliases(row, key, seen):
            seen[label] = key
    return seen


def resolve_dao_hall_project(value: str | None, content: ContentBundle | None = None) -> str | None:
    """Resolve a stable project key or a Chinese label to the project key."""

    if value is None:
        return None
    projects = dao_hall_projects(content)
    if value in projects:
        return value
    return dao_hall_alias_map(content).get(value.strip())