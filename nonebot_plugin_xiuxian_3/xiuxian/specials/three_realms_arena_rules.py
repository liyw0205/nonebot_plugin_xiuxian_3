"""Rules shared by the local three-realms arena mode.

The mode is intentionally local.  It freezes tactical context in each
snapshot, while leaving faction reputation, inventory and other player
assets outside the arena transaction.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

THREE_REALMS_ARENA_MODE_KEY = "arena.three_realms"
THREE_REALMS_ARENA_RULE_VERSION = "arena-three-realms-0.1.0"
THREE_REALMS_ARENA_CONTENT_VERSION = "content-0.3"
THREE_REALMS_ARENA_MIN_REALM = "nascent_soul"
THREE_REALMS_ARENA_MIN_LAYER = 1
THREE_REALMS_ARENA_PERMIT_KEYS = (
    "item.permit.three_realms_arena",
    "permit.arena.three_realms",
    "access.arena.three_realms",
)
THREE_REALMS = ("xuantian", "demon", "beast")


def _json_map(raw: Any) -> dict[str, Any]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return {}
    return dict(raw) if isinstance(raw, Mapping) else {}


def _value(player: Mapping[str, Any], key: str, default: Any = None) -> Any:
    try:
        return player[key]
    except (KeyError, IndexError, TypeError):
        return default


def intro_flags(player: Mapping[str, Any]) -> set[str]:
    intro = _json_map(_value(player, "intro_json", {}))
    return {str(value) for value in intro.get("flags", ())}


def player_inventory(player: Mapping[str, Any]) -> dict[str, int]:
    inventory = _json_map(_value(player, "inventory_json", {}))
    return {str(key): max(0, int(value)) for key, value in inventory.items()}


def player_faction(player: Mapping[str, Any]) -> str:
    """Resolve the frozen tactical faction without trusting client input."""

    for direct_key in ("faction_key", "alliance_key"):
        direct = str(_value(player, direct_key, "") or "").strip().lower()
        if direct.startswith("alliance."):
            direct = direct.split(".", 1)[1]
        if direct in THREE_REALMS:
            return direct
    qualification = _json_map(_value(player, "qualification_json", {}))
    intro = _json_map(_value(player, "intro_json", {}))
    for source in (qualification, intro):
        for key in ("cross_realm_alliance", "alliance_key", "alliance", "盟约"):
            value = str(source.get(key) or "").strip().lower()
            if value.startswith("alliance."):
                value = value.split(".", 1)[1]
            if value in THREE_REALMS:
                return value
    flags = {str(value).strip().lower() for value in intro.get("flags", ())}
    for faction in THREE_REALMS:
        if f"alliance.{faction}" in flags:
            return faction
    reputation = _json_map(_value(player, "faction_reputation_json", {}))
    ranked = sorted(
        ((faction, int(reputation.get(faction, 0))) for faction in THREE_REALMS),
        key=lambda item: (-item[1], THREE_REALMS.index(item[0])),
    )
    if ranked and ranked[0][1] > 0:
        return ranked[0][0]
    return "xuantian"


def has_three_realms_permit(player: Mapping[str, Any]) -> bool:
    inventory = player_inventory(player)
    if any(inventory.get(key, 0) > 0 for key in THREE_REALMS_ARENA_PERMIT_KEYS):
        return True
    flags = intro_flags(player)
    return any(key in flags for key in THREE_REALMS_ARENA_PERMIT_KEYS)


def meets_three_realms_gate(player: Mapping[str, Any]) -> bool:
    return (
        str(_value(player, "stage", "")) == "cultivator"
        and str(_value(player, "realm_key", "")) == THREE_REALMS_ARENA_MIN_REALM
        and int(_value(player, "realm_layer", 0)) >= THREE_REALMS_ARENA_MIN_LAYER
        and has_three_realms_permit(player)
        and player_faction(player) in THREE_REALMS
    )


def tactical_environment(challenger: Mapping[str, Any], defender: Mapping[str, Any]) -> dict[str, Any]:
    left = player_faction(challenger)
    right = player_faction(defender)
    relation = "same_faction" if left == right else "cross_faction"
    return {
        "relation": relation,
        "challenger_faction": left,
        "defender_faction": right,
        "challenger_pollution": int(_value(challenger, "pollution", 0)),
        "defender_pollution": int(_value(defender, "pollution", 0)),
        "challenger_bloodline_stability": int(_value(challenger, "bloodline_stability", 0)),
        "defender_bloodline_stability": int(_value(defender, "bloodline_stability", 0)),
        "rule_version": THREE_REALMS_ARENA_RULE_VERSION,
    }


__all__ = [
    "THREE_REALMS",
    "THREE_REALMS_ARENA_CONTENT_VERSION",
    "THREE_REALMS_ARENA_MODE_KEY",
    "THREE_REALMS_ARENA_MIN_LAYER",
    "THREE_REALMS_ARENA_MIN_REALM",
    "THREE_REALMS_ARENA_PERMIT_KEYS",
    "THREE_REALMS_ARENA_RULE_VERSION",
    "has_three_realms_permit",
    "meets_three_realms_gate",
    "player_faction",
    "tactical_environment",
]
