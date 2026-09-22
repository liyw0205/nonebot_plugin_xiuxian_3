"""Application services for the v0.1 talent tree."""

from __future__ import annotations

from ...contracts import CommandContext, CommandResult
from ..repository import (
    OperationConflictError,
    PlayerNotFoundError,
    PlayerStageConflictError,
    PlayerSuspendedError,
    RepositoryBusyError,
    ResourceInsufficientError,
    TalentNodeAlreadyLearnedError,
    TalentBusyError,
    TalentPathMismatchError,
    TalentPrerequisiteError,
    SQLitePlayerRepository,
)
from .talent_rules import (
    MAX_TALENT_TIER,
    TALENT_POINT_RESOURCE,
    talent_tree_nodes,
    tree_definition,
)


class TalentApplication:
    """Coordinate talent-tree reads and atomic node unlocks."""

    def __init__(self, repository: SQLitePlayerRepository):
        self.repository = repository

    @staticmethod
    def _operation_id(context: CommandContext, operation_name: str) -> str:
        if context.operation_id:
            return context.operation_id
        request_key = context.message_id or context.request_id
        return f"{operation_name}:{context.adapter}:{context.user_id}:{request_key}"

    @staticmethod
    def _display_name(player) -> str:
        value = player.dao_name or "未命名"
        return (
            value.replace("\\", "\\\\")
            .replace("`", "\\`")
            .replace("*", "\\*")
            .replace("_", "\\_")
            .replace("~", "\\~")
        )

    async def preview(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_TALENT_COMMAND", "道脉预览无需附加参数。", context.request_id)
        lines = [
            "## 道脉天书",
            "",
            "入道后按首要道途修习对应道脉。每条道脉五阶，首阶免费，后续消耗天赋点：",
            "",
        ]
        for tree_key in ("body", "spell", "device", "demonic", "beast", "support"):
            _, tree_label = tree_definition(tree_key)
            nodes = talent_tree_nodes(tree_key)
            costs = "/".join(str(node.cost_points) for node in nodes)
            lines.append(f"- **{tree_label}**：{nodes[0].description}；五阶消耗 `{costs}` 点。")
        lines.extend(
            [
                "",
                f"> 当前版本只开放首要道途对应的道脉；天赋点资源键为 `{TALENT_POINT_RESOURCE}`。",
                "> 节点效果写入构筑快照，不直接提高突破成功率。",
            ]
        )
        return CommandResult(True, "TALENT_PREVIEW", "\n".join(lines), context.request_id)

    async def profile(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_TALENT_COMMAND", "查看道脉无需附加参数。", context.request_id)
        try:
            record = await self.repository.get_talent_profile(
                platform=context.adapter,
                platform_user_id=context.user_id,
            )
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id)
        except PlayerStageConflictError:
            return CommandResult(False, "PLAYER_STAGE_CONFLICT", "完成入道后才能查看道脉。", context.request_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能查看道脉。", context.request_id)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, retryable=True)

        learned = {node.tier for node in record.nodes}
        lines = [
            f"## {record.tree_label}",
            "",
            f"**{self._display_name(record.player)}**的天赋点：`{record.points_available}`（已用 `{record.points_spent}`）。",
            "",
        ]
        for node in talent_tree_nodes(record.tree_key):
            marker = "已解锁" if node.tier in learned else "未解锁"
            cost = "免费" if node.cost_points == 0 else f"{node.cost_points} 点"
            lines.append(f"- **{node.label}** · {marker} · {cost}：{node.description}")
        return CommandResult(
            True,
            "TALENT_PROFILE",
            "\n".join(lines),
            context.request_id,
            data={
                "tree_key": record.tree_key,
                "tree_label": record.tree_label,
                "points_available": record.points_available,
                "points_spent": record.points_spent,
                "nodes": [
                    {
                        "node_key": node.node_key,
                        "tier": node.tier,
                        "label": node.label,
                        "description": node.description,
                        "effect": node.effect,
                        "cost_points": node.cost_points,
                        "status": node.status,
                        "unlocked_at": node.unlocked_at,
                    }
                    for node in record.nodes
                ],
            },
        )

    async def unlock(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 1:
            return CommandResult(
                False,
                "INVALID_TALENT_COMMAND",
                "请指定要解锁的层级，例如 `解锁天赋 1`。",
                context.request_id,
            )
        reference = context.command_args[0]
        operation_id = self._operation_id(context, "talent.unlock_node")
        try:
            record = await self.repository.unlock_talent(
                platform=context.adapter,
                platform_user_id=context.user_id,
                node_reference=reference,
                operation_id=operation_id,
            )
        except ValueError:
            return CommandResult(
                False,
                "INVALID_TALENT_NODE",
                f"无法识别天赋层级 `{reference}`，请输入 1-{MAX_TALENT_TIER}。",
                context.request_id,
                operation_id,
            )
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except PlayerStageConflictError:
            return CommandResult(False, "PLAYER_STAGE_CONFLICT", "完成入道后才能解锁道脉。", context.request_id, operation_id)
        except TalentPathMismatchError:
            return CommandResult(False, "TALENT_PATH_MISMATCH", "只能修习当前首要道途对应的道脉。", context.request_id, operation_id)
        except TalentNodeAlreadyLearnedError:
            return CommandResult(False, "TALENT_ALREADY_LEARNED", "这一阶道脉已经解锁。", context.request_id, operation_id)
        except TalentPrerequisiteError:
            return CommandResult(False, "TALENT_PREREQUISITE", "请按顺序解锁前一阶道脉。", context.request_id, operation_id)
        except ResourceInsufficientError:
            return CommandResult(False, "TALENT_POINT_INSUFFICIENT", "天赋点不足，暂时无法解锁这一阶道脉。", context.request_id, operation_id)
        except TalentBusyError:
            return CommandResult(False, "TALENT_BUSY", "当前有其他长时会话进行中，请先完成结算。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能解锁道脉。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于其他道脉操作，请重新发起。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)

        return CommandResult(
            True,
            "TALENT_UNLOCKED",
            f"## 道脉已开\n\n**{self._display_name(record.player)}**解锁了 **{record.label}**。\n\n- **效果**：{record.description}\n- **消耗**：{record.cost_points} 点天赋点\n\n> 效果已写入构筑快照，后续结算按快照执行。",
            context.request_id,
            operation_id,
            data={
                "node_key": record.node_key,
                "tree_key": record.tree_key,
                "tier": record.tier,
                "label": record.label,
                "effect": record.effect,
                "cost_points": record.cost_points,
                "unlocked_at": record.unlocked_at,
                "idempotent_replay": record.already_completed,
            },
        )


__all__ = ["TalentApplication"]
