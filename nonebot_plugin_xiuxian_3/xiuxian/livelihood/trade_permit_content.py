"""Content-backed contracts for the cross-realm trade permits."""

from __future__ import annotations

from typing import Any

from ..content import ContentBundle, ContentError, bundled_content

KIND = "trade_permit"
DEFAULTS_KEY = "trade_permit.defaults"
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


def permit_defaults(content: ContentBundle | None = None) -> dict[str, Any]:
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


def permit_records(content: ContentBundle | None = None) -> tuple[dict[str, Any], ...]:
    bundle = _bundle(content)
    defaults = permit_defaults(content)
    rows = [
        row
        for row in bundle.list(KIND, include_locked=False)
        if str(row.get("key")) != DEFAULTS_KEY
    ]
    if not rows:
        raise ContentError("no trade permits are active")
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    aliases: dict[str, str] = {}
    for row in sorted(rows, key=lambda item: str(item.get("key"))):
        key = _text(row.get("key"), "key", str(row.get("key")))
        if key in seen:
            raise ContentError(f"duplicate trade permit key {key}")
        seen.add(key)
        if not key.startswith("permit."):
            raise ContentError(f"trade permit {key} key must live under permit.")
        for field in ("name", "desc"):
            _text(row.get(field), field, key)
        faction = _text(row.get("faction"), "faction", key)
        if faction not in defaults["factions"]:
            raise ContentError(f"trade permit {key} has an unsupported faction {faction}")
        required_quest_flag = _text(row.get("required_quest_flag"), "required_quest_flag", key)
        if not required_quest_flag.startswith("quest."):
            raise ContentError(
                f"trade permit {key} required_quest_flag must live under quest."
            )
        raw_aliases = row.get("aliases")
        if not isinstance(raw_aliases, list) or not raw_aliases:
            raise ContentError(f"trade permit {key} aliases must be a non-empty list")
        cleaned = [_text(alias, "alias", key) for alias in raw_aliases]
        for alias in cleaned:
            if alias in aliases and aliases[alias] != key:
                raise ContentError(
                    f"trade permit alias {alias} conflicts between {aliases[alias]} and {key}"
                )
            aliases[alias] = key
        records.append(
            {
                "key": key,
                "name": _text(row.get("name"), "name", key),
                "desc": _text(row.get("desc"), "desc", key),
                "label": _text(row.get("label", row.get("name")), "label", key),
                "aliases": tuple(cleaned),
                "faction": faction,
                "required_quest_flag": required_quest_flag,
                "required_reputation": _positive(
                    row.get("required_reputation"), "required_reputation", key
                ),
                "cost": _positive(row.get("cost"), "cost", key),
                "duration_seconds": _positive(row.get("duration_seconds"), "duration_seconds", key),
            }
        )
    return tuple(records)


__all__ = [
    "DEFAULTS_KEY",
    "FACTIONS",
    "KIND",
    "permit_defaults",
    "permit_records",
]
