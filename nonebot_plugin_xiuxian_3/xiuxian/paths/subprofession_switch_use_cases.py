"""Application commands for the standalone support sub-profession switch."""

from __future__ import annotations

from ...contracts import CommandContext, CommandResult
from ..content import ContentBundle, bundled_content
from ..persistence.errors import (
    OperationConflictError,
    PlayerNotFoundError,
    PlayerSuspendedError,
    RepositoryBusyError,
    SubprofessionSwitchConflictError,
    SubprofessionSwitchCooldownError,
    SubprofessionSwitchFundsError,
    SubprofessionSwitchInvalidError,
    SubprofessionSwitchNotFoundError,
    SubprofessionSwitchNotSupportError,
    SubprofessionSwitchPreviewExpiredError,
    SubprofessionSwitchStateError,
)
from ..player.path_rules import subprofession_records
from ..repository import SQLitePlayerRepository
from ..utils.text import command_link
from .subprofession_switch_content import (
    SubprofessionSwitchDefinition,
    subprofession_switch_definition,
)

PREVIEW_COMMAND = "辅修预览"
CONFIRM_COMMAND = "确认辅修"
CANCEL_COMMAND = "取消辅修"


class SubprofessionSwitchApplication:
    """Translate sub-profession switch commands into adapter-neutral results."""

    def __init__(self, repository: SQLitePlayerRepository):
        self.repository = repository

    def _content(self) -> ContentBundle:
        content = getattr(self.repository, "content", None)
        return content if content is not None else bundled_content()

    def _definition(self) -> SubprofessionSwitchDefinition:
        return subprofession_switch_definition(self._content())

    @staticmethod
    def _operation_id(context: CommandContext, suffix: str) -> str:
        if context.operation_id:
            return context.operation_id
        key = context.message_id or context.request_id
        return f"subprofession.{suffix}:{context.adapter}:{context.user_id}:{key}"

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

    def _options(self) -> list[dict]:
        return list(subprofession_records("support", self._content()))

    def _option_lines(self, current_key: str | None) -> list[str]:
        lines: list[str] = []
        for record in self._options():
            marker = "（当前）" if record["key"] == current_key else ""
            lines.append(f"- **{record['name']}**{marker}")
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
            current = (
                str(player.subprofession_key)
                if player is not None and player.path_key == "support"
                else None
            )
            lines = [
                "## 辅修切换",
                "",
                f"> {definition.description}",
                "",
                f"- **道途**：辅修（仅辅修道途可用）",
                f"- **境界**：筑基 L{definition.min_layer}",
                f"- **费用**：灵石 {definition.spirit_stone_cost}",
                f"- **冷却**：{self._duration_text(definition.cooldown_seconds)}",
                f"- **预览期限**：{self._duration_text(definition.preview_ttl_seconds)}",
                "",
                "**可选辅修**",
                "",
                *self._option_lines(current),
                "",
                f"> 发送 {command_link(PREVIEW_COMMAND + ' 炼丹', PREVIEW_COMMAND + ' 炼丹')} 预览；确认与取消分别发送对应命令。",
            ]
            return CommandResult(
                True,
                "SUBPROFESSION_SWITCH_PREVIEW_READY",
                "\n".join(lines),
                context.request_id,
                data={"current_subprofession_key": current},
            )
        if len(context.command_args) > 1:
            return CommandResult(
                False,
                "INVALID_SUBPROFESSION_SWITCH_COMMAND",
                f"请使用 {command_link(PREVIEW_COMMAND + ' 炼丹', PREVIEW_COMMAND + ' 炼丹')}。",
                context.request_id,
            )
        operation_id = self._operation_id(context, "preview_switch")
        try:
            plan = await self.repository.preview_subprofession_switch(
                platform=context.adapter,
                platform_user_id=context.user_id,
                target_reference=context.command_args[0],
                operation_id=operation_id,
            )
        except SubprofessionSwitchNotSupportError:
            return CommandResult(
                False,
                "SUBPROFESSION_SWITCH_NOT_SUPPORT",
                "只有辅修道途可以单独切换辅修；其他道途请使用道途转修。",
                context.request_id,
                operation_id,
            )
        except SubprofessionSwitchInvalidError as exc:
            message = str(exc)
            if "unknown" in message:
                names = "、".join(str(item["name"]) for item in self._options())
                text = f"没有这门辅修。可选：{names}。"
            elif "current one" in message:
                text = "目标辅修与当前辅修相同，无需切换。"
            elif "missing" in message:
                text = "当前角色没有辅修记录，无法预览切换。"
            else:
                text = "辅修切换需要辅修道途且达到筑基一层。"
            return CommandResult(
                False,
                "SUBPROFESSION_SWITCH_INVALID",
                text,
                context.request_id,
                operation_id,
            )
        except SubprofessionSwitchCooldownError as exc:
            text = str(exc).replace("cooldown ", "")
            return CommandResult(
                False,
                "SUBPROFESSION_SWITCH_COOLDOWN",
                f"距上次辅修切换未满 7 天，还需等待 {self._duration_text(int(text))}。",
                context.request_id,
                operation_id,
            )
        except SubprofessionSwitchFundsError:
            return CommandResult(
                False,
                "SUBPROFESSION_SWITCH_FUNDS",
                f"灵石不足 {definition.spirit_stone_cost}，未生成预览。",
                context.request_id,
                operation_id,
            )
        except SubprofessionSwitchConflictError:
            return CommandResult(
                False,
                "SUBPROFESSION_SWITCH_CONFLICT",
                "当前仍有进行中的长动作，暂时不能切换辅修。",
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
                "当前角色处于暂停状态，暂时不能切换辅修。",
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

        lines = [
            "## 辅修切换 · 预览",
            "",
            f"**{plan.from_subprofession_label}** → **{plan.to_subprofession_label}**",
            "",
            f"- **费用**：灵石 {definition.spirit_stone_cost}",
            f"- **确认期限**：{self._duration_text(int(plan.snapshot.get('preview_ttl_seconds', 0)))}",
            f"- **切换后冷却**：{self._duration_text(definition.cooldown_seconds)}",
            "",
            "**保留**",
        ]
        lines.extend(f"- {item}" for item in plan.snapshot.get("retained", []))
        lines.extend(
            [
                "",
                f"发送 {command_link(CONFIRM_COMMAND, CONFIRM_COMMAND)} 确认，"
                f"或发送 {command_link(CANCEL_COMMAND, CANCEL_COMMAND)} 放弃。",
            ]
        )
        return CommandResult(
            True,
            "SUBPROFESSION_SWITCH_PREVIEW",
            "\n".join(lines),
            context.request_id,
            operation_id,
            data={
                "plan_id": plan.plan_id,
                "from_subprofession_key": plan.from_subprofession_key,
                "to_subprofession_key": plan.to_subprofession_key,
                "cost": plan.cost,
                "expires_at": plan.expires_at,
            },
        )

    async def confirm(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) > 1:
            return CommandResult(
                False,
                "INVALID_SUBPROFESSION_SWITCH_COMMAND",
                f"请发送 {command_link(CONFIRM_COMMAND, CONFIRM_COMMAND)}。",
                context.request_id,
            )
        plan_id = context.command_args[0] if context.command_args else None
        operation_id = self._operation_id(context, "confirm_switch")
        try:
            result = await self.repository.confirm_subprofession_switch(
                platform=context.adapter,
                platform_user_id=context.user_id,
                plan_id=plan_id,
                operation_id=operation_id,
            )
        except SubprofessionSwitchNotFoundError:
            return CommandResult(
                False,
                "SUBPROFESSION_SWITCH_NOT_FOUND",
                f"没有待确认的辅修切换，先发送 {command_link(PREVIEW_COMMAND + ' 炼丹', PREVIEW_COMMAND + ' 炼丹')}。",
                context.request_id,
                operation_id,
            )
        except SubprofessionSwitchPreviewExpiredError:
            return CommandResult(
                False,
                "SUBPROFESSION_SWITCH_PREVIEW_EXPIRED",
                "这次预览已过期，未扣任何灵石；请重新预览。",
                context.request_id,
                operation_id,
            )
        except SubprofessionSwitchCooldownError as exc:
            text = str(exc).replace("cooldown ", "")
            return CommandResult(
                False,
                "SUBPROFESSION_SWITCH_COOLDOWN",
                f"距上次辅修切换未满 7 天，还需等待 {self._duration_text(int(text))}。",
                context.request_id,
                operation_id,
            )
        except SubprofessionSwitchFundsError:
            return CommandResult(
                False,
                "SUBPROFESSION_SWITCH_FUNDS",
                "灵石不足 2000，切换未扣除任何灵石。",
                context.request_id,
                operation_id,
            )
        except SubprofessionSwitchConflictError:
            return CommandResult(
                False,
                "SUBPROFESSION_SWITCH_CONFLICT",
                "预览后道途或辅修已变化，请重新预览。",
                context.request_id,
                operation_id,
            )
        except SubprofessionSwitchNotSupportError:
            return CommandResult(
                False,
                "SUBPROFESSION_SWITCH_NOT_SUPPORT",
                "只有辅修道途可以单独切换辅修。",
                context.request_id,
                operation_id,
            )
        except SubprofessionSwitchInvalidError:
            return CommandResult(
                False,
                "SUBPROFESSION_SWITCH_INVALID",
                "当前角色不满足辅修切换条件，请重新预览。",
                context.request_id,
                operation_id,
            )
        except SubprofessionSwitchStateError:
            return CommandResult(
                False,
                "SUBPROFESSION_SWITCH_STATE",
                "这次辅修切换计划已失效或已确认，请重新预览。",
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
                "当前角色处于暂停状态，暂时不能切换辅修。",
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
            "## 辅修切换已成",
            "",
            f"**{self._display_name(player) if player else '你'}** 已从 **{result.from_subprofession_label}** 改修 **{result.to_subprofession_label}**。",
            "",
            f"- **灵石**：{result.spirit_stones_before} → {result.spirit_stones_after}",
            "",
            "> 旧辅修的生产熟练度已保留，切回时继续使用；已接订单按接取时快照结算。",
        ]
        return CommandResult(
            True,
            "SUBPROFESSION_SWITCH_CONFIRMED",
            "\n".join(lines),
            context.request_id,
            operation_id,
            data={
                "switch_id": result.switch_id,
                "from_subprofession_key": result.from_subprofession_key,
                "to_subprofession_key": result.to_subprofession_key,
                "spirit_stones": result.spirit_stones_after,
                "idempotent_replay": result.already_completed,
            },
        )

    async def cancel(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(
                False,
                "INVALID_SUBPROFESSION_SWITCH_COMMAND",
                f"请直接发送 {command_link(CANCEL_COMMAND, CANCEL_COMMAND)}。",
                context.request_id,
            )
        operation_id = self._operation_id(context, "cancel_switch")
        try:
            await self.repository.cancel_subprofession_switch(
                platform=context.adapter,
                platform_user_id=context.user_id,
                operation_id=operation_id,
            )
        except SubprofessionSwitchNotFoundError:
            return CommandResult(
                False,
                "SUBPROFESSION_SWITCH_NOT_FOUND",
                "没有待取消的辅修切换预览。",
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
                "当前角色处于暂停状态，暂时不能取消切换。",
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
            "SUBPROFESSION_SWITCH_CANCELLED",
            "## 辅修切换预览已取消\n\n未扣除灵石。",
            context.request_id,
            operation_id,
        )


__all__ = [
    "CANCEL_COMMAND",
    "CONFIRM_COMMAND",
    "PREVIEW_COMMAND",
    "SubprofessionSwitchApplication",
]
