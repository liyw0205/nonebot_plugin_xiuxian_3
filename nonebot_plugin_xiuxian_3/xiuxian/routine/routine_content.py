"""Validated honor-title and dao-contract definitions from the content package."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..content import ContentBundle, ContentError, bundled_content

if TYPE_CHECKING:  # pragma: no cover - typing only, avoids an import cycle
    from .rules import DaoContractDefinition, HonorTitleDefinition

_CLAIMABLE_STATUSES = frozenset({"active", "open"})
_CLOSED_STATUSES = frozenset({"closed"})
_HIDDEN_STATUSES = frozenset({"locked", "planned"})
_TITLE_FIELDS = frozenset({"key", "label", "source_event", "hint", "status"})
_CONTRACT_FIELDS = frozenset(
    {
        "key",
        "label",
        "duration_days",
        "price",
        "daily_reward",
        "activation_reward",
        "reputation_every_days",
        "reputation_reward",
        "status",
    }
)
_CONTRACT_OPTIONAL_FIELDS = frozenset(
    {"activation_reward", "reputation_every_days", "reputation_reward"}
)


def honor_title_definitions(
    content: ContentBundle | None = None,
) -> tuple["HonorTitleDefinition", ...]:
    """Return every listed honor title in declaration order.

    Closed titles stay in the table so an earned title survives a content
    shutdown and keeps its ``佩戴称号 <序号>`` slot; they are never granted
    automatically any more.  Locked or planned titles stay out of the table.
    """

    from .rules import HonorTitleDefinition

    bundle = content or bundled_content()
    rows, statuses = _listed_rows(bundle, "honor_title", "honor title")
    definitions: list[HonorTitleDefinition] = []
    seen: set[str] = set()
    for row, closed in zip(rows, statuses):
        fields = set(row)
        if fields != _TITLE_FIELDS:
            raise ContentError("honor title fields are invalid")
        key = _text(row.get("key"), "key")
        if not key.startswith("title."):
            raise ContentError(f"honor title key is invalid: {key}")
        label = _text(row.get("label"), f"label {key}")
        hint = _text(row.get("hint"), f"hint {key}")
        source_event = row.get("source_event")
        if source_event is not None:
            source_event = _text(source_event, f"source event {key}")
        if key in seen:
            raise ContentError(f"duplicate honor title: {key}")
        seen.add(key)
        definitions.append(
            HonorTitleDefinition(
                key=key,
                label=label,
                source_event=source_event,
                closed=closed,
                hint=hint,
            )
        )
    return tuple(definitions)


def dao_contract_definitions(
    content: ContentBundle | None = None,
) -> tuple["DaoContractDefinition", ...]:
    """Return every listed dao contract in declaration order."""

    from .rules import DaoContractDefinition

    bundle = content or bundled_content()
    rows, statuses = _listed_rows(bundle, "dao_contract", "dao contract")
    definitions: list[DaoContractDefinition] = []
    seen: set[str] = set()
    for row, closed in zip(rows, statuses):
        fields = set(row)
        if not fields >= _CONTRACT_FIELDS - _CONTRACT_OPTIONAL_FIELDS or fields - (
            _CONTRACT_FIELDS
        ):
            raise ContentError("dao contract fields are invalid")
        key = _text(row.get("key"), "key")
        if not key.startswith("dao_contract."):
            raise ContentError(f"dao contract key is invalid: {key}")
        label = _text(row.get("label"), f"label {key}")
        duration_days = _positive_int(row.get("duration_days"), f"duration {key}")
        price = _non_negative_int(row.get("price"), f"price {key}")
        daily_reward = _reward(row.get("daily_reward"), f"daily reward {key}")
        activation_reward = _reward(
            row.get("activation_reward", {}), f"activation reward {key}", allow_empty=True
        )
        every_days = row.get("reputation_every_days")
        reputation_reward = row.get("reputation_reward", 0)
        if every_days is None:
            if reputation_reward:
                raise ContentError(
                    f"dao contract {key} declares a reputation reward without a period"
                )
            every_days_value = None
            reputation_value = 0
        else:
            every_days_value = _positive_int(every_days, f"reputation period {key}")
            reputation_value = _non_negative_int(
                reputation_reward, f"reputation reward {key}"
            )
        if key in seen:
            raise ContentError(f"duplicate dao contract: {key}")
        seen.add(key)
        definitions.append(
            DaoContractDefinition(
                key=key,
                label=label,
                duration_days=duration_days,
                price=price,
                daily_reward=daily_reward,
                activation_reward=activation_reward,
                reputation_every_days=every_days_value,
                reputation_reward=reputation_value,
                closed=closed,
            )
        )
    return tuple(definitions)


def _listed_rows(
    bundle: ContentBundle, kind: str, label: str
) -> tuple[list[dict[str, Any]], list[bool]]:
    rows = bundle.list(kind)
    if not rows:
        raise ContentError(f"{label} content is missing")
    listed: list[dict[str, Any]] = []
    closed_flags: list[bool] = []
    for row in rows:
        status = row.get("status")
        if status in _CLAIMABLE_STATUSES:
            closed = False
        elif status in _CLOSED_STATUSES:
            closed = True
        elif status in _HIDDEN_STATUSES:
            continue
        else:
            raise ContentError(f"{label} status is invalid: {row.get('key')!r}")
        listed.append(row)
        closed_flags.append(closed)
    if not listed:
        raise ContentError(f"{label} content is missing")
    return listed, closed_flags


def _reward(
    value: Any, field: str, *, allow_empty: bool = False
) -> tuple[tuple[str, int], ...]:
    if not isinstance(value, dict):
        raise ContentError(f"dao contract {field} must be an object")
    if not value:
        if allow_empty:
            return ()
        raise ContentError(f"dao contract {field} must not be empty")
    reward: list[tuple[str, int]] = []
    for reward_key, amount in value.items():
        if not isinstance(reward_key, str) or not reward_key.strip():
            raise ContentError(f"dao contract {field} has an invalid asset key")
        reward.append((reward_key.strip(), _positive_int(amount, f"{field} {reward_key}")))
    return tuple(reward)


def _positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ContentError(f"dao contract {field} must be a positive integer")
    return value


def _non_negative_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ContentError(f"dao contract {field} must be a non-negative integer")
    return value


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContentError(f"honor title {field} must be a non-empty string")
    return value.strip()


__all__ = ["dao_contract_definitions", "honor_title_definitions"]
