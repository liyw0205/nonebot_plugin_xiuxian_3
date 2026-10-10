"""Validation for the map content contract.

The map owns places, regions, travel costs and access requirements.  Action
and environment extension keys are consumed by their respective domains and
are intentionally opaque here.
"""

from __future__ import annotations

from typing import Any

from .content import ContentBundle, ContentError


_STATUSES = {"active", "open", "locked", "planned"}


def validate_world_content(bundle: ContentBundle) -> dict[str, int]:
    """Validate map-owned records and return stable counts for reports."""

    locations = bundle.list("location", include_locked=True)
    regions = bundle.list("world_region", include_locked=True)
    if not locations:
        raise ContentError("world map has no location records")
    if not regions:
        raise ContentError("world map has no region records")

    location_keys = {row.get("key") for row in locations}
    if any(not isinstance(key, str) or not key for key in location_keys):
        raise ContentError("location records require stable string keys")

    for row in locations:
        key = _record_key(row, "location")
        for field in ("name", "desc", "world"):
            _non_empty_string(row.get(field), f"location {key} requires {field}")
        _status(row, key, "location")
        _validate_requirements(row.get("requirements", []), bundle, f"location {key}")
        _validate_travel(row.get("travel", {}), bundle, f"location {key}")
        actions = row.get("actions", [])
        if not isinstance(actions, list) or any(not isinstance(action, str) or not action.strip() for action in actions):
            raise ContentError(f"location {key} actions must be non-empty strings")
        codex_key = row.get("codex_entry_key")
        if codex_key is not None:
            _non_empty_string(codex_key, f"location {key} codex_entry_key")
            if not bundle.has("codex_entry", codex_key, include_locked=True):
                raise ContentError(f"location {key} references unknown codex entry {codex_key}")

    covered: set[str] = set()
    edges: set[tuple[str, str]] = set()
    for region in regions:
        region_key = _record_key(region, "world_region")
        for field in ("name", "desc", "world"):
            _non_empty_string(region.get(field), f"region {region_key} requires {field}")
        _status(region, region_key, "region")
        members = region.get("location_keys")
        if not isinstance(members, list) or not members or any(
            not isinstance(location_key, str) or not location_key for location_key in members
        ):
            raise ContentError(f"region {region_key} location_keys must be a non-empty string list")
        if len(set(members)) != len(members):
            raise ContentError(f"region {region_key} contains duplicate locations")
        missing = set(members) - location_keys
        if missing:
            raise ContentError(f"region {region_key} references unknown locations: {sorted(missing)}")
        covered.update(members)

        connections = region.get("connections")
        if not isinstance(connections, list) or not connections:
            raise ContentError(f"region {region_key} requires connections")
        for connection in connections:
            if not isinstance(connection, dict):
                raise ContentError(f"region {region_key} has a malformed connection")
            source = connection.get("from")
            target = connection.get("to")
            if source not in location_keys or target not in location_keys or source == target:
                raise ContentError(f"region {region_key} has an invalid connection {source!r}->{target!r}")
            edges.add((source, target))
            _non_negative_int(connection.get("duration_seconds"), f"connection {source}->{target} duration_seconds")
            _non_negative_int(connection.get("stamina"), f"connection {source}->{target} stamina")
            _non_negative_int(connection.get("spirit_stone"), f"connection {source}->{target} spirit_stone")
            _validate_requirements(
                connection.get("requirements", []), bundle, f"connection {source}->{target}"
            )

    uncovered = location_keys - covered
    if uncovered:
        raise ContentError(f"locations are not assigned to a region: {sorted(uncovered)}")
    missing_reverse = sorted((source, target) for source, target in edges if (target, source) not in edges)
    if missing_reverse:
        raise ContentError(f"map connections must be bidirectional: {missing_reverse[0]}")
    return {
        "locations": len(locations),
        "regions": len(regions),
        "connections": len(edges),
        "covered_locations": len(covered),
    }


def _record_key(row: dict[str, Any], kind: str) -> str:
    key = row.get("key")
    _non_empty_string(key, f"{kind} requires a stable key")
    return key


def _status(row: dict[str, Any], key: str, kind: str) -> None:
    status = row.get("status")
    if status not in _STATUSES:
        raise ContentError(f"{kind} {key} has invalid status {status!r}")


def _validate_travel(value: Any, bundle: ContentBundle, context: str) -> None:
    if value is None:
        return
    if not isinstance(value, dict):
        raise ContentError(f"{context} travel must be an object")
    for field in ("duration_seconds", "stamina", "spirit_stone"):
        if field in value:
            _non_negative_int(value[field], f"{context} travel {field}")
    item_key = value.get("item_key")
    if item_key is not None:
        _non_empty_string(item_key, f"{context} travel item_key")
        if not bundle.has("item", item_key, include_locked=True):
            raise ContentError(f"{context} travel references unknown item {item_key}")
        quantity = value.get("item_quantity")
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
            raise ContentError(f"{context} travel item_quantity must be positive")


def _validate_requirements(value: Any, bundle: ContentBundle, context: str) -> None:
    if value is None:
        return
    if not isinstance(value, list):
        raise ContentError(f"{context} requirements must be a list")
    for requirement in value:
        if isinstance(requirement, str):
            _non_empty_string(requirement, f"{context} legacy requirement")
            continue
        if not isinstance(requirement, dict):
            raise ContentError(f"{context} has a malformed requirement")
        kind = requirement.get("type")
        _non_empty_string(kind, f"{context} requirement type")
        if kind == "any_of":
            conditions = requirement.get("conditions")
            if not isinstance(conditions, list) or not conditions:
                raise ContentError(f"{context} any_of requires conditions")
            _validate_requirements(conditions, bundle, context)
        elif kind == "realm":
            _non_empty_string(requirement.get("realm_key"), f"{context} realm_key")
            if not bundle.has("realm", requirement["realm_key"], include_locked=True):
                raise ContentError(f"{context} references unknown realm {requirement['realm_key']}")
            _positive_int(requirement.get("min_layer"), f"{context} realm min_layer")
        elif kind == "item":
            _non_empty_string(requirement.get("item_key"), f"{context} item_key")
            if not bundle.has("item", requirement["item_key"], include_locked=True):
                raise ContentError(f"{context} references unknown item {requirement['item_key']}")
            _positive_int(requirement.get("quantity"), f"{context} item quantity")
        elif kind == "quest_completed":
            _non_empty_string(requirement.get("quest_key"), f"{context} quest_key")
            if not (
                bundle.has("quest", requirement["quest_key"], include_locked=True)
                or bundle.has("guide", requirement["quest_key"], include_locked=True)
            ):
                raise ContentError(f"{context} references unknown quest or guide {requirement['quest_key']}")
        elif kind == "mentor_invitation":
            continue
        elif kind in {"stage_min", "intro_flag", "endgame_status"}:
            field = "stage" if kind == "stage_min" else "value"
            _non_empty_string(requirement.get(field), f"{context} {kind} {field}")
        elif kind == "faction_reputation":
            _non_empty_string(requirement.get("faction"), f"{context} faction")
            minimum = requirement.get("minimum", requirement.get("min"))
            _non_negative_int(minimum, f"{context} faction minimum")
        else:
            raise ContentError(f"{context} has unsupported requirement type {kind!r}")


def _non_empty_string(value: Any, message: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ContentError(message)


def _positive_int(value: Any, message: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ContentError(message)


def _non_negative_int(value: Any, message: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ContentError(message)


__all__ = ["validate_world_content"]
