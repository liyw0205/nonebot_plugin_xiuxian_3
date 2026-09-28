"""Adapter-neutral commands for the ancestral-hall instance."""

from __future__ import annotations

from ...contracts import CommandContext, CommandResult
from ..persistence.errors import (
    AncestralHallBusyError,
    AncestralHallNodeError,
    AncestralHallNotFoundError,
    AncestralHallNotReadyError,
    AncestralHallQuotaError,
    AncestralHallRequirementError,
    OperationConflictError,
    ResourceInsufficientError,
)
from .ancestral_hall_rules import (
    ANCESTRAL_HALL_KEY,
    ANCESTRAL_HALL_NODE_LABELS,
    resolve_ancestral_hall_node,
)
from .secret_realm_rules import resolve_secret_realm


class AncestralHallApplication:
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
            "instance_key": ANCESTRAL_HALL_KEY,
            "status": record.status,
            "node_index": record.node_index,
            "current_node": record.current_node,
            "battle_id": record.battle_id,
            "outcome": record.outcome,
            "expires_at": record.expires_at,
            "first_clear": record.first_clear,
            "story_flag_written": record.story_flag_written,
            "idempotent_replay": record.already_completed,
        }

    @staticmethod
    def _label(node_key: str | None) -> str | None:
        return ANCESTRAL_HALL_NODE_LABELS.get(node_key or "", node_key)

    async def enter(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 1 or resolve_secret_realm(context.command_args[0]) != ANCESTRAL_HALL_KEY:
            return CommandResult(False, "INVALID_SECRET_REALM_COMMAND", "请使用 `进入秘境 祖灵殿`。", context.request_id)
        operation_id = self._operation_id(context, "ancestral_hall.enter")
        try:
            record = await self.repository.enter_ancestral_hall(
                platform=context.adapter, platform_user_id=context.user_id, operation_id=operation_id,
            )
        except AncestralHallRequirementError:
            return CommandResult(False, "ANCESTRAL_HALL_REQUIREMENT_MISSING", "地点、境界、妖界声望或血脉稳定不满足要求，未扣除体力。", context.request_id, operation_id)
        except AncestralHallBusyError:
            return CommandResult(False, "ANCESTRAL_HALL_BUSY", "当前已有其他进行中的行动或秘境。", context.request_id, operation_id)
        except AncestralHallQuotaError:
            return CommandResult(False, "ANCESTRAL_HALL_QUOTA_EXHAUSTED", "本 UTC 周已尝试祖灵殿秘境。", context.request_id, operation_id)
        except ResourceInsufficientError:
            return CommandResult(False, "RESOURCE_INSUFFICIENT", "体力不足，未扣除资源。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于其他秘境操作。", context.request_id, operation_id)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "祖灵殿秘境暂时不可用，请稍后重试。", context.request_id, operation_id, retryable=True)
        return CommandResult(
            True, "ANCESTRAL_HALL_ENTERED",
            "## 已进入祖灵殿秘境\n\n已扣除体力 25 点。\n\n"
            f"- **下一节点**：{self._label(record.current_node)}\n- **有效期**：{record.expires_at}\n\n"
            "> 每个 UTC 周限尝试一次；完成始祖祭坛后结算首通故事。",
            context.request_id, operation_id, data=self._data(record),
        )

    async def choose_node(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 1 or not (node_key := resolve_ancestral_hall_node(context.command_args[0])):
            return CommandResult(False, "INVALID_SECRET_REALM_COMMAND", "请按服务端显示的顺序选择祖灵殿节点。", context.request_id)
        operation_id = self._operation_id(context, "ancestral_hall.choose_node")
        try:
            record = await self.repository.choose_ancestral_hall_node(
                platform=context.adapter, platform_user_id=context.user_id, node_key=node_key,
                operation_id=operation_id,
            )
        except AncestralHallNodeError:
            return CommandResult(False, "ANCESTRAL_HALL_NODE_FORBIDDEN", "只能按五节点固定顺序推进祖灵殿。", context.request_id, operation_id)
        except AncestralHallNotFoundError:
            return CommandResult(False, "ANCESTRAL_HALL_NOT_FOUND", "当前没有进行中的祖灵殿秘境。", context.request_id, operation_id)
        except AncestralHallNotReadyError:
            return CommandResult(False, "ANCESTRAL_HALL_NOT_READY", "秘境已过期、尚未进入，或当前节点不能推进。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于不同的秘境操作。", context.request_id, operation_id)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "祖灵殿路线暂时不可用，请稍后重试。", context.request_id, operation_id, retryable=True)
        if record.status == "expired":
            return CommandResult(False, "ANCESTRAL_HALL_EXPIRED", "秘境已过期；入场体力和本周额度不退。", context.request_id, operation_id, data=self._data(record))
        if record.status == "combat_pending":
            text = f"## 祖灵殿守灵\n\n服务器已创建自动战斗 `{record.battle_id}`。发送 `结算秘境` 推进战斗；客户端不能提交行动或结果。"
            code = "ANCESTRAL_HALL_COMBAT_PENDING"
        elif record.status == "cleared":
            text = "## 始祖祭坛\n\n路线完成，发送 `结算秘境` 写入首次通关故事旗标。"
            code = "ANCESTRAL_HALL_ROUTE_CLEARED"
        else:
            text = f"## 节点已完成\n\n下一节点：**{self._label(record.current_node)}**。"
            code = "ANCESTRAL_HALL_NODE_SELECTED"
        return CommandResult(True, code, text, context.request_id, operation_id, data=self._data(record))

    async def settle(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_SECRET_REALM_COMMAND", "结算秘境无需附加参数。", context.request_id)
        operation_id = self._operation_id(context, "ancestral_hall.settle")
        try:
            record = await self.repository.settle_ancestral_hall(
                platform=context.adapter, platform_user_id=context.user_id, operation_id=operation_id,
            )
        except AncestralHallNotFoundError:
            return CommandResult(False, "ANCESTRAL_HALL_NOT_FOUND", "当前没有等待结算的祖灵殿秘境。", context.request_id, operation_id)
        except AncestralHallNotReadyError:
            return CommandResult(False, "ANCESTRAL_HALL_NOT_READY", "请先按路线完成全部节点和守灵自动战。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于不同的秘境操作。", context.request_id, operation_id)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "祖灵殿秘境结算暂时不可用，请稍后重试。", context.request_id, operation_id, retryable=True)
        if record.status == "routing":
            return CommandResult(True, "ANCESTRAL_HALL_BATTLE_SETTLED", f"## 守灵自动战已结算\n\n- **结果**：胜利\n- **下一节点**：{self._label(record.current_node)}", context.request_id, operation_id, data=self._data(record))
        if record.outcome == "won":
            message = "## 祖灵殿秘境已结算\n\n- **结果**：胜利\n- **故事旗标**：" + ("首次写入 `story.ancestral_hall`" if record.story_flag_written else "已记录，不重复发放")
        else:
            outcome = {"lost": "战败", "expired": "过期", "system_aborted": "系统中止"}.get(record.outcome or "", record.outcome or record.status)
            message = f"## 祖灵殿秘境未完成\n\n- **结果**：{outcome}\n- **资源**：体力与周尝试额度不退。"
        return CommandResult(True, "ANCESTRAL_HALL_SETTLED", message, context.request_id, operation_id, data=self._data(record))


__all__ = ["AncestralHallApplication"]
