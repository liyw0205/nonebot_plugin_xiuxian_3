"""Shared normalization for player values read from SQLite rows."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .assets import inventory_value
from .json import json_object


def player_values(row: Mapping[str, Any] | Any) -> dict[str, Any]:
    """Return normalized identity, resources and combat inputs from a player row.

    The query may contain only a subset of player columns (for example a party
    member join), so missing values use the same neutral defaults everywhere.
    """

    def value(key: str, default: Any = None) -> Any:
        if isinstance(row, Mapping):
            return row.get(key, default)
        try:
            return row[key]
        except (IndexError, KeyError):
            return default

    def integer(key: str, default: int = 0) -> int:
        raw = value(key, default)
        if raw is None:
            return default
        return int(raw)

    qualification = json_object(value("qualification_json", {}), {})
    inventory = inventory_value(value("inventory_json", {}))
    intro = json_object(value("intro_json", {}), {})
    return {
        "player_id": str(value("player_id", value("id", ""))),
        "platform": str(value("platform", "") or ""),
        "platform_user_id": str(value("platform_user_id", "") or ""),
        "scene_id": str(value("scene_id", "") or ""),
        "nickname": str(value("nickname", "") or ""),
        "stage": str(value("stage", "new_user") or "new_user"),
        "status": str(value("status", "active") or "active"),
        "dao_name": str(value("dao_name", "") or ""),
        "path_key": value("path_key"),
        "subprofession_key": value("subprofession_key"),
        "location_key": str(value("location_key", "xuantian.new_town")),
        "realm_key": str(value("realm_key", "mortal")),
        "realm_layer": integer("realm_layer"),
        "qualification": {str(key): int(item) for key, item in qualification.items()},
        "inventory": {str(key): int(item) for key, item in inventory.items()},
        "intro_flags": tuple(str(item) for item in intro.get("flags", [])),
        "selected_service": (
            str(intro["selected_service"])
            if intro.get("selected_service") is not None
            else value("selected_service")
        ),
        "spirit_stones": integer("spirit_stones"),
        "stamina": integer("stamina"),
        "stamina_max": integer("stamina_max"),
        "energy": integer("energy"),
        "energy_max": integer("energy_max"),
        "cultivation": integer("cultivation"),
        "total_cultivation": integer("total_cultivation"),
        "foundation_quality": integer("foundation_quality"),
        "world_merit": integer("world_merit"),
        "void_merit": integer("void_merit"),
        "alliance_points": integer("alliance_points"),
        "arena_rating": integer("arena_rating", 1000),
        "arena_wins": integer("arena_wins"),
        "arena_losses": integer("arena_losses"),
        "arena_draws": integer("arena_draws"),
        "talent_points": integer("talent_points"),
        "skill_insights": integer("skill_insights"),
        "max_hp": integer("max_hp"),
        "max_mp": integer("max_mp"),
        "carry_capacity": integer("carry_capacity"),
        "initiative": integer("initiative"),
        "soul_power": integer("soul_power"),
        "soul_power_max": integer("soul_power_max"),
        "pollution": integer("pollution"),
        "bloodline_stability": integer("bloodline_stability"),
        "cross_realm_penalty_bp": integer("cross_realm_penalty_bp"),
        "realm_resistance_bp": integer("realm_resistance_bp"),
        "exploration_efficiency_bp": integer("exploration_efficiency_bp"),
        "heart_demon_bonus_bp": integer("heart_demon_bonus_bp"),
        "breakthrough_pity_bp": integer("breakthrough_pity_bp"),
        "domain_key": value("domain_key"),
        "domain_level": integer("domain_level"),
        "domain_charge": integer("domain_charge"),
        "domain_charge_max": integer("domain_charge_max"),
        "domain_power": integer("domain_power"),
        "void_power": integer("void_power"),
        "void_power_max": integer("void_power_max"),
        "space_resistance_bp": integer("space_resistance_bp"),
        "void_route_count": integer("void_route_count"),
        "void_anchor_capacity": integer("void_anchor_capacity"),
        "dao_fruit_progress": integer("dao_fruit_progress"),
        "ascension_merit": integer("ascension_merit"),
        "tribulation_debt": integer("tribulation_debt"),
        "dao_fruit_key": value("dao_fruit_key"),
        "endgame_status": str(value("endgame_status", "none") or "none"),
        "ending_key": value("ending_key"),
    }


__all__ = ["player_values"]
