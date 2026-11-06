"""Application commands for the nascent-soul path rebuild."""

from __future__ import annotations

from ...contracts import CommandContext, CommandResult
from ..content import ContentBundle, bundled_content
from ..persistence.errors import (
    OperationConflictError,
    PathRebuildConflictError,
    PathRebuildFundsError,
    PathRebuildInvalidError,
    PathRebuildLimitError,
    PathRebuildNotFoundError,
    PathRebuildPreviewExpiredError,
    PathRebuildQuestMissingError,
    PathRebuildRequirementError,
    PathRebuildStateError,
    PathRebuildTokenMissingError,
    PlayerNotFoundError,
    PlayerSuspendedError,
    RepositoryBusyError,
)
from ..player.path_rules import path_records, subprofession_records
from ..repository import SQLitePlayerRepository
from ..utils.text import command_link
from .rebuild_content import PathRebuildDefinition, path_rebuild_definition

PREVIEW_COMMAND = "道途重构预览"
CONFIRM_COMMAND = "确认道途重构"
CANCEL_COMMAND = "取消道途重构"


class PathRebuildApplication:
    """Translate path-rebuild commands into adapter-neutral results."""

    def __init__(self, repository: SQLitePlayerRepository):
        self.repository = repository

    def _content(self) -> ContentBundle:
        content = getattr(self.repository, "content", None)
        return content if content is not None else bundled_content()

    def _definition(self) -> PathRebuildDefinition:
        return path_rebuild_definition(self._content())

    @staticmethod
    def _operation_id(context: CommandContext, suffix: str) -> str:
        if context.operation_id:
            return context.operation_id
        key = context.message_id or context.request_id
        return f"path.{suffix}:{context.adapter}:{context.user_id}:{key}"

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

    def _item_label(self, item_key: str) -> str:
        try:
            return str(self._content().label("item", item_key))
        except KeyError:
            return item_key

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

    def _cost_text(self, cost: dict[str, object]) -> str:
        parts: list[str] = []
        for key, value in cost.items():
            if str(key).startswith("currency.") or str(key) == "spirit_stones":
                parts.append(f"灵石 {int(str(value))}")
            else:
                parts.append(f"{self._item_label(str(key))} ×{int(str(value))}")
        return "、".join(parts)

    def _path_lines(self, current_key: str | None) -> list[str]:
        lines: list[str] = []
        for record in path_records(self._content()):
            key = str(record["key"])
            marker = "（当前）" if key == current_key else ""
            lines.append(f"- **{record['name']}**{marker}")
            if key == "support":
                names = "、".join(
                    str(item["name"])
                    for item in subprofession_records("support", self._content())
                )
                lines.append(f"  - 辅修：{names}")
        return lines

    async def preview(self, context: CommandContext) -> CommandResult:
        definition = self._definition()
        if not context.command_args:
            player = None
            try:
                player = await self.repository.get_player(
                    platform=context.adapter, platform_user_id=context.user_id
                )
            except Exception:
                player = None
            current = str(player.path_key) if player is not None and player.path_key else None
            lines = [
                "## 道途重构",
                "",
                f"> {definition.description}",
                "",
                f"- **境界**：元婴 L{definition.min_layer}",
                f"- **三界声望**：{'、'.join(f'{key} ≥ {value}' for key, value in definition.required_reputation.items())}",
                f"- **费用**：{self._cost_text({definition.currency_key: definition.spirit_stone_cost, definition.token_item_key: definition.token_quantity})}",
                f"- **预览期限**：{self._duration_text(definition.preview_ttl_seconds)}",
                "",
                "**可重构道途**",
                "",
                *self._path_lines(current),
                "",
                f"> 发送 {command_link(PREVIEW_COMMAND + ' 法修', PREVIEW_COMMAND + ' 法修')} 预览；辅修写成 `道途重构预览 辅修 炼丹`。",
            ]
            return CommandResult(
                True,
                "PATH_REBUILD_PREVIEW_READY",
                "\n".join(lines),
                context.request_id,
                data={"current_path_key": current},
            )
        if len(context.command_args) > 2:
            return CommandResult(
                False,
                "INVALID_PATH_REBUILD_COMMAND",
                f"请使用 {command_link(PREVIEW_COMMAND + ' 法修', PREVIEW_COMMAND + ' 法修')}，辅修写成 `道途重构预览 辅修 炼丹`。",
                context.request_id,
            )
        target = context.command_args[0]
        subprofession = context.command_args[1] if len(context.command_args) == 2 else None
        operation_id = self._operation_id(context, "preview_rebuild")
        try:
            plan = await self.repository.preview_path_rebuild(
                platform=context.adapter,
                platform_user_id=context.user_id,
                target_reference=target,
                subprofession_reference=subprofession,
                operation_id=operation_id,
            )
        except PathRebuildQuestMissingError:
            return CommandResult(
                False,
                "PATH_REBUILD_QUEST_MISSING",
                "尚未完成三界回响主线，无法重构道途。",
                context.request_id,
                operation_id,
            )
        except PathRebuildRequirementError:
            return CommandResult(
                False,
                "PATH_REBUILD_REQUIREMENT",
                "元婴一层、三界声望各 1000 后才能重构道途。",
                context.request_id,
                operation_id,
            )
        except PathRebuildFundsError:
            return CommandResult(
                False,
                "PATH_REBUILD_FUNDS",
                "灵石不足 50000，未生成重构预览。",
                context.request_id,
                operation_id,
            )
        except PathRebuildTokenMissingError:
            return CommandResult(
                False,
                "PATH_REBUILD_TOKEN_MISSING",
                "行囊里没有道途重构令。",
                context.request_id,
                operation_id,
            )
        except PathRebuildLimitError:
            return CommandResult(
                False,
                "PATH_REBUILD_LIMIT_REACHED",
                "每名角色只能重构一次道途。",
                context.request_id,
                operation_id,
            )
        except PathRebuildInvalidError as exc:
            message = str(exc)
            if "sub-profession" in message:
                names = "、".join(
                    str(item["name"])
                    for item in subprofession_records("support", self._content())
                )
                text = f"重构为辅修需要指定一门辅修：{names}。"
            elif "current path" in message:
                text = "目标道途与当前道途相同，无需重构。"
            else:
                text = "没有找到这条道途，请查看 `道途重构预览` 列表。"
            return CommandResult(False, "PATH_REBUILD_INVALID", text, context.request_id, operation_id)
        except PathRebuildConflictError:
            return CommandResult(
                False,
                "PATH_STATE_CONFLICT",
                "已选择领域、已得道果或仍有长动作，暂不能重构道途。",
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
                "当前角色处于暂停状态，暂时不能重构道途。",
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
            "## 道途重构 · 预览",
            "",
            f"**{display_name}** 将从 **{plan.from_path_label}** 重构为 **{plan.to_path_label}**。",
            "",
            f"- **旧道途等级**：{plan.old_level} 阶 → **继承 {plan.inherited_level} 阶**",
            f"- **费用**：{self._cost_text(plan.cost)}",
            f"- **确认期限**：{self._duration_text(int(plan.snapshot.get('preview_ttl_seconds', 0)))}",
            "",
        ]
        if plan.to_subprofession_label:
            lines.append(f"- **辅修**：{plan.to_subprofession_label}")
        lines.extend(["", "**保留**"])
        lines.extend(f"- {item}" for item in plan.snapshot.get("retained", []))
        lines.extend(["", "**冻结（切回旧道途后恢复）**"])
        lines.extend(f"- {item}" for item in plan.snapshot.get("frozen", []))
        cleared = plan.snapshot.get("cleared", [])
        if cleared:
            lines.extend(["", "**清理**"])
            lines.extend(f"- {item}" for item in cleared)
        lines.extend(
            [
                "",
                f"发送 {command_link(CONFIRM_COMMAND, CONFIRM_COMMAND)} 确认，"
                f"或发送 {command_link(CANCEL_COMMAND, CANCEL_COMMAND)} 放弃。",
            ]
        )
        return CommandResult(
            True,
            "PATH_REBUILD_PREVIEW",
            "\n".join(lines),
            context.request_id,
            operation_id,
            data={
                "plan_id": plan.plan_id,
                "from_path_key": plan.from_path_key,
                "to_path_key": plan.to_path_key,
                "old_level": plan.old_level,
                "inherited_level": plan.inherited_level,
                "cost": plan.cost,
                "expires_at": plan.expires_at,
            },
        )

    async def confirm(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) > 1:
            return CommandResult(
                False,
                "INVALID_PATH_REBUILD_COMMAND",
                f"请发送 {command_link(CONFIRM_COMMAND, CONFIRM_COMMAND)}。",
                context.request_id,
            )
        plan_id = context.command_args[0] if context.command_args else None
        operation_id = self._operation_id(context, "confirm_rebuild")
        try:
            result = await self.repository.confirm_path_rebuild(
                platform=context.adapter,
                platform_user_id=context.user_id,
                plan_id=plan_id,
                operation_id=operation_id,
            )
        except PathRebuildNotFoundError:
            return CommandResult(
                False,
                "PATH_REBUILD_NOT_FOUND",
                f"没有待确认的重构，先发送 {command_link(PREVIEW_COMMAND + ' 法修', PREVIEW_COMMAND + ' 法修')}。",
                context.request_id,
                operation_id,
            )
        except PathRebuildPreviewExpiredError:
            return CommandResult(
                False,
                "PATH_REBUILD_PREVIEW_EXPIRED",
                "这次预览已经过期，未扣任何资产；请重新预览。",
                context.request_id,
                operation_id,
            )
        except PathRebuildLimitError:
            return CommandResult(
                False,
                "PATH_REBUILD_LIMIT_REACHED",
                "每名角色只能重构一次道途。",
                context.request_id,
                operation_id,
            )
        except PathRebuildTokenMissingError:
            return CommandResult(
                False,
                "PATH_REBUILD_TOKEN_MISSING",
                "行囊里没有道途重构令，重构未扣除任何资产。",
                context.request_id,
                operation_id,
            )
        except PathRebuildFundsError:
            return CommandResult(
                False,
                "PATH_REBUILD_FUNDS",
                "灵石不足 50000，重构未扣除任何资产。",
                context.request_id,
                operation_id,
            )
        except PathRebuildConflictError:
            return CommandResult(
                False,
                "PATH_STATE_CONFLICT",
                "预览后道途、道脉等级或终局状态已变化，请重新预览。",
                context.request_id,
                operation_id,
            )
        except PathRebuildRequirementError:
            return CommandResult(
                False,
                "PATH_REBUILD_REQUIREMENT",
                "重构条件已不满足，请重新预览。",
                context.request_id,
                operation_id,
            )
        except PathRebuildStateError:
            return CommandResult(
                False,
                "PATH_REBUILD_STATE",
                "这次重构计划已失效或已确认，请重新预览。",
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
                "当前角色处于暂停状态，暂时不能重构道途。",
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
            "## 道途重构已成",
            "",
            f"**{self._display_name(player) if player else '你'}** 已从 **{result.from_path_label}** 重构为 **{result.to_path_label}**。",
            "",
            f"- **灵石**：{result.spirit_stones_before} → {result.spirit_stones_after}",
            f"- **道途重构令**：{result.token_quantity_before} → {result.token_quantity_after}",
            f"- **旧道途等级**：{result.old_level} 阶",
            f"- **继承道脉**：{result.inherited_level} 阶",
        ]
        if result.to_subprofession_label:
            lines.append(f"- **辅修**：{result.to_subprofession_label}")
        if result.inherited_nodes:
            lines.extend(["", "**已继承节点**"])
            lines.extend(f"- {node['label']}（第 {node['tier']} 阶）" for node in result.inherited_nodes)
        lines.extend(
            [
                "",
                "> 旧道途已冻结留档；切回旧道途时旧道脉节点仍可用。",
            ]
        )
        return CommandResult(
            True,
            "PATH_REBUILD_CONFIRMED",
            "\n".join(lines),
            context.request_id,
            operation_id,
            data={
                "rebuild_id": result.rebuild_id,
                "from_path_key": result.from_path_key,
                "to_path_key": result.to_path_key,
                "old_level": result.old_level,
                "inherited_level": result.inherited_level,
                "spirit_stones": result.spirit_stones_after,
                "idempotent_replay": result.already_completed,
            },
        )

    async def cancel(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(
                False,
                "INVALID_PATH_REBUILD_COMMAND",
                f"请直接发送 {command_link(CANCEL_COMMAND, CANCEL_COMMAND)}。",
                context.request_id,
            )
        operation_id = self._operation_id(context, "cancel_rebuild")
        try:
            await self.repository.cancel_path_rebuild(
                platform=context.adapter,
                platform_user_id=context.user_id,
                operation_id=operation_id,
            )
        except PathRebuildNotFoundError:
            return CommandResult(
                False,
                "PATH_REBUILD_NOT_FOUND",
                "没有待取消的重构预览。",
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
                "当前角色处于暂停状态，暂时不能取消重构。",
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
            "PATH_REBUILD_CANCELLED",
            "## 道途重构预览已取消\n\n未扣除灵石或道途重构令。",
            context.request_id,
            operation_id,
        )


__all__ = [
    "CANCEL_COMMAND",
    "CONFIRM_COMMAND",
    "PREVIEW_COMMAND",
    "PathRebuildApplication",
]
