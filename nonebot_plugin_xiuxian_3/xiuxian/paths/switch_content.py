"""Content contract for path switching (kind ``path_switch``).

The v0.1 path contract froze a two-phase switch (preview then confirm) but the
runtime never implemented it: ``docs/foundation/paths/use-cases.md`` named
``preview_path_switch`` / ``confirm_path_switch`` while no module referenced
them.  This loader owns the shipped numbers so the repository and application
never carry a second copy.

One active rule is expected.  Every reference is resolved against the same
bundle: both realms must exist and the layers must sit inside their realm's
range, and the cost must name one currency plus exactly one real item.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..content import ContentBundle, ContentError, bundled_content, resolve_content_key

KIND = "path_switch"
KEY_PREFIX = "path.switch."
STATUSES = {"active", "open", "locked", "planned"}
REQUIRED_FIELDS = {
    "key",
    "name",
    "desc",
    "aliases",
    "status",
    "min_realm",
    "min_layer",
    "token_claim_realm",
    "token_claim_layer",
    "cost",
    "cooldown_seconds",
    "preview_ttl_seconds",
    "status_label",
}
ALLOWED_FIELDS = REQUIRED_FIELDS


@dataclass(frozen=True, slots=True)
class PathSwitchDefinition:
    key: str
    label: str
    description: str
    aliases: tuple[str, ...]
    min_realm: str
    min_layer: int
    token_claim_realm: str
    token_claim_layer: int
    currency_key: str
    spirit_stone_cost: int
    token_item_key: str
    token_quantity: int
    cooldown_seconds: int
    preview_ttl_seconds: int
    status_label: str


def _bundle(content: ContentBundle | None) -> ContentBundle:
    return content if content is not None else bundled_content()


def _text(row: dict[str, Any], field: str, key: str) -> str:
    value = row.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ContentError(f"path_switch {key} requires a non-empty {field}")
    return value.strip()


def _positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ContentError(f"path_switch {label} must be a positive integer")
    return int(value)


def _realm_layer(bundle: ContentBundle, realm_key: str, layer: int, label: str) -> None:
    row = bundle.get("realm", realm_key, include_locked=False)
    if row is None:
        raise ContentError(f"path_switch {label} references an unknown realm: {realm_key!r}")
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
            f"path_switch {label} layer {layer} is outside realm {realm_key} range"
        )


def _cost(value: Any, key: str, bundle: ContentBundle) -> tuple[str, int, str, int]:
    if not isinstance(value, dict) or len(value) != 2:
        raise ContentError(f"path_switch {key} cost must name one currency and one item")
    currency_key = None
    spirit_stones = 0
    item_key = None
    item_quantity = 0
    for raw_key, raw_value in value.items():
        if not isinstance(raw_key, str):
            raise ContentError(f"path_switch {key} cost keys must be strings")
        if raw_key.startswith("currency.") or raw_key == "spirit_stones":
            if currency_key is not None:
                raise ContentError(f"path_switch {key} cost has more than one currency")
            currency_key = raw_key
            spirit_stones = _positive_int(raw_value, f"{key} cost[{raw_key}]")
        else:
            if item_key is not None:
                raise ContentError(f"path_switch {key} cost has more than one item")
            item_key = raw_key
            item_quantity = _positive_int(raw_value, f"{key} cost[{raw_key}]")
    if currency_key is None or item_key is None:
        raise ContentError(f"path_switch {key} cost must name one currency and one item")
    if currency_key not in {"currency.spirit_stone", "spirit_stones"}:
        raise ContentError(f"path_switch {key} only supports spirit-stone currency")
    item = bundle.get("item", item_key, include_locked=False)
    if item is None:
        raise ContentError(f"path_switch {key} references an unknown item: {item_key!r}")
    if item.get("item_type") != "token":
        raise ContentError(f"path_switch {key} switch item must be a token")
    return currency_key, spirit_stones, item_key, item_quantity


def path_switch_definitions(
    content: ContentBundle | None = None,
) -> dict[str, PathSwitchDefinition]:
    """Return every active switch rule keyed by its stable key."""

    bundle = _bundle(content)
    definitions: dict[str, PathSwitchDefinition] = {}
    selectors: dict[str, str] = {}
    for row in bundle.list(KIND, include_locked=True):
        key = row.get("key")
        if not isinstance(key, str) or not key.startswith(KEY_PREFIX):
            raise ContentError(f"path_switch {key!r} must use the {KEY_PREFIX} prefix")
        missing = REQUIRED_FIELDS - set(row)
        if missing:
            raise ContentError(f"path_switch {key} is missing fields: {sorted(missing)}")
        unknown = set(row) - ALLOWED_FIELDS
        if unknown:
            raise ContentError(f"path_switch {key} has unknown fields: {sorted(unknown)}")
        status = row.get("status")
        if status not in STATUSES:
            raise ContentError(f"path_switch {key} has an invalid status: {status!r}")
        name = _text(row, "name", key)
        description = _text(row, "desc", key)
        status_label = _text(row, "status_label", key)
        aliases = row.get("aliases")
        if not isinstance(aliases, list) or any(
            not isinstance(alias, str) or not alias.strip() for alias in aliases
        ):
            raise ContentError(f"path_switch {key} aliases must be non-empty strings")
        normalised_aliases = tuple(alias.strip() for alias in aliases)
        if len(set(normalised_aliases)) != len(normalised_aliases):
            raise ContentError(f"path_switch {key} has duplicate aliases")
        for selector in (key, name, *normalised_aliases):
            owner = selectors.get(selector)
            if owner is not None and owner != key:
                raise ContentError(
                    f"path_switch selector {selector!r} is ambiguous between {owner} and {key}"
                )
            selectors[selector] = key
        min_realm = _text(row, "min_realm", key)
        min_layer = _positive_int(row.get("min_layer"), f"{key} min_layer")
        _realm_layer(bundle, min_realm, min_layer, f"{key} min_realm")
        claim_realm = _text(row, "token_claim_realm", key)
        claim_layer = _positive_int(row.get("token_claim_layer"), f"{key} token_claim_layer")
        _realm_layer(bundle, claim_realm, claim_layer, f"{key} token_claim_realm")
        currency_key, spirit_stones, item_key, item_quantity = _cost(
            row.get("cost"), key, bundle
        )
        cooldown = _positive_int(row.get("cooldown_seconds"), f"{key} cooldown_seconds")
        preview_ttl = _positive_int(
            row.get("preview_ttl_seconds"), f"{key} preview_ttl_seconds"
        )
        if status not in {"active", "open"}:
            continue
        definitions[key] = PathSwitchDefinition(
            key=key,
            label=name,
            description=description,
            aliases=normalised_aliases,
            min_realm=min_realm,
            min_layer=min_layer,
            token_claim_realm=claim_realm,
            token_claim_layer=claim_layer,
            currency_key=currency_key,
            spirit_stone_cost=spirit_stones,
            token_item_key=item_key,
            token_quantity=item_quantity,
            cooldown_seconds=cooldown,
            preview_ttl_seconds=preview_ttl,
            status_label=status_label,
        )
    if not definitions:
        raise ContentError("no active path_switch rule is registered")
    return definitions


def path_switch_definition(
    content: ContentBundle | None = None, key: str | None = None
) -> PathSwitchDefinition:
    definitions = path_switch_definitions(content)
    if key is None:
        if len(definitions) != 1:
            raise ContentError("exactly one active path_switch rule is required")
        return next(iter(definitions.values()))
    try:
        return definitions[key]
    except KeyError as exc:
        raise ContentError(f"unknown path_switch rule: {key}") from exc


def resolve_path_switch(
    value: str, content: ContentBundle | None = None
) -> str | None:
    bundle = _bundle(content)
    try:
        return resolve_content_key(bundle, KIND, value, include_locked=False)
    except ValueError:
        return None


__all__ = [
    "PathSwitchDefinition",
    "path_switch_definition",
    "path_switch_definitions",
    "resolve_path_switch",
]
