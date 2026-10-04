"""Adapter-neutral commands for the ancient-domain party instance."""

from __future__ import annotations

from ...contracts import CommandContext, CommandResult
from ..persistence.errors import (
    AncientDomainBusyError,
    AncientDomainNodeError,
    AncientDomainNotFoundError,
    AncientDomainNotReadyError,
    AncientDomainQuotaError,
    AncientDomainRequirementError,
    OperationConflictError,
    ResourceInsufficientError,
)
from .ancient_domain_rules import (
    ANCIENT_DOMAIN_KEY,
    ANCIENT_DOMAIN_NODE_LABELS,
    resolve_ancient_domain_node,
)
from .secret_realm_rules import resolve_secret_realm


class AncientDomainApplication:
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
            "instance_key": ANCIENT_DOMAIN_KEY,
            "party_id": record.party_id,
            "status": record.status,
            "node_index": record.node_index,
            "current_node": record.current_node,
            "battle_id": record.battle_id,
            "rewards": record.rewards,
            "first_clear_members": list(record.first_clear_members),
            "outcome": record.outcome,
            "expires_at": record.expires_at,
            "idempotent_replay": record.already_completed,
        }

    @staticmethod
    def _label(node_key: str | None) -> str | None:
        return ANCIENT_DOMAIN_NODE_LABELS.get(node_key or "", node_key)

    async def enter(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 1 or resolve_secret_realm(context.command_args[0]) != ANCIENT_DOMAIN_KEY:
            return CommandResult(False, "INVALID_SECRET_REALM_COMMAND", "请使用 `进入秘境 远古洞天`。", context.request_id)
        operation_id = self._operation_id(context, "ancient_domain.enter")
        try:
            record = await self.repository.enter_ancient_domain(
                platform=context.adapter, platform_user_id=context.user_id, operation_id=operation_id,
            )
        except AncientDomainRequirementError:
            return CommandResult(False, "ANCIENT_DOMAIN_REQUIREMENT_MISSING", "队伍、地点、境界或领域裂痕状态不满足要求，未扣除资源。", context.request_id, operation_id)
        except AncientDomainBusyError:
            return CommandResult(False, "ANCIENT_DOMAIN_BUSY", "至少一名队员已有冲突行动或锁定资产。", context.request_id, operation_id)
        except AncientDomainQuotaError:
            return CommandResult(False, "ANCIENT_DOMAIN_QUOTA_EXHAUSTED", "至少一名队员本 UTC 周已尝试远古洞天秘境。", context.request_id, operation_id)
        except ResourceInsufficientError:
            return CommandResult(False, "RESOURCE_INSUFFICIENT", "队长体力不足，未扣除任何资源。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "此事已有安排，请重新起意。", context.request_id, operation_id)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "远古洞天秘境暂时不可用，请稍后重试。", context.request_id, operation_id, retryable=True)
        return CommandResult(
            True, "ANCIENT_DOMAIN_ENTERED",
            "## 已进入远古洞天秘境\n\n队长已支付全队 40 点体力；三名队员各占用本周额度。\n\n"
            f"- **下一节点**：{self._label(record.current_node)}\n- **有效期**：{record.expires_at}\n\n"
            "> 队长按固定路线推进；远古洞天之主由服务器自动战斗。",
            context.request_id, operation_id, data=self._data(record),
        )

    async def choose_node(self, context: CommandContext) -> CommandResult:
        if not context.command_args or not (node_key := resolve_ancient_domain_node(context.command_args[0])):
            return CommandResult(False, "INVALID_SECRET_REALM_COMMAND", "请按服务端显示的顺序选择远古洞天秘境节点。", context.request_id)
        path_choice = None
        if node_key == "fractured_gallery":
            if len(context.command_args) != 2:
                return CommandResult(False, "INVALID_SECRET_REALM_COMMAND", "裂痕回廊需额外选择 `内` 或 `外`。", context.request_id)
            path_choice = {"内": "inner", "内侧": "inner", "inner": "inner", "外": "outer", "外侧": "outer", "outer": "outer"}.get(context.command_args[1])
            if path_choice is None:
                return CommandResult(False, "INVALID_SECRET_REALM_COMMAND", "裂痕回廊只接受 `内` 或 `外`。", context.request_id)
        elif len(context.command_args) != 1:
            return CommandResult(False, "INVALID_SECRET_REALM_COMMAND", "该节点无需附加选择。", context.request_id)
        operation_id = self._operation_id(context, "ancient_domain.choose_node")
        try:
            record = await self.repository.choose_ancient_domain_node(
                platform=context.adapter, platform_user_id=context.user_id,
                node_key=node_key, path_choice=path_choice, operation_id=operation_id,
            )
        except AncientDomainNodeError:
            return CommandResult(False, "ANCIENT_DOMAIN_NODE_FORBIDDEN", "只能按固定八节点顺序推进，裂痕回廊须选择内或外。", context.request_id, operation_id)
        except AncientDomainRequirementError:
            return CommandResult(False, "ANCIENT_DOMAIN_PERMISSION_DENIED", "只有队长可以推进秘境路线。", context.request_id, operation_id)
        except AncientDomainNotFoundError:
            return CommandResult(False, "ANCIENT_DOMAIN_NOT_FOUND", "当前没有进行中的远古洞天秘境。", context.request_id, operation_id)
        except AncientDomainNotReadyError:
            return CommandResult(False, "ANCIENT_DOMAIN_NOT_READY", "秘境已过期、尚未进入，或当前节点不能推进。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "此事与先前安排不合，请重新起意。", context.request_id, operation_id)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "远古洞天秘境节点暂时不可用，请稍后重试。", context.request_id, operation_id, retryable=True)
        if record.status == "expired":
            return CommandResult(False, "ANCIENT_DOMAIN_EXPIRED", "秘境已过期，队员锁已释放；本周额度和入场费用不退。", context.request_id, operation_id, data=self._data(record))
        if record.status == "combat_pending":
            return CommandResult(
                True, "ANCIENT_DOMAIN_COMBAT_PENDING",
                f"## 远古洞天之主\n\n服务器已创建自动战斗会话 `{record.battle_id}`。发送 `结算秘境` 推进战斗；客户端不能提交行动或结果。",
                context.request_id, operation_id, data=self._data(record),
            )
        if record.status == "cleared":
            text = "## 远古洞天路线完成\n\n发送 `结算秘境` 领取首通或重复奖励。"
        else:
            text = f"## 节点已完成\n\n下一节点：**{self._label(record.current_node)}**。"
        return CommandResult(True, "ANCIENT_DOMAIN_NODE_SELECTED", text, context.request_id, operation_id, data=self._data(record))

    async def settle(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_SECRET_REALM_COMMAND", "结算秘境无需附加参数。", context.request_id)
        operation_id = self._operation_id(context, "ancient_domain.settle")
        try:
            record = await self.repository.settle_ancient_domain(
                platform=context.adapter, platform_user_id=context.user_id, operation_id=operation_id,
            )
        except AncientDomainNotFoundError:
            return CommandResult(False, "ANCIENT_DOMAIN_NOT_FOUND", "当前没有等待结算的远古洞天秘境。", context.request_id, operation_id)
        except AncientDomainNotReadyError:
            return CommandResult(False, "ANCIENT_DOMAIN_NOT_READY", "请先按路线完成全部节点和首领自动战。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "此事与先前安排不合，请重新起意。", context.request_id, operation_id)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "远古洞天秘境结算暂时不可用，请稍后重试。", context.request_id, operation_id, retryable=True)
        if record.status == "routing":
            label = self._label(record.current_node)
            return CommandResult(True, "ANCIENT_DOMAIN_BATTLE_SETTLED", f"## 自动战已结算\n\n- **结果**：胜利\n- **下一节点**：{label}", context.request_id, operation_id, data=self._data(record))
        if record.status == "settled":
            rewards = "；".join(f"成员 {player}: 古果 +{values.get('item.ancient_fruit', 0)}" for player, values in record.rewards.items()) or "无"
            message = f"## 远古洞天秘境已结算\n\n- **结果**：完成\n- **奖励**：{rewards}\n- **首通成员**：{len(record.first_clear_members)} 人"
        else:
            message = f"## 远古洞天秘境未完成\n\n- **结果**：{record.outcome or record.status}\n- **资源**：失败/过期不退入场体力，本周额度已消耗。"
        return CommandResult(True, "ANCIENT_DOMAIN_SETTLED", message, context.request_id, operation_id, data=self._data(record))


__all__ = ["AncientDomainApplication"]
