"""Content-backed contract for 飞升日 (``event.ascension_day``).

Events v0.6 froze the row as display-only: twenty-four hours after a season
closes it shows the recorded endings, the three boards and the new-chapter
entries, and it must never write assets again.  The loader therefore rejects
any content that would turn the event writable, and every reference it accepts
must already exist.
"""

from __future__ import annotations

from typing import Any

from ..content import ContentBundle, ContentError, bundled_content

KIND = "ascension_day"
DEFAULTS_KEY = "event.ascension_day.defaults"
# The three boards the final-heaven season actually publishes.
BOARD_KEYS = {"ascension", "dao", "cooperation"}
REQUIRED_FIELDS = {
    "key",
    "name",
    "desc",
    "status",
    "window_hours",
    "display_boards",
    "chapter_entry_keys",
    "require_frozen_season",
    "allow_assets",
}


def _bundle(content: ContentBundle | None) -> ContentBundle:
    return content if content is not None else bundled_content()


def _text(row: dict[str, Any], field: str, key: str) -> str:
    value = row.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ContentError(f"ascension day {key} requires a {field}")
    return value.strip()


def ascension_day_defaults(content: ContentBundle | None = None) -> dict[str, Any]:
    """Return the validated ascension-day parameters."""

    bundle = _bundle(content)
    try:
        row = bundle.require(KIND, DEFAULTS_KEY, include_locked=True)
    except KeyError as exc:
        raise ContentError(f"missing ascension_day content: {DEFAULTS_KEY}") from exc
    if row.get("status") != "active":
        raise ContentError(f"{DEFAULTS_KEY} is not active")
    missing = REQUIRED_FIELDS - set(row)
    if missing:
        raise ContentError(f"ascension day {DEFAULTS_KEY} is missing fields: {sorted(missing)}")

    window_hours = row.get("window_hours")
    if isinstance(window_hours, bool) or not isinstance(window_hours, int) or not 1 <= window_hours <= 168:
        raise ContentError(f"ascension day {DEFAULTS_KEY} window_hours must be within 1-168")

    # A display-only event that claims it may touch assets is a contract bug,
    # not a tunable, so it fails the build instead of being honoured.
    if row.get("allow_assets") is not False:
        raise ContentError(f"ascension day {DEFAULTS_KEY} must keep allow_assets false")
    if row.get("require_frozen_season") is not True:
        raise ContentError(f"ascension day {DEFAULTS_KEY} must require a frozen season")

    boards = row.get("display_boards")
    if not isinstance(boards, list) or not boards:
        raise ContentError(f"ascension day {DEFAULTS_KEY} display_boards must be a non-empty list")
    normalised_boards: list[str] = []
    for board in boards:
        if not isinstance(board, str) or board not in BOARD_KEYS:
            raise ContentError(f"ascension day {DEFAULTS_KEY} has an unknown board: {board!r}")
        if board in normalised_boards:
            raise ContentError(f"ascension day {DEFAULTS_KEY} repeats the board {board!r}")
        normalised_boards.append(board)

    entries = row.get("chapter_entry_keys")
    if not isinstance(entries, list) or not entries:
        raise ContentError(
            f"ascension day {DEFAULTS_KEY} chapter_entry_keys must be a non-empty list"
        )
    normalised_entries: list[str] = []
    for entry in entries:
        if not isinstance(entry, str) or not entry.strip():
            raise ContentError(f"ascension day {DEFAULTS_KEY} has a malformed chapter entry")
        if bundle.get("mainline", entry, include_locked=False) is None:
            raise ContentError(
                f"ascension day {DEFAULTS_KEY} references an unknown chapter entry: {entry!r}"
            )
        if entry in normalised_entries:
            raise ContentError(f"ascension day {DEFAULTS_KEY} repeats the entry {entry!r}")
        normalised_entries.append(entry)

    return {
        "key": DEFAULTS_KEY,
        "name": _text(row, "name", DEFAULTS_KEY),
        "description": _text(row, "desc", DEFAULTS_KEY),
        "aliases": _aliases(row, DEFAULTS_KEY),
        "window_hours": int(window_hours),
        "display_boards": tuple(normalised_boards),
        "chapter_entry_keys": tuple(normalised_entries),
        "require_frozen_season": True,
        "allow_assets": False,
    }


def _aliases(row: dict[str, Any], key: str) -> tuple[str, ...]:
    names = [_text(row, "name", key)]
    raw = row.get("aliases", [])
    if not isinstance(raw, list):
        raise ContentError(f"ascension day {key} aliases must be a list")
    for alias in raw:
        if not isinstance(alias, str) or not alias.strip():
            raise ContentError(f"ascension day {key} has a malformed alias")
        names.append(alias.strip())
    return tuple(names)