"""Application command for 飞升日 (``event.ascension_day``).

Display only: the command has no write path, no operation id and no assets.
Outside the window it still answers with a readable state rather than an error
stack, because a closed window is normal, not a failure.
"""

from __future__ import annotations

from ...contracts import CommandContext, CommandResult
from ..content import ContentBundle, bundled_content
from ..repository import (
    PlayerNotFoundError,
    RepositoryBusyError,
    SQLitePlayerRepository,
)
from ..utils.text import command_link
from .ascension_day_rules import CLOSED, OPEN, PENDING

COMMAND = "飞升日"


class AscensionDayApplication:
    """Translate the ascension-day projection into an adapter-neutral result."""

    def __init__(self, repository: SQLitePlayerRepository):
        self.repository = repository

    def _content(self) -> ContentBundle:
        content = getattr(self.repository, "content", None)
        return content if content is not None else bundled_content()

    def _lines(self, record) -> list[str]:
        lines = [f"## {record.definition_name}", ""]
        if record.state == PENDING and not record.season_id:
            lines.append("> 尚无已落幕的赛季，飞升日未至。")
            lines.append("")
            lines.append("**新篇章**")
            for chapter in record.chapters:
                lines.append(f"- {chapter.label}")
            return lines

        lines.append(f"- **赛季**：{record.season_id}")
        lines.append(f"- **落幕**：{record.season_ends_at}")
        if record.state == PENDING:
            lines.append("- **状态**：尚未开始")
        elif record.state == CLOSED:
            lines.append(f"- **状态**：已结束（窗口止于 {record.ends_at}）")
        else:
            lines.append(f"- **状态**：开放中（止于 {record.ends_at}）")
        if record.ending_label:
            lines.append(f"- **你的结局**：{record.ending_label}")

        if record.state != PENDING and record.boards:
            lines.append("")
            for board in record.boards:
                lines.append(f"**{board.label}**")
                if not board.rows:
                    lines.append("- 本届无记录")
                    continue
                for row in board.rows:
                    lines.append(f"- 第 {row.rank} 名 · {row.label} · {row.score}")
        lines.append("")
        lines.append("**新篇章**")
        for chapter in record.chapters:
            lines.append(f"- {command_link(chapter.label, '主线道途')}")
        return lines

    async def preview(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(
                False, "INVALID_ASCENSION_DAY_COMMAND", "飞升日不带参数。", context.request_id
            )
        try:
            record = await self.repository.ascension_day_overview(
                platform=context.adapter, platform_user_id=context.user_id
            )
        except PlayerNotFoundError:
            return CommandResult(
                False, "PLAYER_NOT_FOUND", "尚未登记，先发送“开始修仙”。", context.request_id
            )
        except RepositoryBusyError:
            return CommandResult(
                False, "REPOSITORY_BUSY", "仓储繁忙，请稍后再试。", context.request_id, retryable=True
            )
        if record.state == PENDING and not record.season_id:
            code = "ASCENSION_DAY_NO_SEASON"
        elif record.state == OPEN:
            code = "ASCENSION_DAY_OPEN"
        elif record.state == CLOSED:
            code = "ASCENSION_DAY_CLOSED"
        else:
            code = "ASCENSION_DAY_PENDING"
        return CommandResult(
            True,
            code,
            "\n".join(self._lines(record)),
            context.request_id,
            data={
                "state": record.state,
                "season_id": record.season_id,
                "season_ends_at": record.season_ends_at,
                "starts_at": record.starts_at,
                "ends_at": record.ends_at,
                "ending_key": record.ending_key,
                "boards": [
                    {
                        "board_key": board.board_key,
                        "rows": [
                            {"rank": row.rank, "label": row.label, "score": row.score}
                            for row in board.rows
                        ],
                    }
                    for board in record.boards
                ],
                "chapters": [chapter.key for chapter in record.chapters],
            },
        )