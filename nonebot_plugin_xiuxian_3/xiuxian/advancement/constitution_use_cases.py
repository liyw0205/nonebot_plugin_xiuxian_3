"""Application services for the v0.1 constitution profile."""

from __future__ import annotations

from ...contracts import CommandContext, CommandResult
from ..repository import (
    ConstitutionAlreadySelectedError,
    ConstitutionBusyError,
    ConstitutionCooldownError,
    ConstitutionNotFoundError,
    ConstitutionSameError,
    OperationConflictError,
    PlayerNotFoundError,
    PlayerStageConflictError,
    PlayerSuspendedError,
    RepositoryBusyError,
    ResourceInsufficientError,
    SQLitePlayerRepository,
)
from .constitution_rules import (
    constitution_definition,
    constitution_options,
    constitution_reshape_rules,
    default_content_bundle,
)


class ConstitutionApplication:
    """Coordinate constitution selection without exposing persistence details."""

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

    @staticmethod
    def _effect_value(effect: dict) -> str:
        value = effect["value"]
        if str(effect["type"]).endswith("_bp"):
            return f"+{int(value) / 100:g}%"
        return f"+{value}"

    @staticmethod
    def _duration(seconds: int) -> str:
        if seconds % 86_400 == 0:
            return f"{seconds // 86_400} 天"
        if seconds % 3_600 == 0:
            return f"{seconds // 3_600} 小时"
        if seconds % 60 == 0:
            return f"{seconds // 60} 分钟"
        return f"{seconds} 秒"

    def _resolve_key(self, args: tuple[str, ...]) -> str | None:
        if len(args) != 1:
            return None
        try:
            return constitution_definition(args[0], self.repository.content).key
        except ValueError:
            return None

    async def preview(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_CONSTITUTION_COMMAND", "体质预览无需附加参数。", context.request_id)
        reshape_rules = constitution_reshape_rules(self.repository.content)
        cooldown = int(reshape_rules["cooldown_seconds"])
        content = self.repository.content or default_content_bundle()
        item_key = str(reshape_rules["reset_item_key"])
        item_name = content.label("item", item_key)
        lines = ["## 体质根性", "", f"入道后可选择一项主质，重塑需持有 **{item_name}**：", ""]
        for definition in constitution_options(content):
            suffix = self._effect_value(definition.effect)
            lines.append(f"- **{definition.label}**：{definition.description}{suffix}")
        lines.extend(["", f"> 首次选择不消耗道具；重塑间隔 {self._duration(cooldown)}，且不会返还已用天赋点。"])
        return CommandResult(True, "CONSTITUTION_PREVIEW", "\n".join(lines), context.request_id)

    async def select(self, context: CommandContext) -> CommandResult:
        key = self._resolve_key(context.command_args)
        if key is None:
            return CommandResult(False, "INVALID_CONSTITUTION", "请选择一项体质，例如 `选择体质 铁骨`。", context.request_id)
        operation_id = self._operation_id(context, "constitution.select")
        try:
            record = await self.repository.select_constitution(
                platform=context.adapter,
                platform_user_id=context.user_id,
                constitution_key=key,
                operation_id=operation_id,
            )
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except PlayerStageConflictError:
            return CommandResult(False, "PLAYER_STAGE_CONFLICT", "完成入道后才能选择体质。", context.request_id, operation_id)
        except ConstitutionAlreadySelectedError:
            return CommandResult(False, "CONSTITUTION_ALREADY_SELECTED", "你已经选择过主质，后续请使用 `重塑体质`。", context.request_id, operation_id)
        except ConstitutionBusyError:
            return CommandResult(False, "CONSTITUTION_BUSY", "当前有其他长时会话进行中，请先完成结算。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能选择体质。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于其他体质操作，请重新发起。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        return self._success_result(context, record, operation_id, title="体质已定")

    async def reshape(self, context: CommandContext) -> CommandResult:
        key = self._resolve_key(context.command_args)
        if key is None:
            return CommandResult(False, "INVALID_CONSTITUTION", "请指定要重塑的体质，例如 `重塑体质 风行`。", context.request_id)
        operation_id = self._operation_id(context, "constitution.reshape")
        try:
            record = await self.repository.reshape_constitution(
                platform=context.adapter,
                platform_user_id=context.user_id,
                constitution_key=key,
                operation_id=operation_id,
            )
        except ConstitutionNotFoundError:
            return CommandResult(False, "CONSTITUTION_NOT_SELECTED", "你还没有主质，请先发送 `选择体质 <选项>`。", context.request_id, operation_id)
        except ConstitutionCooldownError:
            cooldown = int(constitution_reshape_rules(self.repository.content)["cooldown_seconds"])
            return CommandResult(False, "CONSTITUTION_COOLDOWN", f"体质重塑间隔未满，请 {self._duration(cooldown)}后再试。", context.request_id, operation_id)
        except ConstitutionSameError:
            return CommandResult(False, "CONSTITUTION_SAME", "当前主质已经是这一项，无需重塑。", context.request_id, operation_id)
        except ResourceInsufficientError:
            return CommandResult(False, "RESOURCE_INSUFFICIENT", "缺少重塑所需凭证，无法改变主质。", context.request_id, operation_id)
        except ConstitutionBusyError:
            return CommandResult(False, "CONSTITUTION_BUSY", "当前有其他长时会话进行中，请先完成结算。", context.request_id, operation_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except PlayerStageConflictError:
            return CommandResult(False, "PLAYER_STAGE_CONFLICT", "完成入道后才能重塑体质。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能重塑体质。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于其他体质操作，请重新发起。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        return self._success_result(context, record, operation_id, title="体质已重塑")

    async def profile(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_CONSTITUTION_COMMAND", "查看体质无需附加参数。", context.request_id)
        try:
            record = await self.repository.get_constitution(
                platform=context.adapter,
                platform_user_id=context.user_id,
            )
        except ConstitutionNotFoundError:
            return CommandResult(False, "CONSTITUTION_NOT_SELECTED", "你还没有主质，请先发送 `选择体质 <选项>`。", context.request_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能查看体质。", context.request_id)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, retryable=True)
        effect_value = self._effect_value(record.effect)
        return CommandResult(
            True,
            "CONSTITUTION_PROFILE",
            f"## 我的体质\n\n**{self._display_name(record.player)}**的主质是 **{record.label}**。\n\n- **效果**：{record.description}（{effect_value}）\n- **选择时间**：{record.selected_at}\n- **重塑次数**：{record.reshape_count}",
            context.request_id,
            data={
                "constitution_key": record.constitution_key,
                "label": record.label,
                "description": record.description,
                "effect": record.effect,
                "status": record.status,
                "selected_at": record.selected_at,
                "last_reshaped_at": record.last_reshaped_at,
                "reshape_count": record.reshape_count,
            },
        )

    @classmethod
    def _success_result(cls, context: CommandContext, record, operation_id: str, *, title: str) -> CommandResult:
        effect_value = cls._effect_value(record.effect)
        return CommandResult(
            True,
            "CONSTITUTION_SELECTED" if title == "体质已定" else "CONSTITUTION_RESHAPED",
            f"## {title}\n\n**{cls._display_name(record.player)}**选择了 **{record.label}**。\n\n- **效果**：{record.description}（{effect_value}）\n- **重塑次数**：{record.reshape_count}\n\n> 新的体质将伴你继续修行。",
            context.request_id,
            operation_id,
            data={
                "constitution_key": record.constitution_key,
                "label": record.label,
                "effect": record.effect,
                "status": record.status,
                "selected_at": record.selected_at,
                "last_reshaped_at": record.last_reshaped_at,
                "reshape_count": record.reshape_count,
                "idempotent_replay": record.already_completed,
            },
        )


__all__ = ["ConstitutionApplication"]
