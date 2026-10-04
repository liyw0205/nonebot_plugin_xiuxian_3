"""Adapter-neutral commands for the dao-origin secret realm."""

from __future__ import annotations

from ...contracts import CommandContext, CommandResult
from ..persistence.errors import (
    DaoOriginBusyError,
    DaoOriginNodeError,
    DaoOriginNotFoundError,
    DaoOriginNotReadyError,
    DaoOriginQuotaError,
    DaoOriginRequirementError,
    OperationConflictError,
    PlayerNotFoundError,
    PlayerSuspendedError,
    ResourceInsufficientError,
)
from .dao_origin_rules import DAO_ORIGIN_KEY, DAO_ORIGIN_NODE_LABELS, resolve_dao_origin_node
from .secret_realm_rules import resolve_secret_realm


class DaoOriginApplication:
    def __init__(self, repository):
        self.repository = repository

    @staticmethod
    def _operation_id(context: CommandContext, name: str) -> str:
        return context.operation_id or f"{name}:{context.adapter}:{context.user_id}:{context.message_id or context.request_id}"

    @staticmethod
    def _data(record) -> dict[str, object]:
        return {
            "run_id": record.run_id, "instance_key": DAO_ORIGIN_KEY, "status": record.status,
            "node_index": record.node_index, "current_node": record.current_node,
            "expires_at": record.expires_at, "outcome": record.outcome,
            "first_clear": record.first_clear, "story_flag_written": record.story_flag_written,
            "codex_written": record.codex_written, "idempotent_replay": record.already_completed,
        }

    @staticmethod
    def _label(node: str | None) -> str | None:
        return DAO_ORIGIN_NODE_LABELS.get(node or "", node)

    async def enter(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 1 or resolve_secret_realm(context.command_args[0]) != DAO_ORIGIN_KEY:
            return CommandResult(False, "INVALID_SECRET_REALM_COMMAND", "请使用 `进入秘境 道源秘境`。", context.request_id)
        operation_id = self._operation_id(context, "dao_origin.enter")
        try:
            record = await self.repository.enter_dao_origin(platform=context.adapter, platform_user_id=context.user_id, operation_id=operation_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能进入道源秘境。", context.request_id, operation_id)
        except DaoOriginRequirementError:
            return CommandResult(False, "DAO_ORIGIN_REQUIREMENT_MISSING", "需要位于道源门、合道 L1 且持有道源许可，未扣除体力。", context.request_id, operation_id)
        except DaoOriginBusyError:
            return CommandResult(False, "DAO_ORIGIN_BUSY", "当前已有其他进行中的行动或秘境。", context.request_id, operation_id)
        except DaoOriginQuotaError:
            return CommandResult(False, "DAO_ORIGIN_QUOTA_EXHAUSTED", "每个角色只能完成一次道源秘境。", context.request_id, operation_id)
        except ResourceInsufficientError:
            return CommandResult(False, "RESOURCE_INSUFFICIENT", "体力不足，未扣除资源。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "此事已有安排，请重新起意。", context.request_id, operation_id)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "道源秘境入口暂时不可用，请稍后重试。", context.request_id, operation_id, retryable=True)
        return CommandResult(True, "DAO_ORIGIN_ENTERED", f"## 已进入道源秘境\n\n已扣除体力 60 点。\n\n- **下一节点**：{self._label(record.current_node)}\n- **有效期**：{record.expires_at}", context.request_id, operation_id, data=self._data(record))

    async def choose_node(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 1 or not (node_key := resolve_dao_origin_node(context.command_args[0])):
            return CommandResult(False, "INVALID_SECRET_REALM_COMMAND", "请按服务端显示的顺序选择道源秘境节点。", context.request_id)
        operation_id = self._operation_id(context, "dao_origin.choose_node")
        try:
            record = await self.repository.choose_dao_origin_node(platform=context.adapter, platform_user_id=context.user_id, node_key=node_key, operation_id=operation_id)
        except DaoOriginNodeError:
            return CommandResult(False, "DAO_ORIGIN_NODE_FORBIDDEN", "只能按八节点固定顺序推进道源秘境。", context.request_id, operation_id)
        except DaoOriginNotFoundError:
            return CommandResult(False, "DAO_ORIGIN_NOT_FOUND", "当前没有进行中的道源秘境。", context.request_id, operation_id)
        except DaoOriginNotReadyError:
            return CommandResult(False, "DAO_ORIGIN_NOT_READY", "秘境已过期或当前节点不能推进。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "此事与先前安排不合，请重新起意。", context.request_id, operation_id)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "道源秘境路线暂时不可用，请稍后重试。", context.request_id, operation_id, retryable=True)
        if record.status == "expired":
            return CommandResult(False, "DAO_ORIGIN_EXPIRED", "秘境已过期；体力和一次性额度不退。", context.request_id, operation_id, data=self._data(record))
        if record.status == "cleared":
            return CommandResult(True, "DAO_ORIGIN_ROUTE_CLEARED", "## 道源秘境路线完成\n\n发送 `结算秘境` 领取首通新篇章线索与展示记录。", context.request_id, operation_id, data=self._data(record))
        return CommandResult(True, "DAO_ORIGIN_NODE_SELECTED", f"## 节点已完成\n\n下一节点：**{self._label(record.current_node)}**。", context.request_id, operation_id, data=self._data(record))

    async def settle(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_SECRET_REALM_COMMAND", "结算秘境无需附加参数。", context.request_id)
        operation_id = self._operation_id(context, "dao_origin.settle")
        try:
            record = await self.repository.settle_dao_origin(platform=context.adapter, platform_user_id=context.user_id, operation_id=operation_id)
        except DaoOriginNotFoundError:
            return CommandResult(False, "DAO_ORIGIN_NOT_FOUND", "当前没有等待结算的道源秘境。", context.request_id, operation_id)
        except DaoOriginNotReadyError:
            return CommandResult(False, "DAO_ORIGIN_NOT_READY", "请先按路线完成八个节点，再结算秘境。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "此事与先前安排不合，请重新起意。", context.request_id, operation_id)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "道源秘境结算暂时不可用，请稍后重试。", context.request_id, operation_id, retryable=True)
        outcome = {"won": "成功", "expired": "过期", "lost": "失败", "system_aborted": "系统中止"}.get(record.outcome or "", "未完成")
        return CommandResult(True, "DAO_ORIGIN_SETTLED", f"## 道源秘境已结算\n\n- **结果**：{outcome}\n- **首通故事**：{'已写入' if record.story_flag_written else '无重复发放'}\n- **展示图鉴**：{'已记录' if record.codex_written else '无重复发放'}", context.request_id, operation_id, data=self._data(record))


__all__ = ["DaoOriginApplication"]
