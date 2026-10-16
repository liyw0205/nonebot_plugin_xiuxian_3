"""Content-backed contracts for the temporary seasons."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..content import ContentBundle, ContentError, bundled_content

KIND = "season"
THREE_REALMS_SEASON_KEY = "season.three_realms"
FINAL_HEAVEN_SEASON_KEY = "season.final_heaven"


def _bundle(content: ContentBundle | None) -> ContentBundle:
    return content if content is not None else bundled_content()


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
    if not isinstance(boards, dict) or not boards:
        raise ContentError(f"{key} boards must be a non-empty object")
    seen: set[str] = set()
    for board_key, board in boards.items():
        if not isinstance(board_key, str) or not board_key.strip() or board_key in seen:
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
    chapter_entitlement = row.get("chapter_entitlement")
    if chapter_entitlement is not None and (
        not isinstance(chapter_entitlement, str) or not chapter_entitlement.strip()
    ):
        raise ContentError(f"{key} has an invalid chapter_entitlement")
    return {
        "key": key,
        "duration_days": _positive(row.get("duration_days"), "duration_days", key),
        "claim_days": _positive(row.get("claim_days"), "claim_days", key),
        "anchor": parsed.astimezone(timezone.utc),
        "rank_limit": _positive(row.get("rank_limit"), "rank_limit", key),
        "boards": {board_key: dict(board) for board_key, board in boards.items()},
        "chapter_entitlement": chapter_entitlement,
    }


__all__ = [
    "FINAL_HEAVEN_SEASON_KEY",
    "KIND",
    "THREE_REALMS_SEASON_KEY",
    "season_record",
]
