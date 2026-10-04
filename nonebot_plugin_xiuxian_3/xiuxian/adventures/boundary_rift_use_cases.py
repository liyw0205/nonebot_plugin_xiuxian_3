"""Adapter-neutral commands for the party boundary-rift instance."""

from __future__ import annotations

from ...contracts import CommandContext, CommandResult
from ..persistence.errors import (
    BoundaryRiftBusyError,
    BoundaryRiftNodeError,
    BoundaryRiftNotFoundError,
    BoundaryRiftNotReadyError,
    BoundaryRiftQuotaError,
    BoundaryRiftRequirementError,
    OperationConflictError,
    ResourceInsufficientError,
)
from .boundary_rift_rules import BOUNDARY_RIFT_KEY, BOUNDARY_RIFT_NODE_DEFINITIONS, resolve_boundary_rift_node
from .secret_realm_rules import resolve_secret_realm


class BoundaryRiftApplication:
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
            "instance_key": BOUNDARY_RIFT_KEY,
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
        return next((node.label for node in BOUNDARY_RIFT_NODE_DEFINITIONS if node.key == node_key), node_key)

    async def enter(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 1 or resolve_secret_realm(context.command_args[0]) != BOUNDARY_RIFT_KEY:
            return CommandResult(False, "INVALID_SECRET_REALM_COMMAND", "请使用 `进入秘境 界隙裂隙`。", context.request_id)
        operation_id = self._operation_id(context, "boundary_rift.enter")
        try:
            record = await self.repository.enter_boundary_rift(
                platform=context.adapter,
                platform_user_id=context.user_id,
                operation_id=operation_id,
            )
        except BoundaryRiftRequirementError:
            return CommandResult(False, "BOUNDARY_RIFT_REQUIREMENT_MISSING", "队伍、地点、境界、主线或神魂晶不满足要求，未扣除资源。", context.request_id, operation_id)
        except BoundaryRiftBusyError:
            return CommandResult(False, "BOUNDARY_RIFT_BUSY", "队伍成员已有进行中的行动或秘境会话。", context.request_id, operation_id)
        except BoundaryRiftQuotaError:
            return CommandResult(False, "BOUNDARY_RIFT_QUOTA_EXHAUSTED", "至少一名队员本 UTC 周已尝试过界隙裂隙秘境。", context.request_id, operation_id)
        except ResourceInsufficientError:
            return CommandResult(False, "RESOURCE_INSUFFICIENT", "至少一名队员体力不足，未扣除任何资源。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "此事已有安排，请重新起意。", context.request_id, operation_id)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "界隙裂隙秘境暂时不可用，请稍后重试。", context.request_id, operation_id, retryable=True)
        return CommandResult(
            True,
            "BOUNDARY_RIFT_ENTERED",
            "## 已进入界隙裂隙秘境\n\n每名成员已支付 30 体力，队长已支付 1 枚神魂晶。\n\n"
            f"- **下一节点**：裂隙入口\n- **周额度**：全队成员各占用 1 次\n- **有效期**：{record.expires_at}\n\n"
            "> 队长按固定路线选择秘境节点；遭遇战由服务器自动推进。",
            context.request_id,
            operation_id,
            data=self._data(record),
        )

    async def choose_node(self, context: CommandContext) -> CommandResult:
        if not context.command_args or not (node_key := resolve_boundary_rift_node(context.command_args[0])):
            return CommandResult(False, "INVALID_SECRET_REALM_COMMAND", "请按服务端显示的顺序选择界隙裂隙秘境节点。", context.request_id)
        path_choice = None
        if node_key == "shattered_path":
            if len(context.command_args) != 2:
                return CommandResult(False, "INVALID_SECRET_REALM_COMMAND", "破碎岔路需额外选择 `内` 或 `外`。", context.request_id)
            path_choice = {"内": "inner", "内侧": "inner", "inner": "inner", "外": "outer", "外侧": "outer", "outer": "outer"}.get(context.command_args[1])
            if path_choice is None:
                return CommandResult(False, "INVALID_SECRET_REALM_COMMAND", "破碎岔路只接受 `内` 或 `外`。", context.request_id)
        elif len(context.command_args) != 1:
            return CommandResult(False, "INVALID_SECRET_REALM_COMMAND", "该节点无需附加选择。", context.request_id)
        operation_id = self._operation_id(context, "boundary_rift.choose_node")
        try:
            record = await self.repository.choose_boundary_rift_node(
                platform=context.adapter,
                platform_user_id=context.user_id,
                node_key=node_key,
                path_choice=path_choice,
                operation_id=operation_id,
            )
        except BoundaryRiftNodeError:
            return CommandResult(False, "BOUNDARY_RIFT_NODE_FORBIDDEN", "只能按服务端规定的六节点顺序推进，破碎岔路须选择内或外。", context.request_id, operation_id)
        except BoundaryRiftNotFoundError:
            return CommandResult(False, "BOUNDARY_RIFT_NOT_FOUND", "当前没有进行中的界隙裂隙秘境。", context.request_id, operation_id)
        except BoundaryRiftNotReadyError:
            return CommandResult(False, "BOUNDARY_RIFT_NOT_READY", "秘境已过期、尚未进入，或当前节点不能推进。", context.request_id, operation_id)
        except BoundaryRiftRequirementError:
            return CommandResult(False, "BOUNDARY_RIFT_PERMISSION_DENIED", "只有队长可以推进秘境路线。", context.request_id, operation_id)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "秘境节点暂时不可用，请稍后重试。", context.request_id, operation_id, retryable=True)
        if record.status == "combat_pending":
            return CommandResult(
                True,
                "BOUNDARY_RIFT_COMBAT_PENDING",
                f"## {self._label(node_key)}遭遇战\n\n"
                f"服务器已创建自动战斗会话 `{record.battle_id}`。使用 `结算界隙裂隙秘境` 推进战斗；客户端不能提交攻击、技能或结果。",
                context.request_id,
                operation_id,
                data=self._data(record),
            )
        if record.status == "cleared":
            text = "## 界隙裂隙秘境路线完成\n\n使用 `结算界隙裂隙秘境` 领取首通或重复奖励。"
        else:
            label = self._label(record.current_node)
            text = f"## 节点已完成\n\n下一节点：**{label}**。"
        return CommandResult(True, "BOUNDARY_RIFT_NODE_SELECTED", text, context.request_id, operation_id, data=self._data(record))

    async def settle(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_SECRET_REALM_COMMAND", "结算界隙裂隙秘境无需附加参数。", context.request_id)
        operation_id = self._operation_id(context, "boundary_rift.settle")
        try:
            record = await self.repository.settle_boundary_rift(
                platform=context.adapter,
                platform_user_id=context.user_id,
                operation_id=operation_id,
            )
        except BoundaryRiftNotFoundError:
            return CommandResult(False, "BOUNDARY_RIFT_NOT_FOUND", "当前没有界隙裂隙秘境会话。", context.request_id, operation_id)
        except BoundaryRiftNotReadyError:
            return CommandResult(False, "BOUNDARY_RIFT_NOT_READY", "秘境尚未到达可结算节点，或会话已失败/过期。", context.request_id, operation_id)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "界隙裂隙秘境结算暂时不可用，请稍后重试。", context.request_id, operation_id, retryable=True)
        if record.status == "settled":
            rewards = "；".join(f"成员 {player_id}: 神魂晶 +{values.get('item.soul_crystal', 0)}" for player_id, values in record.rewards.items()) or "无"
            message = f"## 界隙裂隙秘境已结算\n\n- **结果**：成功\n- **奖励**：{rewards}\n- **首通成员**：{len(record.first_clear_members)} 人"
        elif record.status == "routing":
            node_label = self._label(record.current_node)
            message = f"## 自动战斗已结算\n\n- **结果**：{record.outcome or '胜利'}\n- **下一节点**：{node_label}"
        else:
            message = f"## 界隙裂隙秘境未完成\n\n- **结果**：{record.outcome or record.status}\n- **资源**：入场资源不退，周额度已消耗。"
        return CommandResult(True, "BOUNDARY_RIFT_SETTLED", message, context.request_id, operation_id, data=self._data(record))


__all__ = ["BoundaryRiftApplication"]
