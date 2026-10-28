"""Validated achievement definitions loaded from the content package."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..content import ContentBundle, ContentError, bundled_content
from ..rewards.rules import local_reputation_maximum

if TYPE_CHECKING:  # pragma: no cover - typing only, avoids an import cycle
    from .rules import AchievementDefinition

_NUMERIC_REWARDS = frozenset({"local_reputation", "service_reputation"})
_REWARD_KEYS = _NUMERIC_REWARDS | {"title_key"}
_RECORD_FIELDS = frozenset({"key", "label", "source_event", "reward", "status"})
_OPTIONAL_FIELDS = frozenset({"local_reputation_key"})
_CLAIMABLE_STATUSES = frozenset({"active", "open"})
_CLOSED_STATUSES = frozenset({"closed"})
_HIDDEN_STATUSES = frozenset({"locked", "planned"})


def achievement_definitions(
    content: ContentBundle | None = None,
) -> tuple["AchievementDefinition", ...]:
    """Return every listed achievement in declaration order.

    Closed entries stay in the table so a content shutdown only blocks new
    claims: already claimed rewards, their display rows and the
    ``领取功业 <序号>`` numbering survive it.  Locked or planned entries stay
    out of the table entirely.
    """

    from .rules import AchievementDefinition

    bundle = content or bundled_content()
    rows = bundle.list("achievement")
    if not rows:
        raise ContentError("achievement content is missing")
    definitions: list[AchievementDefinition] = []
    seen: set[str] = set()
    for row in rows:
        status = row.get("status")
        if status in _CLAIMABLE_STATUSES:
            closed = False
        elif status in _CLOSED_STATUSES:
            closed = True
        elif status in _HIDDEN_STATUSES:
            continue
        else:
            raise ContentError(
                f"achievement status is invalid: {row.get('key')!r}"
            )
        definition = _parse_achievement(row, bundle, closed=closed)
        if definition.key in seen:
            raise ContentError(f"duplicate achievement: {definition.key}")
        seen.add(definition.key)
        definitions.append(definition)
    if not definitions:
        raise ContentError("achievement content is missing")
    return tuple(definitions)


def _parse_achievement(
    row: dict[str, Any], bundle: ContentBundle, *, closed: bool = False
) -> AchievementDefinition:
    from .rules import AchievementDefinition

    fields = set(row)
    if not fields >= _RECORD_FIELDS or fields - _RECORD_FIELDS - _OPTIONAL_FIELDS:
        raise ContentError("achievement fields are invalid")
    key = _text(row.get("key"), "key")
    if not key.startswith("achievement."):
        raise ContentError(f"achievement key is invalid: {key}")
    label = _text(row.get("label"), f"label {key}")
    source_event = _text(row.get("source_event"), f"source event {key}")
    reward = _reward(row.get("reward"), key, bundle)
    reputation_key = row.get("local_reputation_key")
    local_reward = dict(reward).get("local_reputation")
    if local_reward is not None:
        if not isinstance(reputation_key, str) or not reputation_key.startswith("local."):
            raise ContentError(f"achievement {key} requires a local reputation key")
        try:
            local_reputation_maximum(reputation_key, bundle)
        except TypeError as exc:
            raise ContentError(
                f"achievement {key} local reputation content is invalid"
            ) from exc
    elif reputation_key is not None:
        raise ContentError(
            f"achievement {key} declares a reputation key without a local reward"
        )
    return AchievementDefinition(
        key=key,
        label=label,
        source_event=source_event,
        reward=reward,
        local_reputation_key=reputation_key,
        closed=closed,
    )


def _reward(
    value: Any, key: str, bundle: ContentBundle
) -> tuple[tuple[str, int | str], ...]:
    from .rules import honor_title

    if not isinstance(value, dict) or not value:
        raise ContentError(f"achievement {key} reward must be a non-empty object")
    reward: list[tuple[str, int | str]] = []
    for reward_key, amount in value.items():
        if reward_key not in _REWARD_KEYS:
            raise ContentError(
                f"achievement {key} rewards an unsupported asset: {reward_key}"
            )
        if reward_key == "title_key":
            title = _text(amount, f"title {key}")
            try:
                definition = honor_title(title)
            except ValueError as exc:
                raise ContentError(
                    f"achievement {key} references an unknown title: {title}"
                ) from exc
            if definition.closed:
                raise ContentError(
                    f"achievement {key} references an inactive title: {title}"
                )
            reward.append((reward_key, title))
            continue
        if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
            raise ContentError(f"achievement {key} reward {reward_key} must be positive")
        reward.append((reward_key, amount))
    return tuple(reward)


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContentError(f"achievement {field} must be a non-empty string")
    return value.strip()


__all__ = ["achievement_definitions"]
