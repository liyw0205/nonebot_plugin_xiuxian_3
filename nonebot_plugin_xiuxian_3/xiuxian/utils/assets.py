"""Pure helpers for player-owned inventory and currency values."""

from __future__ import annotations

from collections.abc import Mapping
import json
from typing import Any

from .json import json_object


class AssetDeltaError(ValueError):
    """Raised when an asset balance or delta is invalid."""


def inventory_value(raw: Any, default: Mapping[str, Any] | None = None) -> dict[str, int]:
    """Decode and validate an inventory stored as JSON or a mapping."""

    decoded = json_object(raw, default)
    result: dict[str, int] = {}
    for raw_key, raw_quantity in decoded.items():
        key = str(raw_key)
        quantity = inventory_amount({key: raw_quantity}, key)
        if quantity:
            result[key] = quantity
    return result


def inventory_json(inventory: Mapping[str, Any]) -> str:
    """Serialize a normalized inventory for a player row."""

    return json.dumps(inventory_value(inventory), ensure_ascii=False, sort_keys=True)


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
    inventory: Mapping[str, Any], delta: Mapping[str, Any]
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


def inventory_spend(inventory: Mapping[str, Any], requirements: Mapping[str, Any]) -> dict[str, int]:
    """Return an inventory after spending required item quantities."""

    missing = inventory_missing(inventory, requirements)
    if missing:
        raise AssetDeltaError(f"inventory is missing items: {missing}")
    return inventory_with_delta(
        inventory,
        {str(key): -int(quantity) for key, quantity in requirements.items()},
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
    "AssetDeltaError",
    "currency_grant",
    "currency_spend",
    "currency_with_delta",
    "inventory_amount",
    "inventory_grant",
    "inventory_json",
    "inventory_missing",
    "inventory_spend",
    "inventory_value",
    "inventory_with_delta",
]
