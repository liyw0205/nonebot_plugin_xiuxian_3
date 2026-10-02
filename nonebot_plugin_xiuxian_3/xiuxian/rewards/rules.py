"""Parse static reward records into the shared player state shape."""

from __future__ import annotations

import hashlib
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


def combine_reward_grants(*grants: RewardGrant) -> RewardGrant:
    """Combine fixed grants that belong to the same application operation."""

    if not grants:
        raise ValueError("at least one reward grant is required")
    operations = {grant.operation for grant in grants}
    if len(operations) != 1:
        raise RewardContentError("reward grants must belong to one operation")
    value_delta = _combine_maps(*(grant.value_delta for grant in grants))
    set_values = _combine_set_values(*(grant.set_values for grant in grants))
    overlap = set(value_delta) & set(set_values)
    if overlap:
        raise RewardContentError(
            f"reward grants supply both delta and fixed values for {sorted(overlap)!r}"
        )
    return RewardGrant(
        key="+".join(grant.key for grant in grants),
        operation=grants[0].operation,
        assets=_combine_maps(*(grant.assets for grant in grants)),
        value_delta=value_delta,
        set_values=set_values,
        reputation=_combine_maps(*(grant.reputation for grant in grants)),
    )


def reward_totals(grant: RewardGrant) -> dict[str, int]:
    """Flatten a grant into the values shown and frozen in an operation."""

    totals = dict(grant.assets)
    for values in (grant.value_delta, grant.set_values, grant.reputation):
        for key, amount in values.items():
            if key.endswith("_max"):
                continue
            totals[key] = totals.get(key, 0) + int(amount)
    return totals


def reward_value_delta(grant: RewardGrant) -> dict[str, int]:
    """Return player numeric changes, including cumulative cultivation."""

    values = dict(grant.value_delta)
    if "cultivation" in values and "total_cultivation" not in values:
        values["total_cultivation"] = values["cultivation"]
    return values


def reward_pool_outcomes(
    key: str,
    content: ContentBundle | None = None,
) -> tuple[tuple[int, dict[str, int]], ...]:
    """Load a weighted reward pool without applying it to player state."""

    bundle = content or _DEFAULT_CONTENT
    row = _reward_pool_record(key, bundle)
    if "battle_failure_rewards" in row:
        _normalize_reward_pool_map(
            key,
            "battle_failure_rewards",
            row["battle_failure_rewards"],
            bundle,
        )
    outcomes = row.get("outcomes")
    if not isinstance(outcomes, list) or not outcomes:
        raise RewardContentError(f"reward pool {key} requires outcomes")
    normalized: list[tuple[int, dict[str, int]]] = []
    for index, outcome in enumerate(outcomes):
        if not isinstance(outcome, dict):
            raise RewardContentError(f"reward pool {key} outcome {index} must be an object")
        weight = outcome.get("weight")
        if isinstance(weight, bool) or not isinstance(weight, int) or weight <= 0:
            raise RewardContentError(f"reward pool {key} outcome {index} has invalid weight")
        if "no_reward" in outcome:
            if outcome["no_reward"] is not True:
                raise RewardContentError(
                    f"reward pool {key} outcome {index} no_reward must be true"
                )
            if "rewards" in outcome:
                raise RewardContentError(
                    f"reward pool {key} outcome {index} cannot combine no_reward and rewards"
                )
            normalized_rewards = {}
        else:
            normalized_rewards = _normalize_reward_pool_map(
                key,
                f"outcome {index}",
                outcome.get("rewards"),
                bundle,
            )
        normalized.append((weight, normalized_rewards))
    return tuple(normalized)


def reward_pool_battle_failure_rewards(
    key: str,
    content: ContentBundle | None = None,
) -> dict[str, int]:
    """Load optional rewards granted when an associated exploration battle is lost."""

    bundle = content or _DEFAULT_CONTENT
    row = _reward_pool_record(key, bundle)
    if "battle_failure_rewards" not in row:
        return {}
    return _normalize_reward_pool_map(
        key,
        "battle_failure_rewards",
        row["battle_failure_rewards"],
        bundle,
    )


def reward_pool_map(
    key: str,
    seed: str,
    content: ContentBundle | None = None,
    *,
    item_weight_bonus_bp: int = 0,
) -> dict[str, int]:
    """Select one deterministic outcome from a content-backed reward pool."""

    outcomes = reward_pool_outcomes(key, content)
    if (
        isinstance(item_weight_bonus_bp, bool)
        or not isinstance(item_weight_bonus_bp, int)
        or item_weight_bonus_bp < 0
    ):
        raise RewardContentError("item reward weight bonus must be a non-negative integer")
    weighted_outcomes = outcomes
    if item_weight_bonus_bp:
        weighted_outcomes = tuple(
            (
                weight * (10_000 + item_weight_bonus_bp)
                if any(reward_key.startswith("item.") for reward_key in rewards)
                else weight * 10_000,
                rewards,
            )
            for weight, rewards in outcomes
        )
    cursor = int.from_bytes(hashlib.blake2b(seed.encode("utf-8"), digest_size=8).digest(), "big")
    cursor %= sum(weight for weight, _ in weighted_outcomes)
    for weight, rewards in weighted_outcomes:
        if cursor < weight:
            return dict(rewards)
        cursor -= weight
    raise AssertionError("weighted reward selection fell through")


def _reward_pool_record(key: str, bundle: ContentBundle) -> dict[str, Any]:
    try:
        row = bundle.require("reward", key, include_locked=False)
    except KeyError as exc:
        raise RewardContentError(f"reward pool is not active: {key}") from exc
    if row.get("pool_type") != "weighted":
        raise RewardContentError(f"reward pool {key} must be weighted")
    return row


def _normalize_reward_pool_map(
    pool_key: str,
    label: str,
    rewards: Any,
    bundle: ContentBundle,
) -> dict[str, int]:
    if not isinstance(rewards, dict) or not rewards:
        raise RewardContentError(f"reward pool {pool_key} {label} requires rewards")
    normalized: dict[str, int] = {}
    for reward_key, quantity in rewards.items():
        if (
            not isinstance(reward_key, str)
            or isinstance(quantity, bool)
            or not isinstance(quantity, int)
            or quantity <= 0
        ):
            raise RewardContentError(
                f"reward pool {pool_key} {label} rewards must be positive integer quantities"
            )
        if reward_key.startswith("item."):
            try:
                bundle.require("item", reward_key, include_locked=False)
            except KeyError as exc:
                raise RewardContentError(
                    f"reward pool {pool_key} {label} references inactive item {reward_key}"
                ) from exc
        elif reward_key not in {"spirit_stones", "currency.spirit_stone"}:
            if reward_key.startswith("faction_reputation."):
                if not reward_key.removeprefix("faction_reputation."):
                    raise RewardContentError(
                        f"reward pool {pool_key} {label} requires a faction key"
                    )
            elif reward_key not in _REWARD_RESOURCE_FIELDS:
                raise RewardContentError(
                    f"reward pool {pool_key} {label} has unsupported reward key {reward_key!r}"
                )
        normalized[reward_key] = quantity
    return normalized


def _combine_maps(*maps: dict[str, int]) -> dict[str, int]:
    result: dict[str, int] = {}
    for values in maps:
        for key, amount in values.items():
            result[key] = result.get(key, 0) + int(amount)
    return result


def _combine_set_values(*maps: dict[str, int]) -> dict[str, int]:
    result: dict[str, int] = {}
    for values in maps:
        for key, amount in values.items():
            if key in result and result[key] != int(amount):
                raise RewardContentError(f"conflicting fixed value for {key}")
            result[key] = int(amount)
    return result


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
                if str(resource_key) in value_delta:
                    raise RewardContentError(
                        f"reward {key} supplies both delta and fixed values for {resource_key}"
                    )
                max_field = _RESOURCE_MAX_FIELDS.get(str(resource_key))
                if max_field is None:
                    raise RewardContentError(
                        f"reward {key} entry {index} cannot set maximum for {resource_key}"
                    )
                if set_max < quantity:
                    raise RewardContentError(
                        f"reward {key} entry {index} set_max cannot be below quantity"
                    )
                _set_value(set_values, str(resource_key), quantity)
                _set_value(set_values, max_field, set_max)
            else:
                _add(value_delta, str(resource_key), quantity)
        else:
            reputation_key = entry.get("reputation_key")
            if not isinstance(reputation_key, str) or not reputation_key.startswith("faction_reputation."):
                raise RewardContentError(f"reward {key} entry {index} requires reputation_key")
            if not reputation_key.removeprefix("faction_reputation."):
                raise RewardContentError(f"reward {key} entry {index} requires a faction")
            _add(reputation, reputation_key, quantity)

    overlap = set(value_delta) & set(set_values)
    if overlap:
        raise RewardContentError(
            f"reward {key} supplies both delta and fixed values for {sorted(overlap)!r}"
        )

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


def _set_value(target: dict[str, int], key: str, amount: int) -> None:
    value = int(amount)
    if key in target and target[key] != value:
        raise RewardContentError(f"conflicting fixed value for {key}")
    target[key] = value


__all__ = [
    "RewardContentError",
    "RewardGrant",
    "combine_reward_grants",
    "reward_definition",
    "reward_pool_battle_failure_rewards",
    "reward_pool_map",
    "reward_pool_outcomes",
    "reward_totals",
    "reward_value_delta",
]
