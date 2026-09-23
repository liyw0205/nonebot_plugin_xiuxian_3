"""Adapter-neutral application commands for world events."""

from __future__ import annotations

from ...contracts import CommandContext, CommandResult
from ..persistence.errors import (
    EventContributionInsufficientError,
    EventNotActiveError,
    EventRewardAlreadyClaimedError,
    EventRewardExpiredError,
    OperationConflictError,
    PlayerNotFoundError,
    PlayerSuspendedError,
    RepositoryBusyError,
)
from .repository import EventsRepositoryMixin


class EventsApplication:
    """Translate world-event state transitions into shared command results."""

    def __init__(self, repository: EventsRepositoryMixin):
        self.repository = repository

    @staticmethod
    def _operation_id(context: CommandContext, name: str) -> str:
        if context.operation_id:
            return context.operation_id
        key = context.message_id or context.request_id
        return f"{name}:{context.adapter}:{context.user_id}:{key}"

    @staticmethod
    def _round_id(args: tuple[str, ...]) -> str | None:
        if not args:
            return None
        if len(args) == 1 and args[0].isdigit() and len(args[0]) == 8:
            return args[0]
        return ""

    @staticmethod
    def _data(record) -> dict[str, object]:
        return {
            "round_id": record.round_id,
            "event_key": record.event_key,
            "status": record.status,
            "starts_at": record.starts_at,
            "ends_at": record.ends_at,
            "claim_expires_at": record.claim_expires_at,
            "target_quantity": record.target_quantity,
            "total_contribution": record.total_contribution,
            "player_contribution": record.player_contribution,
            "success": record.success,
            "reward": record.reward,
            "idempotent_replay": record.already_completed,
        }

    @staticmethod
    def _error(context: CommandContext, operation_id: str, exc: Exception) -> CommandResult:
        errors = {
            EventNotActiveError: ("EVENT_NOT_ACTIVE", "当前没有可参与或可领奖的灵泉事件。"),
            EventContributionInsufficientError: ("EVENT_CONTRIBUTION_INSUFFICIENT", "本轮灵泉事件贡献不足 10 份灵叶。"),
            EventRewardAlreadyClaimedError: ("EVENT_REWARD_ALREADY_CLAIMED", "本轮灵泉事件奖励已经领取。"),
            EventRewardExpiredError: ("EVENT_REWARD_EXPIRED", "灵泉事件领奖窗口已经结束。"),
            PlayerNotFoundError: ("PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。"),
            PlayerSuspendedError: ("PLAYER_SUSPENDED", "当前角色暂时不能操作活动。"),
            OperationConflictError: ("OPERATION_CONFLICT", "这次请求编号已经用于其他活动操作。"),
            RepositoryBusyError: ("PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。"),
        }
        code, message = errors.get(type(exc), ("PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。"))
        return CommandResult(
            False,
            code,
            message,
            context.request_id,
            operation_id,
            retryable=isinstance(exc, RepositoryBusyError),
        )

    async def get_spirit_spring_event(self, context: CommandContext) -> CommandResult:
        round_id = self._round_id(context.command_args)
        if round_id == "":
            return CommandResult(False, "INVALID_EVENT_COMMAND", "请使用 `灵泉事件 [轮次]`。", context.request_id)
        try:
            record = await self.repository.get_spirit_spring_event(
                platform=context.adapter,
                platform_user_id=context.user_id,
                round_id=round_id,
            )
        except Exception as exc:
            return self._error(context, "", exc)
        state = {
            "open": "进行中",
            "running": "进行中",
            "settled": "已结算",
            "failed": "已结束",
        }.get(record.status, record.status)
        success_text = "全服目标已达成" if record.success else "全服目标尚未达成"
        return CommandResult(
            True,
            "EVENT_STATUS",
            (
                "## 灵泉事件\n\n"
                f"**轮次**：`{record.round_id}`\n"
                f"**状态**：{state}\n"
                f"**全服进度**：{record.total_contribution}/{record.target_quantity}\n"
                f"**你的贡献**：{record.player_contribution}/30 份灵叶\n"
                f"**时间**：{record.starts_at} 至 {record.ends_at}\n\n"
                f"> {success_text}；达到 10 份贡献后可在结束后领取奖励。"
            ),
            context.request_id,
            data=self._data(record),
        )

    async def claim_spirit_spring_event(self, context: CommandContext) -> CommandResult:
        round_id = self._round_id(context.command_args)
        if round_id == "":
            return CommandResult(False, "INVALID_EVENT_COMMAND", "请使用 `领取灵泉事件奖励 [轮次]`。", context.request_id)
        operation_id = self._operation_id(context, "event.claim_reward")
        try:
            record = await self.repository.claim_spirit_spring_event(
                platform=context.adapter,
                platform_user_id=context.user_id,
                round_id=round_id,
                operation_id=operation_id,
            )
        except Exception as exc:
            return self._error(context, operation_id, exc)
        reward_lines = [
            f"境内修为 +{record.reward.get('cultivation', 0)}",
            f"灵石 +{record.reward.get('spirit_stones', 0)}",
        ]
        if record.reward.get("faction_reputation.xuantian", 0):
            reward_lines.append("玄天界阵营声望 +10")
        return CommandResult(
            True,
            "EVENT_REWARD_CLAIMED",
            f"## 灵泉事件奖励已领取\n\n本轮贡献 {record.player_contribution} 份灵叶。\n\n- " + "\n- ".join(reward_lines),
            context.request_id,
            operation_id,
            data=self._data(record),
        )


__all__ = ["EventsApplication"]
