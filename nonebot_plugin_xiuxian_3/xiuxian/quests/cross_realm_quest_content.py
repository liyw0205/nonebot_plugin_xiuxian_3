"""Content-backed contracts for cross-realm player quests."""

from __future__ import annotations

from typing import Any

from ..content import ContentBundle, ContentError, bundled_content

KIND = "cross_realm_quest"
DEFAULTS_KEY = "cross_realm_quest.defaults"
FACTIONS = ("demon", "beast", "xuantian")


def _bundle(content: ContentBundle | None) -> ContentBundle:
    return content if content is not None else bundled_content()


def _text(value: Any, field: str, key: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContentError(f"{key} {field} is invalid")
    return value.strip()


def _positive(value: Any, field: str, key: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ContentError(f"{key} {field} must be a positive integer")
    return int(value)


def quest_defaults(content: ContentBundle | None = None) -> dict[str, Any]:
    key = DEFAULTS_KEY
    bundle = _bundle(content)
    try:
        row = bundle.require(KIND, key, include_locked=False)
    except KeyError as exc:
        raise ContentError(f"missing {KIND} content: {key}") from exc
    if row.get("status") != "active":
        raise ContentError(f"{key} status is not active")
    for field in ("name", "desc"):
        if not isinstance(row.get(field), str) or not row[field].strip():
            raise ContentError(f"{key} requires a {field}")
    factions = row.get("factions")
    if not isinstance(factions, list) or not factions:
        raise ContentError(f"{key} factions must be a non-empty list")
    for faction in factions:
        if faction not in FACTIONS:
            raise ContentError(f"{key} has an unsupported faction {faction}")
    return {"key": key, "factions": tuple(factions)}


def quest_records(content: ContentBundle | None = None) -> tuple[dict[str, Any], ...]:
    bundle = _bundle(content)
    defaults = quest_defaults(content)
    rows = [
        row
        for row in bundle.list(KIND, include_locked=False)
        if str(row.get("key")) != DEFAULTS_KEY
    ]
    if not rows:
        raise ContentError("no cross-realm quests are active")
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    aliases: dict[str, str] = {}
    for row in sorted(rows, key=lambda item: str(item.get("key"))):
        key = _text(row.get("key"), "key", str(row.get("key")))
        if key in seen:
            raise ContentError(f"duplicate cross-realm quest key {key}")
        seen.add(key)
        if not key.startswith("quest."):
            raise ContentError(f"cross-realm quest {key} key must live under quest.")
        for field in ("name", "desc"):
            _text(row.get(field), field, key)
        faction = _text(row.get("faction"), "faction", key)
        if faction not in defaults["factions"]:
            raise ContentError(f"cross-realm quest {key} has an unsupported faction {faction}")
        exploration_mode = _text(row.get("exploration_mode"), "exploration_mode", key)
        try:
            mode = bundle.require("exploration_mode", exploration_mode, include_locked=False)
        except KeyError as exc:
            locked = bundle.get("exploration_mode", exploration_mode, include_locked=True)
            if locked is not None:
                raise ContentError(
                    f"cross-realm quest {key} references a non-open exploration mode {exploration_mode}"
                ) from exc
            raise ContentError(
                f"cross-realm quest {key} references unknown exploration mode {exploration_mode}"
            ) from exc
        if str(mode.get("status")) != "open":
            raise ContentError(
                f"cross-realm quest {key} references a non-open exploration mode {exploration_mode}"
            )
        required_realm = _text(row.get("required_realm"), "required_realm", key)
        try:
            bundle.require("realm", required_realm, include_locked=False)
        except KeyError as exc:
            raise ContentError(
                f"cross-realm quest {key} references unknown realm {required_realm}"
            ) from exc
        access_flag = _text(row.get("access_flag"), "access_flag", key)
        if not access_flag.startswith("access."):
            raise ContentError(f"cross-realm quest {key} access_flag must live under access.")
        raw_aliases = row.get("aliases")
        if not isinstance(raw_aliases, list) or not raw_aliases:
            raise ContentError(f"cross-realm quest {key} aliases must be a non-empty list")
        cleaned = [_text(alias, "alias", key) for alias in raw_aliases]
        for alias in cleaned:
            if alias in aliases and aliases[alias] != key:
                raise ContentError(
                    f"cross-realm quest alias {alias} conflicts between {aliases[alias]} and {key}"
                )
            aliases[alias] = key
        records.append(
            {
                "key": key,
                "name": _text(row.get("name"), "name", key),
                "desc": _text(row.get("desc"), "desc", key),
                "label": _text(row.get("label", row.get("name")), "label", key),
                "aliases": tuple(cleaned),
                "exploration_mode": exploration_mode,
                "exploration_target": _positive(
                    row.get("exploration_target"), "exploration_target", key
                ),
                "faction": faction,
                "required_reputation": _positive(
                    row.get("required_reputation"), "required_reputation", key
                ),
                "required_realm": required_realm,
                "required_layer": _positive(row.get("required_layer"), "required_layer", key),
                "access_flag": access_flag,
            }
        )
    return tuple(records)


def quest_record(key: str, content: ContentBundle | None = None) -> dict[str, Any]:
    for record in quest_records(content):
        if record["key"] == key:
            return record
    raise ContentError(f"cross-realm quest is not active: {key}")


__all__ = [
    "DEFAULTS_KEY",
    "FACTIONS",
    "KIND",
    "quest_defaults",
    "quest_record",
    "quest_records",
]
