"""Content contract for the talent-tree reset (kind ``talent_reset``).

``docs/foundation/advancement/content-v0.1.md`` registered ``talent.reset_tree``
as a future use case but never froze its cost or refund, so no runtime command
existed.  This loader owns the shipped first-version numbers; the repository
and application must not carry a second copy.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..content import ContentBundle, ContentError, bundled_content, resolve_content_key

KIND = "talent_reset"
KEY_PREFIX = "talent.reset."
STATUSES = {"active", "open", "locked", "planned"}
REQUIRED_FIELDS = {
    "key",
    "name",
    "desc",
    "aliases",
    "status",
    "min_realm",
    "min_layer",
    "cost",
    "refund_bp",
    "cooldown_seconds",
    "preview_ttl_seconds",
}
ALLOWED_FIELDS = REQUIRED_FIELDS


@dataclass(frozen=True, slots=True)
class TalentResetDefinition:
    key: str
    label: str
    description: str
    aliases: tuple[str, ...]
    min_realm: str
    min_layer: int
    currency_key: str
    spirit_stone_cost: int
    refund_bp: int
    cooldown_seconds: int
    preview_ttl_seconds: int


def _bundle(content: ContentBundle | None) -> ContentBundle:
    return content if content is not None else bundled_content()


def _text(row: dict[str, Any], field: str, key: str) -> str:
    value = row.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ContentError(f"talent_reset {key} requires a non-empty {field}")
    return value.strip()


def _positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ContentError(f"talent_reset {label} must be a positive integer")
    return int(value)


def _realm_layer(bundle: ContentBundle, realm_key: str, layer: int, label: str) -> None:
    row = bundle.get("realm", realm_key, include_locked=False)
    if row is None:
        raise ContentError(f"talent_reset {label} references an unknown realm: {realm_key!r}")
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
            f"talent_reset {label} layer {layer} is outside realm {realm_key} range"
        )


def _cost(value: Any, key: str, bundle: ContentBundle) -> tuple[str, int]:
    if not isinstance(value, dict) or len(value) != 1:
        raise ContentError(f"talent_reset {key} cost must name exactly one currency")
    raw_key, raw_value = next(iter(value.items()))
    if not isinstance(raw_key, str):
        raise ContentError(f"talent_reset {key} cost keys must be strings")
    if raw_key not in {"currency.spirit_stone", "spirit_stones"}:
        raise ContentError(f"talent_reset {key} only supports spirit-stone currency")
    return raw_key, _positive_int(raw_value, f"{key} cost[{raw_key}]")


def _refund_bp(value: Any, key: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 10_000:
        raise ContentError(f"talent_reset {key} refund_bp must be an integer in 0..10000")
    return int(value)


def talent_reset_definitions(
    content: ContentBundle | None = None,
) -> dict[str, TalentResetDefinition]:
    bundle = _bundle(content)
    definitions: dict[str, TalentResetDefinition] = {}
    selectors: dict[str, str] = {}
    for row in bundle.list(KIND, include_locked=True):
        key = row.get("key")
        if not isinstance(key, str) or not key.startswith(KEY_PREFIX):
            raise ContentError(f"talent_reset {key!r} must use the {KEY_PREFIX} prefix")
        missing = REQUIRED_FIELDS - set(row)
        if missing:
            raise ContentError(f"talent_reset {key} is missing fields: {sorted(missing)}")
        unknown = set(row) - ALLOWED_FIELDS
        if unknown:
            raise ContentError(f"talent_reset {key} has unknown fields: {sorted(unknown)}")
        status = row.get("status")
        if status not in STATUSES:
            raise ContentError(f"talent_reset {key} has an invalid status: {status!r}")
        name = _text(row, "name", key)
        description = _text(row, "desc", key)
        aliases = row.get("aliases")
        if not isinstance(aliases, list) or any(
            not isinstance(alias, str) or not alias.strip() for alias in aliases
        ):
            raise ContentError(f"talent_reset {key} aliases must be non-empty strings")
        normalised_aliases = tuple(alias.strip() for alias in aliases)
        if len(set(normalised_aliases)) != len(normalised_aliases):
            raise ContentError(f"talent_reset {key} has duplicate aliases")
        for selector in (key, name, *normalised_aliases):
            owner = selectors.get(selector)
            if owner is not None and owner != key:
                raise ContentError(
                    f"talent_reset selector {selector!r} is ambiguous between {owner} and {key}"
                )
            selectors[selector] = key
        min_realm = _text(row, "min_realm", key)
        min_layer = _positive_int(row.get("min_layer"), f"{key} min_layer")
        _realm_layer(bundle, min_realm, min_layer, f"{key} min_realm")
        currency_key, spirit_stones = _cost(row.get("cost"), key, bundle)
        refund_bp = _refund_bp(row.get("refund_bp"), key)
        cooldown = _positive_int(row.get("cooldown_seconds"), f"{key} cooldown_seconds")
        preview_ttl = _positive_int(
            row.get("preview_ttl_seconds"), f"{key} preview_ttl_seconds"
        )
        if status not in {"active", "open"}:
            continue
        definitions[key] = TalentResetDefinition(
            key=key,
            label=name,
            description=description,
            aliases=normalised_aliases,
            min_realm=min_realm,
            min_layer=min_layer,
            currency_key=currency_key,
            spirit_stone_cost=spirit_stones,
            refund_bp=refund_bp,
            cooldown_seconds=cooldown,
            preview_ttl_seconds=preview_ttl,
        )
    if not definitions:
        raise ContentError("no active talent_reset rule is registered")
    return definitions


def talent_reset_definition(
    content: ContentBundle | None = None, key: str | None = None
) -> TalentResetDefinition:
    definitions = talent_reset_definitions(content)
    if key is None:
        if len(definitions) != 1:
            raise ContentError("exactly one active talent_reset rule is required")
        return next(iter(definitions.values()))
    try:
        return definitions[key]
    except KeyError as exc:
        raise ContentError(f"unknown talent_reset rule: {key}") from exc


def resolve_talent_reset(
    value: str, content: ContentBundle | None = None
) -> str | None:
    try:
        return resolve_content_key(_bundle(content), KIND, value, include_locked=False)
    except ValueError:
        return None


__all__ = [
    "TalentResetDefinition",
    "resolve_talent_reset",
    "talent_reset_definition",
    "talent_reset_definitions",
]
