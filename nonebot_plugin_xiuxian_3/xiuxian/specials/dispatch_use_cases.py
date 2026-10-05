"""Application services for dispatch task commands."""

from __future__ import annotations

from ...contracts import CommandContext, CommandResult
from ..content import bundled_content
from ..persistence.errors import (
    DispatchAlreadySettledError,
    DispatchBusyError,
    DispatchCancellationExpiredError,
    DispatchDailyLimitError,
    DispatchNotFoundError,
    DispatchNotReadyError,
    DispatchRequirementError,
    OperationConflictError,
    PlayerNotFoundError,
    PlayerSuspendedError,
    RepositoryBusyError,
)
from .dispatch_models import (
    DispatchAssignmentRecord,
    DispatchPreviewRecord,
    DispatchSettlementRecord,
)
from .dispatch_repository import DispatchRepositoryMixin
from .dispatch_rules import resolve_dispatch


class DispatchApplication:
    def __init__(self, repository: DispatchRepositoryMixin):
        self.repository = repository

    @staticmethod
    def _operation_id(context: CommandContext, name: str) -> str:
        if context.operation_id:
            return context.operation_id
        key = context.message_id or context.request_id
        return f"{name}:{context.adapter}:{context.user_id}:{key}"

    @staticmethod
    def _error(context: CommandContext, operation_id: str, exc: Exception) -> CommandResult:
        errors = {
            PlayerNotFoundError: ("PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。"),
            PlayerSuspendedError: ("PLAYER_SUSPENDED", "当前角色暂时不能进行派遣操作。"),
            DispatchRequirementError: ("DISPATCH_REQUIREMENT_MISSING", "任务前置、体力、精力或材料不足。"),
            DispatchBusyError: ("DISPATCH_SLOT_BUSY", "当前角色已有进行中的长时行动。"),
            DispatchDailyLimitError: ("DISPATCH_DAILY_LIMIT", "该派遣任务今日接受次数已用尽。"),
            DispatchNotFoundError: ("DISPATCH_NOT_FOUND", "没有找到进行中的派遣。"),
            DispatchNotReadyError: ("DISPATCH_NOT_READY", "派遣尚未到结算时间。"),
            DispatchAlreadySettledError: ("DISPATCH_ALREADY_SETTLED", "这条派遣已经结算或取消。"),
            DispatchCancellationExpiredError: ("DISPATCH_CANCEL_WINDOW_EXPIRED", "接受超过 60 秒，不能再取消。"),
            OperationConflictError: ("OPERATION_CONFLICT", "此事已有安排，请重新起意。"),
            RepositoryBusyError: ("PERSISTENCE_BUSY", "派遣簿暂时繁忙，请稍后再试。"),
        }
        for error_type, (code, message) in errors.items():
            if isinstance(exc, error_type):
                return CommandResult(
                    False,
                    code,
                    message,
                    context.request_id,
                    operation_id or None,
                    retryable=error_type is RepositoryBusyError,
                )
        return CommandResult(
            False,
            "PERSISTENCE_ERROR",
            "派遣簿暂时不可用，请稍后再试。",
            context.request_id,
            operation_id or None,
            retryable=True,
        )

    @staticmethod
    def _preview_data(record: DispatchPreviewRecord) -> dict[str, object]:
        return {
            "dispatch_key": record.dispatch_key,
            "label": record.label,
            "description": record.description,
            "duration_seconds": record.duration_seconds,
            "daily_limit": record.daily_limit,
            "daily_used": record.daily_used,
            "costs": dict(record.costs),
            "ready": record.ready,
            "missing": list(record.missing),
        }

    def _content(self):
        return self.repository.content or bundled_content()

    def _label(self, key: str) -> str:
        content = self._content()
        if key in {"stamina", "energy"}:
            return {"stamina": "体力", "energy": "精力"}[key]
        if key in {"spirit_stones", "currency.spirit_stone"}:
            return "灵石"
        if key == "service_reputation":
            return "服务信誉"
        if key.startswith("item."):
            return content.label("item", key)
        if key.startswith("codex."):
            return content.label("codex_entry", key)
        if key.startswith("local."):
            return content.label("location", key.removeprefix("local.")) + "名望"
        return key

    def _cost_text(self, costs: dict[str, int]) -> str:
        return "、".join(f"{self._label(key)} {value}" for key, value in costs.items()) or "无成本"

    def _reward_text(self, rewards: dict[str, int]) -> str:
        return "、".join(f"{self._label(key)} +{value}" for key, value in rewards.items()) or "无产出"

    @staticmethod
    def _assignment_data(record: DispatchAssignmentRecord) -> dict[str, object]:
        return {
            "assignment_id": record.assignment_id,
            "dispatch_key": record.dispatch_key,
            "status": record.status,
            "outcome": record.outcome,
            "accepted_at": record.accepted_at,
            "running_at": record.running_at,
            "ends_at": record.ends_at,
            "cancel_until": record.cancel_until,
            "costs": dict(record.costs),
            "idempotent_replay": record.already_completed,
        }

    async def preview(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) > 1:
            return CommandResult(False, "INVALID_DISPATCH_COMMAND", "派遣预览最多接收一个任务键。", context.request_id)
        if context.command_args:
            try:
                resolve_dispatch(context.command_args[0], self.repository.content)
            except ValueError:
                return CommandResult(False, "DISPATCH_NOT_FOUND", "没有找到这条派遣任务。", context.request_id)
        try:
            records = await self.repository.preview_dispatch(
                platform=context.adapter,
                platform_user_id=context.user_id,
                dispatch_key=context.command_args[0] if context.command_args else None,
            )
        except Exception as exc:
            return self._error(context, "", exc)
        data = {"dispatches": [self._preview_data(record) for record in records]}
        lines = ["## 派遣任务", ""]
        for record in records:
            duration = record.duration_seconds // 60
            state = "可接受" if record.ready else f"不可接受：{'、'.join(record.missing)}"
            costs = self._cost_text(record.costs)
            lines.append(f"- **{record.label}**：{record.description} · {duration} 分钟 · {costs} · {state}")
        return CommandResult(True, "DISPATCH_PREVIEW", "\n".join(lines), context.request_id, data=data)

    async def accept(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 1:
            return CommandResult(False, "INVALID_DISPATCH_COMMAND", "请使用 `接受派遣 <任务键>`。", context.request_id)
        definition = None
        try:
            definition = resolve_dispatch(context.command_args[0], self.repository.content)
        except ValueError:
            # Let the repository inspect the operation ledger first so a stable-key
            # replay remains available after its content record is closed.
            if not context.command_args[0].strip().startswith("dispatch."):
                return CommandResult(False, "DISPATCH_NOT_FOUND", "没有找到这条派遣任务。", context.request_id)
        operation_id = self._operation_id(context, "specials.accept_dispatch")
        try:
            record = await self.repository.accept_dispatch(
                platform=context.adapter,
                platform_user_id=context.user_id,
                dispatch_key=definition.key if definition is not None else context.command_args[0],
                operation_id=operation_id,
            )
        except Exception as exc:
            return self._error(context, operation_id, exc)
        return CommandResult(
            True,
            "DISPATCH_ACCEPTED",
            f"已接受 **{definition.label if definition is not None else '这项派遣'}**。60 秒内可取消；预计结算：{record.ends_at}。",
            context.request_id,
            operation_id,
            data=self._assignment_data(record),
        )

    @staticmethod
    def _settlement_data(record: DispatchSettlementRecord) -> dict[str, object]:
        return {
            "assignment_id": record.assignment_id,
            "dispatch_key": record.dispatch_key,
            "status": record.status,
            "outcome": record.outcome,
            "reward": dict(record.reward),
            "refunded": dict(record.refunded),
            "idempotent_replay": record.already_completed,
        }

    async def settle(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) > 1:
            return CommandResult(False, "INVALID_DISPATCH_COMMAND", "结算派遣最多接收一个派遣编号。", context.request_id)
        operation_id = self._operation_id(context, "specials.settle_dispatch")
        try:
            record = await self.repository.settle_dispatch(
                platform=context.adapter,
                platform_user_id=context.user_id,
                assignment_id=context.command_args[0] if context.command_args else None,
                operation_id=operation_id,
            )
        except Exception as exc:
            return self._error(context, operation_id, exc)
        reward = self._reward_text(record.reward)
        refund = self._reward_text(record.refunded)
        suffix = f"；返还 {refund}" if refund else ""
        outcome = {
            "success": "顺利完成",
            "delayed": "途中稍有耽搁",
            "partial": "只取得部分成果",
            "failed": "未能完成",
        }.get(record.outcome, "结果已定")
        return CommandResult(
            True,
            "DISPATCH_SETTLED",
            f"派遣已结算，{outcome}；收益：{reward}{suffix}。",
            context.request_id,
            operation_id,
            data=self._settlement_data(record),
        )

    async def cancel(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) > 1:
            return CommandResult(False, "INVALID_DISPATCH_COMMAND", "取消派遣最多接收一个派遣编号。", context.request_id)
        operation_id = self._operation_id(context, "specials.cancel_dispatch")
        try:
            record = await self.repository.cancel_dispatch(
                platform=context.adapter,
                platform_user_id=context.user_id,
                assignment_id=context.command_args[0] if context.command_args else None,
                operation_id=operation_id,
            )
        except Exception as exc:
            return self._error(context, operation_id, exc)
        refund = "、".join(f"{key} +{value}" for key, value in record.refunded.items()) or "无"
        return CommandResult(
            True,
            "DISPATCH_CANCELLED",
            f"派遣已取消，全部成本已返还：{refund}。",
            context.request_id,
            operation_id,
            data={
                "assignment_id": record.assignment_id,
                "dispatch_key": record.dispatch_key,
                "status": record.status,
                "refunded": dict(record.refunded),
                "idempotent_replay": record.already_completed,
            },
        )


__all__ = ["DispatchApplication"]
