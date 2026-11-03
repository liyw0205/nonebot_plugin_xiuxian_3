"""Content-backed contract for 虚空物资寄售 (``market.void_material``).

Economy v0.5 froze the row: void materials listed for six hours with an 800 bp
fee, admission by realm or void merit.  The loader pins the allowed item set to
items that really are tradeable and not character-bound, so the market can
never advertise goods that cannot legally change hands.
"""

from __future__ import annotations

from typing import Any

from ..content import ContentBundle, ContentError, bundled_content

KIND = "void_material_market"
DEFAULTS_KEY = "market.void_material.defaults"
REQUIRED_FIELDS = {
    "key",
    "name",
    "desc",
    "status",
    "listing_hours",
    "fee_bp",
    "expire_grace_minutes",
    "max_listings_per_player",
    "admission",
    "allowed_item_keys",
}
ADMISSION_FIELDS = {"realm", "min_layer", "merit_key", "min_merit"}
MERIT_KEYS = {"void_merit", "world_merit"}


def _bundle(content: ContentBundle | None) -> ContentBundle:
    return content if content is not None else bundled_content()


def _text(row: dict[str, Any], field: str, key: str) -> str:
    value = row.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ContentError(f"void material market {key} requires a {field}")
    return value.strip()


def _bounded_int(value: Any, label: str, *, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ContentError(f"void material market {label} must be between {low} and {high}")
    return int(value)


def void_material_defaults(content: ContentBundle | None = None) -> dict[str, Any]:
    """Return the validated listing parameters."""

    bundle = _bundle(content)
    try:
        row = bundle.require(KIND, DEFAULTS_KEY, include_locked=True)
    except KeyError as exc:
        raise ContentError(f"missing void_material_market content: {DEFAULTS_KEY}") from exc
    if row.get("status") != "active":
        raise ContentError(f"{DEFAULTS_KEY} is not active")
    missing = REQUIRED_FIELDS - set(row)
    if missing:
        raise ContentError(f"void material market {DEFAULTS_KEY} is missing fields: {sorted(missing)}")

    admission = row.get("admission")
    if not isinstance(admission, dict) or set(admission) != ADMISSION_FIELDS:
        raise ContentError(f"void material market {DEFAULTS_KEY} admission is malformed")
    realm_key = _text(admission, "realm", DEFAULTS_KEY)
    realm = bundle.get("realm", realm_key, include_locked=False)
    if realm is None:
        raise ContentError(
            f"void material market {DEFAULTS_KEY} references an unknown realm: {realm_key!r}"
        )
    min_layer = admission.get("min_layer")
    if (
        isinstance(min_layer, bool)
        or not isinstance(min_layer, int)
        or not int(realm.get("layer_min", 1)) <= min_layer <= int(realm.get("layer_max", 1))
    ):
        raise ContentError(f"void material market {DEFAULTS_KEY} admission.min_layer is outside realm")
    merit_key = _text(admission, "merit_key", DEFAULTS_KEY)
    if merit_key not in MERIT_KEYS:
        raise ContentError(f"void material market {DEFAULTS_KEY} admission.merit_key is unsupported")

    keys = row.get("allowed_item_keys")
    if not isinstance(keys, list) or not keys:
        raise ContentError(f"void material market {DEFAULTS_KEY} allowed_item_keys must be a non-empty list")
    normalised_keys: list[str] = []
    for item_key in keys:
        if not isinstance(item_key, str) or not item_key.strip():
            raise ContentError(f"void material market {DEFAULTS_KEY} has a malformed item key")
        item = bundle.get("item", item_key, include_locked=False)
        if item is None:
            raise ContentError(
                f"void material market {DEFAULTS_KEY} references an unknown item: {item_key!r}"
            )
        if item.get("tradeable") is not True:
            raise ContentError(f"void material market {DEFAULTS_KEY} lists an untradeable item: {item_key!r}")
        if str(item.get("bind_type", "")) == "character_bound":
            raise ContentError(f"void material market {DEFAULTS_KEY} lists a bound item: {item_key!r}")
        if item_key in normalised_keys:
            raise ContentError(f"void material market {DEFAULTS_KEY} repeats the item {item_key!r}")
        normalised_keys.append(item_key)

    names = [_text(row, "name", DEFAULTS_KEY)]
    raw_aliases = row.get("aliases", [])
    if not isinstance(raw_aliases, list):
        raise ContentError(f"void material market {DEFAULTS_KEY} aliases must be a list")
    for alias in raw_aliases:
        if not isinstance(alias, str) or not alias.strip():
            raise ContentError(f"void material market {DEFAULTS_KEY} has a malformed alias")
        names.append(alias.strip())

    return {
        "key": DEFAULTS_KEY,
        "name": names[0],
        "description": _text(row, "desc", DEFAULTS_KEY),
        "aliases": tuple(names),
        "listing_hours": _bounded_int(
            row.get("listing_hours"), f"{DEFAULTS_KEY} listing_hours", low=1, high=72
        ),
        "fee_bp": _bounded_int(row.get("fee_bp"), f"{DEFAULTS_KEY} fee_bp", low=0, high=2_000),
        "expire_grace_minutes": _bounded_int(
            row.get("expire_grace_minutes"),
            f"{DEFAULTS_KEY} expire_grace_minutes",
            low=0,
            high=60,
        ),
        "max_listings_per_player": _bounded_int(
            row.get("max_listings_per_player"),
            f"{DEFAULTS_KEY} max_listings_per_player",
            low=1,
            high=50,
        ),
        "admission": {
            "realm": realm_key,
            "min_layer": int(min_layer),
            "merit_key": merit_key,
            "min_merit": _bounded_int(
                admission.get("min_merit"),
                f"{DEFAULTS_KEY} admission.min_merit",
                low=0,
                high=1_000_000,
            ),
        },
        "allowed_item_keys": tuple(normalised_keys),
    }