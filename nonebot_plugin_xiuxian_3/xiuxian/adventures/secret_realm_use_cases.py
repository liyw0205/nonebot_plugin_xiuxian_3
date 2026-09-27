"""Adapter-neutral commands for v0.1 secret realms."""

from __future__ import annotations

from ...contracts import CommandContext, CommandResult
from ..repository import SQLitePlayerRepository
from ..persistence.errors import (
    OperationConflictError,
    PlayerNotFoundError,
    PlayerSuspendedError,
    RepositoryBusyError,
    ResourceInsufficientError,
    SecretRealmAlreadySettledError,
    SecretRealmBusyError,
    SecretRealmCombatPendingError,
    SecretRealmNodeError,
    SecretRealmNotFoundError,
    SecretRealmNotReadyError,
    SecretRealmQuotaError,
    SecretRealmRequirementError,
)
from .secret_realm_rules import resolve_node, resolve_secret_realm


ITEM_LABELS = {
    "spirit_stones": "灵石",
    "item.material.mist_core": "洞天材料",
    "item.herb.spirit_leaf": "灵叶",
    "codex.instance.mist_grotto": "图鉴记录",
    "local_reputation": "地方名望",
}


class SecretRealmApplication:
    def __init__(self, repository: SQLitePlayerRepository):
        self.repository = repository

    @staticmethod
    def _operation_id(context: CommandContext, name: str) -> str:
        if context.operation_id:
            return context.operation_id
        return f"{name}:{context.adapter}:{context.user_id}:{context.message_id or context.request_id}"

    @staticmethod
    def _display_name(player) -> str:
        value = player.dao_name or "未命名"
        return value.replace("\\", "\\\\").replace("`", "\\`").replace("*", "\\*").replace("_", "\\_").replace("~", "\\~")

    @staticmethod
    def _reward_text(reward: dict[str, int]) -> str:
        return "、".join(
            f"{ITEM_LABELS.get(key, key)} +{value}" for key, value in reward.items() if value
        ) or "无"

    async def preview(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_SECRET_REALM_COMMAND", "秘境预览无需附加参数。", context.request_id)
        try:
            record = await self.repository.preview_secret_realms(platform=context.adapter, platform_user_id=context.user_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能查看秘境。", context.request_id)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, retryable=True)
        lines = ["## 秘境试炼", "", f"**{self._display_name(record.player)}**，当前可查看以下秘境：", ""]
        data = []
        for definition in record.definitions:
            lines.extend(
                [
                    f"### {definition.label}",
                    f"- **前置**：{definition.required_realm} L{definition.required_layer} · {definition.location_key}",
                    f"- **路线**：{' → '.join(definition.node_keys)} · 体力 {definition.stamina_cost}",
                    f"- **首通**：{self._reward_text(definition.first_reward)}",
                    f"- **次数**：每{('日' if definition.quota_period == 'day' else '周')} {definition.quota_limit} 次",
                    "",
                ]
            )
            data.append({"instance_key": definition.key, "label": definition.label, "nodes": definition.node_keys, "stamina_cost": definition.stamina_cost, "ticket_key": definition.ticket_key, "first_reward": definition.first_reward, "repeat_reward": definition.repeat_reward, "quota_period": definition.quota_period, "quota_limit": definition.quota_limit})
        if record.active_run_id:
            lines.append(f"> 当前已有进行中的秘境：`{record.active_run_id}`。")
        else:
            lines.append("> 发送 `进入秘境 雾隐秘境` 或 `进入秘境 灵泉小径` 开始。")
        return CommandResult(True, "SECRET_REALM_PREVIEW", "\n".join(lines), context.request_id, data={"realms": data, "active_run_id": record.active_run_id})

    async def enter(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 1 or not (instance_key := resolve_secret_realm(context.command_args[0])):
            return CommandResult(False, "INVALID_SECRET_REALM_COMMAND", "请使用 `进入秘境 雾隐秘境` 或 `进入秘境 灵泉小径`。", context.request_id)
        operation_id = self._operation_id(context, "secret_realm.enter")
        try:
            record = await self.repository.enter_secret_realm(platform=context.adapter, platform_user_id=context.user_id, instance_key=instance_key, operation_id=operation_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色处于暂停状态，暂时不能进入秘境。", context.request_id, operation_id)
        except SecretRealmRequirementError:
            return CommandResult(False, "SECRET_REALM_REQUIREMENT_MISSING", "当前地点、境界或秘境凭证不满足要求，未扣除资源。", context.request_id, operation_id)
        except SecretRealmBusyError:
            return CommandResult(False, "SECRET_REALM_BUSY", "当前已有其他进行中的会话，暂时不能进入秘境。", context.request_id, operation_id)
        except SecretRealmQuotaError:
            return CommandResult(False, "SECRET_REALM_QUOTA_EXHAUSTED", "本周期的秘境次数已用尽。", context.request_id, operation_id)
        except ResourceInsufficientError:
            return CommandResult(False, "RESOURCE_INSUFFICIENT", "体力不足，未扣除任何资源。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于其他秘境操作，请重新发起。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "秘境入口暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        return CommandResult(True, "SECRET_REALM_ENTERED", f"## {record.label}已进入\n\n已锁定体力 {record.stamina_locked} 点和秘境凭证。\n\n- **下一节点**：{record.current_node}\n- **状态**：路线进行中\n\n> 发送 `选择秘境节点 资源` 按服务端顺序推进。", context.request_id, operation_id, data=self._data(record))

    async def choose_node(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 1 or not (node_key := resolve_node(context.command_args[0])):
            return CommandResult(False, "INVALID_SECRET_REALM_COMMAND", "请使用 `选择秘境节点 资源`、`遭遇` 或 `选择`。", context.request_id)
        operation_id = self._operation_id(context, "secret_realm.choose_node")
        try:
            record = await self.repository.choose_secret_realm_node(platform=context.adapter, platform_user_id=context.user_id, node_key=node_key, operation_id=operation_id)
        except SecretRealmNodeError:
            return CommandResult(False, "SECRET_REALM_NODE_FORBIDDEN", "只能选择服务端当前允许的节点，不能跳跃路线。", context.request_id, operation_id)
        except SecretRealmNotFoundError:
            return CommandResult(False, "SECRET_REALM_NOT_FOUND", "当前没有进行中的秘境。", context.request_id, operation_id)
        except SecretRealmNotReadyError:
            return CommandResult(False, "SECRET_REALM_NOT_READY", "当前秘境已过期或尚未到达可选择节点。", context.request_id, operation_id)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "秘境路线暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        if record.status == "combat_pending":
            return CommandResult(True, "SECRET_REALM_COMBAT_PENDING", f"## {record.label}遭遇战\n\n服务器已创建自动战斗会话 ` {record.battle_id or 'pending'} `。\n\n> 发送 `结算秘境` 推进并结算遭遇战；客户端不能提交攻击、目标或结果。", context.request_id, operation_id, data=self._data(record))
        if record.status == "cleared":
            text = f"## {record.label}路线完成\n\n所有节点已通过，发送 `结算秘境` 领取首通或重复挑战奖励。"
        else:
            text = f"## 节点已完成\n\n下一节点：**{record.current_node}**。"
        return CommandResult(True, "SECRET_REALM_NODE_SELECTED", text, context.request_id, operation_id, data=self._data(record))

    async def settle(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_SECRET_REALM_COMMAND", "结算秘境无需附加参数。", context.request_id)
        operation_id = self._operation_id(context, "secret_realm.settle")
        try:
            record = await self.repository.settle_secret_realm(platform=context.adapter, platform_user_id=context.user_id, operation_id=operation_id)
        except SecretRealmNotFoundError:
            return CommandResult(False, "SECRET_REALM_NOT_FOUND", "当前没有等待结算的秘境。", context.request_id, operation_id)
        except SecretRealmCombatPendingError:
            return CommandResult(False, "SECRET_REALM_COMBAT_PENDING", "遭遇战仍在自动推进，请稍后重试。", context.request_id, operation_id, retryable=True)
        except SecretRealmNotReadyError:
            return CommandResult(False, "SECRET_REALM_NOT_READY", "请先按路线完成所有节点，再结算秘境。", context.request_id, operation_id)
        except SecretRealmAlreadySettledError:
            return CommandResult(False, "SECRET_REALM_ALREADY_SETTLED", "这次秘境已经结算。", context.request_id, operation_id)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "秘境结算暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        outcome = "失败" if record.status == "settled" and not record.reward else "完成"
        return CommandResult(True, "SECRET_REALM_SETTLED", f"## {record.label}已结算\n\n- **结果**：{outcome}\n- **奖励**：{self._reward_text(record.reward)}\n- **首通**：{'是' if record.first_clear and record.reward else '否'}\n\n> 同一 operation 会回放原结算，不会重复发放资产。", context.request_id, operation_id, data=self._data(record))

    @staticmethod
    def _data(record) -> dict[str, object]:
        return {"run_id": record.run_id, "instance_key": record.instance_key, "status": record.status, "node_index": record.node_index, "current_node": record.current_node, "allowed_nodes": list(record.allowed_nodes), "battle_id": record.battle_id, "reward": record.reward, "first_clear": record.first_clear, "ticket_locked": record.ticket_locked, "stamina_locked": record.stamina_locked, "outcome": record.outcome, "ticket_refunded": record.ticket_refunded, "stamina_refunded": record.stamina_refunded, "idempotent_replay": record.already_completed}


__all__ = ["SecretRealmApplication"]
