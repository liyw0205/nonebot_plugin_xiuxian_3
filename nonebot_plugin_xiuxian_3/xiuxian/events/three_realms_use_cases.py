"""Adapter-neutral commands for the v0.3 three-realms season."""

from __future__ import annotations

from ...contracts import CommandContext, CommandResult
from ..persistence.errors import (
    OperationConflictError,
    PlayerNotFoundError,
    PlayerSuspendedError,
    RepositoryBusyError,
    ThreeRealmsRankingNotFinalizedError,
    ThreeRealmsRewardAlreadyClaimedError,
    ThreeRealmsRewardExpiredError,
    ThreeRealmsRewardNotEligibleError,
)
from .three_realms_models import ThreeRealmsSeasonRecord
from .three_realms_repository import ThreeRealmsSeasonRepositoryMixin
from .three_realms_rules import BOARDS


_BOARD_ALIASES = {
    "阵营": "faction_merit",
    "阵营功勋": "faction_merit",
    "阵营榜": "faction_merit",
    "多人": "party_contribution",
    "多人贡献": "party_contribution",
    "多人副本": "party_contribution",
    "多人副本贡献": "party_contribution",
    "宗门": "sect_contribution",
    "宗门贡献": "sect_contribution",
    "宗门榜": "sect_contribution",
}


class ThreeRealmsSeasonApplication:
    """Translate season queries and claims into transport-neutral results."""

    def __init__(self, repository: ThreeRealmsSeasonRepositoryMixin):
        self.repository = repository

    @staticmethod
    def _operation_id(context: CommandContext) -> str:
        if context.operation_id:
            return context.operation_id
        key = context.message_id or context.request_id
        return f"event.three_realms.claim:{context.adapter}:{context.user_id}:{key}"

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
            elif value.startswith("season.three_realms:") and season_id is None:
                season_id = value
            else:
                return None
        return season_id, board_key

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
    def _season_data(cls, record: ThreeRealmsSeasonRecord) -> dict[str, object]:
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
    def _error(context: CommandContext, operation_id: str, exc: Exception) -> CommandResult:
        errors = {
            ThreeRealmsRankingNotFinalizedError: (
                "THREE_REALMS_RANKING_NOT_FINALIZED",
                "本赛季尚未结束，三界排名奖励还没有结算。",
            ),
            ThreeRealmsRewardNotEligibleError: (
                "THREE_REALMS_REWARD_NOT_ELIGIBLE",
                "该赛季没有可领取的三界榜单奖励。",
            ),
            ThreeRealmsRewardAlreadyClaimedError: (
                "THREE_REALMS_REWARD_ALREADY_CLAIMED",
                "该赛季三界榜单奖励已经领取。",
            ),
            ThreeRealmsRewardExpiredError: (
                "THREE_REALMS_REWARD_EXPIRED",
                "三界赛季领奖窗口已经结束。",
            ),
            PlayerNotFoundError: ("PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。"),
            PlayerSuspendedError: ("PLAYER_SUSPENDED", "当前角色暂时不能查看或领取三界赛季奖励。"),
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

    async def get_three_realms_season(self, context: CommandContext) -> CommandResult:
        parsed = self._parse_query(context.command_args)
        if parsed is None:
            return CommandResult(False, "INVALID_SEASON_COMMAND", "请使用 `三界赛季 [榜名] [赛季编号]`。", context.request_id)
        season_id, board_key = parsed
        try:
            record = await self.repository.get_three_realms_season(
                platform=context.adapter,
                platform_user_id=context.user_id,
                season_id=season_id,
                board_key=board_key,
            )
        except ValueError:
            return CommandResult(False, "INVALID_SEASON_COMMAND", "赛季编号无效。", context.request_id)
        except Exception as exc:
            return self._error(context, "", exc)

        status = "已冻结" if record.status == "frozen" else "进行中"
        lines = [
            f"## 三界赛季 · {record.season_id}",
            "",
            f"**状态**：{status}",
            f"**赛季时间**：{record.starts_at} 至 {record.ends_at}",
        ]
        if record.status == "frozen":
            lines.append(f"**领奖截止**：{record.claim_expires_at}")
        selected_boards = (board_key,) if board_key else tuple(BOARDS)
        by_board: dict[str, list] = {key: [] for key in selected_boards}
        for standing in record.standings:
            if standing.board_key in by_board:
                by_board[standing.board_key].append(standing)
        for key in selected_boards:
            lines.extend(["", f"### {BOARDS[key]['label']}"])
            if not by_board[key]:
                lines.append("暂无入榜记录。")
            else:
                lines.extend(f"{value.rank}. {value.anonymous_label} · {value.score} 分" for value in by_board[key])
            personal = next((value for value in record.personal_standings if value.board_key == key), None)
            if personal is not None:
                lines.append(f"你的本榜名次：第 {personal.rank} 名，{personal.score} 分。")
        if record.status == "frozen":
            lines.extend(["", "前 100 名可领取对应赛季奖励；多榜入榜奖励会叠加。"])
        return CommandResult(
            True,
            "THREE_REALMS_SEASON_RANKING",
            "\n".join(lines),
            context.request_id,
            data=self._season_data(record),
        )

    async def claim_three_realms_rewards(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 1 or not context.command_args[0].startswith("season.three_realms:"):
            return CommandResult(False, "INVALID_SEASON_COMMAND", "请使用 `领取三界赛季奖励 <赛季编号>`。", context.request_id)
        season_id = context.command_args[0]
        operation_id = self._operation_id(context)
        try:
            record = await self.repository.claim_three_realms_rewards(
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
            "rewards": dict(record.rewards),
            "boards": list(record.boards),
            "idempotent_replay": record.already_completed,
            "expired": record.expired,
        }
        if record.expired:
            return CommandResult(False, "THREE_REALMS_REWARD_EXPIRED", "三界赛季领奖窗口已经结束。", context.request_id, operation_id, data=data)
        soul_crystal = record.rewards.get("item.soul_crystal", 0)
        world_merit = record.rewards.get("world_merit", 0)
        return CommandResult(
            True,
            "THREE_REALMS_REWARD_CLAIMED",
            f"## 三界赛季奖励已领取\n\n- **神魂晶**：{soul_crystal}\n- **世界功勋**：{world_merit}\n- **入榜**：{'、'.join(record.boards)}",
            context.request_id,
            operation_id,
            data=data,
        )


__all__ = ["ThreeRealmsSeasonApplication"]
