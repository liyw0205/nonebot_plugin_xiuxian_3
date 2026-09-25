"""Application commands for the void beacon."""

from __future__ import annotations

from ...contracts import CommandContext, CommandResult
from ..persistence.errors import (
    CrossServerFortressRequiredError,
    OperationConflictError,
    PlayerNotFoundError,
    PlayerSuspendedError,
    RepositoryBusyError,
    SectNotFoundError,
    SectPermissionDeniedError,
    VoidBeaconBuildError,
    VoidBeaconRequiredError,
)


class SectBeaconApplication:
    def __init__(self, repository):
        self.repository = repository

    @staticmethod
    def _operation_id(context: CommandContext, name: str) -> str:
        return context.operation_id or f"{name}:{context.adapter}:{context.user_id}:{context.message_id or context.request_id}"

    @staticmethod
    def _error(context: CommandContext, operation_id: str, exc: Exception) -> CommandResult:
        errors = {
            VoidBeaconRequiredError: ("VOID_BEACON_REQUIRED", "需要先建造并维护激活虚空堡垒与信标。"),
            CrossServerFortressRequiredError: ("SECT_FORTRESS_REQUIRED", "需要先建造并维护激活虚空堡垒。"),
            VoidBeaconBuildError: ("VOID_BEACON_BUILD_FAILED", "虚空信标建造或维护条件不足。"),
            SectPermissionDeniedError: ("SECT_PERMISSION_DENIED", "只有宗主或副宗主可以执行此操作。"),
            SectNotFoundError: ("SECT_NOT_FOUND", "你当前不在有效宗门中。"),
            PlayerNotFoundError: ("PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。"),
            PlayerSuspendedError: ("PLAYER_SUSPENDED", "当前角色暂时不能操作虚空信标。"),
            OperationConflictError: ("OPERATION_CONFLICT", "这次请求编号已经用于其他信标操作。"),
            RepositoryBusyError: ("PERSISTENCE_BUSY", "信标簿暂时繁忙，请稍后再试。"),
        }
        code, message = errors.get(type(exc), ("PERSISTENCE_ERROR", "信标簿暂时不可用，请稍后再试。"))
        return CommandResult(False, code, message, context.request_id, operation_id, retryable=isinstance(exc, RepositoryBusyError))

    async def get(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_VOID_BEACON", "虚空信标状态无需附加参数。", context.request_id)
        try:
            record = await self.repository.get_void_beacon(platform=context.adapter, platform_user_id=context.user_id)
        except Exception as exc:
            return self._error(context, "", exc)
        return CommandResult(True, "VOID_BEACON_STATUS", f"## 虚空信标\n\n- **状态**：{record.status}\n- **建造结束**：{record.build_ends_at or '已完成'}\n- **航道折扣**：{record.route_discount} 锚", context.request_id, data={"status": record.status, "build_ends_at": record.build_ends_at, "maintenance_due_at": record.maintenance_due_at, "route_discount": record.route_discount})

    async def build(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_VOID_BEACON", "建造虚空信标无需附加参数。", context.request_id)
        operation_id = self._operation_id(context, "social.sect_void_beacon.build")
        try:
            record = await self.repository.build_void_beacon(platform=context.adapter, platform_user_id=context.user_id, operation_id=operation_id)
        except Exception as exc:
            return self._error(context, operation_id, exc)
        return CommandResult(True, "VOID_BEACON_BUILDING", "虚空信标已进入 24 小时建造状态。", context.request_id, operation_id, data={"status": record.status, "build_ends_at": record.build_ends_at, "route_discount": record.route_discount})

    async def maintain(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_VOID_BEACON", "维护虚空信标无需附加参数。", context.request_id)
        operation_id = self._operation_id(context, "social.sect_void_beacon.maintain")
        try:
            record = await self.repository.maintain_void_beacon(platform=context.adapter, platform_user_id=context.user_id, operation_id=operation_id)
        except Exception as exc:
            return self._error(context, operation_id, exc)
        return CommandResult(True, "VOID_BEACON_MAINTAINED", "虚空信标维护完成。", context.request_id, operation_id, data={"status": record.status, "maintenance_due_at": record.maintenance_due_at, "route_discount": record.route_discount})


__all__ = ["SectBeaconApplication"]
