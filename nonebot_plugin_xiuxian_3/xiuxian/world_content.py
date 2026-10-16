"""Validation for the map content contract.

The map owns places, regions, travel costs and access requirements.  Action
and environment extension keys are consumed by their respective domains and
are intentionally opaque here.
"""

from __future__ import annotations

import re
from typing import Any

from .content import ContentBundle, ContentError


_STATUSES = {"active", "open", "locked", "planned"}
_STABLE_KEY = re.compile(r"[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*")


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
    selectors: dict[str, str] = {}

    for row in locations:
        key = _record_key(row, "location")
        _stable_key(key, f"location {key} key")
        for field in ("name", "desc", "world"):
            _non_empty_string(row.get(field), f"location {key} requires {field}")
        aliases = row.get("aliases", [])
        if not isinstance(aliases, list) or any(
            not isinstance(alias, str) or not alias.strip() or alias != alias.strip() for alias in aliases
        ):
            raise ContentError(f"location {key} aliases must be non-empty strings")
        for selector in (key, row["name"], *aliases):
            owner = selectors.get(selector)
            if owner is not None and owner != key:
                raise ContentError(f"location selector {selector!r} is ambiguous between {owner} and {key}")
            selectors[selector] = key
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
    region_keys: set[str] = set()
    for region in regions:
        region_key = _record_key(region, "world_region")
        _stable_key(region_key, f"region {region_key} key")
        if region_key in region_keys:
            raise ContentError(f"duplicate world region key {region_key}")
        region_keys.add(region_key)
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
            unknown_fields = set(connection) - {
                "from",
                "to",
                "duration_seconds",
                "stamina",
                "spirit_stone",
                "requirements",
                "item_key",
                "item_quantity",
                "daily_start_limit",
                "consume_pass_on_arrival",
            }
            if unknown_fields:
                raise ContentError(f"region {region_key} connection has unsupported fields: {sorted(unknown_fields)}")
            if not isinstance(source, str) or not source or not isinstance(target, str) or not target:
                raise ContentError(f"region {region_key} connection requires stable from/to keys")
            _stable_key(source, f"connection source {source!r}")
            _stable_key(target, f"connection target {target!r}")
            if source not in location_keys or target not in location_keys or source == target:
                raise ContentError(f"region {region_key} has an invalid connection {source!r}->{target!r}")
            if source not in members and target not in members:
                raise ContentError(f"region {region_key} connection must touch a region member")
            edge = (source, target)
            if edge in edges:
                raise ContentError(f"duplicate world route {source}->{target}")
            edges.add(edge)
            _non_negative_int(connection.get("duration_seconds"), f"connection {source}->{target} duration_seconds")
            _non_negative_int(connection.get("stamina"), f"connection {source}->{target} stamina")
            _non_negative_int(connection.get("spirit_stone"), f"connection {source}->{target} spirit_stone")
            item_key = connection.get("item_key")
            item_quantity = connection.get("item_quantity")
            if item_key is None:
                if item_quantity is not None:
                    raise ContentError(f"connection {source}->{target} has item_quantity without item_key")
            else:
                _non_empty_string(item_key, f"connection {source}->{target} item_key")
                if not bundle.has("item", item_key, include_locked=True):
                    raise ContentError(f"connection {source}->{target} references unknown item {item_key}")
                _positive_int(item_quantity, f"connection {source}->{target} item_quantity")
            if "daily_start_limit" in connection:
                _positive_int(connection["daily_start_limit"], f"connection {source}->{target} daily_start_limit")
            if "consume_pass_on_arrival" in connection and not isinstance(connection["consume_pass_on_arrival"], bool):
                raise ContentError(f"connection {source}->{target} consume_pass_on_arrival must be boolean")
            if connection.get("consume_pass_on_arrival") and item_key is None:
                raise ContentError(f"connection {source}->{target} consumes a pass on arrival without item_key")
            _validate_requirements(
                connection.get("requirements", []), bundle, f"connection {source}->{target}"
            )

    uncovered = location_keys - covered
    if uncovered:
        raise ContentError(f"locations are not assigned to a region: {sorted(uncovered)}")
    _validate_cloud_routes(bundle)
    _validate_void_routes(bundle)
    return {
        "locations": len(locations),
        "regions": len(regions),
        "connections": len(edges),
        "covered_locations": len(covered),
    }


def _validate_cloud_routes(bundle: ContentBundle) -> None:
    rows = bundle.list("world_cloud_route", include_locked=True)
    destinations: set[str] = set()
    selectors: dict[str, str] = {}
    expected = {
        "key", "name", "desc", "status", "aliases", "command_name", "destination",
        "duration_seconds", "stamina", "spirit_stone", "source_locations", "realm_key",
        "realm_layer", "pass_key", "pass_quantity", "required_quest",
    }
    for row in rows:
        key = _record_key(row, "cloud route")
        _stable_key(key, f"cloud route {key} key")
        _only_record_fields(row, expected, f"cloud route {key}")
        for field in ("name", "desc", "command_name", "destination", "realm_key"):
            _non_empty_string(row.get(field), f"cloud route {key} requires {field}")
        _status(row, key, "cloud route")
        aliases = row.get("aliases")
        if not isinstance(aliases, list) or any(
            not isinstance(alias, str) or not alias.strip() or alias != alias.strip() for alias in aliases
        ):
            raise ContentError(f"cloud route {key} aliases must be non-empty strings")
        for selector in (key, row["name"], row["command_name"], *aliases):
            owner = selectors.get(selector)
            if owner is not None and owner != key:
                raise ContentError(f"cloud route selector {selector!r} is ambiguous between {owner} and {key}")
            selectors[selector] = key
        destination = str(row["destination"])
        if destination in destinations:
            raise ContentError(f"duplicate cloud route destination {destination}")
        destinations.add(destination)
        if not bundle.has("location", destination, include_locked=True):
            raise ContentError(f"cloud route {key} references unknown destination {destination}")
        sources = row.get("source_locations")
        if not isinstance(sources, list) or not sources or any(
            not isinstance(source, str) or not source for source in sources
        ) or len(set(sources)) != len(sources):
            raise ContentError(f"cloud route {key} source_locations must be a non-empty unique list")
        for source in sources:
            if source == destination or not bundle.has("location", source, include_locked=True):
                raise ContentError(f"cloud route {key} references invalid source {source!r}")
        if not bundle.has("realm", str(row["realm_key"]), include_locked=False):
            raise ContentError(f"cloud route {key} references unknown or inactive realm {row['realm_key']}")
        _positive_int(row.get("realm_layer"), f"cloud route {key} realm_layer")
        _positive_int(row.get("duration_seconds"), f"cloud route {key} duration_seconds")
        _positive_int(row.get("stamina"), f"cloud route {key} stamina")
        _non_negative_int(row.get("spirit_stone"), f"cloud route {key} spirit_stone")
        pass_key = row.get("pass_key")
        pass_quantity = row.get("pass_quantity")
        if pass_key is None:
            if pass_quantity != 0:
                raise ContentError(f"cloud route {key} pass_quantity requires pass_key")
        else:
            _non_empty_string(pass_key, f"cloud route {key} pass_key")
            if not bundle.has("item", pass_key, include_locked=True):
                raise ContentError(f"cloud route {key} references unknown item {pass_key}")
            _positive_int(pass_quantity, f"cloud route {key} pass_quantity")
        quest_key = row.get("required_quest")
        if quest_key is not None and not (
            isinstance(quest_key, str)
            and (bundle.has("quest", quest_key, include_locked=True) or bundle.has("guide", quest_key, include_locked=True))
        ):
            raise ContentError(f"cloud route {key} references unknown quest {quest_key!r}")


def _validate_void_routes(bundle: ContentBundle) -> None:
    rows = bundle.list("world_void_route", include_locked=True)
    selectors: dict[str, str] = {}
    expected = {
        "key", "name", "desc", "status", "aliases", "duration_seconds", "stamina", "anchor_cost", "random_pool",
    }
    for row in rows:
        key = _record_key(row, "void route")
        _stable_key(key, f"void route {key} key")
        _only_record_fields(row, expected, f"void route {key}")
        for field in ("name", "desc", "random_pool"):
            _non_empty_string(row.get(field), f"void route {key} requires {field}")
        _status(row, key, "void route")
        if not key.startswith("void."):
            raise ContentError(f"void route {key} must use the void location namespace")
        aliases = row.get("aliases")
        if not isinstance(aliases, list) or any(
            not isinstance(alias, str) or not alias.strip() or alias != alias.strip() for alias in aliases
        ):
            raise ContentError(f"void route {key} aliases must be non-empty strings")
        for selector in (key, row["name"], *aliases):
            owner = selectors.get(selector)
            if owner is not None and owner != key:
                raise ContentError(f"void route selector {selector!r} is ambiguous between {owner} and {key}")
            selectors[selector] = key
        for field in ("duration_seconds", "stamina", "anchor_cost"):
            _positive_int(row.get(field), f"void route {key} {field}")
        _stable_key(str(row["random_pool"]), f"void route {key} random_pool")


def _only_record_fields(row: dict[str, Any], allowed: set[str], context: str) -> None:
    unknown = set(row) - allowed
    missing = allowed - set(row)
    if unknown:
        raise ContentError(f"{context} has unsupported fields: {sorted(unknown)}")
    if missing:
        raise ContentError(f"{context} is missing fields: {sorted(missing)}")


def _record_key(row: dict[str, Any], kind: str) -> str:
    key = row.get("key")
    _non_empty_string(key, f"{kind} requires a stable key")
    return key


def _stable_key(value: str, context: str) -> None:
    if _STABLE_KEY.fullmatch(value) is None:
        raise ContentError(f"{context} must be an ASCII stable key")


def _status(row: dict[str, Any], key: str, kind: str) -> None:
    status = row.get("status")
    if status not in _STATUSES:
        raise ContentError(f"{kind} {key} has invalid status {status!r}")


def _validate_travel(value: Any, bundle: ContentBundle, context: str) -> None:
    if value is None:
        return
    if not isinstance(value, dict):
        raise ContentError(f"{context} travel must be an object")
    unknown_fields = set(value) - {"anchor_min", "anchor_max"}
    if unknown_fields:
        raise ContentError(
            f"{context} travel has unsupported fields; ordinary costs and passes belong to a directed route: "
            f"{sorted(unknown_fields)}"
        )
    if value:
        _positive_int(value.get("anchor_min"), f"{context} travel anchor_min")
        _positive_int(value.get("anchor_max"), f"{context} travel anchor_max")
        if value["anchor_min"] > value["anchor_max"]:
            raise ContentError(f"{context} travel anchor range is inverted")


def _validate_requirements(value: Any, bundle: ContentBundle, context: str) -> None:
    if value is None:
        return
    if not isinstance(value, list):
        raise ContentError(f"{context} requirements must be a list")
    for requirement in value:
        if isinstance(requirement, str):
            raise ContentError(f"{context} requirements must use typed records, not legacy strings")
        if not isinstance(requirement, dict):
            raise ContentError(f"{context} has a malformed requirement")
        kind = requirement.get("type")
        _non_empty_string(kind, f"{context} requirement type")
        if kind == "any_of":
            _only_fields(requirement, {"type", "conditions"}, context)
            conditions = requirement.get("conditions")
            if not isinstance(conditions, list) or not conditions:
                raise ContentError(f"{context} any_of requires conditions")
            _validate_requirements(conditions, bundle, context)
        elif kind == "realm":
            _only_fields(requirement, {"type", "realm_key", "min_layer"}, context)
            _non_empty_string(requirement.get("realm_key"), f"{context} realm_key")
            _stable_key(requirement["realm_key"], f"{context} realm_key")
            if not bundle.has("realm", requirement["realm_key"], include_locked=True):
                raise ContentError(f"{context} references unknown realm {requirement['realm_key']}")
            _positive_int(requirement.get("min_layer"), f"{context} realm min_layer")
        elif kind == "item":
            _only_fields(requirement, {"type", "item_key", "quantity"}, context)
            _non_empty_string(requirement.get("item_key"), f"{context} item_key")
            _stable_key(requirement["item_key"], f"{context} item_key")
            if not bundle.has("item", requirement["item_key"], include_locked=True):
                raise ContentError(f"{context} references unknown item {requirement['item_key']}")
            _positive_int(requirement.get("quantity"), f"{context} item quantity")
        elif kind == "quest_completed":
            _only_fields(requirement, {"type", "quest_key"}, context)
            _non_empty_string(requirement.get("quest_key"), f"{context} quest_key")
            _stable_key(requirement["quest_key"], f"{context} quest_key")
            if not (
                bundle.has("quest", requirement["quest_key"], include_locked=True)
                or bundle.has("guide", requirement["quest_key"], include_locked=True)
            ):
                raise ContentError(f"{context} references unknown quest or guide {requirement['quest_key']}")
        elif kind == "mentor_invitation":
            _only_fields(requirement, {"type"}, context)
            continue
        elif kind == "selected_domain":
            _only_fields(requirement, {"type"}, context)
            continue
        elif kind == "dao_fruit_progress":
            _only_fields(requirement, {"type", "minimum", "min"}, context)
            if ("minimum" in requirement) == ("min" in requirement):
                raise ContentError(f"{context} dao_fruit_progress requires exactly one minimum field")
            minimum = requirement.get("minimum", requirement.get("min"))
            _non_negative_int(minimum, f"{context} dao_fruit_progress minimum")
        elif kind in {"stage_min", "intro_flag", "endgame_status"}:
            field = "stage" if kind == "stage_min" else "value"
            _only_fields(requirement, {"type", field}, context)
            _non_empty_string(requirement.get(field), f"{context} {kind} {field}")
            if kind == "stage_min" and requirement[field] not in {"new_user", "mortal", "seeker", "cultivator"}:
                raise ContentError(f"{context} has unsupported stage_min value {requirement[field]!r}")
            if kind in {"intro_flag", "endgame_status"}:
                _stable_key(requirement[field], f"{context} {kind} {field}")
        elif kind == "faction_reputation":
            _only_fields(requirement, {"type", "faction", "minimum", "min"}, context)
            _non_empty_string(requirement.get("faction"), f"{context} faction")
            _stable_key(requirement["faction"], f"{context} faction")
            if ("minimum" in requirement) == ("min" in requirement):
                raise ContentError(f"{context} faction_reputation requires exactly one minimum field")
            minimum = requirement.get("minimum", requirement.get("min"))
            _non_negative_int(minimum, f"{context} faction minimum")
        else:
            raise ContentError(f"{context} has unsupported requirement type {kind!r}")


def _only_fields(requirement: dict[str, Any], allowed: set[str], context: str) -> None:
    unknown = set(requirement) - allowed
    if unknown:
        raise ContentError(f"{context} requirement has unsupported fields: {sorted(unknown)}")


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
