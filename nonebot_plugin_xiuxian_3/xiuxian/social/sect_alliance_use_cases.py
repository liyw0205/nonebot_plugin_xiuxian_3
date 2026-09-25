"""Application commands for production alliance contracts."""

from __future__ import annotations

from ...contracts import CommandContext, CommandResult
from ..persistence.errors import (
    AllianceBreachFeeError,
    AllianceConfirmationExpiredError,
    AllianceNotFoundError,
    AllianceResearchWeeklyCapError,
    AllianceRequirementError,
    OperationConflictError,
    PlayerNotFoundError,
    PlayerSuspendedError,
    RepositoryBusyError,
    SectAllianceCooldownError,
    SectNotFoundError,
    SectPermissionDeniedError,
)


class SectAllianceApplication:
    def __init__(self, repository):
        self.repository = repository

    @staticmethod
    def _operation_id(context: CommandContext, name: str) -> str:
        return context.operation_id or f"{name}:{context.adapter}:{context.user_id}:{context.message_id or context.request_id}"

    @staticmethod
    def _error(context: CommandContext, operation_id: str, exc: Exception) -> CommandResult:
        errors = {
            AllianceConfirmationExpiredError: ("ALLIANCE_CONFIRMATION_EXPIRED", "生产联盟确认窗口已过期。"),
            AllianceResearchWeeklyCapError: ("ALLIANCE_RESEARCH_WEEKLY_CAP", "本周生产联盟最多同步 3 项配方。"),
            SectAllianceCooldownError: ("SECT_ALLIANCE_COOLDOWN", "宗门仍处于生产联盟冷却期。"),
            AllianceBreachFeeError: ("ALLIANCE_BREACH_FEE", "提前解除需要支付公共钱包违约费 10000。"),
            AllianceNotFoundError: ("ALLIANCE_NOT_FOUND", "没有找到有效的生产联盟。"),
            AllianceRequirementError: ("ALLIANCE_REQUIREMENT_MISSING", "生产联盟前置或当前状态不满足。"),
            SectPermissionDeniedError: ("SECT_PERMISSION_DENIED", "只有双方宗主可以确认或管理生产联盟。"),
            SectNotFoundError: ("SECT_NOT_FOUND", "你当前不在有效宗门中。"),
            PlayerNotFoundError: ("PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。"),
            PlayerSuspendedError: ("PLAYER_SUSPENDED", "当前角色暂时不能操作生产联盟。"),
            OperationConflictError: ("OPERATION_CONFLICT", "这次请求编号已经用于其他联盟操作。"),
            RepositoryBusyError: ("PERSISTENCE_BUSY", "联盟簿暂时繁忙，请稍后再试。"),
        }
        code, message = errors.get(type(exc), ("PERSISTENCE_ERROR", "联盟簿暂时不可用，请稍后再试。"))
        return CommandResult(False, code, message, context.request_id, operation_id, retryable=isinstance(exc, RepositoryBusyError))

    @staticmethod
    def _data(record) -> dict[str, object]:
        return {"alliance_id": record.alliance_id, "sect_id": record.sect_id, "partner_sect_id": record.partner_sect_id, "partner_sect_name": record.partner_sect_name, "status": record.status, "confirmation_expires_at": record.confirmation_expires_at, "starts_at": record.starts_at, "ends_at": record.ends_at, "termination_requested": record.termination_requested, "synced_recipe_keys": list(record.synced_recipe_keys), "idempotent_replay": record.already_completed}

    async def create(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 1:
            return CommandResult(False, "INVALID_ALLIANCE", "请使用 `发起生产联盟 <宗门号或宗门名>`。", context.request_id)
        operation_id = self._operation_id(context, "social.sect_alliance.create")
        try:
            record = await self.repository.create_sect_alliance(platform=context.adapter, platform_user_id=context.user_id, partner_ref=context.command_args[0], operation_id=operation_id)
        except Exception as exc:
            return self._error(context, operation_id, exc)
        return CommandResult(True, "ALLIANCE_PROPOSED", f"生产联盟提议已发出，等待对方宗主在 24 小时内确认。\n\n- **联盟号**：`{record.alliance_id}`", context.request_id, operation_id, data=self._data(record))

    async def get(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) > 1:
            return CommandResult(False, "INVALID_ALLIANCE", "请使用 `生产联盟 [联盟号]`。", context.request_id)
        try:
            record = await self.repository.get_sect_alliance(platform=context.adapter, platform_user_id=context.user_id, alliance_id=context.command_args[0] if context.command_args else None)
        except Exception as exc:
            return self._error(context, "", exc)
        return CommandResult(True, "ALLIANCE_STATUS", f"## 生产联盟\n\n- **联盟号**：`{record.alliance_id}`\n- **状态**：{record.status}\n- **伙伴宗门**：{record.partner_sect_name}\n- **有效至**：{record.ends_at or record.confirmation_expires_at}\n- **已同步配方**：{', '.join(record.synced_recipe_keys) or '无'}", context.request_id, data=self._data(record))

    async def confirm(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 1:
            return CommandResult(False, "INVALID_ALLIANCE", "请使用 `确认生产联盟 <联盟号>`。", context.request_id)
        operation_id = self._operation_id(context, "social.sect_alliance.confirm")
        try:
            record = await self.repository.confirm_sect_alliance(platform=context.adapter, platform_user_id=context.user_id, alliance_id=context.command_args[0], operation_id=operation_id)
        except Exception as exc:
            return self._error(context, operation_id, exc)
        return CommandResult(True, "ALLIANCE_CONFIRMED", "生产联盟已完成双方确认并生效。" if record.status == "active" else "生产联盟确认已记录，等待另一方确认。", context.request_id, operation_id, data=self._data(record))

    async def end(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 1:
            return CommandResult(False, "INVALID_ALLIANCE", "请使用 `解除生产联盟 <联盟号>`。", context.request_id)
        operation_id = self._operation_id(context, "social.sect_alliance.end")
        try:
            record = await self.repository.end_sect_alliance(platform=context.adapter, platform_user_id=context.user_id, alliance_id=context.command_args[0], operation_id=operation_id)
        except Exception as exc:
            return self._error(context, operation_id, exc)
        message = "双方解除确认已完成，生产联盟已结束并进入冷却。" if record.status == "ended" else "已记录解除意向，等待另一方宗主确认。"
        return CommandResult(True, "ALLIANCE_END_REQUESTED", message, context.request_id, operation_id, data=self._data(record))

    async def sync_research(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 2:
            return CommandResult(False, "INVALID_ALLIANCE", "请使用 `同步联盟配方 <联盟号> <recipe_key>`。", context.request_id)
        operation_id = self._operation_id(context, "social.sect_alliance.sync_research")
        try:
            record = await self.repository.sync_sect_alliance_research(platform=context.adapter, platform_user_id=context.user_id, alliance_id=context.command_args[0], recipe_key=context.command_args[1], operation_id=operation_id)
        except Exception as exc:
            return self._error(context, operation_id, exc)
        return CommandResult(True, "ALLIANCE_RESEARCH_SYNCED", f"已同步配方解锁标记 `{record.recipe_key}`，本周不会转移材料或资产。", context.request_id, operation_id, data={"alliance_id": record.alliance_id, "recipe_key": record.recipe_key, "week_id": record.week_id, "source_sect_id": record.source_sect_id, "target_sect_id": record.target_sect_id, "idempotent_replay": record.already_completed})


__all__ = ["SectAllianceApplication"]
