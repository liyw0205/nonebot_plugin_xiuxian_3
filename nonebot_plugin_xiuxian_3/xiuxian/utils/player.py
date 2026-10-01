"""Shared normalization for player values read from SQLite rows."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from .assets import inventory_value, player_database_id
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

# Every integer stored on ``players`` that can be exposed to an application
# projection.  Keeping this list beside the projection reader prevents a new
# view from quietly gaining a different conversion/default rule.
PLAYER_NUMERIC_FIELDS = tuple(
    dict.fromkeys(
        (
            *PLAYER_RESOURCE_FIELDS,
            "foundation_quality",
            "arena_rating",
            "arena_wins",
            "arena_losses",
            "arena_draws",
            "max_hp",
            "max_mp",
            "carry_capacity",
            "initiative",
            "cross_realm_penalty_bp",
            "realm_resistance_bp",
            "exploration_efficiency_bp",
            "heart_demon_bonus_bp",
            "breakthrough_pity_bp",
            "domain_level",
            "domain_charge",
            "domain_charge_max",
            "domain_power",
            "void_power",
            "void_power_max",
            "space_resistance_bp",
            "void_route_count",
            "void_anchor_capacity",
            "dao_fruit_progress",
            "ascension_merit",
            "tribulation_debt",
        )
    )
)

PLAYER_NUMERIC_DEFAULTS = {"arena_rating": 1000}

PLAYER_COMBAT_FIELDS = (
    "max_hp",
    "initiative",
    "pollution",
    "bloodline_stability",
    "cross_realm_penalty_bp",
    "soul_power",
    "domain_charge",
    "domain_charge_max",
    "domain_power",
)

PLAYER_STATUS_FIELDS = (
    "player_id",
    "dao_name",
    "stage",
    "status",
    "location_key",
    "realm_key",
    "realm_layer",
    "spirit_stones",
    "stamina",
    "stamina_max",
    "energy",
    "energy_max",
    "cultivation",
    "total_cultivation",
    "inventory",
    "world_merit",
    "void_merit",
    "alliance_points",
    "pollution",
    "bloodline_stability",
    "soul_power",
    "soul_power_max",
    "domain_charge",
    "domain_charge_max",
    "void_power",
    "void_power_max",
)

PLAYER_PROFILE_FIELDS = (
    "player_id",
    "dao_name",
    "platform",
    "stage",
    "status",
    "location_key",
    "realm_key",
    "realm_layer",
    "cultivation",
    "total_cultivation",
    "foundation_quality",
    "world_merit",
    "void_merit",
    "alliance_points",
    "spirit_stones",
    "stamina",
    "stamina_max",
    "energy",
    "energy_max",
    "inventory",
    "intro_flags",
    "selected_service",
    "qualification",
    "path_key",
    "subprofession_key",
    "soul_power",
    "soul_power_max",
    "domain_charge",
    "domain_charge_max",
    "pollution",
    "bloodline_stability",
    "cross_realm_penalty_bp",
    "soul_fatigue_until",
    "domain_key",
    "domain_power",
    "realm_resistance_bp",
    "domain_crack_until",
    "initiative",
    "domain_level",
    "faction_reputation",
    "void_power",
    "void_power_max",
    "space_resistance_bp",
    "void_instability_until",
    "void_route_count",
    "void_anchor_capacity",
    "dao_fruit_progress",
    "ascension_merit",
    "tribulation_debt",
    "dao_fruit_key",
    "endgame_status",
    "ending_key",
)

PLAYER_COMBAT_PROJECTION_FIELDS = (
    "player_id",
    "platform",
    "platform_user_id",
    "scene_id",
    "nickname",
    "stage",
    "status",
    "dao_name",
    "path_key",
    "location_key",
    "realm_key",
    "realm_layer",
    "qualification",
    "inventory",
    "stamina",
    "stamina_max",
    "energy",
    "energy_max",
    "max_hp",
    "initiative",
    "pollution",
    "bloodline_stability",
    "cross_realm_penalty_bp",
    "faction_reputation",
    "soul_power",
    "domain_key",
    "domain_charge",
    "domain_charge_max",
    "domain_power",
)

PlayerViewKind = Literal["profile", "status", "combat"]
PLAYER_VIEW_FIELDS: dict[PlayerViewKind, tuple[str, ...]] = {
    "profile": PLAYER_PROFILE_FIELDS,
    "status": PLAYER_STATUS_FIELDS,
    "combat": PLAYER_COMBAT_PROJECTION_FIELDS,
}

PLAYER_RESOURCE_BARS = (
    ("stamina", "stamina_max"),
    ("energy", "energy_max"),
    ("soul_power", "soul_power_max"),
    ("domain_charge", "domain_charge_max"),
    ("void_power", "void_power_max"),
)


@dataclass(frozen=True, slots=True)
class PlayerStateChange:
    """Validated result of one player asset and numeric state transaction."""

    values: dict[str, Any]
    assets: Any | None = None


def player_field(row: Mapping[str, Any] | Any, key: str, default: Any = None) -> Any:
    """Read a player column from either a mapping or a SQLite row."""

    if isinstance(row, Mapping):
        return row.get(key, default)
    try:
        return row[key]
    except (IndexError, KeyError, TypeError):
        return getattr(row, key, default)


def player_integer(row: Mapping[str, Any] | Any, key: str, default: int = 0) -> int:
    """Read a player numeric column with the shared neutral default."""

    raw = player_field(row, key, default)
    if raw is None:
        return default
    if isinstance(raw, bool):
        raise ValueError(f"player field {key!r} must be an integer")
    return int(raw)


def player_values_missing(
    row: Mapping[str, Any] | Any,
    requirements: Mapping[str, Any],
) -> dict[str, int]:
    """Return the positive shortfall for required player numeric values."""

    missing: dict[str, int] = {}
    for raw_key, raw_required in requirements.items():
        key = str(raw_key)
        if isinstance(raw_required, bool):
            raise ValueError(f"player requirement for {key!r} must be an integer")
        try:
            required = int(raw_required)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"player requirement for {key!r} must be an integer") from exc
        if required < 0:
            raise ValueError(f"player requirement for {key!r} must be non-negative")
        shortfall = required - player_integer(row, key)
        if shortfall > 0:
            missing[key] = shortfall
    return missing


def player_has_values(
    row: Mapping[str, Any] | Any,
    requirements: Mapping[str, Any],
) -> bool:
    """Return whether all required player numeric values are available."""

    return not player_values_missing(row, requirements)


def player_numeric_delta(
    row: Mapping[str, Any] | Any,
    delta: Mapping[str, Any],
    *,
    minimum: int = 0,
    maximums: Mapping[str, Any] | None = None,
) -> dict[str, int]:
    """Calculate validated numeric player values after one signed change.

    Resource updates use this pure helper before persistence.  It keeps the
    non-negative and capped-value rules identical for profile, status and
    battle-related transactions without embedding SQL in the projection layer.
    """

    caps = maximums or {}
    result: dict[str, int] = {}
    for raw_key, raw_delta in delta.items():
        key = str(raw_key)
        if isinstance(raw_delta, bool):
            raise ValueError(f"player delta for {key!r} must be an integer")
        try:
            change = int(raw_delta)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"player delta for {key!r} must be an integer") from exc
        value = player_integer(row, key) + change
        floor = int(minimum)
        if value < floor:
            raise ValueError(f"player value for {key!r} cannot be below {floor}")
        # A cap limits recovery only. Costs and penalties must still apply
        # when an older row has a stale or missing maximum value.
        if key in caps and change > 0:
            cap = player_integer(caps, key)
            if value > cap:
                value = cap
        result[key] = value
    return result


def change_player_values(
    connection: Any,
    row: Mapping[str, Any] | Any,
    delta: Mapping[str, Any],
    updated_at: str,
    *,
    maximums: Mapping[str, Any] | None = None,
) -> dict[str, int]:
    """Persist one validated numeric player delta in the current transaction."""

    return change_player_state(
        connection,
        row,
        updated_at=updated_at,
        value_delta=delta,
        maximums=maximums,
    ).values


def change_player_state(
    connection: Any,
    row: Mapping[str, Any] | Any,
    *,
    updated_at: str,
    asset_values: Mapping[str, Any] | None = None,
    asset_mode: str = "delta",
    value_delta: Mapping[str, Any] | None = None,
    maximums: Mapping[str, Any] | None = None,
    preserve_zero: bool = False,
    player_values: Mapping[str, Any] | None = None,
) -> PlayerStateChange:
    """Commit assets and numeric player values through one transaction kernel.

    ``asset_values`` uses the same ``grant``/``spend``/``delta`` modes as
    :func:`apply_player_assets`.  ``value_delta`` is validated with the shared
    numeric projection and can be capped by ``maximums``.  Callers that only
    change numeric values may omit ``asset_values``; callers changing assets
    and values together get one SQL update and one validation boundary.
    """

    numeric_values = player_numeric_delta(row, value_delta or {}, maximums=maximums)
    if player_values:
        if set(player_values) & set(numeric_values):
            raise ValueError("player value is supplied more than once")
        numeric_values.update(dict(player_values))

    if asset_values is None:
        if not numeric_values:
            raise ValueError("player state change cannot be empty")
        from .assets import write_player_values

        write_player_values(connection, player_database_id(row), numeric_values, updated_at)
        return PlayerStateChange(values=numeric_values)

    from .assets import apply_player_assets

    assets = apply_player_assets(
        connection,
        row,
        asset_values,
        updated_at,
        mode=asset_mode,
        preserve_zero=preserve_zero,
        player_values=numeric_values or None,
    )
    return PlayerStateChange(values=numeric_values, assets=assets)


def grant_player_state(
    connection: Any,
    row: Mapping[str, Any] | Any,
    rewards: Mapping[str, Any] | None,
    updated_at: str,
    *,
    value_delta: Mapping[str, Any] | None = None,
    maximums: Mapping[str, Any] | None = None,
    preserve_zero: bool = False,
    player_values: Mapping[str, Any] | None = None,
) -> PlayerStateChange:
    """Grant assets and numeric rewards through the shared state boundary."""

    return change_player_state(
        connection,
        row,
        updated_at=updated_at,
        asset_values=rewards,
        asset_mode="grant",
        value_delta=value_delta,
        maximums=maximums,
        preserve_zero=preserve_zero,
        player_values=player_values,
    )


def spend_player_state(
    connection: Any,
    row: Mapping[str, Any] | Any,
    costs: Mapping[str, Any] | None,
    updated_at: str,
    *,
    value_delta: Mapping[str, Any] | None = None,
    maximums: Mapping[str, Any] | None = None,
    preserve_zero: bool = False,
    player_values: Mapping[str, Any] | None = None,
) -> PlayerStateChange:
    """Spend assets and numeric resources through the shared state boundary."""

    return change_player_state(
        connection,
        row,
        updated_at=updated_at,
        asset_values=costs,
        asset_mode="spend",
        value_delta=value_delta,
        maximums=maximums,
        preserve_zero=preserve_zero,
        player_values=player_values,
    )


def player_numeric_values(
    row: Mapping[str, Any] | Any,
    fields: tuple[str, ...] = PLAYER_RESOURCE_FIELDS,
    *,
    defaults: Mapping[str, Any] | None = None,
) -> dict[str, int]:
    """Read a consistent set of non-negative player numeric projections."""

    fallback = defaults or {}
    return {
        field: player_integer(row, field, int(fallback[field]) if field in fallback else 0)
        for field in fields
    }


def player_projection(
    row: Mapping[str, Any] | Any,
    fields: tuple[str, ...],
) -> dict[str, Any]:
    """Return one detached projection from the canonical player value reader."""

    values = player_values(row)
    projection: dict[str, Any] = {}
    for field in fields:
        value = values[field]
        if isinstance(value, dict):
            projection[field] = dict(value)
        elif isinstance(value, list):
            projection[field] = list(value)
        elif isinstance(value, tuple):
            projection[field] = tuple(value)
        else:
            projection[field] = value
    return projection


def player_view_values(
    row: Mapping[str, Any] | Any,
    view: PlayerViewKind,
) -> dict[str, Any]:
    """Read one detached player view from the canonical normalized projection."""

    try:
        fields = PLAYER_VIEW_FIELDS[view]
    except KeyError as exc:
        raise ValueError(f"unsupported player view: {view!r}") from exc
    projection = player_projection(row, fields)
    if view == "profile":
        for field in ("soul_fatigue_until", "domain_crack_until", "void_instability_until"):
            value = projection[field]
            if value is not None and hasattr(value, "isoformat"):
                projection[field] = value.isoformat()
    return projection


def player_state_values(
    row: Mapping[str, Any] | Any,
    view: PlayerViewKind | None = None,
) -> dict[str, Any]:
    """Read the canonical player state, optionally narrowed to one view.

    A full read and the profile/status/combat projections all pass through the
    same normalizer.  Callers choose a view for transport size, never for a
    different conversion or fallback rule.
    """

    if view is None:
        return player_values(row)
    return player_view_values(row, view)


def player_resource_bars(
    row: Mapping[str, Any] | Any,
    resources: tuple[tuple[str, str], ...] = PLAYER_RESOURCE_BARS,
) -> dict[str, dict[str, int]]:
    """Return current/max resource pairs from the shared numeric reader."""

    values = player_values(row)
    return {
        current: {
            "current": int(values[current]),
            "maximum": int(values[maximum]),
        }
        for current, maximum in resources
    }


def player_status_values(row: Mapping[str, Any] | Any) -> dict[str, Any]:
    """Return the shared read-only status projection used by status commands."""

    return player_state_values(row, "status")


def player_profile_values(row: Mapping[str, Any] | Any) -> dict[str, Any]:
    """Return the shared public profile projection used by profile commands."""

    return player_state_values(row, "profile")


def player_realm_values(row: Mapping[str, Any] | Any) -> dict[str, Any]:
    """Return the shared realm/location portion used by views and battles."""

    return {
        "stage": str(player_field(row, "stage", "new_user") or "new_user"),
        "status": str(player_field(row, "status", "active") or "active"),
        "location_key": str(player_field(row, "location_key", "xuantian.new_town") or "xuantian.new_town"),
        "realm_key": str(player_field(row, "realm_key", "mortal") or "mortal"),
        "realm_layer": player_integer(row, "realm_layer"),
        "path_key": player_field(row, "path_key"),
        "subprofession_key": player_field(row, "subprofession_key"),
    }


def player_object(
    row: Mapping[str, Any] | Any,
    key: str,
    default: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Read one JSON object column from a player row without sharing defaults."""

    fallback = dict(default or {})
    raw = player_field(row, key, None)
    if raw is None:
        aliases = {
            "qualification_json": "qualification",
            "inventory_json": "inventory",
            "intro_json": "intro",
            "faction_reputation_json": "faction_reputation",
        }
        raw = player_field(row, aliases.get(key, ""), fallback)
    value = json_object(raw, fallback)
    return {str(name): item for name, item in value.items()}


def player_inventory(
    row: Mapping[str, Any] | Any,
    *,
    keep_zero: bool = False,
) -> dict[str, int]:
    """Read the normalized item inventory shared by displays and battles."""

    raw = player_field(row, "inventory_json", None)
    if raw is None:
        raw = player_field(row, "inventory", {})
    return inventory_value(raw, keep_zero=keep_zero)


def player_qualification(row: Mapping[str, Any] | Any) -> dict[str, int]:
    """Read normalized qualification values from a player row."""

    values: dict[str, int] = {}
    raw = player_field(row, "qualification", None)
    source = raw if isinstance(raw, Mapping) else player_object(row, "qualification_json")
    for key, value in source.items():
        # The stored object may also carry non-numeric tactical selections;
        # only numeric entries belong in the shared qualification projection.
        try:
            values[str(key)] = player_integer({"value": value}, "value")
        except (TypeError, ValueError):
            continue
    return values


def player_intro_flags(row: Mapping[str, Any] | Any) -> tuple[str, ...]:
    """Read the immutable-style onboarding flags used by access checks."""

    direct = player_field(row, "intro_flags", None)
    flags = direct if direct is not None else player_object(row, "intro_json").get("flags", [])
    if not isinstance(flags, (list, tuple)):
        return ()
    return tuple(str(flag) for flag in flags)


def player_reputation(row: Mapping[str, Any] | Any) -> dict[str, int]:
    """Read normalized local faction reputation values."""

    direct = player_field(row, "faction_reputation", None)
    values = direct if isinstance(direct, Mapping) else player_object(row, "faction_reputation_json")
    return {str(key): player_integer({"value": value}, "value") for key, value in values.items()}


def player_values(row: Mapping[str, Any] | Any) -> dict[str, Any]:
    """Return normalized identity, resources and combat inputs from a player row.

    The query may contain only a subset of player columns (for example a party
    member join), so missing values use the same neutral defaults everywhere.
    """

    qualification = player_qualification(row)
    inventory = player_inventory(row)
    intro = player_object(row, "intro_json")
    numeric = player_numeric_values(
        row,
        PLAYER_NUMERIC_FIELDS,
        defaults=PLAYER_NUMERIC_DEFAULTS,
    )
    realm = player_realm_values(row)
    return {
        "player_id": str(player_field(row, "player_id", player_field(row, "id", ""))),
        "platform": str(player_field(row, "platform", "") or ""),
        "platform_user_id": str(player_field(row, "platform_user_id", "") or ""),
        "scene_id": str(player_field(row, "scene_id", "") or ""),
        "nickname": str(player_field(row, "nickname", "") or ""),
        "stage": realm["stage"],
        "status": realm["status"],
        "dao_name": str(player_field(row, "dao_name", "") or ""),
        "path_key": realm["path_key"],
        "subprofession_key": realm["subprofession_key"],
        "location_key": realm["location_key"],
        "realm_key": realm["realm_key"],
        "realm_layer": realm["realm_layer"],
        "qualification": qualification,
        "inventory": inventory,
        "intro_flags": player_intro_flags(row),
        "faction_reputation": player_reputation(row),
        "selected_service": (
            str(intro["selected_service"])
            if intro.get("selected_service") is not None
            else player_field(row, "selected_service")
        ),
        **numeric,
        "soul_fatigue_until": player_field(row, "soul_fatigue_until"),
        "domain_key": player_field(row, "domain_key"),
        "domain_crack_until": player_field(row, "domain_crack_until"),
        "void_instability_until": player_field(row, "void_instability_until"),
        "dao_fruit_key": player_field(row, "dao_fruit_key"),
        "endgame_status": str(player_field(row, "endgame_status", "none") or "none"),
        "ending_key": player_field(row, "ending_key"),
    }


def player_combat_values(row: Mapping[str, Any] | Any) -> dict[str, Any]:
    """Return the shared immutable player inputs used at battle start.

    Exploration, ordinary PvE and party PvE all use this same projection;
    companion and equipment modifiers are added by their own snapshot readers.
    """

    return player_state_values(row, "combat")


__all__ = [
    "PlayerStateChange",
    "PLAYER_COMBAT_FIELDS",
    "PLAYER_COMBAT_PROJECTION_FIELDS",
    "PLAYER_NUMERIC_DEFAULTS",
    "PLAYER_NUMERIC_FIELDS",
    "PLAYER_PROFILE_FIELDS",
    "PLAYER_RESOURCE_FIELDS",
    "PLAYER_STATUS_FIELDS",
    "PLAYER_RESOURCE_BARS",
    "PLAYER_VIEW_FIELDS",
    "PlayerViewKind",
    "player_field",
    "player_database_id",
    "player_integer",
    "player_numeric_delta",
    "player_values_missing",
    "player_has_values",
    "change_player_values",
    "change_player_state",
    "grant_player_state",
    "spend_player_state",
    "player_numeric_values",
    "player_projection",
    "player_view_values",
    "player_state_values",
    "player_resource_bars",
    "player_profile_values",
    "player_status_values",
    "player_object",
    "player_inventory",
    "player_realm_values",
    "player_qualification",
    "player_intro_flags",
    "player_reputation",
    "player_values",
    "player_combat_values",
]
