"""Application services for previewing and settling idle routes."""

from __future__ import annotations

from ...contracts import CommandContext, CommandResult
from ..content import bundled_content
from ..persistence.errors import (
    IdleAlreadySettledError,
    IdleBusyError,
    IdleCancellationExpiredError,
    IdleClaimTooEarlyError,
    IdleDailyLimitError,
    IdleNotFoundError,
    IdleRequirementError,
    OperationConflictError,
    PlayerNotFoundError,
    PlayerSuspendedError,
    RepositoryBusyError,
)
from .idle_models import IdleAssignmentRecord, IdleRoutePreviewRecord
from .idle_repository import IdleRepositoryMixin
from .idle_rules import resolve_route


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
    def _error(context: CommandContext, operation_id: str, exc: Exception) -> CommandResult:
        errors = {
            PlayerNotFoundError: ("PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。"),
            PlayerSuspendedError: ("PLAYER_SUSPENDED", "当前角色暂不能安排闲居历练。"),
            IdleRequirementError: ("IDLE_REQUIREMENT_MISSING", "当前路线的地点、资源或设施条件未满足。"),
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
                return CommandResult(False, code, message, context.request_id, operation_id or None, retryable=error_type is RepositoryBusyError)
        return CommandResult(False, "PERSISTENCE_ERROR", "闲居安排未能落定，请稍后再试。", context.request_id, operation_id or None, retryable=True)

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
        content = self.repository.content or bundled_content()
        fixed_labels = {"spirit_stones": "灵石", "stamina": "体力", "energy": "精力"}
        if key in fixed_labels:
            return fixed_labels[key]
        if key.startswith("item."):
            return content.label("item", key)
        if key.startswith("local."):
            location_key = key.removeprefix("local.")
            return f"{content.label('location', location_key)}名望"
        if key.startswith("codex."):
            return content.label("codex_entry", key)
        return key

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
        if context.command_args:
            try:
                resolve_route(context.command_args[0], self.repository.content)
            except ValueError:
                return CommandResult(False, "IDLE_ROUTE_NOT_FOUND", "没有找到这条闲居路线。", context.request_id)
        try:
            records = await self.repository.preview_idle(
                platform=context.adapter,
                platform_user_id=context.user_id,
                route_key=context.command_args[0] if context.command_args else None,
            )
        except Exception as exc:
            return self._error(context, "", exc)
        data = {"routes": [self._preview_data(record) for record in records]}
        lines = ["## 闲居路线", ""]
        for record in records:
            state = "可开始" if record.ready else f"不可开始：{'、'.join(record.missing)}"
            lines.append(
                f"- **{record.label}** · {record.description} · "
                f"{record.duration_seconds // 3600} 小时 · {state}"
            )
        return CommandResult(True, "IDLE_PREVIEW", "\n".join(lines), context.request_id, data=data)

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
            return self._error(context, operation_id, exc)
        return CommandResult(
            True,
            "IDLE_STARTED",
            f"## 闲居安排已定\n\n- **路线**：{record.label}\n- **可领取**：{record.claim_at}\n- **最迟领取**：{record.max_claim_at}\n- **开始后 60 秒内可撤回**：是",
            context.request_id,
            operation_id,
            data=self._assignment_data(record),
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
            return self._error(context, operation_id, exc)
        reward_text = "、".join(
            f"记下「{self._reward_label(key)}」" if key.startswith("codex.")
            else f"{self._reward_label(key)} +{value}"
            for key, value in record.reward.items()
        ) or "无额外所得"
        late = "（逾时所得）" if record.fallback else ""
        return CommandResult(
            True,
            "IDLE_CLAIMED",
            f"## 闲居所得已收取{late}\n\n- **路线**：{record.label}\n- **所得**：{reward_text}",
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
            return self._error(context, operation_id, exc)
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
