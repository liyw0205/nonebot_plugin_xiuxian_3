"""Content contract for switching the support sub-profession (kind
``subprofession_switch``).

The shipped runtime only writes ``players.subprofession_key`` during path
selection, path switch and path rebuild.  A support cultivator therefore cannot
change the craft without changing the whole path and spending a respec token.
This module owns the standalone switch numbers so the repository and
application do not carry a second copy.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..content import ContentBundle, ContentError, bundled_content, resolve_content_key

KIND = "subprofession_switch"
KEY_PREFIX = "subprofession.switch."
STATUSES = {"active", "open", "locked", "planned"}
REQUIRED_FIELDS = {
    "key",
    "name",
    "desc",
    "aliases",
    "status",
    "path_key",
    "min_realm",
    "min_layer",
    "cost",
    "cooldown_seconds",
    "preview_ttl_seconds",
}
ALLOWED_FIELDS = REQUIRED_FIELDS
SUPPORTED_PATH = "support"


@dataclass(frozen=True, slots=True)
class SubprofessionSwitchDefinition:
    key: str
    label: str
    description: str
    aliases: tuple[str, ...]
    path_key: str
    min_realm: str
    min_layer: int
    spirit_stone_cost: int
    cooldown_seconds: int
    preview_ttl_seconds: int


def _bundle(content: ContentBundle | None) -> ContentBundle:
    return content if content is not None else bundled_content()


def _text(row: dict[str, Any], field: str, key: str) -> str:
    value = row.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ContentError(f"subprofession_switch {key} requires a non-empty {field}")
    return value.strip()


def _positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ContentError(f"subprofession_switch {label} must be a positive integer")
    return int(value)


def _realm_layer(bundle: ContentBundle, realm_key: str, layer: int, label: str) -> None:
    row = bundle.get("realm", realm_key, include_locked=False)
    if row is None:
        raise ContentError(
            f"subprofession_switch {label} references an unknown realm: {realm_key!r}"
        )
    minimum = row.get("layer_min")
    maximum = row.get("layer_max")
    if (
        isinstance(minimum, bool)
        or not isinstance(minimum, int)
        or isinstance(maximum, bool)
        or not isinstance(maximum, int)
        or not minimum <= layer <= maximum
    ):
        raise ContentError(
            f"subprofession_switch {label} layer {layer} is outside realm {realm_key} range"
        )


def _cost(value: Any, key: str) -> int:
    if not isinstance(value, dict) or len(value) != 1:
        raise ContentError(
            f"subprofession_switch {key} cost must name exactly one currency"
        )
    raw_key, raw_value = next(iter(value.items()))
    if raw_key not in {"currency.spirit_stone", "spirit_stones"}:
        raise ContentError(
            f"subprofession_switch {key} only supports spirit-stone currency"
        )
    return _positive_int(raw_value, f"{key} cost[{raw_key}]")


def subprofession_switch_definitions(
    content: ContentBundle | None = None,
) -> dict[str, SubprofessionSwitchDefinition]:
    bundle = _bundle(content)
    definitions: dict[str, SubprofessionSwitchDefinition] = {}
    selectors: dict[str, str] = {}
    for row in bundle.list(KIND, include_locked=True):
        key = row.get("key")
        if not isinstance(key, str) or not key.startswith(KEY_PREFIX):
            raise ContentError(
                f"subprofession_switch {key!r} must use the {KEY_PREFIX} prefix"
            )
        missing = REQUIRED_FIELDS - set(row)
        if missing:
            raise ContentError(
                f"subprofession_switch {key} is missing fields: {sorted(missing)}"
            )
        unknown = set(row) - ALLOWED_FIELDS
        if unknown:
            raise ContentError(
                f"subprofession_switch {key} has unknown fields: {sorted(unknown)}"
            )
        status = row.get("status")
        if status not in STATUSES:
            raise ContentError(
                f"subprofession_switch {key} has an invalid status: {status!r}"
            )
        name = _text(row, "name", key)
        description = _text(row, "desc", key)
        aliases = row.get("aliases")
        if not isinstance(aliases, list) or any(
            not isinstance(alias, str) or not alias.strip() for alias in aliases
        ):
            raise ContentError(
                f"subprofession_switch {key} aliases must be non-empty strings"
            )
        normalised_aliases = tuple(alias.strip() for alias in aliases)
        if len(set(normalised_aliases)) != len(normalised_aliases):
            raise ContentError(f"subprofession_switch {key} has duplicate aliases")
        for selector in (key, name, *normalised_aliases):
            owner = selectors.get(selector)
            if owner is not None and owner != key:
                raise ContentError(
                    f"subprofession_switch selector {selector!r} is ambiguous "
                    f"between {owner} and {key}"
                )
            selectors[selector] = key
        path_key = _text(row, "path_key", key)
        if path_key != SUPPORTED_PATH:
            raise ContentError(
                f"subprofession_switch {key} must bind the support path"
            )
        path = bundle.get("path", path_key, include_locked=False)
        if path is None:
            raise ContentError(
                f"subprofession_switch {key} references an unknown path: {path_key!r}"
            )
        subprofessions = path.get("subprofessions")
        if not isinstance(subprofessions, list) or not subprofessions:
            raise ContentError(
                f"subprofession_switch {key} requires support sub-professions"
            )
        min_realm = _text(row, "min_realm", key)
        min_layer = _positive_int(row.get("min_layer"), f"{key} min_layer")
        _realm_layer(bundle, min_realm, min_layer, f"{key} min_realm")
        cost = _cost(row.get("cost"), key)
        cooldown = _positive_int(
            row.get("cooldown_seconds"), f"{key} cooldown_seconds"
        )
        preview_ttl = _positive_int(
            row.get("preview_ttl_seconds"), f"{key} preview_ttl_seconds"
        )
        if status not in {"active", "open"}:
            continue
        definitions[key] = SubprofessionSwitchDefinition(
            key=key,
            label=name,
            description=description,
            aliases=normalised_aliases,
            path_key=path_key,
            min_realm=min_realm,
            min_layer=min_layer,
            spirit_stone_cost=cost,
            cooldown_seconds=cooldown,
            preview_ttl_seconds=preview_ttl,
        )
    if not definitions:
        raise ContentError("no active subprofession_switch rule is registered")
    return definitions


def subprofession_switch_definition(
    content: ContentBundle | None = None, key: str | None = None
) -> SubprofessionSwitchDefinition:
    definitions = subprofession_switch_definitions(content)
    if key is None:
        if len(definitions) != 1:
            raise ContentError(
                "exactly one active subprofession_switch rule is required"
            )
        return next(iter(definitions.values()))
    try:
        return definitions[key]
    except KeyError as exc:
        raise ContentError(f"unknown subprofession_switch rule: {key}") from exc


def resolve_subprofession_switch(
    value: str, content: ContentBundle | None = None
) -> str | None:
    try:
        return resolve_content_key(
            _bundle(content), KIND, value, include_locked=False
        )
    except ValueError:
        return None


__all__ = [
    "SubprofessionSwitchDefinition",
    "resolve_subprofession_switch",
    "subprofession_switch_definition",
    "subprofession_switch_definitions",
]
