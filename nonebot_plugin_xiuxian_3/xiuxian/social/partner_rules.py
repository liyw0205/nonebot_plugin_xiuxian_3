"""Content-driven rules for the partner relationship slice."""

from __future__ import annotations

from dataclasses import asdict, dataclass
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


def partner_definition(content: ContentBundle) -> PartnerDefinition:
    try:
        row = content.require("social_interaction", "social.partner", include_locked=True)
    except KeyError as exc:
        raise ContentError("缺少道侣关系内容") from exc
    if row.get("status") not in {"active", "open"}:
        raise ContentError("道侣关系内容尚未开放")
    required_realm = row.get("required_realm")
    required_layer = row.get("required_layer")
    if not isinstance(required_realm, str) or not required_realm.strip():
        raise ContentError("道侣关系缺少准入境界")
    if isinstance(required_layer, bool) or not isinstance(required_layer, int) or required_layer < 0:
        raise ContentError("道侣关系准入层数无效")
    realm = content.get("realm", required_realm, include_locked=False)
    if realm is None or isinstance(realm.get("rank"), bool) or not isinstance(realm.get("rank"), int):
        raise ContentError("道侣关系准入境界引用无效")

    def positive_int(name: str) -> int:
        value = row.get(name)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ContentError(f"道侣关系字段无效: {name}")
        return value

    cooldown_scope = row.get("cooldown_scope")
    if cooldown_scope != "pair":
        raise ContentError("道侣关系冷却范围无效")
    return PartnerDefinition(
        key="social.partner",
        required_realm=required_realm,
        required_rank=int(realm["rank"]),
        required_layer=required_layer,
        invitation_ttl_seconds=positive_int("invitation_ttl_seconds"),
        dissolution_ttl_seconds=positive_int("dissolution_ttl_seconds"),
        reunion_cooldown_seconds=positive_int("reunion_cooldown_seconds"),
        max_active_relations=positive_int("max_active_relations"),
        cooldown_scope=cooldown_scope,
    )


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


__all__ = ["PartnerDefinition", "partner_definition", "partner_eligible"]
