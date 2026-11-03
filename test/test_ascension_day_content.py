from __future__ import annotations

import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle, ContentError
from nonebot_plugin_xiuxian_3.xiuxian.events.ascension_day_content import (
    ascension_day_defaults,
)
from nonebot_plugin_xiuxian_3.xiuxian.events.ascension_day_rules import (
    CLOSED,
    OPEN,
    PENDING,
    ascension_day_definition,
    ascension_window,
    board_label,
    board_rows,
    ending_label,
    window_state,
)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
EVENT_FILE = Path("事件/飞升日.json")
DEFAULTS = "event.ascension_day.defaults"


def _copy_data(tmp_path: Path) -> Path:
    target = tmp_path / "data"
    shutil.copytree(DATA, target)
    return target


def _document(root: Path) -> dict:
    return json.loads((root / EVENT_FILE).read_text(encoding="utf-8"))


def _write(root: Path, document: dict) -> None:
    (root / EVENT_FILE).write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _record(document: dict) -> dict:
    return next(row for row in document["records"] if row["key"] == DEFAULTS)


def test_shipped_event_content_matches_the_frozen_events_row() -> None:
    bundle = ContentBundle.load(DATA)
    assert EVENT_FILE.as_posix() in bundle.manifest["files"]

    raw = bundle.require("ascension_day", DEFAULTS)
    assert raw["status"] == "active"
    # events v0.6: 24 hours after the season closes, display only.
    assert raw["window_hours"] == 24
    assert raw["allow_assets"] is False
    assert raw["require_frozen_season"] is True

    defaults = ascension_day_defaults(bundle)
    assert defaults["display_boards"] == ("ascension", "dao", "cooperation")
    assert defaults["chapter_entry_keys"] == (
        "lane.builder.chapter.01",
        "lane.witness.chapter.01",
        "lane.traveler.chapter.01",
    )
    definition = ascension_day_definition(bundle)
    assert definition.window_hours == 24
    assert "飞升日" in definition.aliases and "新篇章" in definition.aliases


def test_window_states_are_exact_at_both_edges() -> None:
    ends_at = datetime(2026, 11, 3, 4, 0, tzinfo=timezone.utc)
    start, end = ascension_window(season_ends_at=ends_at, window_hours=24)
    assert start == ends_at
    assert end == ends_at + timedelta(hours=24)

    assert window_state(now=ends_at - timedelta(seconds=1), season_ends_at=ends_at, window_hours=24) == PENDING
    assert window_state(now=ends_at, season_ends_at=ends_at, window_hours=24) == OPEN
    assert window_state(
        now=end - timedelta(seconds=1), season_ends_at=ends_at, window_hours=24
    ) == OPEN
    # The window is half-open: the closing instant already belongs to "closed".
    assert window_state(now=end, season_ends_at=ends_at, window_hours=24) == CLOSED
    assert window_state(
        now=end + timedelta(days=1), season_ends_at=ends_at, window_hours=24
    ) == CLOSED
    assert window_state(now=ends_at, season_ends_at=None, window_hours=24) == PENDING


def test_board_and_ending_labels() -> None:
    snapshot = {
        "ascension": [
            {"rank": 2, "anonymous_label": "乙", "score": 800, "achieved_at": "x"},
            {"rank": 1, "anonymous_label": "甲", "score": 1000, "achieved_at": "y"},
            {"rank": "bad"},
        ],
        "dao": [],
        "cooperation": "not-a-list",
    }
    rows = board_rows(snapshot, "ascension")
    assert [row.rank for row in rows] == [1, 2]
    assert rows[0].label == "甲" and rows[0].score == 1000
    assert board_rows(snapshot, "dao") == ()
    assert board_rows(snapshot, "cooperation") == ()
    assert board_rows({}, "ascension") == ()

    assert board_label("ascension") == "飞升榜"
    assert board_label("dao") == "留界榜"
    assert board_label("cooperation") == "协作榜"
    assert ending_label("ascend") == "飞升"
    assert ending_label("remain_in_world") == "留界"
    assert ending_label(None) is None


@pytest.mark.parametrize(
    "mutate, expected",
    [
        (lambda row: row.update(window_hours=0), "window_hours must be within"),
        (lambda row: row.update(window_hours=200), "window_hours must be within"),
        (lambda row: row.update(allow_assets=True), "must keep allow_assets false"),
        (lambda row: row.update(allow_assets="false"), "must keep allow_assets false"),
        (lambda row: row.update(require_frozen_season=False), "must require a frozen season"),
        (lambda row: row.update(display_boards=[]), "display_boards must be a non-empty list"),
        (lambda row: row.update(display_boards=["ascend"]), "unknown board"),
        (lambda row: row.update(display_boards=["ascension", "ascension"]), "repeats the board"),
        (lambda row: row.update(chapter_entry_keys=[]), "chapter_entry_keys must be a non-empty list"),
        (lambda row: row.update(chapter_entry_keys=["story.nope"]), "unknown chapter entry"),
        (lambda row: row.update(aliases=["   "]), "malformed alias"),
        (lambda row: row.pop("window_hours"), "missing fields"),
        (lambda row: row.update(status="locked"), "not active"),
    ],
)
def test_malformed_event_content_is_rejected(tmp_path: Path, mutate, expected: str) -> None:
    root = _copy_data(tmp_path)
    document = _document(root)
    mutate(_record(document))
    _write(root, document)

    bundle = ContentBundle.load(root)
    with pytest.raises(ContentError) as excinfo:
        ascension_day_defaults(bundle)
    assert expected in str(excinfo.value)