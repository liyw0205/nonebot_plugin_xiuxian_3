"""Adapter-neutral commands for the solo demon-abyss secret realm."""

from __future__ import annotations

from ...contracts import CommandContext, CommandResult
from ..persistence.errors import (
    DemonAbyssBusyError,
    DemonAbyssNodeError,
    DemonAbyssNotFoundError,
    DemonAbyssNotReadyError,
    DemonAbyssQuotaError,
    DemonAbyssRequirementError,
    OperationConflictError,
    PlayerNotFoundError,
    PlayerSuspendedError,
    RepositoryBusyError,
    ResourceInsufficientError,
)
from .demon_abyss_rules import (
    DEMON_ABYSS_ENEMIES,
    DEMON_ABYSS_EXPIRY_SECONDS,
    DEMON_ABYSS_FIRST_REWARD,
    DEMON_ABYSS_KEY,
    DEMON_ABYSS_LABEL,
    DEMON_ABYSS_NODES,
    DEMON_ABYSS_QUOTA_LIMIT,
    DEMON_ABYSS_REPEAT_REWARD,
    DEMON_ABYSS_RISK_MODIFIER_BP,
    DEMON_ABYSS_STAMINA_COST,
    resolve_demon_abyss,
    resolve_demon_abyss_node,
)


ITEM_LABELS = {
    "faction_reputation.demon": "魔界声望",
    "item.clue.demon_abyss_echo": "深渊残响线索",
    "item.demon_core": "魔核",
    "story.demon_abyss_echo": "深渊残响故事",
}


class DemonAbyssApplication:
    def __init__(self, repository):
        self.repository = repository

    @staticmethod
    def _operation_id(context: CommandContext, name: str) -> str:
        if context.operation_id:
            return context.operation_id
        return f"{name}:{context.adapter}:{context.user_id}:{context.message_id or context.request_id}"

    @staticmethod
    def _reward_text(reward: dict[str, int]) -> str:
        return "、".join(
            f"{ITEM_LABELS.get(key, key)} +{value}"
            for key, value in reward.items()
            if value
        ) or "无"

    @staticmethod
    def _data(record) -> dict[str, object]:
        return {
            "run_id": record.run_id,
            "instance_key": DEMON_ABYSS_KEY,
            "status": record.status,
            "node_index": record.node_index,
            "current_node": record.current_node,
            "allowed_nodes": list(record.allowed_nodes),
            "battle_id": record.battle_id,
            "reward": record.reward,
            "first_clear": record.first_clear,
            "outcome": record.outcome,
            "expires_at": record.expires_at,
            "pollution_before": record.pollution_before,
            "pollution_after": record.pollution_after,
            "risk_modifier_bp": DEMON_ABYSS_RISK_MODIFIER_BP,
            "risk_roll_bp": record.risk_roll_bp,
            "system_aborted": record.system_aborted,
            "idempotent_replay": record.already_completed,
        }

    async def has_active(self, context: CommandContext) -> bool:
        try:
            return await self.repository.has_active_demon_abyss(
                platform=context.adapter, platform_user_id=context.user_id
            )
        except PlayerNotFoundError:
            return False

    async def enter(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 1 or resolve_demon_abyss(context.command_args[0]) != DEMON_ABYSS_KEY:
            return CommandResult(False, "INVALID_SECRET_REALM_COMMAND", "请使用 `进入秘境 魔界深渊`。", context.request_id)
        operation_id = self._operation_id(context, "demon_abyss.enter")
        try:
            record = await self.repository.enter_demon_abyss(
                platform=context.adapter,
                platform_user_id=context.user_id,
                operation_id=operation_id,
            )
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能进入秘境。", context.request_id, operation_id)
        except DemonAbyssRequirementError:
            return CommandResult(False, "DEMON_ABYSS_REQUIREMENT_MISSING", "需在魔界深渊门达到筑基 L1、持有门禁并具备 200 点魔界声望；未扣除资源。", context.request_id, operation_id)
        except DemonAbyssBusyError:
            return CommandResult(False, "DEMON_ABYSS_BUSY", "当前已有进行中的长行动或秘境会话。", context.request_id, operation_id)
        except DemonAbyssQuotaError:
            return CommandResult(False, "DEMON_ABYSS_QUOTA_EXHAUSTED", "本 UTC 周的魔界深渊秘境次数已用尽。", context.request_id, operation_id)
        except ResourceInsufficientError:
            return CommandResult(False, "RESOURCE_INSUFFICIENT", "体力不足，未扣除资源。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "此事已有安排，请重新起意。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "魔界深渊秘境入口暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        return CommandResult(
            True,
            "DEMON_ABYSS_ENTERED",
            f"## {DEMON_ABYSS_LABEL}已进入\n\n已扣除体力 {DEMON_ABYSS_STAMINA_COST} 点，无需门票。\n\n"
            f"- **下一节点**：深渊门\n- **周额度**：本 UTC 周 1 次\n- **有效期**：{record.expires_at}\n\n"
            "> 请按顺序选择节点；遭遇战由服务器自动推进。",
            context.request_id,
            operation_id,
            data=self._data(record),
        )

    async def choose_node(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 1 or not (node_key := resolve_demon_abyss_node(context.command_args[0])):
            return CommandResult(False, "INVALID_SECRET_REALM_COMMAND", "请使用 `深渊门`、`污染渗流`、`残响守卫` 或 `深渊之心`。", context.request_id)
        operation_id = self._operation_id(context, "demon_abyss.choose_node")
        try:
            record = await self.repository.choose_demon_abyss_node(
                platform=context.adapter,
                platform_user_id=context.user_id,
                node_key=node_key,
                operation_id=operation_id,
            )
        except DemonAbyssNodeError:
            return CommandResult(False, "DEMON_ABYSS_NODE_FORBIDDEN", "只能按深渊门、污染渗流、残响守卫、深渊之心的顺序推进。", context.request_id, operation_id)
        except DemonAbyssNotFoundError:
            return CommandResult(False, "DEMON_ABYSS_NOT_FOUND", "当前没有进行中的魔界深渊秘境。", context.request_id, operation_id)
        except DemonAbyssNotReadyError:
            return CommandResult(False, "DEMON_ABYSS_NOT_READY", "秘境已过期或当前节点尚不能推进。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "此事已有安排，请重新起意。", context.request_id, operation_id)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "魔界深渊秘境节点暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        if record.status == "combat_pending":
            return CommandResult(
                True,
                "DEMON_ABYSS_COMBAT_PENDING",
                f"## {context.command_args[0]}遭遇战\n\n服务器已创建自动战斗会话 `{record.battle_id}`。发送 `结算秘境` 推进战斗；客户端不能提交攻击或结果。",
                context.request_id,
                operation_id,
                data=self._data(record),
            )
        risk_line = ""
        if node_key == "pollution_seep":
            risk_line = f"\n- **污染判定**：{record.risk_roll_bp} bp roll；污染 {record.pollution_before} → {record.pollution_after}"
        return CommandResult(
            True,
            "DEMON_ABYSS_NODE_SELECTED",
            f"## 节点已完成{risk_line}\n\n下一节点：**{record.current_node or '结算秘境'}**。",
            context.request_id,
            operation_id,
            data=self._data(record),
        )

    async def settle(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_SECRET_REALM_COMMAND", "结算秘境无需附加参数。", context.request_id)
        operation_id = self._operation_id(context, "demon_abyss.settle")
        try:
            record = await self.repository.settle_demon_abyss(
                platform=context.adapter,
                platform_user_id=context.user_id,
                operation_id=operation_id,
            )
        except DemonAbyssNotFoundError:
            return CommandResult(False, "DEMON_ABYSS_NOT_FOUND", "当前没有等待结算的魔界深渊秘境。", context.request_id, operation_id)
        except DemonAbyssNotReadyError:
            return CommandResult(False, "DEMON_ABYSS_NOT_READY", "请先按路线推进当前节点，自动战仍在运行时可稍后重试。", context.request_id, operation_id, retryable=True)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "此事已有安排，请重新起意。", context.request_id, operation_id)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "魔界深渊秘境结算暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)

        if record.status != "settled":
            return CommandResult(
                True,
                "DEMON_ABYSS_NODE_SETTLED",
                f"## 自动战已结算\n\n- **结果**：胜利\n- **下一节点**：{record.current_node}\n\n继续按路线选择节点。",
                context.request_id,
                operation_id,
                data=self._data(record),
            )
        outcome = record.outcome or "unknown"
        outcome_text = {"won": "完成", "lost": "战败", "expired": "过期", "system_aborted": "系统中止并补偿"}.get(outcome, outcome)
        return CommandResult(
            True,
            "DEMON_ABYSS_SETTLED",
            f"## {DEMON_ABYSS_LABEL}已结算\n\n- **结果**：{outcome_text}\n"
            f"- **奖励**：{self._reward_text(record.reward)}\n- **首通**：{'是' if record.first_clear and outcome == 'won' else '否'}\n"
            f"- **污染**：{record.pollution_after}\n\n> 同一 operation 会回放原结算，不会重复发放资产。",
            context.request_id,
            operation_id,
            data=self._data(record),
        )


__all__ = ["DemonAbyssApplication"]
