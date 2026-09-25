"""Adapter-neutral application commands for world events."""

from __future__ import annotations

from ...contracts import CommandContext, CommandResult
from ..persistence.errors import (
    EventContributionInsufficientError,
    EventNotActiveError,
    EventRewardAlreadyClaimedError,
    EventRewardExpiredError,
    EventSourceNotEligibleError,
    OperationConflictError,
    PlayerNotFoundError,
    PlayerSuspendedError,
    RepositoryBusyError,
)
from .repository import EventsRepositoryMixin
from .demon_rules import DEMON_ACTION_VALUES
from .cross_realm_rules import BEAST_TRADE_EVENT_KEY, BOUNDARY_RIFT_EVENT_KEY


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
    def _error(
        context: CommandContext,
        operation_id: str,
        exc: Exception,
        *,
        event_label: str = "灵泉",
    ) -> CommandResult:
        contribution_message = (
            "本轮灵泉事件贡献不足 10 份灵叶。"
            if event_label == "灵泉"
            else f"本轮{event_label}事件贡献不足领取门槛。"
        )
        errors = {
            EventNotActiveError: ("EVENT_NOT_ACTIVE", f"当前没有可参与或可领奖的{event_label}事件。"),
            EventContributionInsufficientError: ("EVENT_CONTRIBUTION_INSUFFICIENT", contribution_message),
            EventRewardAlreadyClaimedError: ("EVENT_REWARD_ALREADY_CLAIMED", f"本轮{event_label}事件奖励已经领取。"),
            EventRewardExpiredError: ("EVENT_REWARD_EXPIRED", f"{event_label}事件领奖窗口已经结束。"),
            EventSourceNotEligibleError: ("EVENT_CONTRIBUTION_SOURCE_INVALID", "没有可核验的已结算战斗、运输或维修记录。"),
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

    async def get_heart_demon_event(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) > 1:
            return CommandResult(False, "INVALID_EVENT_COMMAND", "请使用 `心魔事件 [事件编号]`。", context.request_id)
        event_id = context.command_args[0] if context.command_args else None
        try:
            record = await self.repository.get_heart_demon_event(
                platform=context.adapter,
                platform_user_id=context.user_id,
                event_id=event_id,
            )
        except EventNotActiveError:
            return CommandResult(False, "HEART_DEMON_NOT_FOUND", "当前没有心魔事件记录。", context.request_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能查看心魔事件。", context.request_id)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, retryable=True)
        state = "待处理" if record.status == "pending" else "已结算"
        choice = record.choice_key or "待选择"
        return CommandResult(
            True,
            "HEART_DEMON_EVENT_STATUS",
            (
                "## 心魔试炼\n\n"
                f"**事件**：`{record.event_id}`\n"
                f"**状态**：{state}\n"
                f"**突破来源**：`{record.breakthrough_operation_id}`\n"
                f"**有效期**：{record.starts_at} 至 {record.expires_at}\n"
                f"**处理方式**：{choice}\n\n"
                "> 逾期未选择将自动按 `heart_demon.face` 结算；该事件不进入公共排行。"
            ),
            context.request_id,
            data={
                "event_id": record.event_id,
                "event_key": record.event_key,
                "status": record.status,
                "breakthrough_session_id": record.breakthrough_session_id,
                "breakthrough_operation_id": record.breakthrough_operation_id,
                "starts_at": record.starts_at,
                "expires_at": record.expires_at,
                "choice_key": record.choice_key,
                "resolved_at": record.resolved_at,
                "snapshot": record.snapshot,
                "result": record.result,
            },
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

    @staticmethod
    def _demon_round_id(args: tuple[str, ...]) -> str | None:
        if not args:
            return None
        return args[0] if len(args) == 1 else ""

    async def get_demon_invasion_event(self, context: CommandContext) -> CommandResult:
        round_id = self._demon_round_id(context.command_args)
        if round_id == "":
            return CommandResult(False, "INVALID_EVENT_COMMAND", "请使用 `魔界入侵 [轮次]`。", context.request_id)
        try:
            record = await self.repository.get_demon_invasion_event(
                platform=context.adapter,
                platform_user_id=context.user_id,
                round_id=round_id,
            )
        except Exception as exc:
            return self._error(context, "", exc, event_label="魔界入侵")
        state = {"open": "进行中", "running": "进行中", "settled": "已结算", "failed": "已结束"}.get(record.status, record.status)
        return CommandResult(
            True,
            "EVENT_STATUS",
            (
                "## 魔界入侵\n\n"
                f"**轮次**：`{record.round_id}`\n"
                f"**状态**：{state}\n"
                f"**全服贡献**：{record.total_contribution}/{record.target_quantity}\n"
                f"**你的贡献**：{record.player_contribution}/50\n"
                f"**时间**：{record.starts_at} 至 {record.ends_at}\n\n"
                "> 贡献来源必须是服务器已结算的战斗、运输或维修 operation。"
            ),
            context.request_id,
            data=self._data(record),
        )

    async def contribute_demon_invasion(self, context: CommandContext) -> CommandResult:
        if not context.command_args or len(context.command_args) > 2:
            return CommandResult(False, "INVALID_EVENT_COMMAND", "请使用 `贡献魔界战场 战斗|运输|维修 [来源operation]`。", context.request_id)
        action_key = DEMON_ACTION_VALUES.get(context.command_args[0])
        if action_key is None:
            return CommandResult(False, "INVALID_EVENT_COMMAND", "贡献类型只能是战斗、运输或维修。", context.request_id)
        source_operation_id = context.command_args[1] if len(context.command_args) == 2 else None
        operation_id = self._operation_id(context, "event.demon_invasion.contribute")
        try:
            record = await self.repository.record_demon_invasion_contribution(
                platform=context.adapter,
                platform_user_id=context.user_id,
                action_key=action_key,
                source_operation_id=source_operation_id,
                operation_id=operation_id,
            )
        except Exception as exc:
            return self._error(context, operation_id, exc, event_label="魔界入侵")
        return CommandResult(
            True,
            "EVENT_CONTRIBUTION_RECORDED",
            f"## 魔界战场贡献已记录\n\n- **本轮贡献**：{record.player_contribution}\n- **全服贡献**：{record.total_contribution}/{record.target_quantity}",
            context.request_id,
            operation_id,
            data=self._data(record),
        )

    async def claim_demon_invasion_event(self, context: CommandContext) -> CommandResult:
        round_id = self._demon_round_id(context.command_args)
        if round_id == "":
            return CommandResult(False, "INVALID_EVENT_COMMAND", "请使用 `领取魔界入侵奖励 [轮次]`。", context.request_id)
        operation_id = self._operation_id(context, "event.demon_invasion.claim_reward")
        try:
            record = await self.repository.claim_demon_invasion_event(
                platform=context.adapter,
                platform_user_id=context.user_id,
                round_id=round_id,
                operation_id=operation_id,
            )
        except Exception as exc:
            return self._error(context, operation_id, exc, event_label="魔界入侵")
        return CommandResult(
            True,
            "EVENT_REWARD_CLAIMED",
            "## 魔界入侵奖励已领取\n\n- 世界功勋 +50\n- 魔界声望 +20",
            context.request_id,
            operation_id,
            data=self._data(record),
        )

    @staticmethod
    def _cross_event_round_id(args: tuple[str, ...]) -> str | None:
        if not args:
            return None
        return args[0] if len(args) == 1 else ""

    async def _get_cross_realm_event(self, context: CommandContext, event_key: str, label: str, usage: str) -> CommandResult:
        round_id = self._cross_event_round_id(context.command_args)
        if round_id == "":
            return CommandResult(False, "INVALID_EVENT_COMMAND", usage, context.request_id)
        try:
            record = await self.repository.get_cross_realm_event(
                event_key=event_key,
                platform=context.adapter,
                platform_user_id=context.user_id,
                round_id=round_id,
            )
        except Exception as exc:
            return self._error(context, "", exc, event_label=label)
        state = {"open": "进行中", "running": "进行中", "settled": "已结算", "failed": "已结束"}.get(record.status, record.status)
        return CommandResult(
            True,
            "EVENT_STATUS",
            (
                f"## {label}\n\n"
                f"**轮次**：`{record.round_id}`\n"
                f"**状态**：{state}\n"
                f"**全服贡献**：{record.total_contribution}/{record.target_quantity}\n"
                f"**你的贡献**：{record.player_contribution}\n"
                f"**时间**：{record.starts_at} 至 {record.ends_at}\n\n"
                "> 贡献来源必须是服务器已结算的 operation；事件结束后 24 小时内可领奖。"
            ),
            context.request_id,
            data=self._data(record),
        )

    async def get_beast_trade_event(self, context: CommandContext) -> CommandResult:
        return await self._get_cross_realm_event(
            context, BEAST_TRADE_EVENT_KEY, "妖界贸易", "请使用 `妖界贸易事件 [轮次]`。"
        )

    async def get_boundary_rift_event(self, context: CommandContext) -> CommandResult:
        return await self._get_cross_realm_event(
            context, BOUNDARY_RIFT_EVENT_KEY, "界隙裂痕", "请使用 `界隙裂痕 [轮次]`。"
        )

    async def _contribute_cross_realm_event(
        self, context: CommandContext, event_key: str, label: str, action_values: dict[str, str], usage: str
    ) -> CommandResult:
        if len(context.command_args) > 2:
            return CommandResult(False, "INVALID_EVENT_COMMAND", usage, context.request_id)
        action = context.command_args[0] if context.command_args else next(iter(action_values))
        action_key = action_values.get(action)
        source_operation_id = context.command_args[1] if len(context.command_args) == 2 else None
        if action_key is None and len(context.command_args) == 1 and event_key == BOUNDARY_RIFT_EVENT_KEY:
            action_key = "complete"
            source_operation_id = action
        if action_key is None:
            return CommandResult(False, "INVALID_EVENT_COMMAND", usage, context.request_id)
        operation_id = self._operation_id(context, f"{event_key}.contribute")
        try:
            record = await self.repository.record_cross_realm_contribution(
                event_key=event_key,
                platform=context.adapter,
                platform_user_id=context.user_id,
                action_key=action_key,
                source_operation_id=source_operation_id,
                operation_id=operation_id,
            )
        except Exception as exc:
            return self._error(context, operation_id, exc, event_label=label)
        return CommandResult(
            True,
            "EVENT_CONTRIBUTION_RECORDED",
            f"## {label}贡献已记录\n\n- **本轮贡献**：{record.player_contribution}\n- **全服贡献**：{record.total_contribution}/{record.target_quantity}",
            context.request_id,
            operation_id,
            data=self._data(record),
        )

    async def contribute_beast_trade_event(self, context: CommandContext) -> CommandResult:
        return await self._contribute_cross_realm_event(
            context,
            BEAST_TRADE_EVENT_KEY,
            "妖界贸易",
            {"贸易": "trade", "跨界贸易": "trade", "妖血": "blood", "提交妖血": "blood"},
            "请使用 `贡献妖界贸易 贸易|妖血 [来源operation]`。",
        )

    async def contribute_boundary_rift_event(self, context: CommandContext) -> CommandResult:
        return await self._contribute_cross_realm_event(
            context,
            BOUNDARY_RIFT_EVENT_KEY,
            "界隙裂痕",
            {"路线": "route", "首领": "boss", "完成": "complete"},
            "请使用 `贡献界隙裂痕 [来源operation]`。",
        )

    async def _claim_cross_realm_event(self, context: CommandContext, event_key: str, label: str, usage: str) -> CommandResult:
        round_id = self._cross_event_round_id(context.command_args)
        if not round_id or round_id == "":
            return CommandResult(False, "INVALID_EVENT_COMMAND", usage, context.request_id)
        operation_id = self._operation_id(context, f"{event_key}.claim_reward")
        try:
            record = await self.repository.claim_cross_realm_event(
                event_key=event_key,
                platform=context.adapter,
                platform_user_id=context.user_id,
                round_id=round_id,
                operation_id=operation_id,
            )
        except Exception as exc:
            return self._error(context, operation_id, exc, event_label=label)
        return CommandResult(
            True,
            "EVENT_REWARD_CLAIMED",
            f"## {label}奖励已领取\n\n" + "\n".join(f"- {key} +{value}" for key, value in record.reward.items()),
            context.request_id,
            operation_id,
            data=self._data(record),
        )

    async def claim_beast_trade_event(self, context: CommandContext) -> CommandResult:
        return await self._claim_cross_realm_event(
            context, BEAST_TRADE_EVENT_KEY, "妖界贸易", "请使用 `领取妖界贸易奖励 <轮次>`。"
        )

    async def claim_boundary_rift_event(self, context: CommandContext) -> CommandResult:
        return await self._claim_cross_realm_event(
            context, BOUNDARY_RIFT_EVENT_KEY, "界隙裂痕", "请使用 `领取界隙裂痕奖励 <轮次>`。"
        )


__all__ = ["EventsApplication"]
