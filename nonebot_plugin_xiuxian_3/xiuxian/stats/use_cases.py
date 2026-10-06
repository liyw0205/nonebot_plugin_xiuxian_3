"""Application queries for character attributes."""

from __future__ import annotations

from ...contracts import CommandContext, CommandResult
from ..persistence.errors import PlayerNotFoundError, PlayerSuspendedError, OperationConflictError, RepositoryBusyError
from .models import StatSnapshotError
from .presentation import SOURCE_LABELS, STAT_LABELS, stat_lines, stat_value_text
from .rules import StatError


class StatsApplication:
    def __init__(self, repository):
        self.repository = repository

    @staticmethod
    def _operation_id(context: CommandContext, purpose: str) -> str:
        if context.operation_id:
            return context.operation_id
        return f"stats.freeze:{context.adapter}:{context.user_id}:{context.message_id or context.request_id}:{purpose}"

    @staticmethod
    def _error(context: CommandContext, operation_id: str, exc: Exception) -> CommandResult:
        if isinstance(exc, PlayerNotFoundError):
            return CommandResult(False, "PLAYER_NOT_FOUND", "尚未结成仙缘，请先开始修仙。", context.request_id, operation_id)
        if isinstance(exc, PlayerSuspendedError):
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能查看属性。", context.request_id, operation_id)
        if isinstance(exc, StatError):
            return CommandResult(False, exc.code, str(exc), context.request_id, operation_id)
        if isinstance(exc, StatSnapshotError):
            return CommandResult(False, exc.code, "此番修行的记录有误，暂时无法推演。", context.request_id, operation_id)
        if isinstance(exc, OperationConflictError):
            return CommandResult(False, "OPERATION_CONFLICT", "此番修行已有不同约定，请重新发起。", context.request_id, operation_id)
        if isinstance(exc, RepositoryBusyError):
            return CommandResult(False, "PERSISTENCE_BUSY", "属性推演暂时未能通达，请稍后再试。", context.request_id, operation_id, retryable=True)
        return CommandResult(False, "PERSISTENCE_ERROR", "属性推演暂不可用，请稍后再试。", context.request_id, operation_id, retryable=True)

    async def preview(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_STATS_COMMAND", "查看属性无需附加参数。", context.request_id)
        try:
            preview = await self.repository.preview_stats(platform=context.adapter, platform_user_id=context.user_id)
        except Exception as exc:
            return self._error(context, "", exc)
        derived = preview["derived_stats"]
        base = preview["base_stats"]
        lines = ["## 当前属性", "", "### 六项资质"]
        labels = {"body": "体魄", "spirit": "灵力", "insight": "悟性", "root": "根骨", "agility": "身法", "fortune": "气运"}
        lines.extend(f"- **{labels[key]}**：{base[key]}" for key in base)
        lines.extend(["", "### 周身气象", *stat_lines(derived)])
        return CommandResult(True, "STATS_PREVIEW", "\n".join(lines), context.request_id, data=preview)

    async def explain(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 1:
            return CommandResult(False, "INVALID_STATS_COMMAND", "请指定要查看的属性，例如 `属性说明 气血上限`。", context.request_id)
        labels = {label: key for key, label in STAT_LABELS.items()}
        stat_key = labels.get(context.command_args[0], context.command_args[0])
        try:
            explanation = await self.repository.explain_stats(platform=context.adapter, platform_user_id=context.user_id, stat_key=stat_key)
        except Exception as exc:
            return self._error(context, "", exc)
        sources = list(dict.fromkeys(
            SOURCE_LABELS[source["key"]] for source in explanation["sources"]
            if source["key"] in {"realm", "qualification"} or source.get("effect", {}).get(stat_key, 0)
        ))
        value = stat_value_text(stat_key, explanation["value"])
        message = f"**{STAT_LABELS[stat_key]}**：{value}\n\n源自{'、'.join(sources)}。"
        return CommandResult(True, "STAT_EXPLAINED", message, context.request_id, data=explanation)

    async def freeze(self, context: CommandContext, *, purpose: str) -> CommandResult:
        operation_id = self._operation_id(context, purpose)
        try:
            snapshot = await self.repository.freeze_stats(platform=context.adapter, platform_user_id=context.user_id, purpose=purpose, operation_id=operation_id)
        except Exception as exc:
            return self._error(context, operation_id, exc)
        return CommandResult(
            True,
            "STATS_FROZEN",
            "此刻的根基与修为已记下，可供此番修行参照。",
            context.request_id,
            operation_id,
            data={**snapshot.payload(), "idempotent_replay": snapshot.already_completed},
        )


__all__ = ["StatsApplication"]
