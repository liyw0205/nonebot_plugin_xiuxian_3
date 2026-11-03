"""Immutable records for 飞升日 (``event.ascension_day``)."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class AscensionBoardRow:
    rank: int
    label: str
    score: int
    achieved_at: str


@dataclass(frozen=True, slots=True)
class AscensionBoard:
    board_key: str
    label: str
    rows: tuple[AscensionBoardRow, ...] = ()


@dataclass(frozen=True, slots=True)
class AscensionChapterEntry:
    key: str
    label: str


@dataclass(frozen=True, slots=True)
class AscensionDayRecord:
    state: str
    season_id: str
    season_ends_at: str
    starts_at: str
    ends_at: str
    definition_name: str
    ending_key: str | None
    ending_label: str | None
    boards: tuple[AscensionBoard, ...] = ()
    chapters: tuple[AscensionChapterEntry, ...] = field(default_factory=tuple)