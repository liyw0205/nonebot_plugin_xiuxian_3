"""Rules shared by the local three-realms arena mode.

The mode is intentionally local.  It freezes tactical context in each
snapshot, while leaving faction reputation, inventory and other player
assets outside the arena transaction.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..utils.player import (
    player_field,
    player_integer,
    player_intro_flags,
    player_inventory,
    player_object,
    player_reputation,
)

THREE_REALMS_ARENA_MODE_KEY = "arena.three_realms"
THREE_REALMS_ARENA_MIN_REALM = "nascent_soul"
THREE_REALMS_ARENA_MIN_LAYER = 1
THREE_REALMS_ARENA_PERMIT_KEY = "item.permit.three_realms_arena"
THREE_REALMS = ("xuantian", "demon", "beast")


def intro_flags(player: Mapping[str, Any]) -> set[str]:
    return set(player_intro_flags(player))


def player_faction(player: Mapping[str, Any]) -> str:
    """Resolve the frozen tactical faction without trusting client input."""

    for direct_key in ("faction_key", "alliance_key"):
        direct = str(player_field(player, direct_key, "") or "").strip().lower()
        if direct.startswith("alliance."):
            direct = direct.split(".", 1)[1]
        if direct in THREE_REALMS:
            return direct
    qualification = player_object(player, "qualification_json")
    intro = player_object(player, "intro_json")
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
    reputation = player_reputation(player)
    ranked = sorted(
        ((faction, int(reputation.get(faction, 0))) for faction in THREE_REALMS),
        key=lambda item: (-item[1], THREE_REALMS.index(item[0])),
    )
    if ranked and ranked[0][1] > 0:
        return ranked[0][0]
    return "xuantian"


def has_three_realms_permit(player: Mapping[str, Any]) -> bool:
    inventory = player_inventory(player)
    return inventory.get(THREE_REALMS_ARENA_PERMIT_KEY, 0) > 0


def meets_three_realms_gate(player: Mapping[str, Any]) -> bool:
    return (
        str(player_field(player, "stage", "")) == "cultivator"
        and str(player_field(player, "realm_key", "")) == THREE_REALMS_ARENA_MIN_REALM
        and player_integer(player, "realm_layer") >= THREE_REALMS_ARENA_MIN_LAYER
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
        "challenger_pollution": player_integer(challenger, "pollution"),
        "defender_pollution": player_integer(defender, "pollution"),
        "challenger_bloodline_stability": player_integer(challenger, "bloodline_stability"),
        "defender_bloodline_stability": player_integer(defender, "bloodline_stability"),
    }


__all__ = [
    "THREE_REALMS",
    "THREE_REALMS_ARENA_MODE_KEY",
    "THREE_REALMS_ARENA_MIN_LAYER",
    "THREE_REALMS_ARENA_MIN_REALM",
    "THREE_REALMS_ARENA_PERMIT_KEY",
    "has_three_realms_permit",
    "meets_three_realms_gate",
    "player_faction",
    "tactical_environment",
]
