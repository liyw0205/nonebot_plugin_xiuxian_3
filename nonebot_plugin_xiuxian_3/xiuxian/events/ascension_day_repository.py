"""Read-only projection for 飞升日 (``event.ascension_day``).

The event never writes: it reads the most recently frozen final-heaven season,
the player's own recorded ending and the frozen board snapshot, then projects
the display window.  Reads use ``writable=False`` so a suspended or read-only
identity still gets the display, and no `operations` row is created.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any

from ..content import ContentBundle, bundled_content
from .ascension_day_models import (
    AscensionBoard,
    AscensionBoardRow,
    AscensionChapterEntry,
    AscensionDayRecord,
)
from .ascension_day_rules import (
    OPEN,
    PENDING,
    ascension_day_definition,
    board_label,
    board_rows,
    ending_label,
    parse_instant,
    window_state,
)


class AscensionDayRepositoryMixin:
    """Persistence read path for the ascension day display."""

    def _ascension_day_content(self) -> ContentBundle:
        content = getattr(self, "content", None)
        return content if content is not None else bundled_content()

    async def ascension_day_overview(
        self, *, platform: str, platform_user_id: str
    ) -> AscensionDayRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._ascension_day_once, platform, platform_user_id
            )

    def _ascension_day_once(self, platform: str, platform_user_id: str) -> AscensionDayRecord:
        content = self._ascension_day_content()
        definition = ascension_day_definition(content)
        now = self._now()
        with self._connect() as connection:
            row = self._require_player(connection, platform, platform_user_id, writable=False)
            season = connection.execute(
                "SELECT * FROM final_heaven_seasons WHERE status = 'frozen' "
                "ORDER BY ends_at DESC LIMIT 1"
            ).fetchone()
            if season is None:
                return AscensionDayRecord(
                    state=PENDING,
                    season_id="",
                    season_ends_at="",
                    starts_at="",
                    ends_at="",
                    definition_name=definition.name,
                    ending_key=None,
                    ending_label=None,
                    chapters=self._ascension_day_chapters(connection, content, definition),
                )

            season_ends_at = parse_instant(str(season["ends_at"]))
            state = window_state(
                now=now,
                season_ends_at=season_ends_at,
                window_hours=definition.window_hours,
            )
            ending = connection.execute(
                "SELECT ending_key FROM endgame_endings WHERE player_id = ?",
                (int(row["id"]),),
            ).fetchone()
            ending_key = str(ending["ending_key"]) if ending is not None else None
            boards: tuple[AscensionBoard, ...] = ()
            # Only the open window publishes the boards; before it opens and
            # after it closes the page shows the state alone.
            if state == OPEN:
                snapshot = json.loads(str(season["snapshot_json"]) or "{}")
                raw_boards = snapshot.get("boards") if isinstance(snapshot, dict) else None
                boards = tuple(
                    AscensionBoard(
                        board_key=board_key,
                        label=board_label(board_key),
                        rows=board_rows(
                            raw_boards if isinstance(raw_boards, dict) else {},
                            board_key,
                        ),
                    )
                    for board_key in definition.display_boards
                )
            return AscensionDayRecord(
                state=state,
                season_id=str(season["season_id"]),
                season_ends_at=str(season["ends_at"]),
                starts_at=str(season["ends_at"]),
                ends_at=str(season["claim_expires_at"]),
                definition_name=definition.name,
                ending_key=ending_key,
                ending_label=ending_label(ending_key),
                boards=boards,
                chapters=self._ascension_day_chapters(connection, content, definition),
            )

    def _ascension_day_chapters(
        self,
        connection: Any,
        content: ContentBundle,
        definition,
    ) -> tuple[AscensionChapterEntry, ...]:
        entries: list[AscensionChapterEntry] = []
        for key in definition.chapter_entry_keys:
            record = content.get("mainline", key, include_locked=False)
            label = str(record.get("name") or key) if record is not None else key
            entries.append(AscensionChapterEntry(key=key, label=label))
        return tuple(entries)