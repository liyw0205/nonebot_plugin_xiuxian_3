"""Pure helpers for player-owned inventory and currency values."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
import re
from typing import Any

from .json import json_object


class AssetDeltaError(ValueError):
    """Raised when an asset balance or delta is invalid."""


@dataclass(frozen=True, slots=True)
class AssetState:
    """A detached player balance containing currency and stackable items."""

    currency: int
    inventory: dict[str, int]


_PLAYER_COLUMN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def player_asset_state(row: Any, *, preserve_zero: bool = False) -> AssetState:
    """Read a detached asset state from a player row or mapping."""

    try:
        currency = row["spirit_stones"]
        raw_inventory = row["inventory_json"]
    except (IndexError, KeyError, TypeError) as exc:
        raise AssetDeltaError("player row does not contain asset columns") from exc
    return AssetState(
        currency=currency_with_delta(currency, 0),
        inventory=inventory_value(raw_inventory, keep_zero=preserve_zero),
    )


def write_player_values(
    connection: Any,
    player_id: int,
    values: Mapping[str, Any],
    updated_at: str,
) -> None:
    """Write validated player columns in the current transaction.

    Callers provide already calculated values.  The helper only handles SQL
    identifier validation and deterministic parameter binding so asset and
    non-asset fields can be committed together.
    """

    if not values:
        raise ValueError("player update cannot be empty")
    assignments: dict[str, Any] = {}
    for raw_key, value in values.items():
        key = str(raw_key)
        if key == "id" or not _PLAYER_COLUMN.fullmatch(key):
            raise ValueError(f"invalid player column: {key!r}")
        assignments[key] = value
    assignments["updated_at"] = updated_at
    columns = sorted(assignments)
    connection.execute(
        f"UPDATE players SET {', '.join(f'{column} = ?' for column in columns)} WHERE id = ?",
        tuple(assignments[column] for column in columns) + (player_id,),
    )


def write_player_assets(
    connection: Any,
    player_id: int,
    assets: AssetState,
    updated_at: str,
    *,
    preserve_zero: bool = False,
    player_values: Mapping[str, Any] | None = None,
) -> AssetState:
    """Persist one player's currency and inventory in the current transaction."""

    values = {
        "spirit_stones": assets.currency,
        "inventory_json": inventory_json(assets.inventory, keep_zero=preserve_zero),
    }
    if player_values:
        if set(player_values) & {"id", "spirit_stones", "inventory_json", "updated_at"}:
            raise ValueError("asset columns must be supplied through AssetState")
        values.update(player_values)
    write_player_values(connection, player_id, values, updated_at)
    return assets


def _player_asset_state(row: Any, *, preserve_zero: bool = False) -> AssetState:
    return player_asset_state(row, preserve_zero=preserve_zero)


def grant_player_assets(
    connection: Any,
    row: Any,
    rewards: Mapping[str, Any],
    updated_at: str,
    *,
    preserve_zero: bool = False,
    player_values: Mapping[str, Any] | None = None,
) -> AssetState:
    """Grant currency and stackable items, then persist them atomically."""
    return apply_player_assets(
        connection,
        row,
        rewards,
        updated_at,
        mode="grant",
        preserve_zero=preserve_zero,
        player_values=player_values,
    )


def spend_player_assets(
    connection: Any,
    row: Any,
    costs: Mapping[str, Any],
    updated_at: str,
    *,
    preserve_zero: bool = False,
    player_values: Mapping[str, Any] | None = None,
) -> AssetState:
    """Spend currency and stackable items, then persist them atomically."""
    return apply_player_assets(
        connection,
        row,
        costs,
        updated_at,
        mode="spend",
        preserve_zero=preserve_zero,
        player_values=player_values,
    )


def change_player_assets(
    connection: Any,
    row: Any,
    delta: Mapping[str, Any],
    updated_at: str,
    *,
    preserve_zero: bool = False,
    player_values: Mapping[str, Any] | None = None,
) -> AssetState:
    """Apply one signed asset delta and persist it in the current transaction."""
    return apply_player_assets(
        connection,
        row,
        delta,
        updated_at,
        mode="delta",
        preserve_zero=preserve_zero,
        player_values=player_values,
    )


def grant_player_items(
    connection: Any,
    row: Any,
    items: Mapping[str, Any],
    updated_at: str,
    *,
    preserve_zero: bool = False,
    player_values: Mapping[str, Any] | None = None,
) -> AssetState:
    """Grant only stackable items while preserving the player's currency."""

    return grant_player_assets(
        connection,
        row,
        items,
        updated_at,
        preserve_zero=preserve_zero,
        player_values=player_values,
    )


def spend_player_items(
    connection: Any,
    row: Any,
    items: Mapping[str, Any],
    updated_at: str,
    *,
    preserve_zero: bool = False,
    player_values: Mapping[str, Any] | None = None,
) -> AssetState:
    """Spend only stackable items while preserving the player's currency."""

    return spend_player_assets(
        connection,
        row,
        items,
        updated_at,
        preserve_zero=preserve_zero,
        player_values=player_values,
    )


def add_player_currency(
    connection: Any,
    row: Any,
    amount: Any,
    updated_at: str,
    *,
    player_values: Mapping[str, Any] | None = None,
) -> AssetState:
    """Add spirit stones without duplicating inventory persistence."""

    return grant_player_assets(
        connection,
        row,
        {"spirit_stones": amount},
        updated_at,
        player_values=player_values,
    )


def spend_player_currency(
    connection: Any,
    row: Any,
    amount: Any,
    updated_at: str,
    *,
    player_values: Mapping[str, Any] | None = None,
) -> AssetState:
    """Spend spirit stones without duplicating inventory persistence."""

    return spend_player_assets(
        connection,
        row,
        {"spirit_stones": amount},
        updated_at,
        player_values=player_values,
    )


def apply_player_assets(
    connection: Any,
    row: Any,
    values: Mapping[str, Any],
    updated_at: str,
    *,
    mode: str = "delta",
    preserve_zero: bool = False,
    player_values: Mapping[str, Any] | None = None,
) -> AssetState:
    """Apply one asset operation and persist it in the current transaction.

    ``mode`` selects the domain rule for the same transaction boundary:
    ``grant`` accepts only positive rewards, ``spend`` checks every cost before
    writing, and ``delta`` applies signed changes.  Keeping this dispatch in one
    place prevents callers from drifting in their inventory/currency handling.
    """

    current = _player_asset_state(row, preserve_zero=preserve_zero)
    if mode == "grant":
        next_assets = assets_grant(current.currency, current.inventory, values)
    elif mode == "spend":
        next_assets = assets_spend(
            current.currency,
            current.inventory,
            values,
            preserve_zero=preserve_zero,
        )
    elif mode == "delta":
        next_assets = assets_with_delta(current.currency, current.inventory, values)
    else:
        raise ValueError(f"unsupported asset operation: {mode!r}")
    return write_player_assets(
        connection,
        int(row["id"]),
        next_assets,
        updated_at,
        preserve_zero=preserve_zero,
        player_values=player_values,
    )


def _asset_delta_parts(
    delta: Mapping[str, Any], *, currency_key: str
) -> tuple[Any, dict[str, Any]]:
    currency_delta: Any = 0
    currency_seen = False
    item_delta: dict[str, Any] = {}
    for raw_key, raw_value in delta.items():
        key = str(raw_key)
        if key == currency_key or (
            currency_key == "spirit_stones" and key == "currency.spirit_stone"
        ):
            if currency_seen:
                raise AssetDeltaError("currency delta must use one key")
            currency_delta = raw_value
            currency_seen = True
        else:
            item_delta[key] = raw_value
    return currency_delta, item_delta


def assets_with_delta(
    currency: Any,
    inventory: Mapping[str, Any],
    delta: Mapping[str, Any],
    *,
    currency_key: str = "spirit_stones",
) -> AssetState:
    """Apply one signed change map to currency and inventory atomically.

    The function is pure: both returned values are detached from the inputs,
    and validation happens before a caller persists either value.
    """

    currency_delta, item_delta = _asset_delta_parts(delta, currency_key=currency_key)
    return AssetState(
        currency=currency_with_delta(currency, currency_delta),
        inventory=inventory_with_delta(inventory, item_delta),
    )


def assets_grant(
    currency: Any,
    inventory: Mapping[str, Any],
    rewards: Mapping[str, Any],
    *,
    currency_key: str = "spirit_stones",
) -> AssetState:
    """Grant non-negative currency and item quantities in one operation."""

    currency_amount, item_rewards = _asset_delta_parts(rewards, currency_key=currency_key)
    return AssetState(
        currency=currency_grant(currency, currency_amount),
        inventory=inventory_grant(inventory, item_rewards),
    )


def assets_spend(
    currency: Any,
    inventory: Mapping[str, Any],
    costs: Mapping[str, Any],
    *,
    currency_key: str = "spirit_stones",
    preserve_zero: bool = False,
) -> AssetState:
    """Spend non-negative currency and item quantities in one operation."""

    currency_amount, item_costs = _asset_delta_parts(costs, currency_key=currency_key)
    return AssetState(
        currency=currency_spend(currency, currency_amount),
        inventory=inventory_spend(inventory, item_costs, preserve_zero=preserve_zero),
    )


def inventory_value(
    raw: Any,
    default: Mapping[str, Any] | None = None,
    *,
    keep_zero: bool = False,
) -> dict[str, int]:
    """Decode and validate an inventory stored as JSON or a mapping."""

    decoded = json_object(raw, default)
    result: dict[str, int] = {}
    for raw_key, raw_quantity in decoded.items():
        key = str(raw_key)
        quantity = inventory_amount({key: raw_quantity}, key)
        if quantity or keep_zero:
            result[key] = quantity
    return result


def inventory_json(inventory: Mapping[str, Any], *, keep_zero: bool = False) -> str:
    """Serialize a normalized inventory for a player row."""

    normalized: dict[str, int] = {}
    for raw_key, raw_quantity in inventory.items():
        key = str(raw_key)
        quantity = inventory_amount({key: raw_quantity}, key)
        if quantity or keep_zero:
            normalized[key] = quantity
    return json.dumps(normalized, ensure_ascii=False, sort_keys=True)


def inventory_amount(inventory: Mapping[str, Any], key: str) -> int:
    """Return a normalized inventory quantity for one stable item key."""

    value = inventory.get(key, 0)
    if isinstance(value, bool):
        raise AssetDeltaError(f"inventory quantity for {key!r} must be an integer")
    try:
        quantity = int(value)
    except (TypeError, ValueError) as exc:
        raise AssetDeltaError(f"inventory quantity for {key!r} must be an integer") from exc
    if quantity < 0:
        raise AssetDeltaError(f"inventory quantity for {key!r} cannot be negative")
    return quantity


def inventory_missing(
    inventory: Mapping[str, Any], requirements: Mapping[str, Any]
) -> dict[str, int]:
    """Return the positive shortfall for each required item."""

    missing: dict[str, int] = {}
    for raw_key, raw_required in requirements.items():
        key = str(raw_key)
        if isinstance(raw_required, bool):
            raise AssetDeltaError(f"inventory requirement for {key!r} must be an integer")
        try:
            required = int(raw_required)
        except (TypeError, ValueError) as exc:
            raise AssetDeltaError(f"inventory requirement for {key!r} must be an integer") from exc
        if required < 0:
            raise AssetDeltaError(f"inventory requirement for {key!r} cannot be negative")
        shortfall = required - inventory_amount(inventory, key)
        if shortfall > 0:
            missing[key] = shortfall
    return missing


def inventory_with_delta(
    inventory: Mapping[str, Any], delta: Mapping[str, Any], *, preserve_zero: bool = False
) -> dict[str, int]:
    """Return a detached inventory after applying signed item deltas."""

    result: dict[str, int] = {}
    for raw_key in inventory:
        key = str(raw_key)
        quantity = inventory_amount(inventory, key)
        if quantity > 0:
            result[key] = quantity
    for raw_key, raw_delta in delta.items():
        key = str(raw_key)
        if isinstance(raw_delta, bool):
            raise AssetDeltaError(f"inventory delta for {key!r} must be an integer")
        try:
            change = int(raw_delta)
        except (TypeError, ValueError) as exc:
            raise AssetDeltaError(f"inventory delta for {key!r} must be an integer") from exc
        next_quantity = result.get(key, 0) + change
        if next_quantity < 0:
            raise AssetDeltaError(f"inventory quantity for {key!r} cannot be negative")
        if next_quantity:
            result[key] = next_quantity
        elif preserve_zero:
            result[key] = 0
        else:
            result.pop(key, None)
    return result


def inventory_grant(inventory: Mapping[str, Any], rewards: Mapping[str, Any]) -> dict[str, int]:
    """Return an inventory after granting positive item quantities."""

    for raw_key, raw_quantity in rewards.items():
        key = str(raw_key)
        if isinstance(raw_quantity, bool):
            raise AssetDeltaError(f"inventory grant for {key!r} must be non-negative")
        try:
            quantity = int(raw_quantity)
        except (TypeError, ValueError) as exc:
            raise AssetDeltaError(f"inventory grant for {key!r} must be an integer") from exc
        if quantity < 0:
            raise AssetDeltaError(f"inventory grant for {key!r} must be non-negative")
    return inventory_with_delta(inventory, rewards)


def inventory_spend(
    inventory: Mapping[str, Any],
    requirements: Mapping[str, Any],
    *,
    preserve_zero: bool = False,
) -> dict[str, int]:
    """Return an inventory after spending required item quantities."""

    missing = inventory_missing(inventory, requirements)
    if missing:
        raise AssetDeltaError(f"inventory is missing items: {missing}")
    return inventory_with_delta(
        inventory,
        {str(key): -int(quantity) for key, quantity in requirements.items()},
        preserve_zero=preserve_zero,
    )


def currency_with_delta(balance: Any, delta: Any) -> int:
    """Return a non-negative currency balance after a signed delta."""

    if isinstance(balance, bool) or isinstance(delta, bool):
        raise AssetDeltaError("currency balance and delta must be integers")
    try:
        current = int(balance)
        change = int(delta)
    except (TypeError, ValueError) as exc:
        raise AssetDeltaError("currency balance and delta must be integers") from exc
    next_balance = current + change
    if next_balance < 0:
        raise AssetDeltaError("currency balance cannot be negative")
    return next_balance


def currency_grant(balance: Any, amount: Any) -> int:
    """Return a balance after granting currency."""

    if isinstance(amount, bool):
        raise AssetDeltaError("currency amount must be an integer")
    try:
        amount = int(amount)
    except (TypeError, ValueError) as exc:
        raise AssetDeltaError("currency amount must be an integer") from exc
    if amount < 0:
        raise AssetDeltaError("currency amount must be non-negative")
    return currency_with_delta(balance, amount)


def currency_spend(balance: Any, amount: Any) -> int:
    """Return a balance after spending currency."""

    if isinstance(amount, bool):
        raise AssetDeltaError("currency amount must be an integer")
    try:
        amount = int(amount)
    except (TypeError, ValueError) as exc:
        raise AssetDeltaError("currency amount must be an integer") from exc
    if amount < 0:
        raise AssetDeltaError("currency amount must be non-negative")
    return currency_with_delta(balance, -amount)


__all__ = [
    "AssetState",
    "AssetDeltaError",
    "apply_player_assets",
    "assets_grant",
    "assets_spend",
    "assets_with_delta",
    "change_player_assets",
    "add_player_currency",
    "currency_grant",
    "currency_spend",
    "currency_with_delta",
    "grant_player_assets",
    "grant_player_items",
    "inventory_amount",
    "inventory_grant",
    "inventory_json",
    "inventory_missing",
    "inventory_spend",
    "inventory_value",
    "inventory_with_delta",
    "player_asset_state",
    "spend_player_assets",
    "spend_player_currency",
    "spend_player_items",
    "write_player_values",
    "write_player_assets",
]
