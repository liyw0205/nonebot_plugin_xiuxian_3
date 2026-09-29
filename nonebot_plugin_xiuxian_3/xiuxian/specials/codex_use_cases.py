"""Application services for the discovery codex."""

from __future__ import annotations

from ...contracts import CommandContext, CommandResult
from ..persistence.errors import (
    CodexMilestoneAlreadyClaimedError,
    CodexMilestoneNotFoundError,
    CodexMilestoneNotReadyError,
    OperationConflictError,
    PlayerNotFoundError,
    PlayerSuspendedError,
    RepositoryBusyError,
)
from .codex_repository import CodexRepositoryMixin
from .codex_rules import category_labels, codex_milestones, unlock_label


class CodexApplication:
    def __init__(self, repository: CodexRepositoryMixin):
        self.repository = repository

    @staticmethod
    def _operation_id(context: CommandContext) -> str:
        if context.operation_id:
            return context.operation_id
        key = context.message_id or context.request_id
        return f"specials.claim_codex_milestone:{context.adapter}:{context.user_id}:{key}"

    @staticmethod
    def _error(context: CommandContext, operation_id: str, exc: Exception) -> CommandResult:
        errors = {
            PlayerNotFoundError: ("PLAYER_NOT_FOUND", "尚未结成仙缘，请先开始修仙。"),
            PlayerSuspendedError: ("PLAYER_SUSPENDED", "当前角色暂时不能查看或领取见闻。"),
            CodexMilestoneNotFoundError: ("CODEX_MILESTONE_NOT_FOUND", "未曾听闻这份见闻之赏。"),
            CodexMilestoneNotReadyError: ("CODEX_MILESTONE_NOT_READY", "所需见闻尚未齐全。"),
            CodexMilestoneAlreadyClaimedError: ("CODEX_MILESTONE_ALREADY_CLAIMED", "这份见闻之赏已收入囊中。"),
            OperationConflictError: ("OPERATION_CONFLICT", "此番所求与先前不同，请另择一赏。"),
            RepositoryBusyError: ("PERSISTENCE_BUSY", "灵识未能通达，稍后再试。"),
        }
        for error_type, (code, message) in errors.items():
            if isinstance(exc, error_type):
                return CommandResult(
                    False,
                    code,
                    message,
                    context.request_id,
                    operation_id or None,
                    retryable=error_type is RepositoryBusyError,
                )
        return CommandResult(
            False,
            "PERSISTENCE_ERROR",
            "图卷暂不可阅，稍后再试。",
            context.request_id,
            operation_id or None,
            retryable=True,
        )

    async def get_codex(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) > 1:
            return CommandResult(False, "INVALID_CODEX_COMMAND", "图鉴查询最多接收一个分类或关键词。", context.request_id)
        try:
            record = await self.repository.get_codex(
                platform=context.adapter,
                platform_user_id=context.user_id,
            )
        except Exception as exc:
            return self._error(context, "", exc)

        filter_value = context.command_args[0].strip() if context.command_args else ""
        labels = category_labels(self.repository.content)
        normalized_category = next(
            (key for key, label in labels.items() if filter_value in {key, label}),
            None,
        )
        entries = tuple(
            item
            for item in record.entries
            if not filter_value
            or (item.category == normalized_category if normalized_category else filter_value.lower() in item.label.lower() or filter_value.lower() in item.entry_key.lower())
        )
        lines = ["## 修行图鉴", ""]
        if entries:
            for item in entries:
                lines.append(f"- **{item.label}** · {labels.get(item.category, item.category)} · 首见 {item.first_seen_at[:10]}")
        else:
            lines.append("尚无相符的见闻。")
        lines.extend(["", "### 见闻收录", ""])
        milestones: list[dict[str, object]] = []
        for index, item in enumerate(record.milestones, start=1):
            if item.claimed:
                status = "已得"
            elif item.ready:
                status = "可领取"
            else:
                status = f"收录 {item.discovered_count}/{item.required_count}"
            lines.append(f"- **{index}. {item.label}**：{status}")
            if item.claimed and item.unlocks:
                lines.append(f"  - 得：{'、'.join(unlock_label(key, self.repository.content) for key in item.unlocks)}")
            milestones.append(
                {
                    "index": index,
                    "milestone_key": item.milestone_key,
                    "label": item.label,
                    "discovered_count": item.discovered_count,
                    "required_count": item.required_count,
                    "ready": item.ready,
                    "claimed": item.claimed,
                    "reward": ({item.reputation_key: item.reputation_reward}
                               if item.reputation_key and item.reputation_reward else {}),
                    "unlocks": list(item.unlocks),
                }
            )
        return CommandResult(
            True,
            "CODEX_OVERVIEW",
            "\n".join(lines),
            context.request_id,
            data={
                "entries": [
                    {
                        "entry_key": item.entry_key,
                        "category": item.category,
                        "label": item.label,
                        "first_seen_at": item.first_seen_at,
                    }
                    for item in entries
                ],
                "milestones": milestones,
            },
        )

    async def claim_milestone(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 1:
            return CommandResult(
                False,
                "INVALID_CODEX_COMMAND",
                "请说出要领取的见闻序号或名称。",
                context.request_id,
            )
        value = context.command_args[0].strip()
        definitions = tuple(codex_milestones(self.repository.content).values())
        if value.isdecimal() and 1 <= int(value) <= len(definitions):
            milestone_key = definitions[int(value) - 1].key
        else:
            milestone_key = value
        operation_id = self._operation_id(context)
        try:
            record = await self.repository.claim_codex_milestone(
                platform=context.adapter,
                platform_user_id=context.user_id,
                milestone_key=milestone_key,
                operation_id=operation_id,
            )
        except Exception as exc:
            return self._error(context, operation_id, exc)
        definition = codex_milestones(self.repository.content)[record.milestone_key]
        reward = "、".join(
            f"{definition.reputation_name} +{amount}"
            for amount in record.reward.values()
        )
        unlocks = "、".join(unlock_label(key, self.repository.content) for key in record.unlocks)
        replay_text = "（此赏此前已领取）" if record.already_completed else ""
        benefits = "、".join(value for value in (reward, unlocks) if value)
        return CommandResult(
            True,
            "CODEX_MILESTONE_CLAIMED",
            f"已领取 **{definition.label}**。所得：{benefits}。{replay_text}",
            context.request_id,
            operation_id,
            data={
                "milestone_key": record.milestone_key,
                "reward": dict(record.reward),
                "unlocks": list(record.unlocks),
                "idempotent_replay": record.already_completed,
            },
        )


__all__ = ["CodexApplication"]
