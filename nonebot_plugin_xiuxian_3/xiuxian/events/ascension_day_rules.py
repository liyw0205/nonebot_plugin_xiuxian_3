"""Rules and records for 飞升日 (``event.ascension_day``).

The event is a pure projection: the season's frozen snapshot, the player's own
recorded ending, and the new-chapter entries.  Nothing here writes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from ..content import ContentBundle
from .ascension_day_content import ascension_day_defaults
from .ascension_day_models import AscensionBoardRow

PENDING = "pending"
OPEN = "open"
CLOSED = "closed"


@dataclass(frozen=True, slots=True)
class AscensionDayDefinition:
    name: str
    description: str
    aliases: tuple[str, ...]
    window_hours: int
    display_boards: tuple[str, ...]
    chapter_entry_keys: tuple[str, ...]


BOARD_LABELS = {"ascension": "飞升榜", "dao": "留界榜", "cooperation": "协作榜"}
ENDING_LABELS = {"ascend": "飞升", "remain_in_world": "留界"}


def ascension_day_definition(content: ContentBundle) -> AscensionDayDefinition:
    raw = ascension_day_defaults(content)
    return AscensionDayDefinition(
        name=str(raw["name"]),
        description=str(raw["description"]),
        aliases=tuple(raw["aliases"]),
        window_hours=int(raw["window_hours"]),
        display_boards=tuple(raw["display_boards"]),
        chapter_entry_keys=tuple(raw["chapter_entry_keys"]),
    )


def ascension_window(*, season_ends_at: datetime, window_hours: int) -> tuple[datetime, datetime]:
    """Return the ``[starts_at, ends_at)`` display window after a season closes."""

    start = season_ends_at
    return start, start + timedelta(hours=window_hours)


def window_state(
    *, now: datetime, season_ends_at: datetime | None, window_hours: int
) -> str:
    """Return ``pending``/``open``/``closed`` for the current instant."""

    if season_ends_at is None:
        return PENDING
    start, end = ascension_window(season_ends_at=season_ends_at, window_hours=window_hours)
    if now < start:
        return PENDING
    if now >= end:
        return CLOSED
    return OPEN


def parse_instant(value: str | None) -> datetime | None:
    if value is None:
        return None
    moment = datetime.fromisoformat(value)
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def board_rows(boards: dict[str, object], board_key: str) -> tuple[AscensionBoardRow, ...]:
    """Project one board from a frozen season snapshot."""

    raw = boards.get(board_key)
    if not isinstance(raw, list):
        return ()
    rows: list[AscensionBoardRow] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            rows.append(
                AscensionBoardRow(
                    rank=int(item["rank"]),
                    label=str(item.get("anonymous_label", "")),
                    score=int(item.get("score", 0)),
                    achieved_at=str(item.get("achieved_at", "")),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return tuple(sorted(rows, key=lambda row: row.rank))


def board_label(board_key: str) -> str:
    return BOARD_LABELS.get(board_key, board_key)


def ending_label(ending_key: str | None) -> str | None:
    if ending_key is None:
        return None
    return ENDING_LABELS.get(ending_key, ending_key)