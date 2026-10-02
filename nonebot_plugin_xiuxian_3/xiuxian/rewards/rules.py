"""Parse static reward records into the shared player state shape."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..content import ContentBundle, ContentError, bundled_content
from ..utils.player import PLAYER_RESOURCE_FIELDS


class RewardContentError(ContentError):
    """Raised when a reward record cannot be applied safely."""


_DEFAULT_CONTENT = bundled_content()
_RESOURCE_MAX_FIELDS = {"stamina": "stamina_max", "energy": "energy_max"}
_REWARD_RESOURCE_FIELDS = frozenset(
    key for key in PLAYER_RESOURCE_FIELDS if key != "spirit_stones" and not key.endswith("_max")
)


@dataclass(frozen=True, slots=True)
class RewardGrant:
    """Normalized result consumed by the shared player state transaction."""

    key: str
    operation: str
    assets: dict[str, int]
    value_delta: dict[str, int]
    set_values: dict[str, int]
    reputation: dict[str, int]

    def snapshot(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "operation": self.operation,
            "assets": dict(self.assets),
            "value_delta": dict(self.value_delta),
            "set_values": dict(self.set_values),
            "reputation": dict(self.reputation),
        }


def reward_definition(
    key: str,
    content: ContentBundle | None = None,
    *,
    operation: str | None = None,
) -> RewardGrant:
    """Load and validate one active reward record from the content bundle."""

    bundle = content or _DEFAULT_CONTENT
    try:
        row = bundle.require("reward", key, include_locked=False)
    except KeyError as exc:
        raise RewardContentError(f"reward record is not active: {key}") from exc
    record_operation = row.get("operation")
    if not isinstance(record_operation, str) or not record_operation:
        raise RewardContentError(f"reward {key} requires operation")
    if operation is not None and record_operation != operation:
        raise RewardContentError(
            f"reward {key} belongs to {record_operation}, not {operation}"
        )
    entries = row.get("entries")
    if not isinstance(entries, list) or not entries:
        raise RewardContentError(f"reward {key} requires non-empty entries")

    assets: dict[str, int] = {}
    value_delta: dict[str, int] = {}
    set_values: dict[str, int] = {}
    reputation: dict[str, int] = {}
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise RewardContentError(f"reward {key} entry {index} must be an object")
        kind = entry.get("kind")
        quantity = entry.get("quantity")
        if not isinstance(kind, str) or kind not in {"currency", "item", "resource", "reputation"}:
            raise RewardContentError(f"reward {key} entry {index} has unsupported kind")
        if "quantity_range" in entry and entry.get("quantity_range") is not None:
            raise RewardContentError(f"reward {key} entry {index} is not a fixed grant")
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
            raise RewardContentError(f"reward {key} entry {index} quantity must be positive")

        if kind == "currency":
            currency_key = entry.get("currency_key")
            if currency_key != "currency.spirit_stone":
                raise RewardContentError(f"reward {key} entry {index} has unsupported currency")
            _add(assets, "spirit_stones", quantity)
        elif kind == "item":
            item_key = entry.get("item_key")
            if not isinstance(item_key, str) or not item_key.startswith("item."):
                raise RewardContentError(f"reward {key} entry {index} requires item_key")
            try:
                bundle.require("item", item_key, include_locked=False)
            except KeyError as exc:
                raise RewardContentError(
                    f"reward {key} entry {index} references inactive item {item_key}"
                ) from exc
            _add(assets, item_key, quantity)
        elif kind == "resource":
            resource_key = entry.get("resource_key")
            if resource_key not in _REWARD_RESOURCE_FIELDS:
                raise RewardContentError(
                    f"reward {key} entry {index} references unsupported resource {resource_key}"
                )
            set_max = entry.get("set_max")
            if set_max is not None and (
                isinstance(set_max, bool) or not isinstance(set_max, int) or set_max <= 0
            ):
                raise RewardContentError(f"reward {key} entry {index} set_max must be positive")
            if set_max is not None and set_max < quantity:
                raise RewardContentError(
                    f"reward {key} entry {index} set_max must be at least quantity"
                )
            if set_max is not None:
                max_field = _RESOURCE_MAX_FIELDS.get(str(resource_key))
                if max_field is None:
                    raise RewardContentError(
                        f"reward {key} entry {index} cannot set maximum for {resource_key}"
                    )
                if set_max < quantity:
                    raise RewardContentError(
                        f"reward {key} entry {index} set_max cannot be below quantity"
                    )
                _add(set_values, str(resource_key), quantity)
                _add(set_values, max_field, set_max)
            else:
                _add(value_delta, str(resource_key), quantity)
        else:
            reputation_key = entry.get("reputation_key")
            if not isinstance(reputation_key, str) or not reputation_key.startswith("faction_reputation."):
                raise RewardContentError(f"reward {key} entry {index} requires reputation_key")
            _add(reputation, reputation_key, quantity)

    return RewardGrant(
        key=key,
        operation=record_operation,
        assets=assets,
        value_delta=value_delta,
        set_values=set_values,
        reputation=reputation,
    )


def _add(target: dict[str, int], key: str, amount: int) -> None:
    target[key] = target.get(key, 0) + int(amount)


__all__ = ["RewardContentError", "RewardGrant", "reward_definition"]
