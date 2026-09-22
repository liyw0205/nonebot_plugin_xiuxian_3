"""Application commands for previewing and completing world movement."""

from __future__ import annotations

from ...contracts import CommandContext, CommandResult, validate_command_identity
from ..repository import (
    CurrencyInsufficientError,
    LocationRequirementError,
    OperationConflictError,
    PlayerNotFoundError,
    PlayerStageConflictError,
    PlayerSuspendedError,
    RepositoryBusyError,
    ResourceInsufficientError,
    TravelBusyError,
    TravelNotFoundError,
    TravelNotReadyError,
    WeaknessActiveError,
    SQLitePlayerRepository,
)
from .rules import CAVE_LOCATION, destination_definition, resolve_destination

class WorldApplication:
    """Coordinates movement commands while keeping adapter text out of storage."""

    def __init__(self, repository: SQLitePlayerRepository):
        self.repository = repository

    @staticmethod
    def _operation_id(context: CommandContext, name: str) -> str:
        if context.operation_id:
            return context.operation_id
        request_key = context.message_id or context.request_id
        return f"{name}:{context.adapter}:{context.user_id}:{request_key}"

    @staticmethod
    def _display_name(player) -> str:
        value = player.dao_name or "未命名"
        return (
            value.replace("\\", "\\\\")
            .replace("`", "\\`")
            .replace("*", "\\*")
            .replace("_", "\\_")
            .replace("~", "\\~")
        )

    @staticmethod
    def _destination(args: tuple[str, ...]) -> str | None:
        if len(args) != 1:
            return None
        return resolve_destination(args[0])

    async def preview_travel(self, context: CommandContext) -> CommandResult:
        invalid = validate_command_identity(context)
        if invalid is not None:
            return invalid
        destination = self._destination(context.command_args)
        if destination is None:
            return CommandResult(False, "INVALID_DESTINATION", "请使用 `移动预览 雾隐洞天`。", context.request_id)
        try:
            record = await self.repository.preview_travel(
                platform=context.adapter,
                platform_user_id=context.user_id,
                destination=destination,
            )
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id)
        except LocationRequirementError:
            # The preview repository returns a normal record with missing gates;
            # this branch is reserved for an unknown or closed destination.
            return CommandResult(False, "LOCATION_NOT_FOUND", "暂时没有这个地点。", context.request_id)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, retryable=True)
        definition = destination_definition(destination)
        missing_labels = tuple(
            item.replace("qi_gathering", "聚气").replace("qi_sensing", "感气").replace("foundation", "筑基")
            for item in record.missing
        )
        missing = "、".join(missing_labels) if missing_labels else "无"
        message = (
            f"## {definition.label} · 移动预览\n\n"
            f"**{self._display_name(record.player)}**可以查看这条路线。\n\n"
            f"- **预计耗时**：{definition.duration_seconds // 60} 分钟\n"
            f"- **体力消耗**：{definition.stamina_cost}\n"
            f"- **灵石消耗**：{definition.currency_cost}\n"
            f"- **凭证**：{definition.pass_key and '洞天凭证 ×' + str(definition.pass_quantity) or '无'}\n"
            f"- **当前缺少**：{missing}\n\n"
            f"> {'发送 `前往 雾隐洞天` 开始移动。' if record.ready else '满足条件后才可创建移动会话。'}"
        )
        return CommandResult(True, "TRAVEL_PREVIEW", message, context.request_id, data={
            "destination": destination,
            "ready": record.ready,
            "missing": record.missing,
            "duration_seconds": definition.duration_seconds,
            "stamina_cost": definition.stamina_cost,
            "currency_cost": definition.currency_cost,
        })

    async def start_travel(self, context: CommandContext, destination: str | None = None) -> CommandResult:
        invalid = validate_command_identity(
            context,
            require_write=True,
            write_message="当前事件不允许开始移动。",
        )
        if invalid is not None:
            return invalid
        destination = destination or (self._destination(context.command_args) or "")
        if not destination:
            return CommandResult(False, "INVALID_DESTINATION", "请使用 `前往 雾隐洞天`。", context.request_id)
        resolved = resolve_destination(destination)
        if resolved is None:
            return CommandResult(False, "LOCATION_NOT_FOUND", "暂时没有这个地点。", context.request_id)
        operation_id = self._operation_id(context, "world.start_travel")
        try:
            record = await self.repository.start_travel(
                platform=context.adapter,
                platform_user_id=context.user_id,
                destination=resolved,
                operation_id=operation_id,
            )
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色处于暂停状态，暂时不能移动。", context.request_id, operation_id)
        except PlayerStageConflictError:
            return CommandResult(False, "LOCATION_LOCKED", "完成入道后才能开始这段移动。", context.request_id, operation_id)
        except WeaknessActiveError:
            return CommandResult(False, "PLAYER_OCCUPIED", "突破虚弱期间不能前往雾隐洞天，请先恢复状态。", context.request_id, operation_id)
        except LocationRequirementError:
            return CommandResult(False, "LOCATION_REQUIREMENT_MISSING", "当前境界、来源地点或凭证不满足进入条件。", context.request_id, operation_id)
        except TravelBusyError:
            return CommandResult(False, "TRAVEL_BUSY", "已有移动、修炼、生产或突破会话，请先完成后再试。", context.request_id, operation_id)
        except ResourceInsufficientError:
            return CommandResult(False, "TRAVEL_RESOURCE_INSUFFICIENT", "体力不足，未扣除任何资源。", context.request_id, operation_id)
        except CurrencyInsufficientError:
            return CommandResult(False, "TRAVEL_RESOURCE_INSUFFICIENT", "灵石不足，未扣除任何资源。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于其他移动输入，请重新发起。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        definition = destination_definition(record.destination)
        return CommandResult(
            True,
            "TRAVEL_STARTED",
            (
                f"## 正在前往 {definition.label}\n\n"
                f"**{self._display_name(record.player)}**已开始移动。\n\n"
                f"- **预计耗时**：{definition.duration_seconds // 60} 分钟\n"
                f"- **体力**：{record.player.stamina}/{record.player.stamina_max}\n"
                f"- **灵石**：{record.player.spirit_stones}\n\n"
                "> 到达后发送 `结算移动`。移动期间不能修炼、生产、突破或再次移动。"
            ),
            context.request_id,
            operation_id,
            data={"session_id": record.session_id, "destination": record.destination, "status": record.status,
                  "ends_at": record.ends_at, "idempotent_replay": record.already_completed},
        )

    async def settle_travel(self, context: CommandContext) -> CommandResult:
        invalid = validate_command_identity(
            context,
            require_write=True,
            write_message="当前事件不允许结算移动。",
        )
        if invalid is not None:
            return invalid
        if context.command_args:
            return CommandResult(False, "INVALID_TRAVEL_COMMAND", "结算移动无需附加参数。", context.request_id)
        operation_id = self._operation_id(context, "world.settle_travel")
        try:
            record = await self.repository.settle_travel(
                platform=context.adapter,
                platform_user_id=context.user_id,
                operation_id=operation_id,
            )
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except TravelNotFoundError:
            return CommandResult(False, "TRAVEL_NOT_FOUND", "当前没有等待结算的移动。", context.request_id, operation_id)
        except TravelNotReadyError:
            return CommandResult(False, "TRAVEL_NOT_READY", "移动尚未到达，请稍后再来结算。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色处于暂停状态，暂时不能结算移动。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于其他移动结算，请重新发起。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        definition = destination_definition(record.destination)
        return CommandResult(
            True,
            "TRAVEL_COMPLETED",
            (
                f"## 已抵达 {definition.label}\n\n"
                f"**{self._display_name(record.player)}**已抵达目的地。\n\n"
                f"- **当前位置**：{definition.label}\n"
                f"- **体力**：{record.player.stamina}/{record.player.stamina_max}\n"
                f"- **灵石**：{record.player.spirit_stones}\n\n"
                "> 已写入位置状态，重复结算不会重复消耗资源。"
            ),
            context.request_id,
            operation_id,
            data={"session_id": record.session_id, "destination": record.destination, "status": record.status,
                  "arrived": record.arrived, "idempotent_replay": record.already_completed},
        )


__all__ = ["WorldApplication"]
