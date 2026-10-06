"""Content-driven rules for the partner relationship slice."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, fields
from typing import Any

from ..content import ContentBundle, ContentError
from ..utils.player import player_integer


@dataclass(frozen=True, slots=True)
class PartnerDefinition:
    key: str
    required_realm: str
    required_rank: int
    required_layer: int
    invitation_ttl_seconds: int
    dissolution_ttl_seconds: int
    reunion_cooldown_seconds: int
    max_active_relations: int
    cooldown_scope: str

    def snapshot(self) -> dict[str, Any]:
        return asdict(self)


_SNAPSHOT_FIELDS = frozenset(field.name for field in fields(PartnerDefinition))


def partner_definition_from_snapshot(value: object) -> PartnerDefinition:
    if not isinstance(value, Mapping) or set(value) != _SNAPSHOT_FIELDS:
        raise ValueError("partner snapshot fields are incomplete or unsupported")
    if value["key"] != "social.partner":
        raise ValueError("partner snapshot key is invalid")
    required_realm = value["required_realm"]
    if not isinstance(required_realm, str) or not required_realm or required_realm != required_realm.strip():
        raise ValueError("partner snapshot required_realm is invalid")

    def integer(name: str, minimum: int) -> int:
        item = value[name]
        if isinstance(item, bool) or not isinstance(item, int) or item < minimum:
            raise ValueError(f"partner snapshot {name} is invalid")
        return item

    required_rank = integer("required_rank", 0)
    required_layer = integer("required_layer", 0)
    invitation_ttl_seconds = integer("invitation_ttl_seconds", 1)
    dissolution_ttl_seconds = integer("dissolution_ttl_seconds", 1)
    reunion_cooldown_seconds = integer("reunion_cooldown_seconds", 1)
    max_active_relations = integer("max_active_relations", 1)
    if max_active_relations != 1:
        raise ValueError("partner snapshot max_active_relations is unsupported")
    if value["cooldown_scope"] != "pair":
        raise ValueError("partner snapshot cooldown_scope is unsupported")
    return PartnerDefinition(
        key=value["key"],
        required_realm=required_realm,
        required_rank=required_rank,
        required_layer=required_layer,
        invitation_ttl_seconds=invitation_ttl_seconds,
        dissolution_ttl_seconds=dissolution_ttl_seconds,
        reunion_cooldown_seconds=reunion_cooldown_seconds,
        max_active_relations=max_active_relations,
        cooldown_scope=value["cooldown_scope"],
    )


def partner_definition(content: ContentBundle) -> PartnerDefinition:
    try:
        row = content.require("social_interaction", "social.partner", include_locked=True)
    except KeyError as exc:
        raise ContentError("missing social_interaction content: social.partner") from exc
    if row.get("status") not in {"active", "open"}:
        raise ContentError("social.partner status is not open")
    required_realm = row.get("required_realm")
    if not isinstance(required_realm, str) or not required_realm.strip():
        raise ContentError("social.partner required_realm is invalid")
    realm = content.get("realm", required_realm, include_locked=False)
    if realm is None:
        raise ContentError("social.partner required_realm reference is not open")
    try:
        snapshot = {name: row[name] for name in _SNAPSHOT_FIELDS if name != "required_rank"}
        snapshot["required_rank"] = realm["rank"]
        return partner_definition_from_snapshot(snapshot)
    except (KeyError, ValueError) as exc:
        raise ContentError(f"invalid social.partner content: {exc}") from exc


def partner_eligible(player: Any, definition: PartnerDefinition, content: ContentBundle) -> bool:
    if str(player["stage"]) != "cultivator" or str(player["status"]) != "active":
        return False
    realm_key = str(player["realm_key"])
    realm = content.get("realm", realm_key, include_locked=False)
    if realm is None or not isinstance(realm.get("rank"), int):
        return False
    rank = int(realm["rank"])
    layer = player_integer(player, "realm_layer")
    return rank > definition.required_rank or (rank == definition.required_rank and layer >= definition.required_layer)


__all__ = ["PartnerDefinition", "partner_definition", "partner_definition_from_snapshot", "partner_eligible"]
