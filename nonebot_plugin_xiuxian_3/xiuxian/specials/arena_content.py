"""Content-backed contracts for the arena gameplay family."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ..content import ContentBundle, ContentError, bundled_content

KIND = "arena_rule"
DEFAULTS_KEY = "arena.defaults"
FACTIONS = ("xuantian", "demon", "beast")


def _bundle(content: ContentBundle | None) -> ContentBundle:
    return content if content is not None else bundled_content()


def _text(value: Any, field: str, key: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContentError(f"{key} {field} is invalid")
    return value.strip()


def _signed(value: Any, field: str, key: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ContentError(f"{key} {field} must be an integer")
    return int(value)


def _positive(value: Any, field: str, key: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ContentError(f"{key} {field} must be a positive integer")
    return int(value)


def arena_defaults(content: ContentBundle | None = None) -> dict[str, Any]:
    key = DEFAULTS_KEY
    bundle = _bundle(content)
    try:
        row = bundle.require(KIND, key, include_locked=False)
    except KeyError as exc:
        raise ContentError(f"missing {KIND} content: {key}") from exc
    if row.get("status") != "active":
        raise ContentError(f"{key} status is not active")
    for field in ("name", "desc"):
        if not isinstance(row.get(field), str) or not row[field].strip():
            raise ContentError(f"{key} requires a {field}")
    bands = row.get("rating_bands")
    if not isinstance(bands, list) or not bands:
        raise ContentError(f"{key} rating_bands must be a non-empty list")
    cleaned = [_positive(band, "rating_bands", key) for band in bands]
    if any(later <= earlier for earlier, later in zip(cleaned, cleaned[1:])):
        raise ContentError(f"{key} rating_bands must be strictly ascending")
    factions = row.get("factions")
    if not isinstance(factions, list) or not factions:
        raise ContentError(f"{key} factions must be a non-empty list")
    for faction in factions:
        if faction not in FACTIONS:
            raise ContentError(f"{key} has an unsupported faction {faction}")
    return {
        "key": key,
        "rating_bands": tuple(cleaned),
        "factions": tuple(factions),
    }


def _mode_row(bundle: ContentBundle, key: str) -> dict[str, Any]:
    try:
        row = bundle.require(KIND, key, include_locked=False)
    except KeyError as exc:
        raise ContentError(f"missing {KIND} content: {key}") from exc
    if row.get("status") != "active":
        raise ContentError(f"{key} status is not active")
    for field in ("name", "desc"):
        if not isinstance(row.get(field), str) or not row[field].strip():
            raise ContentError(f"{key} requires a {field}")
    _text(row.get("mode_key"), "mode_key", key)
    return row


def spar_record(content: ContentBundle | None = None) -> dict[str, Any]:
    key = "arena.spar"
    row = _mode_row(_bundle(content), key)
    fields = (
        "snapshot_valid_days",
        "daily_challenge_limit",
        "weekly_rank_limit",
        "daily_practice_limit",
        "daily_counted_opponent_limit",
        "max_rounds",
    )
    values = {field: _positive(row.get(field), field, key) for field in fields}
    return {
        "key": key,
        "mode_key": str(row["mode_key"]),
        "rank_mode_key": _text(row.get("rank_mode_key"), "rank_mode_key", key),
        "practice_mode_key": _text(row.get("practice_mode_key"), "practice_mode_key", key),
        "match_delay_seconds": _positive(row.get("match_delay_seconds"), "match_delay_seconds", key),
        **values,
        "win_rating_delta": _positive(row.get("win_rating_delta"), "win_rating_delta", key),
        "loss_rating_delta": _signed(row.get("loss_rating_delta"), "loss_rating_delta", key),
        "draw_rating_delta": _signed(row.get("draw_rating_delta"), "draw_rating_delta", key),
    }


def team_record(content: ContentBundle | None = None) -> dict[str, Any]:
    key = "arena.team"
    row = _mode_row(_bundle(content), key)
    min_size = _positive(row.get("min_team_size"), "min_team_size", key)
    max_size = _positive(row.get("max_team_size"), "max_team_size", key)
    if max_size < min_size:
        raise ContentError(f"{key} max_team_size is below min_team_size")
    return {
        "key": key,
        "mode_key": str(row["mode_key"]),
        "snapshot_valid_days": _positive(row.get("snapshot_valid_days"), "snapshot_valid_days", key),
        "match_delay_seconds": _positive(row.get("match_delay_seconds"), "match_delay_seconds", key),
        "daily_challenge_limit": _positive(row.get("daily_challenge_limit"), "daily_challenge_limit", key),
        "min_team_size": min_size,
        "max_team_size": max_size,
        "win_rating_delta": _positive(row.get("win_rating_delta"), "win_rating_delta", key),
        "loss_rating_delta": _signed(row.get("loss_rating_delta"), "loss_rating_delta", key),
    }


def three_realms_record(content: ContentBundle | None = None) -> dict[str, Any]:
    key = "arena.three_realms"
    bundle = _bundle(content)
    row = _mode_row(bundle, key)
    required_realm = _text(row.get("required_realm"), "required_realm", key)
    try:
        bundle.require("realm", required_realm, include_locked=False)
    except KeyError as exc:
        raise ContentError(
            f"{key} references unknown realm {required_realm}"
        ) from exc
    factions = row.get("factions")
    if not isinstance(factions, list) or not factions:
        raise ContentError(f"{key} factions must be a non-empty list")
    for faction in factions:
        if faction not in FACTIONS:
            raise ContentError(f"{key} has an unsupported faction {faction}")
    return {
        "key": key,
        "mode_key": str(row["mode_key"]),
        "required_realm": required_realm,
        "required_layer": _positive(row.get("required_layer"), "required_layer", key),
        # The permit key is an identifier constant: the runtime never resolves
        # it as an item, so it is validated as a non-empty identifier only.
        "permit_key": _text(row.get("permit_key"), "permit_key", key),
        "factions": tuple(factions),
    }


def _reward_map(
    value: Any, field: str, key: str, bundle: ContentBundle, reputation_key: str
) -> dict[str, int]:
    """Validate a flat rank reward: stones, the record's local reputation, items.

    Local reputation is one shared amount routed to the record's
    ``local_reputation_key``, matching how other content declares it.
    """

    if not isinstance(value, dict) or not value:
        raise ContentError(f"{key} {field} must be a non-empty object")
    cleaned: dict[str, int] = {}
    for reward_key, amount in value.items():
        if not isinstance(reward_key, str) or not reward_key:
            raise ContentError(f"{key} {field} has an invalid key")
        if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
            raise ContentError(f"{key} {field} {reward_key} must be a positive integer")
        if reward_key == "spirit_stones" or reward_key == "local_reputation":
            cleaned[reward_key] = amount
        elif reward_key.startswith("item."):
            try:
                bundle.require("item", reward_key, include_locked=False)
            except KeyError as exc:
                raise ContentError(
                    f"{key} {field} references unavailable item {reward_key}"
                ) from exc
            cleaned[reward_key] = amount
        else:
            raise ContentError(f"{key} {field} has an unsupported reward {reward_key!r}")
    if "local_reputation" in cleaned and not reputation_key:
        raise ContentError(f"{key} {field} grants reputation without a reputation key")
    return cleaned


def season_record(content: ContentBundle | None = None) -> dict[str, Any]:
    """The local weekly ladder contract: window anchor, board and rank payouts."""

    key = "arena.season"
    bundle = _bundle(content)
    try:
        row = bundle.require(KIND, key, include_locked=False)
    except KeyError as exc:
        raise ContentError(f"missing {KIND} content: {key}") from exc
    if row.get("status") != "active":
        raise ContentError(f"{key} status is not active")
    for field in ("name", "desc"):
        if not isinstance(row.get(field), str) or not row[field].strip():
            raise ContentError(f"{key} requires a {field}")

    anchor_text = row.get("week_anchor")
    if not isinstance(anchor_text, str) or not anchor_text.strip():
        raise ContentError(f"{key} week_anchor must be an ISO timestamp")
    try:
        anchor = datetime.fromisoformat(anchor_text)
    except ValueError as exc:
        raise ContentError(f"{key} week_anchor is not an ISO timestamp") from exc
    if anchor.tzinfo is None:
        raise ContentError(f"{key} week_anchor must carry a timezone")

    board_size = _positive(row.get("board_size"), "board_size", key)
    reputation_key = _text(row.get("local_reputation_key"), "local_reputation_key", key)
    if not reputation_key.startswith("local."):
        raise ContentError(f"{key} local_reputation_key must be a local reputation key")
    from ..rewards.rules import local_reputation_maximum

    local_reputation_maximum(reputation_key, bundle)
    title_key = _text(row.get("title_key"), "title_key", key)
    if not bundle.has("honor_title", title_key, include_locked=False):
        raise ContentError(f"{key} references unknown title {title_key}")

    rewards_value = row.get("rank_rewards")
    if not isinstance(rewards_value, list) or not rewards_value:
        raise ContentError(f"{key} rank_rewards must be a non-empty list")
    rank_rewards: list[dict[str, Any]] = []
    seen: set[int] = set()
    for index, entry in enumerate(rewards_value):
        if not isinstance(entry, dict) or set(entry) != {"rank", "reward"}:
            raise ContentError(f"{key} rank_rewards[{index}] must be a rank/reward object")
        rank = _positive(entry.get("rank"), f"rank_rewards[{index}].rank", key)
        if rank > board_size:
            raise ContentError(f"{key} rank_rewards[{index}] rank exceeds board_size")
        if rank in seen:
            raise ContentError(f"{key} rank_rewards has a duplicate rank {rank}")
        seen.add(rank)
        rank_rewards.append(
            {"rank": rank, "reward": _reward_map(entry.get("reward"), f"rank_rewards[{index}].reward", key, bundle, reputation_key)}
        )
    default_reward = _reward_map(row.get("default_rank_reward"), "default_rank_reward", key, bundle, reputation_key)
    return {
        "key": key,
        "week_anchor": anchor,
        "board_size": board_size,
        "local_reputation_key": reputation_key,
        "title_key": title_key,
        "rank_rewards": tuple(rank_rewards),
        "default_rank_reward": default_reward,
    }


__all__ = [
    "DEFAULTS_KEY",
    "FACTIONS",
    "KIND",
    "arena_defaults",
    "season_record",
    "spar_record",
    "team_record",
    "three_realms_record",
]
