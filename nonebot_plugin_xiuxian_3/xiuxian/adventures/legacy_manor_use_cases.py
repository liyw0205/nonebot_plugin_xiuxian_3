"""Adapter-neutral commands for clue-driven legacy manors."""

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
from .legacy_manor_rules import LEGACY_MANOR_KEY, get_legacy_manor_definition, resolve_legacy_manor_node


class LegacyManorApplication:
    def __init__(
        self,
        repository,
        *,
        instance_key: str = LEGACY_MANOR_KEY,
        display_name: str = "魔界遗府",
        enter_command: str = "进入遗府",
        status_command: str = "遗府状态",
        choose_command: str = "选择遗府节点",
        settle_command: str = "结算遗府",
    ):
        self.repository = repository
        self.definition = get_legacy_manor_definition(instance_key)
        self.display_name = display_name
        self.enter_command = enter_command
        self.status_command = status_command
        self.choose_command = choose_command
        self.settle_command = settle_command

    def _operation_id(self, context: CommandContext, action: str) -> str:
        name = f"{self.definition.operation_scope}.{action}"
        return context.operation_id or f"{name}:{context.adapter}:{context.user_id}:{context.message_id or context.request_id}"

    def _data(self, record) -> dict[str, object]:
        return {
            "run_id": record.run_id,
            "instance_key": self.definition.instance_key,
            "status": record.status,
            "node_index": record.node_index,
            "current_node": record.current_node,
            "expires_at": record.expires_at,
            "outcome": record.outcome,
            "first_clear": record.first_clear,
            "story_flag_written": record.story_flag_written,
            "idempotent_replay": record.already_completed,
        }

    def _label(self, node: str | None) -> str | None:
        return self.definition.labels.get(node or "", node)

    async def status(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_LEGACY_MANOR_COMMAND", f"`{self.status_command}` 无需附加参数。", context.request_id)
        try:
            record = await self.repository.get_legacy_manor_status(
                platform=context.adapter,
                platform_user_id=context.user_id,
                instance_key=self.definition.instance_key,
            )
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", f"当前角色暂时不能查看{self.display_name}。", context.request_id)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", f"{self.display_name}状态暂时不可用，请稍后重试。", context.request_id, retryable=True)
        if record is None:
            return CommandResult(False, "LEGACY_MANOR_NOT_FOUND", f"当前没有进行中的{self.display_name}。", context.request_id)
        if record.status == "expired":
            message = f"## {self.display_name}已过期\n\n发送 `{self.settle_command}` 关闭本次记录；没有资源需要返还。"
        elif record.status == "cleared":
            message = f"## {self.display_name}路线已完成\n\n发送 `{self.settle_command}` 记录首通故事旗标。"
        else:
            message = (
                f"## {self.display_name}进行中\n\n- **当前节点**：{self._label(record.current_node)}\n"
                f"- **有效期**：{record.expires_at}\n\n发送 `{self.choose_command} <当前节点>` 继续。"
            )
        return CommandResult(True, "LEGACY_MANOR_STATUS", message, context.request_id, data=self._data(record))

    async def enter(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_LEGACY_MANOR_COMMAND", f"`{self.enter_command}` 无需附加参数。", context.request_id)
        operation_id = self._operation_id(context, "enter")
        try:
            record = await self.repository.enter_legacy_manor(
                platform=context.adapter,
                platform_user_id=context.user_id,
                operation_id=operation_id,
                instance_key=self.definition.instance_key,
            )
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", f"当前角色暂时不能进入{self.display_name}。", context.request_id, operation_id)
        except LegacyManorRequirementError:
            return CommandResult(False, "LEGACY_MANOR_REQUIREMENT_MISSING", f"未满足{self.display_name}的境界、地点、权限或线索要求；未消耗线索或资源。", context.request_id, operation_id)
        except LegacyManorBusyError:
            return CommandResult(False, "LEGACY_MANOR_BUSY", "当前已有其他进行中的行动或遗府。", context.request_id, operation_id)
        except LegacyManorQuotaError:
            return CommandResult(False, "LEGACY_MANOR_ALREADY_CLEARED", "这处遗府已完成首通，不可再次进入。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "此事已有安排，请重新起意。", context.request_id, operation_id)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", f"{self.display_name}入口暂时不可用，请稍后重试。", context.request_id, operation_id, retryable=True)
        return CommandResult(
            True,
            "LEGACY_MANOR_ENTERED",
            f"## 已发现{self.display_name}\n\n- **下一节点**：{self._label(record.current_node)}\n- **有效期**：{record.expires_at}\n\n> 绑定线索仅用于准入，没有消耗。",
            context.request_id,
            operation_id,
            data=self._data(record),
        )

    async def choose_node(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 1 or not (
            node_key := resolve_legacy_manor_node(context.command_args[0], self.definition.instance_key)
        ):
            return CommandResult(False, "INVALID_LEGACY_MANOR_COMMAND", "请按服务端显示的顺序选择遗府节点。", context.request_id)
        operation_id = self._operation_id(context, "choose_node")
        try:
            record = await self.repository.choose_legacy_manor_node(
                platform=context.adapter,
                platform_user_id=context.user_id,
                node_key=node_key,
                operation_id=operation_id,
                instance_key=self.definition.instance_key,
            )
        except LegacyManorNodeError:
            return CommandResult(False, "LEGACY_MANOR_NODE_FORBIDDEN", "只能按固定节点顺序推进遗府。", context.request_id, operation_id)
        except LegacyManorNotFoundError:
            return CommandResult(False, "LEGACY_MANOR_NOT_FOUND", f"当前没有进行中的{self.display_name}。", context.request_id, operation_id)
        except LegacyManorNotReadyError:
            return CommandResult(False, "LEGACY_MANOR_NOT_READY", f"{self.display_name}已过期或当前节点不能推进。", context.request_id, operation_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", f"当前角色暂时不能推进{self.display_name}。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "此事与先前安排不合，请重新起意。", context.request_id, operation_id)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", f"{self.display_name}路线暂时不可用，请稍后重试。", context.request_id, operation_id, retryable=True)
        if record.status == "expired":
            return CommandResult(False, "LEGACY_MANOR_EXPIRED", f"{self.display_name}已过期，未获得故事记录；没有资源需要返还。", context.request_id, operation_id, data=self._data(record))
        if record.status == "cleared":
            return CommandResult(True, "LEGACY_MANOR_ROUTE_CLEARED", f"## {self.display_name}路线完成\n\n发送 `{self.settle_command}` 写入首通故事记录。", context.request_id, operation_id, data=self._data(record))
        return CommandResult(True, "LEGACY_MANOR_NODE_SELECTED", f"## 节点已完成\n\n下一节点：**{self._label(record.current_node)}**。", context.request_id, operation_id, data=self._data(record))

    async def settle(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_LEGACY_MANOR_COMMAND", f"`{self.settle_command}` 无需附加参数。", context.request_id)
        operation_id = self._operation_id(context, "settle")
        try:
            record = await self.repository.settle_legacy_manor(
                platform=context.adapter,
                platform_user_id=context.user_id,
                operation_id=operation_id,
                instance_key=self.definition.instance_key,
            )
        except LegacyManorNotFoundError:
            return CommandResult(False, "LEGACY_MANOR_NOT_FOUND", f"当前没有等待结算的{self.display_name}。", context.request_id, operation_id)
        except LegacyManorNotReadyError:
            return CommandResult(False, "LEGACY_MANOR_NOT_READY", "请先按路线完成三个节点，再结算遗府。", context.request_id, operation_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", f"当前角色暂时不能结算{self.display_name}。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "此事与先前安排不合，请重新起意。", context.request_id, operation_id)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", f"{self.display_name}结算暂时不可用，请稍后重试。", context.request_id, operation_id, retryable=True)
        outcome = {"won": "成功", "expired": "过期", "system_aborted": "系统中止"}.get(record.outcome or "", "未完成")
        story = f"已写入 `{self.definition.story_flag}`" if record.story_flag_written else "未新增"
        return CommandResult(
            True,
            "LEGACY_MANOR_SETTLED",
            f"## {self.display_name}已结算\n\n- **结果**：{outcome}\n- **故事旗标**：{story}\n\n> 本遗府不发放或扣除任何资产。",
            context.request_id,
            operation_id,
            data=self._data(record),
        )


__all__ = ["LegacyManorApplication"]
