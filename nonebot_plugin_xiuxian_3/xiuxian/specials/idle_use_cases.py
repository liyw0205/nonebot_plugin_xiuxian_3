"""Application services for previewing and settling idle routes."""

from __future__ import annotations

import logging

from ...contracts import CommandAction, CommandContext, CommandResult
from ..content import bundled_content
from ..persistence.errors import (
    IdleAlreadySettledError,
    IdleBusyError,
    IdleCancellationExpiredError,
    IdleClaimTooEarlyError,
    IdleDailyLimitError,
    IdleNotFoundError,
    IdleRequirementError,
    IdleRouteNotFoundError,
    OperationConflictError,
    PlayerNotFoundError,
    PlayerSuspendedError,
    RepositoryBusyError,
)
from .idle_models import IdleAssignmentRecord, IdleRoutePreviewRecord
from .idle_repository import IdleRepositoryMixin
from .idle_rules import idle_reward_label
from ..utils.text import command_link


logger = logging.getLogger(__name__)


class IdleApplication:
    """Translate normalized commands into idle DTOs."""

    def __init__(self, repository: IdleRepositoryMixin):
        self.repository = repository

    @staticmethod
    def _operation_id(context: CommandContext, operation_name: str) -> str:
        if context.operation_id:
            return context.operation_id
        key = context.message_id or context.request_id
        return f"{operation_name}:{context.adapter}:{context.user_id}:{key}"

    @staticmethod
    def _error(context: CommandContext, operation_id: str, exc: Exception, *, command: str) -> CommandResult:
        errors = {
            PlayerNotFoundError: ("PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。"),
            PlayerSuspendedError: ("PLAYER_SUSPENDED", "当前角色暂不能安排闲居历练。"),
            IdleRequirementError: ("IDLE_REQUIREMENT_MISSING", "当前路线的地点、资源或设施条件未满足。"),
            IdleRouteNotFoundError: ("IDLE_ROUTE_NOT_FOUND", "没有找到这条闲居路线。"),
            IdleBusyError: ("IDLE_BUSY", "当前角色已有进行中的长时行动，请先结算或取消。"),
            IdleDailyLimitError: ("IDLE_DAILY_LIMIT", "该路线今日结算次数已用尽。"),
            IdleNotFoundError: ("IDLE_NOT_FOUND", "眼下没有待领取的闲居安排。"),
            IdleClaimTooEarlyError: ("IDLE_CLAIM_TOO_EARLY", "这项安排尚未到收取所得的时候。"),
            IdleAlreadySettledError: ("IDLE_ALREADY_SETTLED", "这项闲居安排已经结束。"),
            IdleCancellationExpiredError: ("IDLE_CANCEL_WINDOW_EXPIRED", "安排已过撤回时限。"),
            OperationConflictError: ("OPERATION_CONFLICT", "同一请求已用于另一项安排，无法重复提交。"),
            RepositoryBusyError: ("PERSISTENCE_BUSY", "眼下事务繁忙，请稍后再试。"),
        }
        for error_type, (code, message) in errors.items():
            if isinstance(exc, error_type):
                if isinstance(exc, IdleRequirementError):
                    message = f"无法安排闲居：{exc}。"
                return CommandResult(
                    False, code, message, context.request_id, operation_id or None,
                    retryable=error_type is RepositoryBusyError,
                    data={"reason": str(exc), "subject": context.command_args[0] if context.command_args else "本人闲居安排"},
                )
        logger.error(
            "idle command failed command=%s adapter=%s request=%s operation=%s args=%r",
            command, context.adapter, context.request_id, operation_id, context.command_args,
            exc_info=(type(exc), exc, exc.__traceback__),
        )
        raise exc

    @staticmethod
    def _preview_data(record: IdleRoutePreviewRecord) -> dict[str, object]:
        return {
            "route_key": record.route_key,
            "label": record.label,
            "description": record.description,
            "duration_seconds": record.duration_seconds,
            "stamina_cost": record.stamina_cost,
            "energy_cost": record.energy_cost,
            "daily_limit": record.daily_limit,
            "daily_used": record.daily_used,
            "ready": record.ready,
            "missing": list(record.missing),
            "requirements": dict(record.requirements),
        }

    def _reward_label(self, key: str) -> str:
        return idle_reward_label(key, self.repository.content)

    @staticmethod
    def _uses_text(journal: dict) -> str:
        return "、".join(command_link(use["label"], use["command"]) for use in journal.get("uses", []))

    def _ranges_text(self, ranges: dict) -> str:
        return "、".join(
            f"{self._reward_label(key)} {low}" if low == high
            else f"{self._reward_label(key)} {low}-{high}"
            for key, (low, high) in ranges.items()
        )

    @staticmethod
    def _assignment_data(record: IdleAssignmentRecord) -> dict[str, object]:
        return {
            "assignment_id": record.assignment_id,
            "route_key": record.route_key,
            "status": record.status,
            "starts_at": record.starts_at,
            "claim_at": record.claim_at,
            "max_claim_at": record.max_claim_at,
            "cancel_until": record.cancel_until,
            "cost": dict(record.cost),
            "tool_key": record.tool_key,
            "facility_slot_key": record.facility_slot_key,
            "idempotent_replay": record.already_completed,
        }

    async def preview(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) > 1:
            return CommandResult(False, "INVALID_IDLE_COMMAND", "一次只可查看一条路线。", context.request_id)
        try:
            records = await self.repository.preview_idle(
                platform=context.adapter,
                platform_user_id=context.user_id,
                route_key=context.command_args[0] if context.command_args else None,
            )
        except Exception as exc:
            return self._error(context, "", exc, command="挂机预览")
        data = {"routes": [self._preview_data(record) for record in records]}
        lines = ["**闲居路线**", ""]
        actions = ()
        for record in records:
            state = "可开始" if record.ready else f"不可开始：{'、'.join(record.missing)}"
            lines.append(
                f"- **{record.label}** · {record.description} · "
                f"{record.duration_seconds // 3600} 小时 · {state}"
            )
            if not context.command_args:
                lines.append(command_link("查看详情", f"挂机预览 {record.label}"))
            else:
                conditions = record.requirements
                bundle = self.repository.content or bundled_content()
                if conditions["required_location"]:
                    lines.append(f"地点：{bundle.label('location', conditions['required_location'])}")
                if conditions["required_realm"]:
                    lines.append(f"境界：{bundle.label('realm', conditions['required_realm'])} L{conditions['required_layer']} 起")
                lines.extend([
                    f"花费：体力 {record.stamina_cost}、精力 {record.energy_cost}",
                    f"本日已结算：{record.daily_used}/{record.daily_limit}",
                    f"完整所得：{self._ranges_text(conditions['full_reward_ranges'])}",
                    f"逾时所得：{self._ranges_text(conditions['fallback_reward_ranges'])}",
                ])
                journal = conditions["gathering_journal"]
                if journal:
                    lines.extend(["", journal["start_text"], f"材料去向：{self._uses_text(journal)}"])
                if record.ready:
                    actions = (CommandAction("安排此项闲居", f"开始挂机 {record.label}", enter=True),)
        lines.extend(["", command_link("当前安排", "挂机状态")])
        return CommandResult(True, "IDLE_PREVIEW", "\n".join(lines), context.request_id, data=data, actions=actions)

    async def status(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_IDLE_COMMAND", "挂机状态只查看本人当前安排，无需填写参数。", context.request_id)
        try:
            record = await self.repository.get_idle_status(platform=context.adapter, platform_user_id=context.user_id)
        except Exception as exc:
            return self._error(context, "", exc, command="挂机状态")
        if record is None:
            return CommandResult(True, "IDLE_STATUS", f"眼下没有待领取的闲居安排。\n\n{command_link('挑选路线', '挂机预览')}", context.request_id, data={"assignment": None})
        item = record.assignment
        state = "逾时，可领保底" if record.fallback else "可领取完整所得" if record.claimable else f"还需 {record.remaining_seconds} 秒"
        lines = [f"**{item.label}**", "", state, f"可领取：{item.claim_at}", f"完整领取截止：{item.max_claim_at}"]
        if item.journal:
            lines.extend(["", item.journal["start_text"]])
        actions = ()
        if record.claimable:
            actions = (CommandAction("领取保底" if record.fallback else "领取所得", "领取挂机", enter=True),)
        elif record.cancellable:
            actions = (CommandAction("撤回安排", "取消挂机", enter=True),)
        return CommandResult(
            True, "IDLE_STATUS", "\n".join(lines), context.request_id,
            data={"assignment": self._assignment_data(item), "remaining_seconds": record.remaining_seconds,
                  "claimable": record.claimable, "fallback": record.fallback, "cancellable": record.cancellable},
            actions=actions,
        )

    async def journals(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_IDLE_COMMAND", "采集行记无需填写参数。", context.request_id)
        try:
            records = await self.repository.get_idle_journals(platform=context.adapter, platform_user_id=context.user_id)
        except Exception as exc:
            return self._error(context, "", exc, command="采集行记")
        lines = ["**山野采集行记**", ""]
        for item in records:
            lines.extend([f"**{item['label']}**", item["complete_text"], f"材料去向：{self._uses_text(item)}", ""])
        if not records:
            lines.append("尚未完整收回山野采集所得。")
        lines.append(command_link("挑选路线", "挂机预览"))
        return CommandResult(True, "IDLE_JOURNALS", "\n".join(lines), context.request_id, data={"journals": list(records)})

    async def start(self, context: CommandContext) -> CommandResult:
        if not 1 <= len(context.command_args) <= 2:
            return CommandResult(False, "INVALID_IDLE_COMMAND", "请写明路线名称，可附上工具或作坊槽位。", context.request_id)
        operation_id = self._operation_id(context, "specials.assign_idle")
        try:
            record = await self.repository.start_idle(
                platform=context.adapter,
                platform_user_id=context.user_id,
                route_key=context.command_args[0],
                tool_or_facility=context.command_args[1] if len(context.command_args) == 2 else None,
                operation_id=operation_id,
            )
        except Exception as exc:
            return self._error(context, operation_id, exc, command="开始挂机")
        return CommandResult(
            True,
            "IDLE_STARTED",
            f"**闲居安排已定**\n\n{record.label}\n{record.journal.get('start_text', '')}\n"
            f"可领取：{record.claim_at}\n完整领取截止：{record.max_claim_at}\n\n{command_link('当前安排', '挂机状态')}",
            context.request_id,
            operation_id,
            data=self._assignment_data(record),
            actions=() if record.already_completed else (CommandAction("撤回安排", "取消挂机", enter=True),),
        )

    async def claim(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) > 1:
            return CommandResult(False, "INVALID_IDLE_COMMAND", "一次只可领取一项闲居所得。", context.request_id)
        operation_id = self._operation_id(context, "specials.claim_idle")
        try:
            record = await self.repository.claim_idle(
                platform=context.adapter,
                platform_user_id=context.user_id,
                assignment_id=context.command_args[0] if context.command_args else None,
                operation_id=operation_id,
            )
        except Exception as exc:
            return self._error(context, operation_id, exc, command="领取挂机")
        reward_parts = []
        for key, value in record.reward.items():
            label = record.reward_labels[key] if key in record.reward_labels else self._reward_label(key)
            reward_parts.append(f"记下「{label}」" if key.startswith("codex.") else f"{label} +{value}")
        reward_text = "、".join(reward_parts) or "无额外所得"
        late = "（逾时所得）" if record.fallback else ""
        narrative = record.journal.get("expired_text" if record.fallback else "complete_text", "")
        followup = f"\n\n材料去向：{self._uses_text(record.journal)}" if record.journal else ""
        if record.journal and not record.fallback:
            followup += f"\n{command_link('回看采集行记', '采集行记')}"
        return CommandResult(
            True,
            "IDLE_CLAIMED",
            f"**闲居所得已收取{late}**\n\n{record.label}\n{narrative}\n所得：{reward_text}{followup}",
            context.request_id,
            operation_id,
            data={
                "assignment_id": record.assignment_id,
                "route_key": record.route_key,
                "status": record.status,
                "reward": dict(record.reward),
                "fallback": record.fallback,
                "tool_durability_before": record.tool_durability_before,
                "tool_durability_after": record.tool_durability_after,
                "idempotent_replay": record.already_completed,
            },
        )

    async def cancel(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) > 1:
            return CommandResult(False, "INVALID_IDLE_COMMAND", "一次只可撤回一项闲居安排。", context.request_id)
        operation_id = self._operation_id(context, "specials.cancel_idle")
        try:
            record = await self.repository.cancel_idle(
                platform=context.adapter,
                platform_user_id=context.user_id,
                assignment_id=context.command_args[0] if context.command_args else None,
                operation_id=operation_id,
            )
        except Exception as exc:
            return self._error(context, operation_id, exc, command="取消挂机")
        refunds = [f"{self._reward_label(key)} +{value}" for key, value in record.refunded.items() if value]
        if record.returned_tool_key:
            refunds.append(f"{self._reward_label(record.returned_tool_key)} ×1")
        refund_text = "、".join(refunds) or "无"
        return CommandResult(
            True,
            "IDLE_CANCELLED",
            f"{record.label}已取消，已返还：{refund_text}。",
            context.request_id,
            operation_id,
            data={
                "assignment_id": record.assignment_id,
                "route_key": record.route_key,
                "status": record.status,
                "refunded": dict(record.refunded),
                "returned_tool_key": record.returned_tool_key,
                "idempotent_replay": record.already_completed,
            },
        )


__all__ = ["IdleApplication"]
