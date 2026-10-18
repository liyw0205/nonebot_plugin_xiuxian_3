"""Content-backed contracts for cave facilities and endgame recipes."""

from __future__ import annotations

from typing import Any

from ..content import ContentBundle, ContentError, bundled_content

FACILITY_KIND = "production_facility"
FACILITY_DEFAULTS_KEY = "facility.defaults"
ENDGAME_KIND = "endgame_recipe"
ENDGAME_DEFAULTS_KEY = "endgame.defaults"

FACILITY_KINDS = ("field", "alchemy", "artifice", "array")
ENDGAME_STATUSES = ("none", "dao_union", "tribulation", "ascension_ready")


def _bundle(content: ContentBundle | None) -> ContentBundle:
    return content if content is not None else bundled_content()


def _record(bundle: ContentBundle, kind: str, key: str) -> dict[str, Any]:
    try:
        row = bundle.require(kind, key, include_locked=False)
    except KeyError as exc:
        raise ContentError(f"missing {kind} content: {key}") from exc
    if row.get("status") != "active":
        raise ContentError(f"{key} status is not active")
    for field in ("name", "desc"):
        if not isinstance(row.get(field), str) or not row[field].strip():
            raise ContentError(f"{key} requires a {field}")
    return row


def _positive(value: Any, field: str, key: str, *, allow_zero: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0 or (not allow_zero and value <= 0):
        raise ContentError(f"{key} {field} must be a {'non-negative' if allow_zero else 'positive'} integer")
    return int(value)


def _text(value: Any, field: str, key: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContentError(f"{key} {field} is invalid")
    return value.strip()


def _location(bundle: ContentBundle, value: Any, key: str, field: str) -> str:
    location_key = _text(value, field, key)
    try:
        bundle.require("location", location_key, include_locked=True)
    except KeyError as exc:
        raise ContentError(f"{key} {field} references unknown location {location_key}") from exc
    return location_key


def facility_defaults(content: ContentBundle | None = None) -> dict[str, Any]:
    key = FACILITY_DEFAULTS_KEY
    bundle = _bundle(content)
    row = _record(bundle, FACILITY_KIND, key)
    return {
        "key": key,
        "location_key": _location(bundle, row.get("location_key"), key, "location_key"),
        "maintenance_fee": _positive(row.get("maintenance_fee"), "maintenance_fee", key),
        "duration_bonus_bp": _positive(row.get("duration_bonus_bp"), "duration_bonus_bp", key),
    }


def facility_records(content: ContentBundle | None = None) -> tuple[dict[str, Any], ...]:
    bundle = _bundle(content)
    defaults = facility_defaults(content)
    rows = [
        row
        for row in bundle.list(FACILITY_KIND, include_locked=False)
        if str(row.get("key")) != FACILITY_DEFAULTS_KEY
    ]
    if not rows:
        raise ContentError("no production facility slots are active")
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    aliases: dict[str, str] = {}
    kind_order = {kind: index for index, kind in enumerate(FACILITY_KINDS)}
    for row in sorted(
        rows,
        key=lambda item: (kind_order.get(str(item.get("facility_kind")), -1), int(item.get("slot_index", 0))),
    ):
        key = _text(row.get("key"), "key", str(row.get("key")))
        if key in seen:
            raise ContentError(f"duplicate facility key {key}")
        seen.add(key)
        facility_kind = _text(row.get("facility_kind"), "facility_kind", key)
        if facility_kind not in FACILITY_KINDS:
            raise ContentError(f"facility {key} has an unsupported facility_kind")
        slot_index = _positive(row.get("slot_index"), "slot_index", key)
        record = {
            "key": key,
            "name": _text(row.get("name"), "name", key),
            "label": _text(row.get("label", row.get("name")), "label", key),
            "facility_kind": facility_kind,
            "slot_index": slot_index,
            "location_key": defaults["location_key"],
        }
        raw_aliases = row.get("aliases")
        if not isinstance(raw_aliases, list) or not raw_aliases:
            raise ContentError(f"facility {key} aliases must be a non-empty list")
        for alias in raw_aliases:
            alias = _text(alias, "alias", key)
            if alias in aliases and aliases[alias] != key:
                raise ContentError(f"facility alias {alias} conflicts between {aliases[alias]} and {key}")
            aliases[alias] = key
        record["aliases"] = tuple(_text(alias, "alias", key) for alias in raw_aliases)
        records.append(record)
    return tuple(records)


def endgame_defaults(content: ContentBundle | None = None) -> dict[str, Any]:
    key = ENDGAME_DEFAULTS_KEY
    bundle = _bundle(content)
    row = _record(bundle, ENDGAME_KIND, key)
    certificate_key = _text(row.get("ascension_certificate_key"), "ascension_certificate_key", key)
    try:
        bundle.require("item", certificate_key, include_locked=True)
    except KeyError as exc:
        raise ContentError(f"{key} references unknown item {certificate_key}") from exc
    return {
        "key": key,
        "success_threshold_bp": _positive(row.get("success_threshold_bp"), "success_threshold_bp", key),
        "dao_fruit_progress_cap": _positive(row.get("dao_fruit_progress_cap"), "dao_fruit_progress_cap", key),
        "ascension_certificate_key": certificate_key,
    }


def endgame_records(content: ContentBundle | None = None) -> tuple[dict[str, Any], ...]:
    bundle = _bundle(content)
    rows = [
        row
        for row in bundle.list(ENDGAME_KIND, include_locked=False)
        if str(row.get("key")) != ENDGAME_DEFAULTS_KEY
    ]
    if not rows:
        raise ContentError("no endgame recipes are active")
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    aliases: dict[str, str] = {}
    for row in sorted(rows, key=lambda item: str(item.get("key"))):
        key = _text(row.get("key"), "key", str(row.get("key")))
        if key in seen:
            raise ContentError(f"duplicate endgame recipe key {key}")
        seen.add(key)
        record: dict[str, Any] = {
            "key": key,
            "name": _text(row.get("name"), "name", key),
            "label": _text(row.get("label", row.get("name")), "label", key),
            "duration_seconds": _positive(row.get("duration_seconds"), "duration_seconds", key),
        }
        inputs_raw = row.get("inputs") or {}
        if not isinstance(inputs_raw, dict):
            raise ContentError(f"endgame recipe {key} inputs must be an object")
        inputs: dict[str, int] = {}
        for item_key, quantity in inputs_raw.items():
            item_key = str(item_key)
            if not item_key.strip():
                raise ContentError(f"endgame recipe {key} has an empty input key")
            try:
                bundle.require("item", item_key, include_locked=True)
            except KeyError as exc:
                raise ContentError(f"endgame recipe {key} references unknown item {item_key}") from exc
            inputs[item_key] = _positive(quantity, f"inputs.{item_key}", key)
        record["inputs"] = inputs
        output_item = row.get("output_item")
        if output_item is not None:
            output_item = _text(output_item, "output_item", key)
            try:
                bundle.require("item", output_item, include_locked=True)
            except KeyError as exc:
                raise ContentError(f"endgame recipe {key} references unknown item {output_item}") from exc
            record["output_item"] = output_item
        output_progress = row.get("output_progress")
        if output_progress is not None:
            record["output_progress"] = _positive(output_progress, "output_progress", key)
        world_merit_cost = row.get("world_merit_cost")
        if world_merit_cost is not None:
            record["world_merit_cost"] = _positive(world_merit_cost, "world_merit_cost", key, allow_zero=True)
        required_progress = row.get("required_progress")
        if required_progress is not None:
            record["required_progress"] = _positive(required_progress, "required_progress", key, allow_zero=True)
        required_ascension_merit = row.get("required_ascension_merit")
        if required_ascension_merit is not None:
            record["required_ascension_merit"] = _positive(
                required_ascension_merit, "required_ascension_merit", key, allow_zero=True
            )
        required_realm = _text(row.get("required_realm"), "required_realm", key)
        try:
            bundle.require("realm", required_realm, include_locked=False)
        except KeyError as exc:
            raise ContentError(f"endgame recipe {key} references unknown realm {required_realm}") from exc
        record["required_realm"] = required_realm
        statuses = row.get("required_endgame_statuses")
        if statuses is not None:
            if not isinstance(statuses, list) or not statuses:
                raise ContentError(f"endgame recipe {key} required_endgame_statuses must be a non-empty list")
            for status in statuses:
                if status not in ENDGAME_STATUSES:
                    raise ContentError(f"endgame recipe {key} has an unsupported endgame status {status}")
            record["required_endgame_statuses"] = tuple(statuses)
        required_location = row.get("required_location")
        if required_location is not None:
            record["required_location"] = _location(bundle, required_location, key, "required_location")
        raw_aliases = row.get("aliases")
        if not isinstance(raw_aliases, list) or not raw_aliases:
            raise ContentError(f"endgame recipe {key} aliases must be a non-empty list")
        for alias in raw_aliases:
            alias = _text(alias, "alias", key)
            if alias in aliases and aliases[alias] != key:
                raise ContentError(f"endgame recipe alias {alias} conflicts between {aliases[alias]} and {key}")
            aliases[alias] = key
        record["aliases"] = tuple(_text(alias, "alias", key) for alias in raw_aliases)
        records.append(record)
    return tuple(records)


__all__ = [
    "ENDGAME_DEFAULTS_KEY",
    "ENDGAME_KIND",
    "ENDGAME_STATUSES",
    "FACILITY_DEFAULTS_KEY",
    "FACILITY_KIND",
    "FACILITY_KINDS",
    "endgame_defaults",
    "endgame_records",
    "facility_defaults",
    "facility_records",
]
