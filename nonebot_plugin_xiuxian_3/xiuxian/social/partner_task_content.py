"""Content-backed contract for 道侣终局协作 (``partner.endgame_task``).

Social v0.6 froze the row: a valid partner pair whose endgame sessions are both
still open may take on a shared task, each side earns merit, and the task must
never decide either side's ending.  The loader therefore pins the reward set to
ordinary assets and rejects anything endgame-only.
"""

from __future__ import annotations

from typing import Any

from ..content import ContentBundle, ContentError, bundled_content

KIND = "partner_task"
DEFAULTS_KEY = "task.partner.endgame.defaults"
ENDING_STATES = {"open"}
TARGET_KINDS = {"endgame_assist_wins"}
# Endgame-only assets must never be paid out by a partner task.
FORBIDDEN_REWARD_ITEMS = {
    "item.tribulation_token",
    "item.ascension_certificate",
    "item.tribulation_guard",
    "item.dao_fruit_fragment",
    "item.domain_core",
}
REQUIRED_FIELDS = {
    "key",
    "name",
    "desc",
    "status",
    "required_ending_state",
    "window_days",
    "target_kind",
    "target_amount",
    "reward_world_merit",
    "reward_items",
}


def _bundle(content: ContentBundle | None) -> ContentBundle:
    return content if content is not None else bundled_content()


def _text(row: dict[str, Any], field: str, key: str) -> str:
    value = row.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ContentError(f"partner task {key} requires a {field}")
    return value.strip()


def _positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ContentError(f"partner task {label} must be a positive integer")
    return int(value)


def partner_task_defaults(content: ContentBundle | None = None) -> dict[str, Any]:
    """Return the validated shared-task parameters."""

    bundle = _bundle(content)
    try:
        row = bundle.require(KIND, DEFAULTS_KEY, include_locked=True)
    except KeyError as exc:
        raise ContentError(f"missing partner_task content: {DEFAULTS_KEY}") from exc
    if row.get("status") != "active":
        raise ContentError(f"{DEFAULTS_KEY} is not active")
    missing = REQUIRED_FIELDS - set(row)
    if missing:
        raise ContentError(f"partner task {DEFAULTS_KEY} is missing fields: {sorted(missing)}")

    ending_state = _text(row, "required_ending_state", DEFAULTS_KEY)
    if ending_state not in ENDING_STATES:
        raise ContentError(f"partner task {DEFAULTS_KEY} has an unsupported ending state")

    target_kind = _text(row, "target_kind", DEFAULTS_KEY)
    if target_kind not in TARGET_KINDS:
        raise ContentError(f"partner task {DEFAULTS_KEY} has an unsupported target kind")

    rewards = row.get("reward_items")
    if not isinstance(rewards, dict) or not rewards:
        raise ContentError(f"partner task {DEFAULTS_KEY} reward_items must be a non-empty object")
    normalised_rewards: dict[str, int] = {}
    for item_key, quantity in rewards.items():
        if not isinstance(item_key, str) or bundle.get("item", item_key, include_locked=False) is None:
            raise ContentError(f"partner task {DEFAULTS_KEY} references an unknown item: {item_key!r}")
        if item_key in FORBIDDEN_REWARD_ITEMS:
            raise ContentError(
                f"partner task {DEFAULTS_KEY} may not pay out the endgame asset {item_key!r}"
            )
        normalised_rewards[item_key] = _positive_int(
            quantity, f"{DEFAULTS_KEY} reward_items[{item_key}]"
        )

    names = [_text(row, "name", DEFAULTS_KEY)]
    raw_aliases = row.get("aliases", [])
    if not isinstance(raw_aliases, list):
        raise ContentError(f"partner task {DEFAULTS_KEY} aliases must be a list")
    for alias in raw_aliases:
        if not isinstance(alias, str) or not alias.strip():
            raise ContentError(f"partner task {DEFAULTS_KEY} has a malformed alias")
        names.append(alias.strip())

    return {
        "key": DEFAULTS_KEY,
        "name": names[0],
        "description": _text(row, "desc", DEFAULTS_KEY),
        "aliases": tuple(names),
        "required_ending_state": ending_state,
        "window_days": _positive_int(row.get("window_days"), f"{DEFAULTS_KEY} window_days"),
        "target_kind": target_kind,
        "target_amount": _positive_int(
            row.get("target_amount"), f"{DEFAULTS_KEY} target_amount"
        ),
        "reward_world_merit": _positive_int(
            row.get("reward_world_merit"), f"{DEFAULTS_KEY} reward_world_merit"
        ),
        "reward_items": normalised_rewards,
    }