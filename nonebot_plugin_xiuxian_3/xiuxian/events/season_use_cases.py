"""Adapter-neutral use cases for final-heaven seasonal rankings."""

from __future__ import annotations

from ...contracts import CommandContext, CommandResult
from ..persistence.errors import (
    FinalHeavenRankingNotFinalizedError,
    FinalHeavenRewardAlreadyClaimedError,
    FinalHeavenRewardNotEligibleError,
    OperationConflictError,
    PlayerNotFoundError,
    PlayerSuspendedError,
    RepositoryBusyError,
)
from ..routine.rules import honor_title
from .season_models import FinalHeavenSeasonRecord
from .season_repository import FinalHeavenSeasonRepositoryMixin
from .season_rules import FINAL_HEAVEN_BOARDS


_BOARD_ALIASES = {
    "飞升": "ascension",
    "飞升榜": "ascension",
    "道统": "dao",
    "留界": "dao",
    "道统榜": "dao",
    "留界榜": "dao",
    "留界道统榜": "dao",
    "协作": "cooperation",
    "协作榜": "cooperation",
    "终局战": "cooperation",
    "协作终局战榜": "cooperation",
}


class FinalHeavenSeasonApplication:
    """Translate season queries and claims into shared command results."""

    def __init__(self, repository: FinalHeavenSeasonRepositoryMixin):
        self.repository = repository

    @staticmethod
    def _operation_id(context: CommandContext) -> str:
        if context.operation_id:
            return context.operation_id
        key = context.message_id or context.request_id
        return f"event.final_heaven.claim:{context.adapter}:{context.user_id}:{key}"

    @staticmethod
    def _standing_data(standing) -> dict[str, object]:
        return {
            "board_key": standing.board_key,
            "rank": standing.rank,
            "anonymous_label": standing.anonymous_label,
            "score": standing.score,
            "achieved_at": standing.achieved_at,
        }

    @classmethod
    def _season_data(cls, record: FinalHeavenSeasonRecord) -> dict[str, object]:
        return {
            "season_id": record.season_id,
            "status": record.status,
            "starts_at": record.starts_at,
            "ends_at": record.ends_at,
            "claim_expires_at": record.claim_expires_at,
            "frozen_at": record.frozen_at,
            "standings": [cls._standing_data(value) for value in record.standings],
            "personal_standings": [cls._standing_data(value) for value in record.personal_standings],
        }

    @staticmethod
    def _parse_query(args: tuple[str, ...]) -> tuple[str | None, str | None] | None:
        if len(args) > 2:
            return None
        season_id: str | None = None
        board_key: str | None = None
        for value in args:
            parsed_board = _BOARD_ALIASES.get(value)
            if parsed_board is not None and board_key is None:
                board_key = parsed_board
            elif value.startswith("season.final_heaven:") and season_id is None:
                season_id = value
            else:
                return None
        return season_id, board_key

    @staticmethod
    def _error(context: CommandContext, operation_id: str, exc: Exception) -> CommandResult:
        errors = {
            FinalHeavenRankingNotFinalizedError: (
                "FINAL_RANKING_NOT_FINALIZED",
                "本赛季尚未结束，排名奖励还没有结算。",
            ),
            FinalHeavenRewardNotEligibleError: (
                "FINAL_RANKING_NOT_ELIGIBLE",
                "该赛季没有可领取的榜单奖励。",
            ),
            FinalHeavenRewardAlreadyClaimedError: (
                "FINAL_RANKING_REWARD_CLAIMED",
                "该赛季榜单奖励已经领取。",
            ),
            PlayerNotFoundError: ("PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。"),
            PlayerSuspendedError: ("PLAYER_SUSPENDED", "当前角色暂时不能查看或领取赛季奖励。"),
            OperationConflictError: ("OPERATION_CONFLICT", "这次请求编号已经用于其他操作。"),
            RepositoryBusyError: ("PERSISTENCE_BUSY", "赛季簿暂时繁忙，请稍后再试。"),
        }
        code, message = errors.get(type(exc), ("PERSISTENCE_ERROR", "赛季簿暂时不可用，请稍后再试。"))
        return CommandResult(
            False,
            code,
            message,
            context.request_id,
            operation_id,
            retryable=isinstance(exc, RepositoryBusyError),
        )

    async def get_final_heaven_season(self, context: CommandContext) -> CommandResult:
        parsed = self._parse_query(context.command_args)
        if parsed is None:
            return CommandResult(
                False,
                "INVALID_SEASON_COMMAND",
                "请使用 `终局赛季 [榜名] [赛季编号]`。",
                context.request_id,
            )
        season_id, board_key = parsed
        try:
            record = await self.repository.get_final_heaven_season(
                platform=context.adapter,
                platform_user_id=context.user_id,
                season_id=season_id,
                board_key=board_key,
            )
        except ValueError:
            return CommandResult(False, "INVALID_SEASON_COMMAND", "赛季编号无效。", context.request_id)
        except Exception as exc:
            return self._error(context, "", exc)

        data = self._season_data(record)
        status = "已冻结" if record.status == "frozen" else "进行中"
        lines = [
            f"## 终局赛季 · {record.season_id}",
            "",
            f"**状态**：{status}",
            f"**赛季时间**：{record.starts_at} 至 {record.ends_at}",
        ]
        if record.status == "frozen":
            lines.append(f"**领奖截止**：{record.claim_expires_at}")
        by_board: dict[str, list] = {key: [] for key in FINAL_HEAVEN_BOARDS}
        for standing in record.standings:
            by_board[standing.board_key].append(standing)
        selected_boards = (board_key,) if board_key else tuple(FINAL_HEAVEN_BOARDS)
        for key in selected_boards:
            lines.extend(["", f"### {FINAL_HEAVEN_BOARDS[key]['label']}"])
            if not by_board[key]:
                lines.append("暂无入榜记录。")
            else:
                lines.extend(
                    f"{value.rank}. {value.anonymous_label} · {value.score} 分"
                    for value in by_board[key]
                )
            personal = next(
                (value for value in record.personal_standings if value.board_key == key),
                None,
            )
            if personal is not None:
                lines.append(f"你的本榜名次：第 {personal.rank} 名，{personal.score} 分。")
        if record.status == "frozen":
            lines.extend(["", "前十名可领取对应展示称号；榜首额外确认新篇章资格。"])
        return CommandResult(
            True,
            "FINAL_SEASON_RANKING",
            "\n".join(lines),
            context.request_id,
            data=data,
        )

    async def claim_final_heaven_rewards(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 1 or not context.command_args[0].startswith(
            "season.final_heaven:"
        ):
            return CommandResult(
                False,
                "INVALID_SEASON_COMMAND",
                "请使用 `领取终局赛季奖励 <赛季编号>`。",
                context.request_id,
            )
        season_id = context.command_args[0]
        operation_id = self._operation_id(context)
        try:
            record = await self.repository.claim_final_heaven_rewards(
                platform=context.adapter,
                platform_user_id=context.user_id,
                season_id=season_id,
                operation_id=operation_id,
            )
        except ValueError:
            return CommandResult(False, "INVALID_SEASON_COMMAND", "赛季编号无效。", context.request_id, operation_id)
        except Exception as exc:
            return self._error(context, operation_id, exc)
        data = {
            "season_id": record.season_id,
            "title_keys": list(record.title_keys),
            "entitlements": list(record.entitlements),
            "idempotent_replay": record.already_completed,
            "expired": record.expired,
        }
        if record.expired:
            return CommandResult(
                False,
                "FINAL_RANKING_CLAIM_EXPIRED",
                "领取窗口已经结束；展示称号已按赛季规则自动补发，新篇章资格不会自动确认。",
                context.request_id,
                operation_id,
                data=data,
            )
        title_labels = [honor_title(key).label for key in record.title_keys]
        rewards = "、".join(title_labels) if title_labels else "无展示称号"
        entitlement_text = "已确认新篇章资格" if record.entitlements else "无新篇章资格"
        return CommandResult(
            True,
            "FINAL_RANKING_REWARD_CLAIMED",
            f"## 终局赛季奖励已领取\n\n- **展示称号**：{rewards}\n- **资格**：{entitlement_text}",
            context.request_id,
            operation_id,
            data=data,
        )


__all__ = ["FinalHeavenSeasonApplication"]
