"""Application commands for the first-stage path switch.

The adapter layer only normalizes events; every branch here is shared by QQ and
OneBot.  Messages stay adapter-neutral Markdown and use ``command_link`` so the
QQ formatter can turn the command names blue, while plain-text adapters keep a
readable hint.
"""

from __future__ import annotations

from ...contracts import CommandContext, CommandResult
from ..content import ContentBundle, bundled_content
from ..persistence.errors import (
    OperationConflictError,
    PathSwitchBusyError,
    PathSwitchCooldownError,
    PathSwitchConflictError,
    PathSwitchInvalidError,
    PathSwitchNotFoundError,
    PathSwitchPreviewExpiredError,
    PathSwitchRequirementError,
    PathSwitchStateError,
    PathSwitchTokenClaimedError,
    PathSwitchTokenMissingError,
    PlayerNotFoundError,
    PlayerSuspendedError,
    RepositoryBusyError,
    ResourceInsufficientError,
)
from ..repository import SQLitePlayerRepository
from ..player.path_rules import path_records, subprofession_records
from ..utils.text import command_link
from .switch_content import PathSwitchDefinition, path_switch_definition

CLAIM_COMMAND = "领取转修令"
PREVIEW_COMMAND = "转修道途"
CONFIRM_COMMAND = "确认转修"
CANCEL_COMMAND = "取消转修"


class PathSwitchApplication:
    """Translate path-switch commands into adapter-neutral results."""

    def __init__(self, repository: SQLitePlayerRepository):
        self.repository = repository

    def _content(self) -> ContentBundle:
        content = getattr(self.repository, "content", None)
        return content if content is not None else bundled_content()

    def _definition(self) -> PathSwitchDefinition:
        return path_switch_definition(self._content())

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

    def _cost_text(self, cost: dict[str, object]) -> str:
        parts: list[str] = []
        for key, value in cost.items():
            if str(key).startswith("currency.") or str(key) == "spirit_stones":
                parts.append(f"灵石 {int(str(value))}")
            else:
                parts.append(f"{self._item_label(str(key))} ×{int(str(value))}")
        return "、".join(parts)

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

    async def claim_token(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(
                False,
                "INVALID_PATH_SWITCH_COMMAND",
                f"请直接发送 {command_link(CLAIM_COMMAND, CLAIM_COMMAND)}。",
                context.request_id,
            )
        operation_id = self._operation_id(context, "claim_switch_token")
        try:
            record = await self.repository.claim_path_switch_token(
                platform=context.adapter,
                platform_user_id=context.user_id,
                operation_id=operation_id,
            )
        except PlayerNotFoundError:
            return CommandResult(
                False,
                "PLAYER_NOT_FOUND",
                f"还没有角色，先{command_link('开始修仙', '开始修仙')}。",
                context.request_id,
                operation_id,
            )
        except PathSwitchRequirementError:
            return CommandResult(
                False,
                "PATH_SWITCH_REQUIREMENT",
                "筑基之后才能请领洗心转道令。",
                context.request_id,
                operation_id,
            )
        except PathSwitchTokenClaimedError:
            return CommandResult(
                False,
                "PATH_SWITCH_TOKEN_CLAIMED",
                "行囊里已有洗心转道令，先转修用掉后再来领取。",
                context.request_id,
                operation_id,
            )
        except PathSwitchCooldownError as exc:
            return CommandResult(
                False,
                "PATH_SWITCH_COOLDOWN",
                f"距上次领取未满冷却，还需 {self._duration_text(exc.remaining_seconds)}。",
                context.request_id,
                operation_id,
            )
        except PlayerSuspendedError:
            return CommandResult(
                False,
                "PLAYER_SUSPENDED",
                "当前角色处于暂停状态，暂时不能请领转修令。",
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

        player = record.player
        if record.already_completed:
            message = (
                "## 洗心转道令\n\n"
                f"**{self._display_name(player)}**，你已经领过洗心转道令。\n\n"
                f"- **行囊**：{self._item_label(record.item_key)} ×"
                f"{player.inventory.get(record.item_key, 0)}\n\n"
                f"> 发送 {command_link(PREVIEW_COMMAND + ' 法修', PREVIEW_COMMAND + ' 法修')} "
                "可先看转修得失。"
            )
            return CommandResult(
                True,
                "PATH_SWITCH_TOKEN_CLAIMED_ALREADY",
                message,
                context.request_id,
                operation_id,
                data={
                    "item_key": record.item_key,
                    "quantity": record.quantity,
                    "idempotent_replay": True,
                },
            )
        message = (
            "## 洗心转道令\n\n"
            f"**{self._display_name(player)}**，你领到 **{record.item_label} ×{record.quantity}**。\n\n"
            f"- **境界**：{self._content().label('realm', str(player.realm_key))} "
            f"{player.realm_layer} 层\n"
            f"- **灵石**：{player.spirit_stones}\n"
            "- **用途**：筑基后可凭此令与 500 灵石重择首要道途\n\n"
            f"> 先发送 {command_link(PREVIEW_COMMAND + ' 法修', PREVIEW_COMMAND + ' 法修')} "
            "预览，再发送 "
            f"{command_link(CONFIRM_COMMAND, CONFIRM_COMMAND)} 确认。"
        )
        return CommandResult(
            True,
            "PATH_SWITCH_TOKEN_CLAIMED",
            message,
            context.request_id,
            operation_id,
            data={
                "item_key": record.item_key,
                "quantity": record.quantity,
                "inventory": player.inventory,
            },
        )

    async def preview(self, context: CommandContext) -> CommandResult:
        definition = self._definition()
        if not context.command_args:
            try:
                player = await self.repository.get_player(
                    platform=context.adapter, platform_user_id=context.user_id
                )
            except Exception:
                player = None
            current = str(player.path_key) if player is not None and player.path_key else None
            lines = [
                "## 道途转修",
                "",
                f"> {definition.description}",
                "",
                f"- **费用**：{self._cost_text({definition.currency_key: definition.spirit_stone_cost, definition.token_item_key: definition.token_quantity})}",
                f"- **确认期限**：{self._duration_text(definition.preview_ttl_seconds)}",
                f"- **转修冷却**：{self._duration_text(definition.cooldown_seconds)}",
                "",
                "**可转道途**",
                "",
                *self._path_lines(current),
                "",
                f"> 发送 {command_link(PREVIEW_COMMAND + ' 法修', PREVIEW_COMMAND + ' 法修')} "
                "预览；辅修需写成 `转修道途 辅修 炼丹`。",
            ]
            return CommandResult(
                True,
                "PATH_SWITCH_PREVIEW_READY",
                "\n".join(lines),
                context.request_id,
                data={"current_path_key": current},
            )
        if len(context.command_args) > 2:
            return CommandResult(
                False,
                "INVALID_PATH_SWITCH_COMMAND",
                f"请使用 {command_link(PREVIEW_COMMAND + ' 法修', PREVIEW_COMMAND + ' 法修')}，"
                "辅修写成 `转修道途 辅修 炼丹`。",
                context.request_id,
            )
        target = context.command_args[0]
        subprofession = context.command_args[1] if len(context.command_args) == 2 else None
        operation_id = self._operation_id(context, "preview_switch")
        try:
            plan = await self.repository.preview_path_switch(
                platform=context.adapter,
                platform_user_id=context.user_id,
                target_reference=target,
                subprofession_reference=subprofession,
                operation_id=operation_id,
            )
        except PlayerNotFoundError:
            return CommandResult(
                False,
                "PLAYER_NOT_FOUND",
                f"还没有角色，先{command_link('开始修仙', '开始修仙')}。",
                context.request_id,
                operation_id,
            )
        except PathSwitchRequirementError:
            return CommandResult(
                False,
                "PATH_SWITCH_REQUIREMENT",
                "入道并达到筑基一层后才能转修。",
                context.request_id,
                operation_id,
            )
        except PathSwitchInvalidError as exc:
            message = str(exc)
            if "sub-profession" in message:
                names = "、".join(
                    str(item["name"])
                    for item in subprofession_records("support", self._content())
                )
                text = f"转入辅修需要指定一门辅修：{names}。"
            elif "current path" in message:
                text = "目标道途与当前道途相同，无需转修。"
            else:
                text = "没有找到这条道途，请查看 `转修道途` 列表。"
            return CommandResult(False, "PATH_SWITCH_INVALID", text, context.request_id, operation_id)
        except PathSwitchConflictError:
            return CommandResult(
                False,
                "PATH_SWITCH_CONFLICT",
                "已选择领域或已得道果的角色暂不能转修；当前阶段请继续原有道途。",
                context.request_id,
                operation_id,
            )
        except PathSwitchBusyError:
            return CommandResult(
                False,
                "PATH_SWITCH_BUSY",
                "仍有进行中的长动作，结束后再转修。",
                context.request_id,
                operation_id,
            )
        except PathSwitchCooldownError as exc:
            return CommandResult(
                False,
                "PATH_SWITCH_COOLDOWN",
                f"距上次转修未满冷却，还需 {self._duration_text(exc.remaining_seconds)}。",
                context.request_id,
                operation_id,
            )
        except PlayerSuspendedError:
            return CommandResult(
                False,
                "PLAYER_SUSPENDED",
                "当前角色处于暂停状态，暂时不能转修。",
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

        snapshot = plan.snapshot
        player = None
        try:
            player = await self.repository.get_player(
                platform=context.adapter, platform_user_id=context.user_id
            )
        except Exception:
            player = None
        display_name = self._display_name(player) if player is not None else "你"
        lines = [
            "## 道途转修 · 预览",
            "",
            f"**{display_name}** 将从 **{plan.from_path_label}** 转为 "
            f"**{plan.to_path_label}**。",
            "",
            f"- **费用**：{self._cost_text(plan.cost)}",
            f"- **确认期限**：{self._duration_text(int(snapshot.get('preview_ttl_seconds', 0)))}",
            f"- **转修冷却**：{self._duration_text(int(snapshot.get('cooldown_seconds', 0)))}",
        ]
        if plan.to_subprofession_label:
            lines.append(f"- **辅修**：{plan.to_subprofession_label}")
        lines.extend(["", "**保留**"])
        lines.extend(f"- {item}" for item in plan.snapshot.get("retained", []))
        lines.extend(["", "**冻结（回到旧道途后恢复）**"])
        lines.extend(f"- {item}" for item in plan.snapshot.get("frozen", []))
        cleared = plan.snapshot.get("cleared", [])
        if cleared:
            lines.extend(["", "**清理**"])
            lines.extend(f"- {item}" for item in cleared)
        lines.extend(
            [
                "",
                "> 旧道脉已用天赋点不返还，也不折算到新道途。",
                "",
                f"发送 {command_link(CONFIRM_COMMAND, CONFIRM_COMMAND)} 确认，"
                f"或发送 {command_link(CANCEL_COMMAND, CANCEL_COMMAND)} 放弃。",
            ]
        )
        return CommandResult(
            True,
            "PATH_SWITCH_PREVIEW",
            "\n".join(lines),
            context.request_id,
            operation_id,
            data={
                "plan_id": plan.plan_id,
                "from_path_key": plan.from_path_key,
                "to_path_key": plan.to_path_key,
                "to_subprofession_key": plan.to_subprofession_key,
                "cost": plan.cost,
                "expires_at": plan.expires_at,
            },
        )

    async def confirm(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) > 1:
            return CommandResult(
                False,
                "INVALID_PATH_SWITCH_COMMAND",
                f"请发送 {command_link(CONFIRM_COMMAND, CONFIRM_COMMAND)}。",
                context.request_id,
            )
        plan_id = context.command_args[0] if context.command_args else None
        operation_id = self._operation_id(context, "confirm_switch")
        try:
            result = await self.repository.confirm_path_switch(
                platform=context.adapter,
                platform_user_id=context.user_id,
                plan_id=plan_id,
                operation_id=operation_id,
            )
        except PathSwitchNotFoundError:
            return CommandResult(
                False,
                "PATH_SWITCH_NOT_FOUND",
                f"没有待确认的转修，先发送 {command_link(PREVIEW_COMMAND + ' 法修', PREVIEW_COMMAND + ' 法修')}。",
                context.request_id,
                operation_id,
            )
        except PathSwitchPreviewExpiredError:
            return CommandResult(
                False,
                "PATH_SWITCH_PREVIEW_EXPIRED",
                "这次预览已经过期，未扣任何资产；请重新预览。",
                context.request_id,
                operation_id,
            )
        except PathSwitchTokenMissingError:
            return CommandResult(
                False,
                "PATH_SWITCH_TOKEN_MISSING",
                f"行囊里没有洗心转道令，先发送 {command_link(CLAIM_COMMAND, CLAIM_COMMAND)}。",
                context.request_id,
                operation_id,
            )
        except ResourceInsufficientError:
            return CommandResult(
                False,
                "RESOURCE_INSUFFICIENT",
                "灵石不足 500，转修未扣除任何资产。",
                context.request_id,
                operation_id,
            )
        except PathSwitchConflictError:
            return CommandResult(
                False,
                "PATH_SWITCH_CONFLICT",
                "预览后角色状态已变化（道途、领域、道果或长动作），请重新预览。",
                context.request_id,
                operation_id,
            )
        except PathSwitchBusyError:
            return CommandResult(
                False,
                "PATH_SWITCH_BUSY",
                "仍有进行中的长动作，结束后再确认转修。",
                context.request_id,
                operation_id,
            )
        except PathSwitchStateError:
            return CommandResult(
                False,
                "PATH_SWITCH_STATE",
                "这次转修计划已失效或已确认，请重新预览。",
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
                "当前角色处于暂停状态，暂时不能转修。",
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
            "## 道途转修已成",
            "",
            f"**{self._display_name(player) if player else '你'}** 已从 "
            f"**{result.from_path_label}** 转为 **{result.to_path_label}**。",
            "",
            f"- **灵石**：{result.spirit_stones_before} → {result.spirit_stones_after}",
            f"- **洗心转道令**：{result.token_quantity_before} → {result.token_quantity_after}",
        ]
        if result.to_subprofession_label:
            lines.append(f"- **辅修**：{result.to_subprofession_label}")
        if result.retained:
            lines.extend(["", "**保留**"])
            lines.extend(f"- {item}" for item in result.retained)
        if result.frozen:
            lines.extend(["", "**已冻结（回到旧道途后恢复）**"])
            lines.extend(f"- {item}" for item in result.frozen)
        if result.cleared:
            lines.extend(["", "**已清理**"])
            lines.extend(f"- {item}" for item in result.cleared)
        lines.extend(
            [
                "",
                "> 旧道脉节点与神通仍留档；新道途的道脉从第 1 阶起重新修习。",
            ]
        )
        return CommandResult(
            True,
            "PATH_SWITCH_CONFIRMED",
            "\n".join(lines),
            context.request_id,
            operation_id,
            data={
                "plan_id": result.plan_id,
                "from_path_key": result.from_path_key,
                "to_path_key": result.to_path_key,
                "to_subprofession_key": result.to_subprofession_key,
                "spirit_stones": result.spirit_stones_after,
                "idempotent_replay": result.already_completed,
            },
        )

    async def cancel(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(
                False,
                "INVALID_PATH_SWITCH_COMMAND",
                f"请直接发送 {command_link(CANCEL_COMMAND, CANCEL_COMMAND)}。",
                context.request_id,
            )
        operation_id = self._operation_id(context, "cancel_switch")
        try:
            plan = await self.repository.cancel_path_switch(
                platform=context.adapter,
                platform_user_id=context.user_id,
                operation_id=operation_id,
            )
        except PathSwitchNotFoundError:
            return CommandResult(
                False,
                "PATH_SWITCH_NOT_FOUND",
                "没有待取消的转修预览。",
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
                "当前角色处于暂停状态，暂时不能取消转修。",
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
            "PATH_SWITCH_CANCELLED",
            "## 转修预览已取消\n\n未扣除洗心转道令或灵石。",
            context.request_id,
            operation_id,
            data={"plan_id": plan.plan_id, "status": plan.status},
        )


__all__ = [
    "CANCEL_COMMAND",
    "CLAIM_COMMAND",
    "CONFIRM_COMMAND",
    "PREVIEW_COMMAND",
    "PathSwitchApplication",
]
