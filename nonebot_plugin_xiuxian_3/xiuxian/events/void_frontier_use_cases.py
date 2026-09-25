"""Adapter-neutral application commands for the v0.5 void frontier."""

from __future__ import annotations

from ...contracts import CommandContext, CommandResult
from ..persistence.errors import (
    OperationConflictError,
    PlayerNotFoundError,
    PlayerSuspendedError,
    RepositoryBusyError,
    VoidFrontierRewardAlreadyClaimedError,
    VoidFrontierRewardExpiredError,
    VoidFrontierRewardNotEligibleError,
    VoidFrontierSeasonNotFinalizedError,
    VoidFrontierWeeklyNotAvailableError,
)
from .void_frontier_models import VoidFrontierSeasonRecord
from .void_frontier_repository import VoidFrontierRepositoryMixin


class VoidFrontierApplication:
    """Expose one shared season contract to QQ and OneBot V11."""

    def __init__(self, repository: VoidFrontierRepositoryMixin):
        self.repository = repository

    @staticmethod
    def _operation_id(context: CommandContext, name: str) -> str:
        if context.operation_id:
            return context.operation_id
        key = context.message_id or context.request_id
        return f"event.void_frontier.{name}:{context.adapter}:{context.user_id}:{key}"

    @staticmethod
    def _error(context: CommandContext, operation_id: str, exc: Exception) -> CommandResult:
        errors = {
            VoidFrontierSeasonNotFinalizedError: ("VOID_FRONTIER_SEASON_NOT_FINALIZED", "虚空前线赛季尚未结束，排名还没有冻结。"),
            VoidFrontierRewardNotEligibleError: ("VOID_FRONTIER_REWARD_NOT_ELIGIBLE", "你不在本赛季虚空前线前 100 名。"),
            VoidFrontierRewardAlreadyClaimedError: ("VOID_FRONTIER_REWARD_ALREADY_CLAIMED", "本赛季虚空前线奖励已经领取。"),
            VoidFrontierRewardExpiredError: ("VOID_FRONTIER_REWARD_EXPIRED", "虚空前线赛季领奖窗口已经结束。"),
            VoidFrontierWeeklyNotAvailableError: ("VOID_FRONTIER_WEEKLY_NOT_AVAILABLE", "当前没有可领取的虚空前线周任务奖励。"),
            PlayerNotFoundError: ("PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。"),
            PlayerSuspendedError: ("PLAYER_SUSPENDED", "当前角色暂时不能查看或领取虚空前线奖励。"),
            OperationConflictError: ("OPERATION_CONFLICT", "这次请求编号已经用于其他虚空前线操作。"),
            RepositoryBusyError: ("PERSISTENCE_BUSY", "虚空前线簿暂时繁忙，请稍后再试。"),
        }
        code, message = errors.get(type(exc), ("PERSISTENCE_ERROR", "虚空前线簿暂时不可用，请稍后再试。"))
        return CommandResult(False, code, message, context.request_id, operation_id, retryable=isinstance(exc, RepositoryBusyError))

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
    def _season_data(cls, record: VoidFrontierSeasonRecord) -> dict[str, object]:
        return {
            "season_id": record.season_id,
            "status": record.status,
            "starts_at": record.starts_at,
            "ends_at": record.ends_at,
            "claim_expires_at": record.claim_expires_at,
            "frozen_at": record.frozen_at,
            "standings": [cls._standing_data(item) for item in record.standings],
            "personal_standings": [cls._standing_data(item) for item in record.personal_standings],
            "sect_standings": [cls._standing_data(item) for item in record.sect_standings],
            "market_priorities": [cls._standing_data(item) for item in record.market_priorities],
            "weekly_pending": record.weekly_pending,
            "weekly_claimed": record.weekly_claimed,
        }

    async def get_void_frontier_season(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) > 1:
            return CommandResult(False, "INVALID_VOID_FRONTIER_COMMAND", "请使用 `虚空前线 [赛季编号]`。", context.request_id)
        season_id = context.command_args[0] if context.command_args else None
        if season_id is not None and not season_id.startswith("season.void_frontier:"):
            return CommandResult(False, "INVALID_VOID_FRONTIER_COMMAND", "赛季编号无效。", context.request_id)
        try:
            record = await self.repository.get_void_frontier_season(platform=context.adapter, platform_user_id=context.user_id, season_id=season_id)
        except ValueError:
            return CommandResult(False, "INVALID_VOID_FRONTIER_COMMAND", "赛季编号无效。", context.request_id)
        except Exception as exc:
            return self._error(context, "", exc)
        status = "已冻结" if record.status == "frozen" else "进行中"
        lines = [
            f"## 虚空前线 · `{record.season_id}`",
            "",
            f"**状态**：{status}",
            f"**赛季时间**：{record.starts_at} 至 {record.ends_at}",
            f"**周任务箱**：待领取 {record.weekly_pending}，已领取 {record.weekly_claimed}",
        ]
        if record.status == "frozen":
            lines.append(f"**领奖截止**：{record.claim_expires_at}")
        lines.extend(["", "### 玩家榜（匿名）"])
        lines.extend(f"{item.rank}. {item.anonymous_label} · {item.score} 分" for item in record.standings if item.board_key == "player_score")
        if not any(item.board_key == "player_score" for item in record.standings):
            lines.append("暂无入榜记录。")
        lines.extend(["", "### 宗门榜（匿名）"])
        lines.extend(f"{item.rank}. {item.anonymous_label} · {item.score} 分" for item in record.sect_standings[:3])
        if record.personal_standings:
            personal = record.personal_standings[0]
            lines.append(f"\n你的玩家榜名次：第 {personal.rank} 名，{personal.score} 分。")
        return CommandResult(True, "VOID_FRONTIER_SEASON_RANKING", "\n".join(lines), context.request_id, data=self._season_data(record))

    async def claim_void_frontier_weekly(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) > 1:
            return CommandResult(False, "INVALID_VOID_FRONTIER_COMMAND", "请使用 `领取虚空前线周任务 [周次]`。", context.request_id)
        requested_week = context.command_args[0] if context.command_args else None
        operation_id = self._operation_id(context, "weekly")
        try:
            record = await self.repository.claim_void_frontier_weekly(
                platform=context.adapter,
                platform_user_id=context.user_id,
                operation_id=operation_id,
                week_id_value=requested_week,
            )
        except Exception as exc:
            return self._error(context, operation_id, exc)
        reward_text = "、".join(f"{key} ×{value}" for key, value in record.reward.items())
        return CommandResult(
            True,
            "VOID_FRONTIER_WEEKLY_CLAIMED",
            f"## 虚空前线周任务奖励已领取\n\n- **周次**：{record.week_id}\n- **奖励**：{reward_text}",
            context.request_id,
            operation_id,
            data={"week_id": record.week_id, "season_id": record.season_id, "reward": record.reward, "source_key": record.source_key, "idempotent_replay": record.already_completed},
        )

    async def claim_void_frontier_reward(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 1 or not context.command_args[0].startswith("season.void_frontier:"):
            return CommandResult(False, "INVALID_VOID_FRONTIER_COMMAND", "请使用 `领取虚空前线奖励 <赛季编号>`。", context.request_id)
        season_id = context.command_args[0]
        operation_id = self._operation_id(context, "season_claim")
        try:
            record = await self.repository.claim_void_frontier_reward(
                platform=context.adapter,
                platform_user_id=context.user_id,
                season_id=season_id,
                operation_id=operation_id,
            )
        except ValueError:
            return CommandResult(False, "INVALID_VOID_FRONTIER_COMMAND", "赛季编号无效。", context.request_id, operation_id)
        except Exception as exc:
            return self._error(context, operation_id, exc)
        reward_text = "、".join(f"{key} ×{value}" for key, value in record.rewards.items())
        return CommandResult(
            True,
            "VOID_FRONTIER_REWARD_CLAIMED",
            f"## 虚空前线赛季奖励已领取\n\n- **名次**：第 {record.rank} 名\n- **奖励**：{reward_text}",
            context.request_id,
            operation_id,
            data={"season_id": record.season_id, "rank": record.rank, "rewards": record.rewards, "idempotent_replay": record.already_completed},
        )


__all__ = ["VoidFrontierApplication"]
