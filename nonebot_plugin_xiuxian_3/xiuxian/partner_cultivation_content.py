"""Strict content and frozen rules for consensual partner cultivation."""

from __future__ import annotations

from typing import Any

from .content import ContentBundle, ContentError

KIND = "partner_cultivation"
KEY = "social.partner_cultivation"
FIELDS = frozenset({
    "key", "name", "aliases", "desc", "status", "required_realm", "required_layer",
    "allowed_locations", "invitation_ttl_seconds", "daily_limit", "quota_timezone",
    "cost", "effect", "gain_bp", "gain_min", "gain_max",
})


def _integer(value: object, label: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ContentError(f"partner cultivation {label} must be an integer in [{minimum}, {maximum}]")
    return value


def validate_definition(row: object, content: ContentBundle, *, frozen: bool = False) -> dict[str, Any]:
    expected = FIELDS | {"required_rank"} if frozen else FIELDS
    if not isinstance(row, dict) or set(row) != expected or row.get("key") != KEY:
        raise ContentError("partner cultivation fields/key are incomplete or unsupported")
    for field in ("name", "desc", "required_realm"):
        value = row[field]
        if not isinstance(value, str) or not value.strip() or value != value.strip():
            raise ContentError(f"partner cultivation {field} must be non-empty text")
    if not isinstance(row["status"], str) or row["status"] not in {"active", "closed", "placeholder"} or (frozen and row["status"] != "active"):
        raise ContentError("partner cultivation status is invalid")
    aliases = row["aliases"]
    if not isinstance(aliases, list) or any(
        not isinstance(alias, str) or not alias.strip() or alias != alias.strip() for alias in aliases
    ) or len(set([row["name"], *aliases])) != len(aliases) + 1:
        raise ContentError("partner cultivation aliases must be unique non-empty text")
    realm = content.get("realm", row["required_realm"])
    if realm is None:
        raise ContentError("partner cultivation required_realm does not resolve")
    rank = _integer(realm.get("rank"), "realm rank", 0, 100)
    layer_min = _integer(realm.get("layer_min"), "realm layer_min", 0, 100)
    layer_max = _integer(realm.get("layer_max"), "realm layer_max", layer_min, 100)
    layer = _integer(row["required_layer"], "required_layer", layer_min, layer_max)
    if frozen:
        rank = _integer(row["required_rank"], "required_rank", 0, 100)
    locations = row["allowed_locations"]
    if not isinstance(locations, list) or not locations or any(
        not isinstance(key, str) or content.get("location", key) is None for key in locations
    ) or len(set(locations)) != len(locations):
        raise ContentError("partner cultivation allowed_locations must resolve uniquely")
    for field, maximum in (("invitation_ttl_seconds", 86400), ("daily_limit", 100),
                           ("gain_bp", 10000), ("gain_min", 1000000), ("gain_max", 1000000)):
        _integer(row[field], field, 1, maximum)
    if row["gain_min"] > row["gain_max"]:
        raise ContentError("partner cultivation gain bounds are inverted")
    if row["quota_timezone"] != "UTC" or row["effect"] != "personal_layer_progress":
        raise ContentError("partner cultivation timezone/effect is unsupported")
    cost = row["cost"]
    if not isinstance(cost, dict) or set(cost) != {"spirit_stones", "energy"}:
        raise ContentError("partner cultivation cost assets are unsupported")
    for key, amount in cost.items():
        _integer(amount, f"cost.{key}", 1, 1000000)
    return dict(row, required_layer=layer, required_rank=rank)


def dual_cultivation_definition(content: ContentBundle) -> dict[str, Any]:
    rows = content.list(KIND)
    if len(rows) != 1:
        raise ContentError("partner cultivation requires exactly one definition")
    return validate_definition(rows[0], content)


def personal_gain(player: Any, rule: dict[str, Any], content: ContentBundle) -> int:
    realm = content.get("realm", str(player["realm_key"]), include_locked=False)
    if realm is None or player["stage"] != "cultivator" or player["status"] != "active":
        return 0
    rank, layer = realm["rank"], player["realm_layer"]
    if rank < rule["required_rank"] or (rank == rule["required_rank"] and layer < rule["required_layer"]):
        return 0
    thresholds = realm["layer_thresholds"]
    if type(layer) is not int or not realm["layer_min"] <= layer <= realm["layer_max"]:
        return 0
    floor = thresholds.get(str(layer))
    ceiling = thresholds.get(str(min(layer + 1, realm["layer_max"])))
    cultivation = player["cultivation"]
    if type(floor) is not int or type(ceiling) is not int or type(cultivation) is not int or cultivation < floor:
        return 0
    span = ceiling - floor
    desired = min(rule["gain_max"], max(rule["gain_min"], span * rule["gain_bp"] // 10000))
    return max(0, min(desired, ceiling - cultivation))
