"""Adapter-neutral commands for the void-ruins team instance."""

from __future__ import annotations

from ...contracts import CommandContext, CommandResult
from ..persistence.errors import (
    OperationConflictError,
    ResourceInsufficientError,
    VoidRuinsBusyError,
    VoidRuinsNodeError,
    VoidRuinsNotFoundError,
    VoidRuinsNotReadyError,
    VoidRuinsQuotaError,
    VoidRuinsRequirementError,
)
from .secret_realm_rules import resolve_secret_realm
from .void_ruins_rules import (
    VOID_RUINS_CODEX,
    VOID_RUINS_KEY,
    VOID_RUINS_NODE_LABELS,
    VOID_RUINS_ROUTE_PERMISSION,
    resolve_void_ruins_node,
)


class VoidRuinsApplication:
    def __init__(self, repository):
        self.repository = repository

    @staticmethod
    def _operation_id(context: CommandContext, name: str) -> str:
        if context.operation_id:
            return context.operation_id
        return f"{name}:{context.adapter}:{context.user_id}:{context.message_id or context.request_id}"

    @staticmethod
    def _data(record) -> dict[str, object]:
        return {
            "run_id": record.run_id,
            "party_id": record.party_id,
            "instance_key": VOID_RUINS_KEY,
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
    def _label(node_key: str | None) -> str | None:
        return VOID_RUINS_NODE_LABELS.get(node_key or "", node_key)

    async def enter(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 1 or resolve_secret_realm(context.command_args[0]) != VOID_RUINS_KEY:
            return CommandResult(False, "INVALID_SECRET_REALM_COMMAND", "请使用 `进入秘境 虚空遗迹`。", context.request_id)
        operation_id = self._operation_id(context, "void_ruins.enter")
        try:
            record = await self.repository.enter_void_ruins(
                platform=context.adapter, platform_user_id=context.user_id, operation_id=operation_id,
            )
        except VoidRuinsRequirementError:
            return CommandResult(False, "VOID_RUINS_REQUIREMENT_MISSING", "需由专用队伍队长在档案遗迹启动；全员需炼虚 L1、各持 1 枚虚空锚。", context.request_id, operation_id)
        except VoidRuinsBusyError:
            return CommandResult(False, "VOID_RUINS_BUSY", "至少一名队员已有冲突行动、秘境或战斗资产锁。", context.request_id, operation_id)
        except VoidRuinsQuotaError:
            return CommandResult(False, "VOID_RUINS_QUOTA_EXHAUSTED", "至少一名队员本 UTC 周已进入虚空遗迹秘境。", context.request_id, operation_id)
        except ResourceInsufficientError:
            return CommandResult(False, "RESOURCE_INSUFFICIENT", "队长体力不足，未扣除体力或托管虚空锚。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于不同的秘境操作。", context.request_id, operation_id)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "虚空遗迹秘境暂时不可用，请稍后重试。", context.request_id, operation_id, retryable=True)
        return CommandResult(
            True,
            "VOID_RUINS_ENTERED",
            "## 虚空遗迹秘境已开启\n\n队长已支付体力 50；全员各托管虚空锚 1 枚，终态返还。"
            f"\n\n- **下一节点**：{self._label(record.current_node)}\n- **有效期**：{record.expires_at}"
            "\n\n> 队长按服务端路线推进；任一队员可续跑自动战与最终结算。",
            context.request_id, operation_id, data=self._data(record),
        )

    async def choose_node(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 1 or not (node_key := resolve_void_ruins_node(context.command_args[0])):
            return CommandResult(False, "INVALID_SECRET_REALM_COMMAND", "请按服务端显示的顺序选择虚空遗迹节点。", context.request_id)
        operation_id = self._operation_id(context, "void_ruins.choose_node")
        try:
            record = await self.repository.choose_void_ruins_node(
                platform=context.adapter,
                platform_user_id=context.user_id,
                node_key=node_key,
                operation_id=operation_id,
            )
        except VoidRuinsRequirementError:
            return CommandResult(False, "VOID_RUINS_PERMISSION_DENIED", "只有虚空遗迹队长可以推进路线。", context.request_id, operation_id)
        except VoidRuinsNodeError:
            return CommandResult(False, "VOID_RUINS_NODE_FORBIDDEN", "只能按固定十节点顺序推进。", context.request_id, operation_id)
        except VoidRuinsNotFoundError:
            return CommandResult(False, "VOID_RUINS_NOT_FOUND", "当前没有进行中的虚空遗迹秘境。", context.request_id, operation_id)
        except VoidRuinsNotReadyError:
            return CommandResult(False, "VOID_RUINS_NOT_READY", "秘境已过期、尚未进入，或当前节点不能推进。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于不同的秘境操作。", context.request_id, operation_id)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "虚空遗迹路线暂时不可用，请稍后重试。", context.request_id, operation_id, retryable=True)
        if record.status == "expired":
            return CommandResult(False, "VOID_RUINS_EXPIRED", "秘境已过期；体力与周额度不退，托管虚空锚已返还。", context.request_id, operation_id, data=self._data(record))
        if record.status == "combat_pending":
            return CommandResult(
                True,
                "VOID_RUINS_COMBAT_PENDING",
                f"## {self._label(node_key)}\n\n服务器已创建自动队伍战 `{record.battle_id}`。发送 `结算秘境` 推进战斗；客户端不能提交行动或结果。",
                context.request_id, operation_id, data=self._data(record),
            )
        if record.status == "cleared":
            text = "## 虚空遗迹路线完成\n\n发送 `结算秘境` 领取成员各自的首通权限/图鉴或重复材料。"
            code = "VOID_RUINS_ROUTE_CLEARED"
        else:
            text = f"## 节点已完成\n\n下一节点：**{self._label(record.current_node)}**。"
            code = "VOID_RUINS_NODE_SELECTED"
        return CommandResult(True, code, text, context.request_id, operation_id, data=self._data(record))

    async def settle(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_SECRET_REALM_COMMAND", "结算秘境无需附加参数。", context.request_id)
        operation_id = self._operation_id(context, "void_ruins.settle")
        try:
            record = await self.repository.settle_void_ruins(
                platform=context.adapter, platform_user_id=context.user_id, operation_id=operation_id,
            )
        except VoidRuinsNotFoundError:
            return CommandResult(False, "VOID_RUINS_NOT_FOUND", "当前没有等待结算的虚空遗迹秘境。", context.request_id, operation_id)
        except VoidRuinsNotReadyError:
            return CommandResult(False, "VOID_RUINS_NOT_READY", "请先按路线完成全部节点和两场自动战。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于不同的秘境操作。", context.request_id, operation_id)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "虚空遗迹结算暂时不可用，请稍后重试。", context.request_id, operation_id, retryable=True)
        if record.status == "routing":
            return CommandResult(
                True, "VOID_RUINS_BATTLE_SETTLED",
                f"## 自动战已结算\n\n- **结果**：胜利\n- **下一节点**：{self._label(record.current_node)}",
                context.request_id, operation_id, data=self._data(record),
            )
        if record.status == "settled":
            message = (
                "## 虚空遗迹秘境已结算\n\n"
                f"- **结果**：完成\n- **首通成员**：{len(record.first_clear_members)} 人\n"
                "- **全员奖励**：虚空晶 ×1\n"
                f"- **首通权限**：`{VOID_RUINS_ROUTE_PERMISSION}`\n"
                f"- **展示记录**：`{VOID_RUINS_CODEX}`"
            )
        else:
            outcome = {"failed": "战败", "expired": "过期", "system_aborted": "系统中止"}.get(record.status, record.outcome or record.status)
            cost = "系统故障已补偿体力并释放周额度。" if record.status == "system_aborted" else "体力与周额度不退，托管锚已返还。"
            message = f"## 虚空遗迹秘境未完成\n\n- **结果**：{outcome}\n- **资源**：{cost}"
        return CommandResult(True, "VOID_RUINS_SETTLED", message, context.request_id, operation_id, data=self._data(record))


__all__ = ["VoidRuinsApplication"]
