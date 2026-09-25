"""Application service for cave facility slot claims."""

from __future__ import annotations

from ...contracts import CommandContext, CommandResult
from ..repository import (
    FacilityOwnerRequirementError,
    FacilitySlotOccupiedError,
    FacilitySlotNotFoundError,
    OperationConflictError,
    PlayerNotFoundError,
    PlayerSuspendedError,
    RepositoryBusyError,
)
from .facility_rules import resolve_facility


class FacilityApplication:
    """Translate the facility claim command into an adapter-neutral result."""

    def __init__(self, repository):
        self.repository = repository

    @staticmethod
    def _operation_id(context: CommandContext) -> str:
        if context.operation_id:
            return context.operation_id
        request_key = context.message_id or context.request_id
        return f"production.claim_facility_slot:{context.adapter}:{context.user_id}:{request_key}"

    async def claim_facility_slot(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) not in {1, 2}:
            return CommandResult(False, "INVALID_FACILITY_COMMAND", "请指定设施，例如 `认领设施槽位 炼丹房`。", context.request_id)
        try:
            definition = resolve_facility(context.command_args[0])
        except ValueError:
            return CommandResult(False, "FACILITY_SLOT_NOT_FOUND", "未找到这个洞天设施槽位。", context.request_id)
        owner_type = "personal"
        if len(context.command_args) == 2:
            owner_type = {"个人": "personal", "宗门": "sect", "personal": "personal", "sect": "sect"}.get(
                context.command_args[1], ""
            )
            if not owner_type:
                return CommandResult(False, "FACILITY_OWNER_INVALID", "所有者只能是个人或宗门。", context.request_id)
        operation_id = self._operation_id(context)
        try:
            record = await self.repository.claim_facility_slot(
                platform=context.adapter,
                platform_user_id=context.user_id,
                facility_key=definition.slot_key,
                owner_type=owner_type,
                operation_id=operation_id,
            )
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except FacilitySlotNotFoundError:
            return CommandResult(False, "FACILITY_SLOT_NOT_FOUND", "未找到这个洞天设施槽位。", context.request_id, operation_id)
        except FacilitySlotOccupiedError:
            return CommandResult(False, "FACILITY_SLOT_OCCUPIED", "这个设施槽位已被其他所有者锁定。", context.request_id, operation_id)
        except FacilityOwnerRequirementError:
            return CommandResult(False, "FACILITY_OWNER_INVALID", "需要位于洞天二层；宗门所有者还需要有效的宗门成员资格。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能认领设施。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于其他设施操作，请重新发起。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        owner_label = "宗门" if record.owner_type == "sect" else "个人"
        return CommandResult(
            True,
            "FACILITY_SLOT_CLAIMED",
            f"## 设施槽位已锁定\n\n**{record.name}**已由{owner_label}所有者启用。每日维护费 100 灵石；维护不足时设施会暂停，但不会取消进行中的订单。",
            context.request_id,
            operation_id,
            data={
                "slot_key": record.slot_key,
                "facility_kind": record.facility_kind,
                "owner_type": record.owner_type,
                "owner_id": record.owner_id,
                "status": record.status,
                "idempotent_replay": record.already_completed,
            },
        )


__all__ = ["FacilityApplication"]
