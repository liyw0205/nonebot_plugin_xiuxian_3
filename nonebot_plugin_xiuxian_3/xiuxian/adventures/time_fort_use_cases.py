"""Adapter-neutral commands for the time-fort instance."""

from __future__ import annotations

from ...contracts import CommandContext, CommandResult
from ..persistence.errors import (
    OperationConflictError,
    PlayerNotFoundError,
    ResourceInsufficientError,
    TimeFortBusyError,
    TimeFortNodeError,
    TimeFortNotFoundError,
    TimeFortNotReadyError,
    TimeFortQuotaError,
    TimeFortRequirementError,
)
from .secret_realm_rules import resolve_secret_realm
from .time_fort_rules import TIME_FORT_KEY, TIME_FORT_NODE_LABELS, TIME_FORT_NODES, resolve_time_fort_node


class TimeFortApplication:
    def __init__(self, repository):
        self.repository = repository

    @staticmethod
    def _operation_id(context: CommandContext, name: str) -> str:
        return context.operation_id or f"{name}:{context.adapter}:{context.user_id}:{context.message_id or context.request_id}"

    @staticmethod
    def _data(record) -> dict[str, object]:
        return {
            "run_id": record.run_id,
            "instance_key": TIME_FORT_KEY,
            "status": record.status,
            "node_index": record.node_index,
            "current_node": record.current_node,
            "battle_id": record.battle_id,
            "expires_at": record.expires_at,
            "rewards": record.rewards,
            "first_clear_members": list(record.first_clear_members),
            "outcome": record.outcome,
            "idempotent_replay": record.already_completed,
        }

    @staticmethod
    def _label(node: str | None) -> str:
        return TIME_FORT_NODE_LABELS.get(node or "", node or "未知")

    async def enter(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 1 or resolve_secret_realm(context.command_args[0]) != TIME_FORT_KEY:
            return CommandResult(False, "INVALID_SECRET_REALM_COMMAND", "请使用 `进入秘境 时序堡垒`。", context.request_id)
        operation_id = self._operation_id(context, "time_fort.enter")
        try:
            record = await self.repository.enter_time_fort(platform=context.adapter, platform_user_id=context.user_id, operation_id=operation_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except TimeFortRequirementError:
            return CommandResult(False, "TIME_FORT_REQUIREMENT_MISSING", "队伍、地点、境界或时序许可不满足要求，未扣除体力。", context.request_id, operation_id)
        except TimeFortBusyError:
            return CommandResult(False, "TIME_FORT_BUSY", "队员已有其他行动或锁定资产。", context.request_id, operation_id)
        except TimeFortQuotaError:
            return CommandResult(False, "TIME_FORT_QUOTA_EXHAUSTED", "本 UTC 周已有队员尝试时序堡垒秘境。", context.request_id, operation_id)
        except ResourceInsufficientError:
            return CommandResult(False, "RESOURCE_INSUFFICIENT", "队长体力不足，未扣除资源。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "此事已有安排，请重新起意。", context.request_id, operation_id)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "时序堡垒入口暂时不可用，请稍后重试。", context.request_id, operation_id, retryable=True)
        return CommandResult(True, "TIME_FORT_ENTERED", f"## 已进入时序堡垒秘境\n\n已扣除队长体力 40 点。\n\n- **下一节点**：{self._label(record.current_node)}\n- **有效期**：{record.expires_at}", context.request_id, operation_id, data=self._data(record))

    async def choose_node(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 1 or not (node_key := resolve_time_fort_node(context.command_args[0])):
            return CommandResult(False, "INVALID_SECRET_REALM_COMMAND", "请按服务端显示的顺序选择时序堡垒节点。", context.request_id)
        operation_id = self._operation_id(context, "time_fort.choose_node")
        try:
            record = await self.repository.choose_time_fort_node(platform=context.adapter, platform_user_id=context.user_id, node_key=node_key, operation_id=operation_id)
        except TimeFortNodeError:
            return CommandResult(False, "TIME_FORT_NODE_FORBIDDEN", "只能按六节点固定顺序推进时序堡垒。", context.request_id, operation_id)
        except TimeFortNotFoundError:
            return CommandResult(False, "TIME_FORT_NOT_FOUND", "当前没有进行中的时序堡垒秘境。", context.request_id, operation_id)
        except TimeFortNotReadyError:
            return CommandResult(False, "TIME_FORT_NOT_READY", "秘境已过期或当前节点尚未准备好。", context.request_id, operation_id)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "时序堡垒路线暂时不可用，请稍后重试。", context.request_id, operation_id, retryable=True)
        if record.status == "expired":
            return CommandResult(False, "TIME_FORT_EXPIRED", "秘境已过期；体力和本周额度不退。", context.request_id, operation_id, data=self._data(record))
        if record.status == "combat_pending":
            return CommandResult(True, "TIME_FORT_COMBAT_PENDING", f"## 时序守时者\n\n服务器已创建自动战斗 `{record.battle_id or 'pending'}`。发送 `结算秘境` 推进战斗。", context.request_id, operation_id, data=self._data(record))
        if record.status == "cleared":
            return CommandResult(True, "TIME_FORT_ROUTE_CLEARED", "## 时序堡垒路线完成\n\n发送 `结算秘境` 领取首通或重复奖励。", context.request_id, operation_id, data=self._data(record))
        return CommandResult(True, "TIME_FORT_NODE_SELECTED", f"## 节点已完成\n\n下一节点：**{self._label(record.current_node)}**。", context.request_id, operation_id, data=self._data(record))

    async def settle(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_SECRET_REALM_COMMAND", "结算秘境无需附加参数。", context.request_id)
        operation_id = self._operation_id(context, "time_fort.settle")
        try:
            record = await self.repository.settle_time_fort(platform=context.adapter, platform_user_id=context.user_id, operation_id=operation_id)
        except TimeFortNotFoundError:
            return CommandResult(False, "TIME_FORT_NOT_FOUND", "当前没有等待结算的时序堡垒秘境。", context.request_id, operation_id)
        except TimeFortNotReadyError:
            return CommandResult(False, "TIME_FORT_NOT_READY", "请先按路线完成节点或等待自动战结算。", context.request_id, operation_id)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "时序堡垒结算暂时不可用，请稍后重试。", context.request_id, operation_id, retryable=True)
        if record.status == "routing" and record.outcome == "won":
            return CommandResult(True, "TIME_FORT_BATTLE_SETTLED", f"## 时序守时者战斗已结算\n\n下一节点：**{self._label(record.current_node)}**。", context.request_id, operation_id, data=self._data(record))
        return CommandResult(True, "TIME_FORT_SETTLED", f"## 时序堡垒已结算\n\n- **结果**：{'成功' if record.outcome == 'won' else '未获得通关奖励'}\n- **奖励**：{record.rewards}\n- **首通成员**：{', '.join(record.first_clear_members) if record.first_clear_members else '无'}", context.request_id, operation_id, data=self._data(record))


__all__ = ["TimeFortApplication"]
