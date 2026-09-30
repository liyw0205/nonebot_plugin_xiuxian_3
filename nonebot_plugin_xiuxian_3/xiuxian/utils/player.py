"""Shared normalization for player values read from SQLite rows."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .assets import inventory_value
from .json import json_object


PLAYER_RESOURCE_FIELDS = (
    "spirit_stones",
    "stamina",
    "stamina_max",
    "energy",
    "energy_max",
    "cultivation",
    "total_cultivation",
    "world_merit",
    "void_merit",
    "alliance_points",
    "talent_points",
    "skill_insights",
    "soul_power",
    "soul_power_max",
    "pollution",
    "bloodline_stability",
)


def player_field(row: Mapping[str, Any] | Any, key: str, default: Any = None) -> Any:
    """Read a player column from either a mapping or a SQLite row."""

    if isinstance(row, Mapping):
        return row.get(key, default)
    try:
        return row[key]
    except (IndexError, KeyError):
        return default


def player_integer(row: Mapping[str, Any] | Any, key: str, default: int = 0) -> int:
    """Read a player numeric column with the shared neutral default."""

    raw = player_field(row, key, default)
    if raw is None:
        return default
    if isinstance(raw, bool):
        raise ValueError(f"player field {key!r} must be an integer")
    return int(raw)


def player_numeric_values(
    row: Mapping[str, Any] | Any,
    fields: tuple[str, ...] = PLAYER_RESOURCE_FIELDS,
) -> dict[str, int]:
    """Read a consistent set of non-negative player numeric projections."""

    return {field: player_integer(row, field) for field in fields}


def player_resource_values(row: Mapping[str, Any] | Any) -> dict[str, int]:
    """Return the shared resource projection used by views and transactions."""

    return player_numeric_values(row)


def player_object(
    row: Mapping[str, Any] | Any,
    key: str,
    default: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Read one JSON object column from a player row without sharing defaults."""

    fallback = dict(default or {})
    value = json_object(player_field(row, key, fallback), fallback)
    return {str(name): item for name, item in value.items()}


def player_inventory(row: Mapping[str, Any] | Any) -> dict[str, int]:
    """Read the normalized item inventory shared by displays and battles."""

    return inventory_value(player_field(row, "inventory_json", {}))


def player_qualification(row: Mapping[str, Any] | Any) -> dict[str, int]:
    """Read normalized qualification values from a player row."""

    return {
        key: player_integer({key: value}, key)
        for key, value in player_object(row, "qualification_json").items()
    }


def player_intro_flags(row: Mapping[str, Any] | Any) -> tuple[str, ...]:
    """Read the immutable-style onboarding flags used by access checks."""

    flags = player_object(row, "intro_json").get("flags", [])
    if not isinstance(flags, (list, tuple)):
        return ()
    return tuple(str(flag) for flag in flags)


def player_reputation(row: Mapping[str, Any] | Any) -> dict[str, int]:
    """Read normalized local faction reputation values."""

    values = player_object(row, "faction_reputation_json")
    return {str(key): player_integer({"value": value}, "value") for key, value in values.items()}


def player_values(row: Mapping[str, Any] | Any) -> dict[str, Any]:
    """Return normalized identity, resources and combat inputs from a player row.

    The query may contain only a subset of player columns (for example a party
    member join), so missing values use the same neutral defaults everywhere.
    """

    qualification = player_qualification(row)
    inventory = player_inventory(row)
    intro = player_object(row, "intro_json")
    resources = player_resource_values(row)
    return {
        "player_id": str(player_field(row, "player_id", player_field(row, "id", ""))),
        "platform": str(player_field(row, "platform", "") or ""),
        "platform_user_id": str(player_field(row, "platform_user_id", "") or ""),
        "scene_id": str(player_field(row, "scene_id", "") or ""),
        "nickname": str(player_field(row, "nickname", "") or ""),
        "stage": str(player_field(row, "stage", "new_user") or "new_user"),
        "status": str(player_field(row, "status", "active") or "active"),
        "dao_name": str(player_field(row, "dao_name", "") or ""),
        "path_key": player_field(row, "path_key"),
        "subprofession_key": player_field(row, "subprofession_key"),
        "location_key": str(player_field(row, "location_key", "xuantian.new_town")),
        "realm_key": str(player_field(row, "realm_key", "mortal")),
        "realm_layer": player_integer(row, "realm_layer"),
        "qualification": qualification,
        "inventory": inventory,
        "intro_flags": player_intro_flags(row),
        "faction_reputation": player_reputation(row),
        "selected_service": (
            str(intro["selected_service"])
            if intro.get("selected_service") is not None
            else player_field(row, "selected_service")
        ),
        **resources,
        "foundation_quality": player_integer(row, "foundation_quality"),
        "arena_rating": player_integer(row, "arena_rating", 1000),
        "arena_wins": player_integer(row, "arena_wins"),
        "arena_losses": player_integer(row, "arena_losses"),
        "arena_draws": player_integer(row, "arena_draws"),
        "max_hp": player_integer(row, "max_hp"),
        "max_mp": player_integer(row, "max_mp"),
        "carry_capacity": player_integer(row, "carry_capacity"),
        "initiative": player_integer(row, "initiative"),
        "cross_realm_penalty_bp": player_integer(row, "cross_realm_penalty_bp"),
        "realm_resistance_bp": player_integer(row, "realm_resistance_bp"),
        "exploration_efficiency_bp": player_integer(row, "exploration_efficiency_bp"),
        "heart_demon_bonus_bp": player_integer(row, "heart_demon_bonus_bp"),
        "breakthrough_pity_bp": player_integer(row, "breakthrough_pity_bp"),
        "domain_key": player_field(row, "domain_key"),
        "domain_level": player_integer(row, "domain_level"),
        "domain_charge": player_integer(row, "domain_charge"),
        "domain_charge_max": player_integer(row, "domain_charge_max"),
        "domain_power": player_integer(row, "domain_power"),
        "void_power": player_integer(row, "void_power"),
        "void_power_max": player_integer(row, "void_power_max"),
        "space_resistance_bp": player_integer(row, "space_resistance_bp"),
        "void_route_count": player_integer(row, "void_route_count"),
        "void_anchor_capacity": player_integer(row, "void_anchor_capacity"),
        "dao_fruit_progress": player_integer(row, "dao_fruit_progress"),
        "ascension_merit": player_integer(row, "ascension_merit"),
        "tribulation_debt": player_integer(row, "tribulation_debt"),
        "dao_fruit_key": player_field(row, "dao_fruit_key"),
        "endgame_status": str(player_field(row, "endgame_status", "none") or "none"),
        "ending_key": player_field(row, "ending_key"),
    }


def player_combat_values(row: Mapping[str, Any] | Any) -> dict[str, Any]:
    """Return the shared immutable player inputs used at battle start.

    Exploration, ordinary PvE and party PvE all use this same projection;
    companion and equipment modifiers are added by their own snapshot readers.
    """

    values = player_values(row)
    return {
        "player_id": values["player_id"],
        "dao_name": values["dao_name"],
        "path_key": values["path_key"],
        "location_key": values["location_key"],
        "realm_key": values["realm_key"],
        "realm_layer": values["realm_layer"],
        "qualification": dict(values["qualification"]),
        "inventory": dict(values["inventory"]),
        "max_hp": values["max_hp"],
        "initiative": values["initiative"],
        "pollution": values["pollution"],
        "bloodline_stability": values["bloodline_stability"],
        "cross_realm_penalty_bp": values["cross_realm_penalty_bp"],
        "faction_reputation": dict(values["faction_reputation"]),
        "soul_power": values["soul_power"],
        "domain_key": values["domain_key"],
        "domain_charge": values["domain_charge"],
        "domain_charge_max": values["domain_charge_max"],
        "domain_power": values["domain_power"],
    }


__all__ = [
    "PLAYER_RESOURCE_FIELDS",
    "player_field",
    "player_integer",
    "player_numeric_values",
    "player_object",
    "player_inventory",
    "player_resource_values",
    "player_qualification",
    "player_intro_flags",
    "player_reputation",
    "player_values",
    "player_combat_values",
]
