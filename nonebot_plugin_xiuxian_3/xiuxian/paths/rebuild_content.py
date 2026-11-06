"""Content contract for the nascent-soul path rebuild (kind ``path_rebuild``).

``docs/foundation/paths/content-v0.3.md`` froze the rebuild prerequisites and
level inheritance, but the runtime never implemented it.  The three-realms
mainline already grants ``item.token.rebuild_path`` and the three faction
reputations; this loader owns the shipped rebuild numbers so the repository and
application do not carry a second copy.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..content import ContentBundle, ContentError, bundled_content, resolve_content_key

KIND = "path_rebuild"
KEY_PREFIX = "path.rebuild."
STATUSES = {"active", "open", "locked", "planned"}
FACTION_KEYS = ("xuantian", "demon", "beast")
REQUIRED_FIELDS = {
    "key",
    "name",
    "desc",
    "aliases",
    "status",
    "min_realm",
    "min_layer",
    "required_reputation",
    "required_intro_flag",
    "cost",
    "level_deduction",
    "preview_ttl_seconds",
}
ALLOWED_FIELDS = REQUIRED_FIELDS


@dataclass(frozen=True, slots=True)
class PathRebuildDefinition:
    key: str
    label: str
    description: str
    aliases: tuple[str, ...]
    min_realm: str
    min_layer: int
    required_reputation: dict[str, int]
    required_intro_flag: str
    currency_key: str
    spirit_stone_cost: int
    token_item_key: str
    token_quantity: int
    level_deduction: int
    preview_ttl_seconds: int


def _bundle(content: ContentBundle | None) -> ContentBundle:
    return content if content is not None else bundled_content()


def _text(row: dict[str, Any], field: str, key: str) -> str:
    value = row.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ContentError(f"path_rebuild {key} requires a non-empty {field}")
    return value.strip()


def _positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ContentError(f"path_rebuild {label} must be a positive integer")
    return int(value)


def _realm_layer(bundle: ContentBundle, realm_key: str, layer: int, label: str) -> None:
    row = bundle.get("realm", realm_key, include_locked=False)
    if row is None:
        raise ContentError(f"path_rebuild {label} references an unknown realm: {realm_key!r}")
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
            f"path_rebuild {label} layer {layer} is outside realm {realm_key} range"
        )


def _reputation(value: Any, key: str) -> dict[str, int]:
    if not isinstance(value, dict) or set(value) != set(FACTION_KEYS):
        raise ContentError(
            f"path_rebuild {key} required_reputation must name exactly "
            f"{', '.join(FACTION_KEYS)}"
        )
    result: dict[str, int] = {}
    for faction in FACTION_KEYS:
        result[faction] = _positive_int(
            value.get(faction), f"{key} required_reputation[{faction}]"
        )
    return result


def _cost(value: Any, key: str, bundle: ContentBundle) -> tuple[str, int, str, int]:
    if not isinstance(value, dict) or len(value) != 2:
        raise ContentError(f"path_rebuild {key} cost must name one currency and one item")
    currency_key = None
    spirit_stones = 0
    item_key = None
    item_quantity = 0
    for raw_key, raw_value in value.items():
        if not isinstance(raw_key, str):
            raise ContentError(f"path_rebuild {key} cost keys must be strings")
        if raw_key.startswith("currency.") or raw_key == "spirit_stones":
            if currency_key is not None:
                raise ContentError(f"path_rebuild {key} cost has more than one currency")
            currency_key = raw_key
            spirit_stones = _positive_int(raw_value, f"{key} cost[{raw_key}]")
        else:
            if item_key is not None:
                raise ContentError(f"path_rebuild {key} cost has more than one item")
            item_key = raw_key
            item_quantity = _positive_int(raw_value, f"{key} cost[{raw_key}]")
    if currency_key is None or item_key is None:
        raise ContentError(f"path_rebuild {key} cost must name one currency and one item")
    if currency_key not in {"currency.spirit_stone", "spirit_stones"}:
        raise ContentError(f"path_rebuild {key} only supports spirit-stone currency")
    item = bundle.get("item", item_key, include_locked=False)
    if item is None:
        raise ContentError(f"path_rebuild {key} references an unknown item: {item_key!r}")
    if item.get("item_type") != "token":
        raise ContentError(f"path_rebuild {key} rebuild item must be a token")
    return currency_key, spirit_stones, item_key, item_quantity


def path_rebuild_definitions(
    content: ContentBundle | None = None,
) -> dict[str, PathRebuildDefinition]:
    bundle = _bundle(content)
    definitions: dict[str, PathRebuildDefinition] = {}
    selectors: dict[str, str] = {}
    for row in bundle.list(KIND, include_locked=True):
        key = row.get("key")
        if not isinstance(key, str) or not key.startswith(KEY_PREFIX):
            raise ContentError(f"path_rebuild {key!r} must use the {KEY_PREFIX} prefix")
        missing = REQUIRED_FIELDS - set(row)
        if missing:
            raise ContentError(f"path_rebuild {key} is missing fields: {sorted(missing)}")
        unknown = set(row) - ALLOWED_FIELDS
        if unknown:
            raise ContentError(f"path_rebuild {key} has unknown fields: {sorted(unknown)}")
        status = row.get("status")
        if status not in STATUSES:
            raise ContentError(f"path_rebuild {key} has an invalid status: {status!r}")
        name = _text(row, "name", key)
        description = _text(row, "desc", key)
        aliases = row.get("aliases")
        if not isinstance(aliases, list) or any(
            not isinstance(alias, str) or not alias.strip() for alias in aliases
        ):
            raise ContentError(f"path_rebuild {key} aliases must be non-empty strings")
        normalised_aliases = tuple(alias.strip() for alias in aliases)
        if len(set(normalised_aliases)) != len(normalised_aliases):
            raise ContentError(f"path_rebuild {key} has duplicate aliases")
        for selector in (key, name, *normalised_aliases):
            owner = selectors.get(selector)
            if owner is not None and owner != key:
                raise ContentError(
                    f"path_rebuild selector {selector!r} is ambiguous between {owner} and {key}"
                )
            selectors[selector] = key
        min_realm = _text(row, "min_realm", key)
        min_layer = _positive_int(row.get("min_layer"), f"{key} min_layer")
        _realm_layer(bundle, min_realm, min_layer, f"{key} min_realm")
        reputation = _reputation(row.get("required_reputation"), key)
        intro_flag = _text(row, "required_intro_flag", key)
        currency_key, spirit_stones, item_key, item_quantity = _cost(
            row.get("cost"), key, bundle
        )
        deduction = row.get("level_deduction")
        if isinstance(deduction, bool) or not isinstance(deduction, int) or not 0 <= deduction <= 2:
            raise ContentError(f"path_rebuild {key} level_deduction must be an integer in 0..2")
        preview_ttl = _positive_int(
            row.get("preview_ttl_seconds"), f"{key} preview_ttl_seconds"
        )
        if status not in {"active", "open"}:
            continue
        definitions[key] = PathRebuildDefinition(
            key=key,
            label=name,
            description=description,
            aliases=normalised_aliases,
            min_realm=min_realm,
            min_layer=min_layer,
            required_reputation=reputation,
            required_intro_flag=intro_flag,
            currency_key=currency_key,
            spirit_stone_cost=spirit_stones,
            token_item_key=item_key,
            token_quantity=item_quantity,
            level_deduction=int(deduction),
            preview_ttl_seconds=preview_ttl,
        )
    if not definitions:
        raise ContentError("no active path_rebuild rule is registered")
    return definitions


def path_rebuild_definition(
    content: ContentBundle | None = None, key: str | None = None
) -> PathRebuildDefinition:
    definitions = path_rebuild_definitions(content)
    if key is None:
        if len(definitions) != 1:
            raise ContentError("exactly one active path_rebuild rule is required")
        return next(iter(definitions.values()))
    try:
        return definitions[key]
    except KeyError as exc:
        raise ContentError(f"unknown path_rebuild rule: {key}") from exc


def resolve_path_rebuild(
    value: str, content: ContentBundle | None = None
) -> str | None:
    try:
        return resolve_content_key(_bundle(content), KIND, value, include_locked=False)
    except ValueError:
        return None


__all__ = [
    "PathRebuildDefinition",
    "path_rebuild_definition",
    "path_rebuild_definitions",
    "resolve_path_rebuild",
]
