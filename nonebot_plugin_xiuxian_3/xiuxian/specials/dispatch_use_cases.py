"""Application services for dispatch task commands."""

from __future__ import annotations

import logging
from typing import Mapping

from ...contracts import CommandAction, CommandContext, CommandResult
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
from .dispatch_rules import DispatchDefinition, resolve_dispatch
from .dispatch_planning import select_preparation
from ..utils.text import command_link

logger = logging.getLogger(__name__)


_STAGE_LABELS = {
    "new_user": "初入仙途",
    "mortal": "凡人以上",
    "seeker": "寻道期",
    "cultivator": "入道后",
}
_RISK_LABELS = {
    "success": "顺利",
    "delayed": "耽搁",
    "partial": "部分",
    "failed": "失败",
}


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
    def _error(context: CommandContext, operation_id: str, exc: Exception, command: str = "派遣预览") -> CommandResult:
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
                reason = str(exc)
                return CommandResult(
                    False,
                    code,
                    f"{message} {reason}",
                    context.request_id,
                    operation_id or None,
                    retryable=error_type is RepositoryBusyError,
                    data={"reason": reason, "subject": " ".join(context.command_args) or "本人派遣"},
                )
        logger.error("dispatch command failed command=%s adapter=%s request=%s operation=%s args=%r",
                     command, context.adapter, context.request_id, operation_id, context.command_args,
                     exc_info=(type(exc), exc, exc.__traceback__))
        raise exc

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
            "accept_command": (f"接受派遣 {record.label}" + (f" {record.planning['plan_name']}" if record.planning else "")) if record.ready else None,
            "planning": record.planning,
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

    def _realm_label(self, realm_key: str | None) -> str:
        if not realm_key:
            return "凡人"
        try:
            return self._content().label("realm", realm_key)
        except Exception:
            return realm_key

    def _cost_text(self, costs: dict[str, int]) -> str:
        return "、".join(f"{self._label(key)} {value}" for key, value in costs.items()) or "无成本"

    def _reward_text(self, rewards: dict[str, int]) -> str:
        return "、".join(f"{self._label(key)} +{value}" for key, value in rewards.items()) or "无产出"

    def _reward_spec_text(self, rewards: Mapping[str, int | tuple[int, int]]) -> str:
        parts: list[str] = []
        for key, value in rewards.items():
            if isinstance(value, tuple) and len(value) == 2:
                amount = f"{int(value[0])}–{int(value[1])}"
            else:
                amount = str(int(value))  # type: ignore[arg-type]
            parts.append(f"{self._label(str(key))} +{amount}")
        return "、".join(parts) or "无产出"

    def _requirement_text(self, definition: DispatchDefinition) -> str:
        parts: list[str] = []
        stage = _STAGE_LABELS.get(definition.required_stage or "")
        if stage:
            parts.append(stage)
        if definition.required_realm and definition.required_layer is not None:
            realm = f"{self._realm_label(definition.required_realm)} L{definition.required_layer}"
            if definition.required_service_reputation is not None:
                realm += f" 或服务信誉 {definition.required_service_reputation}"
            parts.append(realm)
        elif definition.required_service_reputation is not None:
            parts.append(f"服务信誉 {definition.required_service_reputation}")
        if definition.required_intro_flag:
            parts.append("完成对应引导")
        if definition.required_location:
            parts.append("位于" + self._content().label("location", definition.required_location))
        if definition.required_permit:
            parts.append("持有有效贸易许可")
        return "、".join(parts) or "无额外前置"

    @staticmethod
    def _risk_text(definition: DispatchDefinition) -> str:
        total = sum(weight for _, weight in definition.risk_weights) or 1
        return "、".join(
            f"{_RISK_LABELS.get(outcome, outcome)} {weight * 100 / total:.0f}%"
            for outcome, weight in definition.risk_weights
        )

    def _detail_lines(self, record: DispatchPreviewRecord, definition: DispatchDefinition) -> list[str]:
        reward_map = dict(definition.rewards)
        success = {str(key): value for key, value in dict(reward_map.get("success", {})).items()}
        partial = {str(key): value for key, value in dict(reward_map.get("partial", {})).items()}
        refunds = dict(definition.failure_refunds)
        lines = [
            f"**{record.label}" + (f" · {record.planning['plan_name']}**" if record.planning else "**"),
            record.description,
            f"- **前置**：{self._requirement_text(definition)}",
            f"- **耗时**：{record.duration_seconds // 60} 分钟 · 每日 {record.daily_limit} 次（今日已接 {record.daily_used} 次）",
            f"- **成本**：{self._cost_text(record.costs)}",
            f"- **风险**：{self._risk_text(definition)}",
            f"- **顺利**：{self._reward_spec_text(success)}",
        ]
        if partial:
            lines.append(f"- **部分**：{self._reward_spec_text(partial)}")
        lines.append(f"- **失败返还**：{self._cost_text({key: value for key, value in refunds.items()}) if refunds else '无'}")
        return lines

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
            "label": record.label,
            "planning": record.planning,
        }

    async def preview(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) > 2:
            return self._invalid(context, "请使用 `派遣预览 [任务] [方案]`。")
        definition = None
        if context.command_args:
            try:
                definition = resolve_dispatch(context.command_args[0], self.repository.content)
            except ValueError:
                return self._invalid(context, f"没有开放派遣：{context.command_args[0]}", "DISPATCH_NOT_FOUND")
            except Exception as exc:
                return self._error(context, "", exc, "派遣预览")
        try:
            records = await self.repository.preview_dispatch(
                platform=context.adapter,
                platform_user_id=context.user_id,
                dispatch_key=context.command_args[0] if context.command_args else None,
                preparation=context.command_args[1] if len(context.command_args) == 2 else None,
            )
        except ValueError as exc:
            return self._invalid(context, str(exc))
        except Exception as exc:
            return self._error(context, "", exc)
        data = {"dispatches": [self._preview_data(record) for record in records]}
        lines = ["**派遣任务**", ""]
        actions: tuple[CommandAction, ...] = ()
        if definition is not None:
            if definition.planning:
                lines.extend([definition.planning["scene"], ""])
                sources = definition.planning["sources"]
                lines.append("备料：" + "、".join(
                    command_link(self._content().label("item", source["item_key"]),
                                 "开始探索 " + self._content().label("exploration_mode", source["exploration_key"]))
                    for source in sources
                ))
                lines.append("用途：" + self._uses_text(records[0].planning))
            buttons = []
            for record in records:
                selected = select_preparation(definition, record.planning["plan_key"] if record.planning else None, self._content())
                lines.extend(self._detail_lines(record, selected))
                if record.planning:
                    lines.append(record.planning["plan_desc"])
                if record.ready:
                    lines.append("- **状态**：可接受")
                    suffix = f" {record.planning['plan_name']}" if record.planning else ""
                    buttons.append(CommandAction(f"接受{record.planning['plan_name']}" if record.planning else "接受此项派遣",
                                                 f"接受派遣 {record.label}{suffix}", enter=True))
                else:
                    lines.append(f"- **状态**：不可接受：{'、'.join(record.missing)}")
                lines.append("")
            actions = tuple(buttons)
        else:
            for record in records:
                duration = record.duration_seconds // 60
                state = "可接受" if record.ready else f"不可接受：{'、'.join(record.missing)}"
                costs = self._cost_text(record.costs)
                accept = f" · {command_link('筹备', f'派遣预览 {record.label}')}" if record.planning else (
                    f" · {command_link('接受', f'接受派遣 {record.label}')}" if record.ready else ""
                )
                lines.append(
                    f"- **{record.label}**：{record.description} · {duration} 分钟 · {costs} · {state}{accept}"
                )
        return CommandResult(
            True,
            "DISPATCH_PREVIEW",
            "\n".join(lines),
            context.request_id,
            data=data,
            actions=actions,
        )

    async def accept(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) not in (1, 2):
            return self._invalid(context, "请使用 `接受派遣 <任务> [方案]`。")
        definition = None
        try:
            definition = resolve_dispatch(context.command_args[0], self.repository.content)
        except ValueError:
            # New fieldwork requests retain their public selector so closing or
            # renaming content cannot strand an already committed acceptance.
            pass
        except Exception as exc:
            return self._error(context, self._operation_id(context, "specials.accept_dispatch"), exc, "接受派遣")
        operation_id = self._operation_id(context, "specials.accept_dispatch")
        try:
            record = await self.repository.accept_dispatch(
                platform=context.adapter,
                platform_user_id=context.user_id,
                dispatch_key=definition.key if definition is not None and definition.planning is None else context.command_args[0],
                operation_id=operation_id,
                preparation=context.command_args[1] if len(context.command_args) == 2 else None,
            )
        except Exception as exc:
            return self._error(context, operation_id, exc, "接受派遣")
        return CommandResult(
            True,
            "DISPATCH_ACCEPTED",
            f"已接受 **{record.label or (definition.label if definition else '这项派遣')}**。"
            + (f"筹备：{record.planning['plan_name']}。\n{record.planning['start_text']}\n" if record.planning else "")
            + f"成本：{self._frozen_assets(record.costs, record.planning)}。60 秒内可取消；预计结算：{record.ends_at}。\n"
            + command_link("派遣状态", "派遣状态"),
            context.request_id,
            operation_id,
            data=self._assignment_data(record),
            actions=(
                (CommandAction("取消派遣", "取消派遣", enter=True),)
                if not record.already_completed
                else ()
            ),
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
            "label": record.label,
            "planning": record.planning,
        }

    async def settle(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) > 1:
            return self._invalid(context, "结算派遣最多接收一个派遣编号。")
        operation_id = self._operation_id(context, "specials.settle_dispatch")
        try:
            record = await self.repository.settle_dispatch(
                platform=context.adapter,
                platform_user_id=context.user_id,
                assignment_id=context.command_args[0] if context.command_args else None,
                operation_id=operation_id,
            )
        except Exception as exc:
            return self._error(context, operation_id, exc, "结算派遣")
        reward = self._frozen_assets(record.reward, record.planning, gain=True)
        suffix = f"；返还 {self._frozen_assets(record.refunded, record.planning, gain=True)}" if record.refunded else ""
        outcome = {
            "success": "顺利完成",
            "delayed": "途中稍有耽搁",
            "partial": "只取得部分成果",
            "failed": "未能完成",
        }[record.outcome]
        return CommandResult(
            True,
            "DISPATCH_SETTLED",
            (record.planning["result_text"] + "\n" if record.planning else "")
            + f"派遣已结算，{outcome}；收益：{reward}{suffix}。\n"
            + ("用途：" + self._uses_text(record.planning) + "\n" if record.planning else "")
            + command_link('再看派遣', '派遣预览'),
            context.request_id,
            operation_id,
            data=self._settlement_data(record),
        )

    async def cancel(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) > 1:
            return self._invalid(context, "取消派遣最多接收一个派遣编号。")
        operation_id = self._operation_id(context, "specials.cancel_dispatch")
        try:
            record = await self.repository.cancel_dispatch(
                platform=context.adapter,
                platform_user_id=context.user_id,
                assignment_id=context.command_args[0] if context.command_args else None,
                operation_id=operation_id,
            )
        except Exception as exc:
            return self._error(context, operation_id, exc, "取消派遣")
        refund = self._frozen_assets(record.refunded, record.planning, gain=True)
        return CommandResult(
            True,
            "DISPATCH_CANCELLED",
            f"派遣已取消，全部成本已返还：{refund}。\n{command_link('再看派遣', '派遣预览')}",
            context.request_id,
            operation_id,
            data={
                "assignment_id": record.assignment_id,
                "dispatch_key": record.dispatch_key,
                "status": record.status,
                "refunded": dict(record.refunded),
                "planning": record.planning,
                "idempotent_replay": record.already_completed,
            },
        )

    @staticmethod
    def _invalid(context, reason, code="INVALID_DISPATCH_COMMAND"):
        return CommandResult(False, code, reason, context.request_id,
                             data={"reason": reason, "subject": " ".join(context.command_args) or "本人派遣"})

    @staticmethod
    def _uses_text(planning):
        return "、".join(command_link(use["name"], use["command"]) for use in planning["uses"]) if planning else ""

    def _frozen_assets(self, assets, planning, *, gain=False):
        labels = planning["asset_labels"] if planning else {}
        return "、".join(f"{labels[key] if key in labels else self._label(key)} {'+' if gain else ''}{amount}" for key, amount in sorted(assets.items())) or "无"

    async def status(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return self._invalid(context, "派遣状态不接收参数。")
        try:
            status = await self.repository.status_dispatch(platform=context.adapter, platform_user_id=context.user_id)
        except Exception as exc:
            return self._error(context, "", exc, "派遣状态")
        if status is None:
            return CommandResult(True, "DISPATCH_STATUS", "暂无派遣。\n" + command_link("派遣预览", "派遣预览"), context.request_id,
                                 data={"assignment": None})
        record = status.assignment
        data = self._assignment_data(record)
        data.update(remaining_seconds=status.remaining_seconds, cancel_seconds=status.cancel_seconds, result=status.result)
        lines = [f"**{record.label}**", "筹备：" + record.planning["plan_name"] if record.planning else "",
                 "成本：" + self._frozen_assets(record.costs, record.planning)]
        actions = ()
        if record.status in {"accepted", "running"}:
            lines.append(f"距结算 {status.remaining_seconds} 秒 · 预计 {record.ends_at}")
            if status.remaining_seconds == 0:
                actions = (CommandAction("结算派遣", f"结算派遣 {record.assignment_id}", enter=True),)
            elif status.cancel_seconds > 0:
                lines.append(f"可取消窗口剩余 {status.cancel_seconds} 秒")
                actions = (CommandAction("取消派遣", f"取消派遣 {record.assignment_id}", enter=True),)
            if record.planning:
                lines.append(record.planning["start_text"])
        else:
            lines.append("已取消" if record.status == "cancelled" else "已结算")
            if record.status == "settled" and record.planning:
                lines.append(record.planning["result_text"])
            lines.append("实得：" + self._frozen_assets(status.result.get("reward", {}), record.planning, gain=True))
            if status.result.get("refunded"):
                lines.append("返还：" + self._frozen_assets(status.result["refunded"], record.planning, gain=True))
            lines.append(command_link("再看派遣", "派遣预览"))
        return CommandResult(True, "DISPATCH_STATUS", "\n".join(line for line in lines if line), context.request_id,
                             data={"assignment": data}, actions=actions)


__all__ = ["DispatchApplication"]
