"""Adapter-neutral commands for the demon legacy manor."""

from __future__ import annotations

from ...contracts import CommandContext, CommandResult
from ..persistence.errors import (
    LegacyManorBusyError,
    LegacyManorNodeError,
    LegacyManorNotFoundError,
    LegacyManorNotReadyError,
    LegacyManorQuotaError,
    LegacyManorRequirementError,
    OperationConflictError,
    PlayerNotFoundError,
    PlayerSuspendedError,
)
from .legacy_manor_rules import LEGACY_MANOR_KEY, LEGACY_MANOR_NODE_LABELS, resolve_legacy_manor_node


class LegacyManorApplication:
    def __init__(self, repository):
        self.repository = repository

    @staticmethod
    def _operation_id(context: CommandContext, name: str) -> str:
        return context.operation_id or f"{name}:{context.adapter}:{context.user_id}:{context.message_id or context.request_id}"

    @staticmethod
    def _data(record) -> dict[str, object]:
        return {
            "run_id": record.run_id,
            "instance_key": LEGACY_MANOR_KEY,
            "status": record.status,
            "node_index": record.node_index,
            "current_node": record.current_node,
            "expires_at": record.expires_at,
            "outcome": record.outcome,
            "first_clear": record.first_clear,
            "story_flag_written": record.story_flag_written,
            "idempotent_replay": record.already_completed,
        }

    @staticmethod
    def _label(node: str | None) -> str | None:
        return LEGACY_MANOR_NODE_LABELS.get(node or "", node)

    async def status(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_LEGACY_MANOR_COMMAND", "`遗府状态` 无需附加参数。", context.request_id)
        try:
            record = await self.repository.get_legacy_manor_status(
                platform=context.adapter, platform_user_id=context.user_id
            )
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能查看遗府。", context.request_id)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "遗府状态暂时不可用，请稍后重试。", context.request_id, retryable=True)
        if record is None:
            return CommandResult(False, "LEGACY_MANOR_NOT_FOUND", "当前没有进行中的遗府。", context.request_id)
        if record.status == "expired":
            message = "## 遗府已过期\n\n发送 `结算遗府` 关闭本次记录；没有资源需要返还。"
        elif record.status == "cleared":
            message = "## 遗府路线已完成\n\n发送 `结算遗府` 记录首通故事旗标。"
        else:
            message = (
                f"## 遗府进行中\n\n- **当前节点**：{self._label(record.current_node)}\n"
                f"- **有效期**：{record.expires_at}\n\n发送 `选择遗府节点 <当前节点>` 继续。"
            )
        return CommandResult(True, "LEGACY_MANOR_STATUS", message, context.request_id, data=self._data(record))

    async def enter(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_LEGACY_MANOR_COMMAND", "`进入遗府` 无需附加参数。", context.request_id)
        operation_id = self._operation_id(context, "legacy_manor.enter")
        try:
            record = await self.repository.enter_legacy_manor(
                platform=context.adapter, platform_user_id=context.user_id, operation_id=operation_id
            )
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能进入遗府。", context.request_id, operation_id)
        except LegacyManorRequirementError:
            return CommandResult(False, "LEGACY_MANOR_REQUIREMENT_MISSING", "需要元婴 L1、堕落遗迹地点权限和魔界契约线索；未消耗线索或资源。", context.request_id, operation_id)
        except LegacyManorBusyError:
            return CommandResult(False, "LEGACY_MANOR_BUSY", "当前已有其他进行中的行动或遗府。", context.request_id, operation_id)
        except LegacyManorQuotaError:
            return CommandResult(False, "LEGACY_MANOR_ALREADY_CLEARED", "这处遗府已完成首通，不可再次进入。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于其他遗府操作。", context.request_id, operation_id)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "遗府入口暂时不可用，请稍后重试。", context.request_id, operation_id, retryable=True)
        return CommandResult(
            True,
            "LEGACY_MANOR_ENTERED",
            f"## 已发现魔界遗府\n\n- **下一节点**：{self._label(record.current_node)}\n- **有效期**：{record.expires_at}\n\n> 契约线索仅用于准入，没有消耗。",
            context.request_id,
            operation_id,
            data=self._data(record),
        )

    async def choose_node(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 1 or not (node_key := resolve_legacy_manor_node(context.command_args[0])):
            return CommandResult(False, "INVALID_LEGACY_MANOR_COMMAND", "请按服务端显示的顺序选择遗府节点。", context.request_id)
        operation_id = self._operation_id(context, "legacy_manor.choose_node")
        try:
            record = await self.repository.choose_legacy_manor_node(
                platform=context.adapter,
                platform_user_id=context.user_id,
                node_key=node_key,
                operation_id=operation_id,
            )
        except LegacyManorNodeError:
            return CommandResult(False, "LEGACY_MANOR_NODE_FORBIDDEN", "只能按三节点固定顺序推进遗府。", context.request_id, operation_id)
        except LegacyManorNotFoundError:
            return CommandResult(False, "LEGACY_MANOR_NOT_FOUND", "当前没有进行中的遗府。", context.request_id, operation_id)
        except LegacyManorNotReadyError:
            return CommandResult(False, "LEGACY_MANOR_NOT_READY", "遗府已过期或当前节点不能推进。", context.request_id, operation_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能推进遗府。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于不同的遗府操作。", context.request_id, operation_id)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "遗府路线暂时不可用，请稍后重试。", context.request_id, operation_id, retryable=True)
        if record.status == "expired":
            return CommandResult(False, "LEGACY_MANOR_EXPIRED", "遗府已过期，未获得故事记录；没有资源需要返还。", context.request_id, operation_id, data=self._data(record))
        if record.status == "cleared":
            return CommandResult(True, "LEGACY_MANOR_ROUTE_CLEARED", "## 遗府路线完成\n\n发送 `结算遗府` 写入首通故事记录。", context.request_id, operation_id, data=self._data(record))
        return CommandResult(True, "LEGACY_MANOR_NODE_SELECTED", f"## 节点已完成\n\n下一节点：**{self._label(record.current_node)}**。", context.request_id, operation_id, data=self._data(record))

    async def settle(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_LEGACY_MANOR_COMMAND", "`结算遗府` 无需附加参数。", context.request_id)
        operation_id = self._operation_id(context, "legacy_manor.settle")
        try:
            record = await self.repository.settle_legacy_manor(
                platform=context.adapter, platform_user_id=context.user_id, operation_id=operation_id
            )
        except LegacyManorNotFoundError:
            return CommandResult(False, "LEGACY_MANOR_NOT_FOUND", "当前没有等待结算的遗府。", context.request_id, operation_id)
        except LegacyManorNotReadyError:
            return CommandResult(False, "LEGACY_MANOR_NOT_READY", "请先按路线完成三个节点，再结算遗府。", context.request_id, operation_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能结算遗府。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于不同的遗府结算。", context.request_id, operation_id)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "遗府结算暂时不可用，请稍后重试。", context.request_id, operation_id, retryable=True)
        outcome = {"won": "成功", "expired": "过期", "system_aborted": "系统中止"}.get(record.outcome or "", "未完成")
        return CommandResult(
            True,
            "LEGACY_MANOR_SETTLED",
            f"## 遗府已结算\n\n- **结果**：{outcome}\n- **故事旗标**：{'已写入 `story.legacy.demon_reliquary`' if record.story_flag_written else '未新增'}\n\n> 本遗府不发放或扣除任何资产。",
            context.request_id,
            operation_id,
            data=self._data(record),
        )


__all__ = ["LegacyManorApplication"]
