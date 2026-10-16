"""Content-backed contracts for the temporary seasons."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..content import ContentBundle, ContentError, bundled_content

KIND = "season"
THREE_REALMS_SEASON_KEY = "season.three_realms"
FINAL_HEAVEN_SEASON_KEY = "season.final_heaven"
VOID_FRONTIER_SEASON_KEY = "season.void_frontier"


def _bundle(content: ContentBundle | None) -> ContentBundle:
    return content if content is not None else bundled_content()


def _score_map(value: Any, field: str, key: str) -> dict[str, int]:
    if not isinstance(value, dict) or not value:
        raise ContentError(f"{key} {field} must be a non-empty object")
    parsed: dict[str, int] = {}
    for name, amount in value.items():
        if not isinstance(name, str) or not name.strip():
            raise ContentError(f"{key} {field} has an invalid key")
        parsed[name] = _positive(amount, f"{field}.{name}", key)
    return parsed


def _rank_rewards(value: Any, key: str) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, list) or not value:
        raise ContentError(f"{key} rank_rewards must be a non-empty list")
    parsed: list[dict[str, Any]] = []
    seen: set[int] = set()
    for index, entry in enumerate(value):
        if not isinstance(entry, dict):
            raise ContentError(f"{key} rank_rewards[{index}] must be an object")
        rank = _positive(entry.get("rank"), f"rank_rewards[{index}].rank", key)
        if rank in seen:
            raise ContentError(f"{key} rank_rewards has a duplicate rank {rank}")
        seen.add(rank)
        parsed.append(
            {
                "rank": rank,
                "reward": _score_map(
                    entry.get("reward"), f"rank_rewards[{index}].reward", key
                ),
            }
        )
    return tuple(parsed)


def _positive(value: Any, field: str, key: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ContentError(f"{key} {field} must be a positive integer")
    return int(value)


def season_record(key: str, content: ContentBundle | None = None) -> dict[str, Any]:
    bundle = _bundle(content)
    try:
        row = bundle.require(KIND, key, include_locked=True)
    except KeyError as exc:
        raise ContentError(f"missing season content: {key}") from exc
    if row.get("status") not in {"active", "open"}:
        raise ContentError(f"{key} status is not open")
    for field in ("name", "desc"):
        if not isinstance(row.get(field), str) or not row[field].strip():
            raise ContentError(f"{key} requires a {field}")
    anchor = row.get("anchor")
    if not isinstance(anchor, str):
        raise ContentError(f"{key} anchor is invalid")
    try:
        parsed = datetime.fromisoformat(anchor)
    except ValueError as exc:
        raise ContentError(f"{key} anchor is invalid") from exc
    if parsed.tzinfo is None:
        raise ContentError(f"{key} anchor must be timezone-aware")
    boards = row.get("boards")
    parsed_boards: dict[str, dict[str, Any]] = {}
    if boards is not None:
        if not isinstance(boards, dict) or not boards:
            raise ContentError(f"{key} boards must be a non-empty object")
        seen: set[str] = set()
        for board_key, board in boards.items():
            if (
                not isinstance(board_key, str)
                or not board_key.strip()
                or board_key in seen
            ):
                raise ContentError(f"{key} has an invalid or duplicate board key")
            seen.add(board_key)
            if not isinstance(board, dict):
                raise ContentError(f"{key} board {board_key} must be an object")
            label = board.get("label")
            if not isinstance(label, str) or not label.strip():
                raise ContentError(f"{key} board {board_key} requires a label")
            if "score" in board:
                _positive(board["score"], f"boards.{board_key}.score", key)
            for field in ("title_key", "title_label"):
                if field in board and (
                    not isinstance(board[field], str) or not board[field].strip()
                ):
                    raise ContentError(f"{key} board {board_key} has an invalid {field}")
            parsed_boards[board_key] = dict(board)
    chapter_entitlement = row.get("chapter_entitlement")
    if chapter_entitlement is not None and (
        not isinstance(chapter_entitlement, str) or not chapter_entitlement.strip()
    ):
        raise ContentError(f"{key} has an invalid chapter_entitlement")
    result: dict[str, Any] = {
        "key": key,
        "duration_days": _positive(row.get("duration_days"), "duration_days", key),
        "claim_days": _positive(row.get("claim_days"), "claim_days", key),
        "anchor": parsed.astimezone(timezone.utc),
        "rank_limit": _positive(row.get("rank_limit"), "rank_limit", key),
        "boards": parsed_boards,
        "chapter_entitlement": chapter_entitlement,
    }
    weekly_cap = row.get("weekly_cap")
    if weekly_cap is not None:
        result["weekly_cap"] = _positive(weekly_cap, "weekly_cap", key)
    for field in ("weekly_reward", "score_values", "default_rank_reward"):
        value = row.get(field)
        if value is not None:
            result[field] = _score_map(value, field, key)
    rank_rewards = row.get("rank_rewards")
    if rank_rewards is not None:
        result["rank_rewards"] = _rank_rewards(rank_rewards, key)
    return result


__all__ = [
    "FINAL_HEAVEN_SEASON_KEY",
    "KIND",
    "THREE_REALMS_SEASON_KEY",
    "VOID_FRONTIER_SEASON_KEY",
    "season_record",
]
