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
from .codex_rules import MILESTONES


_CATEGORY_LABELS = {
    "place": "地点",
    "material": "材料",
    "creature": "异兽",
    "path": "道途",
    "route": "路线",
    "dispatch": "派遣",
    "challenge": "挑战",
    "story": "故事",
}
_UNLOCK_LABELS = {
    "commission.town.extra_offer": "城镇委托展示额外条目",
    "hint.herb_route": "药圃路线提示",
    "display.codex_creature_badge": "异兽收集徽记",
    "hint.tower_route": "试炼塔路线提示",
    "encyclopedia.paths_6": "六道途百科页",
}


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
            PlayerNotFoundError: ("PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。"),
            PlayerSuspendedError: ("PLAYER_SUSPENDED", "当前角色暂时不能查看或领取图鉴。"),
            CodexMilestoneNotFoundError: ("CODEX_MILESTONE_NOT_FOUND", "没有找到这项图鉴里程碑。"),
            CodexMilestoneNotReadyError: ("CODEX_MILESTONE_NOT_READY", "图鉴条目尚未收录齐全。"),
            CodexMilestoneAlreadyClaimedError: ("CODEX_MILESTONE_ALREADY_CLAIMED", "这项图鉴里程碑已经领取。"),
            OperationConflictError: ("OPERATION_CONFLICT", "这次请求编号已用于其他图鉴操作。"),
            RepositoryBusyError: ("PERSISTENCE_BUSY", "图鉴暂时繁忙，请稍后再试。"),
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
            "图鉴暂时不可用，请稍后再试。",
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
        normalized_category = next(
            (key for key, label in _CATEGORY_LABELS.items() if filter_value in {key, label}),
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
                lines.append(f"- **{item.label}** · {_CATEGORY_LABELS.get(item.category, item.category)} · 首见 {item.first_seen_at[:10]}")
        else:
            lines.append("尚无符合条件的已发现条目。")
        lines.extend(["", "### 集合里程碑", ""])
        milestones: list[dict[str, object]] = []
        for index, item in enumerate(record.milestones, start=1):
            if item.claimed:
                status = "已领取"
            elif item.ready:
                status = "可领取"
            else:
                status = f"收录 {item.discovered_count}/{item.required_count}"
            lines.append(f"- **{index}. {item.label}**：{status}")
            milestones.append(
                {
                    "index": index,
                    "milestone_key": item.milestone_key,
                    "label": item.label,
                    "discovered_count": item.discovered_count,
                    "required_count": item.required_count,
                    "ready": item.ready,
                    "claimed": item.claimed,
                    "reward": {"local_reputation": item.reputation_reward} if item.reputation_reward else {},
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
                "请使用 `领取图鉴里程碑 <序号>`，序号可在 `我的图鉴` 中查看。",
                context.request_id,
            )
        value = context.command_args[0].strip()
        definitions = tuple(MILESTONES.values())
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
        definition = MILESTONES[record.milestone_key]
        reward = "、".join(f"{key} +{amount}" for key, amount in record.reward.items()) or "无数值奖励"
        unlocks = "、".join(_UNLOCK_LABELS.get(key, key) for key in record.unlocks)
        replay_text = "（请求已回放）" if record.already_completed else ""
        return CommandResult(
            True,
            "CODEX_MILESTONE_CLAIMED",
            f"已领取 **{definition.label}**：{reward}；解锁：{unlocks}。{replay_text}",
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
