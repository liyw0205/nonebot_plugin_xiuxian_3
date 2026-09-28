"""Adapter-neutral commands for the v0.6 heaven-echo secret realm."""

from __future__ import annotations

from ...contracts import CommandContext, CommandResult
from ..persistence.errors import (
    HeavenEchoBusyError,
    HeavenEchoFinalBattleError,
    HeavenEchoNodeError,
    HeavenEchoNotFoundError,
    HeavenEchoNotReadyError,
    HeavenEchoRequirementError,
    OperationConflictError,
    PlayerNotFoundError,
    PlayerSuspendedError,
)
from .heaven_echo_rules import HEAVEN_ECHO_KEY, HEAVEN_ECHO_NODE_LABELS, resolve_heaven_echo_node
from .secret_realm_rules import resolve_secret_realm


class HeavenEchoApplication:
    def __init__(self, repository):
        self.repository = repository

    @staticmethod
    def _operation_id(context: CommandContext, name: str) -> str:
        return context.operation_id or f"{name}:{context.adapter}:{context.user_id}:{context.message_id or context.request_id}"

    @staticmethod
    def _data(record) -> dict[str, object]:
        return {
            "run_id": record.run_id,
            "instance_key": HEAVEN_ECHO_KEY,
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
        return HEAVEN_ECHO_NODE_LABELS.get(node or "", node)

    async def enter(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 1 or resolve_secret_realm(context.command_args[0]) != HEAVEN_ECHO_KEY:
            return CommandResult(False, "INVALID_SECRET_REALM_COMMAND", "请使用 `进入秘境 天劫回音`。", context.request_id)
        operation_id = self._operation_id(context, "heaven_echo.enter")
        try:
            record = await self.repository.enter_heaven_echo(platform=context.adapter, platform_user_id=context.user_id, operation_id=operation_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能进入天劫回音。", context.request_id, operation_id)
        except HeavenEchoRequirementError:
            return CommandResult(False, "HEAVEN_ECHO_REQUIREMENT_MISSING", "需要渡劫 L1，未扣除资源。", context.request_id, operation_id)
        except HeavenEchoFinalBattleError:
            return CommandResult(False, "HEAVEN_ECHO_FINAL_BATTLE_ACTIVE", "最终战进行中，不能同时进入天劫回音。", context.request_id, operation_id)
        except HeavenEchoBusyError:
            return CommandResult(False, "HEAVEN_ECHO_BUSY", "当前已有其他进行中的行动或秘境。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于其他秘境操作。", context.request_id, operation_id)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "天劫回音入口暂时不可用，请稍后重试。", context.request_id, operation_id, retryable=True)
        return CommandResult(True, "HEAVEN_ECHO_ENTERED", f"## 已进入天劫回音\n\n- **下一节点**：{self._label(record.current_node)}\n- **有效期**：{record.expires_at}\n\n> 此旁线不消耗体力，也不改变天劫债。", context.request_id, operation_id, data=self._data(record))

    async def choose_node(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 1 or not (node_key := resolve_heaven_echo_node(context.command_args[0])):
            return CommandResult(False, "INVALID_SECRET_REALM_COMMAND", "请按服务端显示的顺序选择天劫回音节点。", context.request_id)
        operation_id = self._operation_id(context, "heaven_echo.choose_node")
        try:
            record = await self.repository.choose_heaven_echo_node(platform=context.adapter, platform_user_id=context.user_id, node_key=node_key, operation_id=operation_id)
        except HeavenEchoNodeError:
            return CommandResult(False, "HEAVEN_ECHO_NODE_FORBIDDEN", "只能按三节点固定顺序推进天劫回音。", context.request_id, operation_id)
        except HeavenEchoNotFoundError:
            return CommandResult(False, "HEAVEN_ECHO_NOT_FOUND", "当前没有进行中的天劫回音。", context.request_id, operation_id)
        except HeavenEchoNotReadyError:
            return CommandResult(False, "HEAVEN_ECHO_NOT_READY", "秘境已过期或当前节点不能推进。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于不同的秘境操作。", context.request_id, operation_id)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "天劫回音路线暂时不可用，请稍后重试。", context.request_id, operation_id, retryable=True)
        if record.status == "expired":
            return CommandResult(False, "HEAVEN_ECHO_EXPIRED", "秘境已过期；本旁线没有资源可退。", context.request_id, operation_id, data=self._data(record))
        if record.status == "cleared":
            return CommandResult(True, "HEAVEN_ECHO_ROUTE_CLEARED", "## 天劫回音路线完成\n\n发送 `结算秘境` 写入首通结局旁线旗标。", context.request_id, operation_id, data=self._data(record))
        return CommandResult(True, "HEAVEN_ECHO_NODE_SELECTED", f"## 节点已完成\n\n下一节点：**{self._label(record.current_node)}**。", context.request_id, operation_id, data=self._data(record))

    async def settle(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_SECRET_REALM_COMMAND", "结算秘境无需附加参数。", context.request_id)
        operation_id = self._operation_id(context, "heaven_echo.settle")
        try:
            record = await self.repository.settle_heaven_echo(platform=context.adapter, platform_user_id=context.user_id, operation_id=operation_id)
        except HeavenEchoNotFoundError:
            return CommandResult(False, "HEAVEN_ECHO_NOT_FOUND", "当前没有等待结算的天劫回音。", context.request_id, operation_id)
        except HeavenEchoNotReadyError:
            return CommandResult(False, "HEAVEN_ECHO_NOT_READY", "请先按路线完成三个节点，再结算秘境。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于不同的结算操作。", context.request_id, operation_id)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "天劫回音结算暂时不可用，请稍后重试。", context.request_id, operation_id, retryable=True)
        outcome = {"won": "成功", "expired": "过期", "system_aborted": "系统中止"}.get(record.outcome or "", "未完成")
        return CommandResult(True, "HEAVEN_ECHO_SETTLED", f"## 天劫回音已结算\n\n- **结果**：{outcome}\n- **首通旁线旗标**：{'已写入 `story.heaven_echo`' if record.story_flag_written else '已记录，不重复发放'}\n\n> 天劫债、终局状态和飞升资源均未改变。", context.request_id, operation_id, data=self._data(record))


__all__ = ["HeavenEchoApplication"]
