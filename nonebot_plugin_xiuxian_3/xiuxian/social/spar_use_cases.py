"""Application query for immediate, read-only player spar previews."""

from __future__ import annotations

from ...contracts import CommandContext, CommandResult
from ..combat.models import SpectatorPreviewRecord
from ..persistence.errors import (
    BattleRequirementError,
    PlayerNotFoundError,
    PlayerSuspendedError,
    RepositoryBusyError,
)
from ..utils.text import escape_markdown


class SparApplication:
    """Render a shared domain preview without persisting an interaction."""

    def __init__(self, repository):
        self.repository = repository

    @staticmethod
    def _data(record: SpectatorPreviewRecord) -> dict[str, object]:
        return {
            "status": "preview",
            "outcome": record.outcome,
            "rounds": record.rounds,
            "snapshots": dict(record.snapshots),
            "actions": [dict(action) for action in record.actions],
            "persistent": False,
        }

    @staticmethod
    def _error(context: CommandContext, exc: Exception) -> CommandResult:
        errors = {
            PlayerNotFoundError: ("PLAYER_NOT_FOUND", "没有找到目标角色。"),
            PlayerSuspendedError: ("PLAYER_SUSPENDED", "角色当前不可参与观战。"),
            BattleRequirementError: ("SPAR_REQUIREMENT_MISSING", "双方都需已踏入仙途，且不能与自己切磋。"),
            RepositoryBusyError: ("PERSISTENCE_BUSY", "演武场中人影纷乱，稍后再来。"),
        }
        for error_type, (code, message) in errors.items():
            if isinstance(exc, error_type):
                return CommandResult(
                    False,
                    code,
                    message,
                    context.request_id,
                    retryable=error_type is RepositoryBusyError,
                )
        return CommandResult(
            False,
            "SPECTATOR_UNAVAILABLE",
            "切磋暂不可观，请稍后再试。",
            context.request_id,
            retryable=True,
        )

    @staticmethod
    def _text(record: SpectatorPreviewRecord, *, title: str) -> str:
        names = {
            "player": escape_markdown(str(record.snapshots.get("player", {}).get("display_name", "修士"))),
            "enemy": escape_markdown(str(record.snapshots.get("enemy", {}).get("display_name", "对手"))),
            "challenger": escape_markdown(str(record.snapshots.get("challenger", {}).get("display_name", "修士"))),
            "defender": escape_markdown(str(record.snapshots.get("defender", {}).get("display_name", "对手"))),
        }
        outcome = {
            "challenger_won": "切磋者略胜一筹",
            "defender_won": "应战者略胜一筹",
            "won": "你胜过了训练傀儡",
            "lost": "你败给了训练傀儡",
            "draw": "双方势均力敌",
        }.get(record.outcome, "斗法已毕")
        lines = [f"## {title}", "", f"- **胜负**：{outcome}", f"- **交手合数**：{record.rounds}", "", "### 招式往来"]
        for action in record.actions:
            actor = names.get(str(action.get("actor_key", "")), "修士")
            target = names.get(str(action.get("target_key", "")), "对手")
            if not action.get("hit", int(action.get("damage", 0)) > 0):
                exchange = f"{actor} 一招落空"
            else:
                exchange = f"{actor} 招势命中 {target}，气血损去 {action['damage']}"
            lines.append(f"- 第 {action['round_no']} 合：{exchange}")
        lines.extend(("", "> 此番只为观招，不入斗法功业；随身资粮与法器皆无损。"))
        return "\n".join(lines)

    async def spar(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 1:
            return CommandResult(
                False,
                "INVALID_SPAR_COMMAND",
                "请使用 `切磋 玩家`，并填写对方道号。",
                context.request_id,
            )
        try:
            record = await self.repository.preview_player_spar(
                platform=context.adapter,
                platform_user_id=context.user_id,
                target_ref=context.command_args[0],
            )
        except Exception as exc:
            return self._error(context, exc)
        return CommandResult(
            True,
            "SPAR_SPECTATOR",
            self._text(record, title="切磋观战"),
            context.request_id,
            data=self._data(record),
        )


__all__ = ["SparApplication"]
