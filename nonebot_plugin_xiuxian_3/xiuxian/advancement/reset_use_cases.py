"""Application commands for the talent-tree reset."""

from __future__ import annotations

from ...contracts import CommandContext, CommandResult
from ..content import ContentBundle, bundled_content
from ..persistence.errors import (
    OperationConflictError,
    PlayerNotFoundError,
    PlayerSuspendedError,
    RepositoryBusyError,
    ResourceInsufficientError,
    TalentResetBusyError,
    TalentResetCooldownError,
    TalentResetConflictError,
    TalentResetEmptyError,
    TalentResetNotFoundError,
    TalentResetPreviewExpiredError,
    TalentResetRequirementError,
    TalentResetStateError,
)
from ..repository import SQLitePlayerRepository
from ..utils.text import command_link
from .reset_content import TalentResetDefinition, talent_reset_definition
from .talent_rules import talent_tree_nodes

PREVIEW_COMMAND = "道脉重置预览"
CONFIRM_COMMAND = "确认道脉重置"
CANCEL_COMMAND = "取消道脉重置"


class TalentResetApplication:
    """Translate talent-reset commands into adapter-neutral results."""

    def __init__(self, repository: SQLitePlayerRepository):
        self.repository = repository

    def _content(self) -> ContentBundle:
        content = getattr(self.repository, "content", None)
        return content if content is not None else bundled_content()

    def _definition(self) -> TalentResetDefinition:
        return talent_reset_definition(self._content())

    @staticmethod
    def _operation_id(context: CommandContext, suffix: str) -> str:
        if context.operation_id:
            return context.operation_id
        key = context.message_id or context.request_id
        return f"talent.{suffix}:{context.adapter}:{context.user_id}:{key}"

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

    @staticmethod
    def _duration_text(seconds: int) -> str:
        remaining = max(0, int(seconds))
        days, remainder = divmod(remaining, 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes = remainder // 60
        parts = []
        if days:
            parts.append(f"{days} 天")
        if hours:
            parts.append(f"{hours} 小时")
        if minutes and not days:
            parts.append(f"{minutes} 分钟")
        return " ".join(parts) or "片刻"

    def _node_lines(self, nodes, tree_key: str) -> list[str]:
        if not nodes:
            return ["- 无可重置节点"]
        try:
            labels = {
                node.key: node.label
                for node in talent_tree_nodes(tree_key, self._content())
            }
        except Exception:
            labels = {}
        lines: list[str] = []
        for node in nodes:
            node_key = str(node["node_key"])
            tier = int(node["tier"])
            cost = int(node["cost_points"])
            label = labels.get(node_key, f"第 {tier} 阶")
            lines.append(f"- {label}（消耗 {cost} 点）")
        return lines

    async def preview(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(
                False,
                "INVALID_TALENT_RESET_COMMAND",
                f"请直接发送 {command_link(PREVIEW_COMMAND, PREVIEW_COMMAND)}。",
                context.request_id,
            )
        operation_id = self._operation_id(context, "preview_reset")
        try:
            plan = await self.repository.preview_talent_reset(
                platform=context.adapter,
                platform_user_id=context.user_id,
                operation_id=operation_id,
            )
        except TalentResetRequirementError:
            return CommandResult(
                False,
                "TALENT_RESET_REQUIREMENT",
                "入道并达到筑基一层后才能重置道脉。",
                context.request_id,
                operation_id,
            )
        except TalentResetEmptyError:
            return CommandResult(
                False,
                "TALENT_RESET_EMPTY",
                "当前道途还没有已修习的道脉节点，无需重置。",
                context.request_id,
                operation_id,
            )
        except TalentResetBusyError:
            return CommandResult(
                False,
                "TALENT_RESET_BUSY",
                "仍有进行中的长动作，结束后再重置道脉。",
                context.request_id,
                operation_id,
            )
        except TalentResetCooldownError as exc:
            return CommandResult(
                False,
                "TALENT_RESET_COOLDOWN",
                f"距上次重置未满冷却，还需 {self._duration_text(exc.remaining_seconds)}。",
                context.request_id,
                operation_id,
            )
        except PlayerNotFoundError:
            return CommandResult(
                False,
                "PLAYER_NOT_FOUND",
                f"还没有角色，先{command_link('开始修仙', '开始修仙')}。",
                context.request_id,
                operation_id,
            )
        except PlayerSuspendedError:
            return CommandResult(
                False,
                "PLAYER_SUSPENDED",
                "当前角色处于暂停状态，暂时不能重置道脉。",
                context.request_id,
                operation_id,
            )
        except OperationConflictError:
            return CommandResult(
                False,
                "OPERATION_CONFLICT",
                "这次请求的操作编号已用于其他输入，请重新发起操作。",
                context.request_id,
                operation_id,
            )
        except RepositoryBusyError:
            return CommandResult(
                False,
                "PERSISTENCE_BUSY",
                "仙缘簿暂时繁忙，请稍后再试。",
                context.request_id,
                operation_id,
                retryable=True,
            )
        except Exception:
            return CommandResult(
                False,
                "PERSISTENCE_ERROR",
                "仙缘簿暂时不可用，请稍后再试。",
                context.request_id,
                operation_id,
                retryable=True,
            )

        player = None
        try:
            player = await self.repository.get_player(
                platform=context.adapter, platform_user_id=context.user_id
            )
        except Exception:
            player = None
        display_name = self._display_name(player) if player is not None else "你"
        lines = [
            "## 道脉重置 · 预览",
            "",
            f"**{display_name}** 的 **{plan.tree_label}** 将被重置。",
            "",
            f"- **清空节点**：{len(plan.nodes)} 阶",
            *self._node_lines(plan.nodes, plan.tree_key),
            f"- **返还天赋点**：{plan.refund_points}",
            f"- **费用**：灵石 {int(str(next(iter(plan.cost.values()))))}",
            f"- **确认期限**：{self._duration_text(int(plan.snapshot.get('preview_ttl_seconds', 0)))}",
            f"- **重置冷却**：{self._duration_text(int(plan.snapshot.get('cooldown_seconds', 0)))}",
            "",
            "> 重置后当前道脉从第 1 阶重新修习；其它道途的历史节点不受影响。",
            "",
            f"发送 {command_link(CONFIRM_COMMAND, CONFIRM_COMMAND)} 确认，"
            f"或发送 {command_link(CANCEL_COMMAND, CANCEL_COMMAND)} 放弃。",
        ]
        return CommandResult(
            True,
            "TALENT_RESET_PREVIEW",
            "\n".join(lines),
            context.request_id,
            operation_id,
            data={
                "plan_id": plan.plan_id,
                "tree_key": plan.tree_key,
                "nodes": list(plan.nodes),
                "refund_points": plan.refund_points,
                "cost": plan.cost,
                "expires_at": plan.expires_at,
            },
        )

    async def confirm(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) > 1:
            return CommandResult(
                False,
                "INVALID_TALENT_RESET_COMMAND",
                f"请发送 {command_link(CONFIRM_COMMAND, CONFIRM_COMMAND)}。",
                context.request_id,
            )
        plan_id = context.command_args[0] if context.command_args else None
        operation_id = self._operation_id(context, "confirm_reset")
        try:
            result = await self.repository.confirm_talent_reset(
                platform=context.adapter,
                platform_user_id=context.user_id,
                plan_id=plan_id,
                operation_id=operation_id,
            )
        except TalentResetNotFoundError:
            return CommandResult(
                False,
                "TALENT_RESET_NOT_FOUND",
                f"没有待确认的重置，先发送 {command_link(PREVIEW_COMMAND, PREVIEW_COMMAND)}。",
                context.request_id,
                operation_id,
            )
        except TalentResetPreviewExpiredError:
            return CommandResult(
                False,
                "TALENT_RESET_PREVIEW_EXPIRED",
                "这次预览已经过期，未扣任何资产；请重新预览。",
                context.request_id,
                operation_id,
            )
        except TalentResetConflictError:
            return CommandResult(
                False,
                "TALENT_RESET_CONFLICT",
                "预览后道途或道脉节点已变化，请重新预览。",
                context.request_id,
                operation_id,
            )
        except TalentResetBusyError:
            return CommandResult(
                False,
                "TALENT_RESET_BUSY",
                "仍有进行中的长动作，结束后再确认重置。",
                context.request_id,
                operation_id,
            )
        except ResourceInsufficientError:
            return CommandResult(
                False,
                "RESOURCE_INSUFFICIENT",
                "灵石不足 300，重置未扣除任何资产。",
                context.request_id,
                operation_id,
            )
        except TalentResetStateError:
            return CommandResult(
                False,
                "TALENT_RESET_STATE",
                "这次重置计划已失效或已确认，请重新预览。",
                context.request_id,
                operation_id,
            )
        except PlayerNotFoundError:
            return CommandResult(
                False,
                "PLAYER_NOT_FOUND",
                f"还没有角色，先{command_link('开始修仙', '开始修仙')}。",
                context.request_id,
                operation_id,
            )
        except PlayerSuspendedError:
            return CommandResult(
                False,
                "PLAYER_SUSPENDED",
                "当前角色处于暂停状态，暂时不能重置道脉。",
                context.request_id,
                operation_id,
            )
        except OperationConflictError:
            return CommandResult(
                False,
                "OPERATION_CONFLICT",
                "这次请求的操作编号已用于其他输入，请重新发起操作。",
                context.request_id,
                operation_id,
            )
        except RepositoryBusyError:
            return CommandResult(
                False,
                "PERSISTENCE_BUSY",
                "仙缘簿暂时繁忙，请稍后再试。",
                context.request_id,
                operation_id,
                retryable=True,
            )
        except Exception:
            return CommandResult(
                False,
                "PERSISTENCE_ERROR",
                "仙缘簿暂时不可用，请稍后再试。",
                context.request_id,
                operation_id,
                retryable=True,
            )

        player = result.player
        lines = [
            "## 道脉重置已成",
            "",
            f"**{self._display_name(player) if player else '你'}** 的 **{result.tree_label}** 已重置。",
            "",
            f"- **灵石**：{result.spirit_stones_before} → {result.spirit_stones_after}",
            f"- **天赋点**：{result.talent_points_before} → {result.talent_points_after}",
            f"- **返还**：{result.refund_points} 点",
            f"- **清空节点**：{len(result.nodes)} 阶",
            "",
            "> 当前道脉从第 1 阶重新修习；被清空节点的完整快照已留档。",
        ]
        return CommandResult(
            True,
            "TALENT_RESET_CONFIRMED",
            "\n".join(lines),
            context.request_id,
            operation_id,
            data={
                "plan_id": result.plan_id,
                "tree_key": result.tree_key,
                "refund_points": result.refund_points,
                "talent_points": result.talent_points_after,
                "spirit_stones": result.spirit_stones_after,
                "idempotent_replay": result.already_completed,
            },
        )

    async def cancel(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(
                False,
                "INVALID_TALENT_RESET_COMMAND",
                f"请直接发送 {command_link(CANCEL_COMMAND, CANCEL_COMMAND)}。",
                context.request_id,
            )
        operation_id = self._operation_id(context, "cancel_reset")
        try:
            await self.repository.cancel_talent_reset(
                platform=context.adapter,
                platform_user_id=context.user_id,
                operation_id=operation_id,
            )
        except TalentResetNotFoundError:
            return CommandResult(
                False,
                "TALENT_RESET_NOT_FOUND",
                "没有待取消的重置预览。",
                context.request_id,
                operation_id,
            )
        except PlayerNotFoundError:
            return CommandResult(
                False,
                "PLAYER_NOT_FOUND",
                f"还没有角色，先{command_link('开始修仙', '开始修仙')}。",
                context.request_id,
                operation_id,
            )
        except PlayerSuspendedError:
            return CommandResult(
                False,
                "PLAYER_SUSPENDED",
                "当前角色处于暂停状态，暂时不能取消重置。",
                context.request_id,
                operation_id,
            )
        except OperationConflictError:
            return CommandResult(
                False,
                "OPERATION_CONFLICT",
                "这次请求的操作编号已用于其他输入，请重新发起操作。",
                context.request_id,
                operation_id,
            )
        except RepositoryBusyError:
            return CommandResult(
                False,
                "PERSISTENCE_BUSY",
                "仙缘簿暂时繁忙，请稍后再试。",
                context.request_id,
                operation_id,
                retryable=True,
            )
        except Exception:
            return CommandResult(
                False,
                "PERSISTENCE_ERROR",
                "仙缘簿暂时不可用，请稍后再试。",
                context.request_id,
                operation_id,
                retryable=True,
            )
        return CommandResult(
            True,
            "TALENT_RESET_CANCELLED",
            "## 道脉重置预览已取消\n\n未扣除灵石或天赋点。",
            context.request_id,
            operation_id,
        )


__all__ = [
    "CANCEL_COMMAND",
    "CONFIRM_COMMAND",
    "PREVIEW_COMMAND",
    "TalentResetApplication",
]
