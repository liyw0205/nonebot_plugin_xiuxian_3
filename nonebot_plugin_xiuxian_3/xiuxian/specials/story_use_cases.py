"""Application services for the branching story."""

from __future__ import annotations

from ...contracts import CommandContext, CommandResult
from ..persistence.errors import (
    OperationConflictError,
    PlayerNotFoundError,
    PlayerSuspendedError,
    RepositoryBusyError,
    StoryChoiceConflictError,
    StoryChoiceRequirementError,
    StoryEndingAlreadyClaimedError,
    StoryEndingNotAvailableError,
    StoryNotStartedError,
    StoryRequirementError,
)
from .story_repository import StoryRepositoryMixin
from .story_rules import BRANCHES, resolve_branch


class StoryApplication:
    def __init__(self, repository: StoryRepositoryMixin):
        self.repository = repository

    @staticmethod
    def _operation_id(context: CommandContext, name: str) -> str:
        if context.operation_id:
            return context.operation_id
        key = context.message_id or context.request_id
        return f"{name}:{context.adapter}:{context.user_id}:{key}"

    @staticmethod
    def _error(context: CommandContext, operation_id: str, exc: Exception) -> CommandResult:
        errors = {
            PlayerNotFoundError: ("PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。"),
            PlayerSuspendedError: ("PLAYER_SUSPENDED", "当前角色暂时不能查看或推进剧情。"),
            StoryRequirementError: ("STORY_REQUIREMENT_MISSING", "请先完成 `寻仙问道`，再开始剧情。"),
            StoryNotStartedError: ("STORY_NOT_STARTED", "请先发送 `开始剧情`。"),
            StoryChoiceRequirementError: ("STORY_CHOICE_NOT_READY", "该分支前置来源尚未达成，或分支无效。"),
            StoryChoiceConflictError: ("STORY_CHOICE_LOCKED", "剧情分支已经锁定，不能改选。"),
            StoryEndingNotAvailableError: ("STORY_ENDING_NOT_READY", "当前没有待领取的剧情结局。"),
            StoryEndingAlreadyClaimedError: ("STORY_ENDING_ALREADY_CLAIMED", "剧情结局奖励已经领取。"),
            OperationConflictError: ("OPERATION_CONFLICT", "这次请求编号已用于其他剧情操作。"),
            RepositoryBusyError: ("PERSISTENCE_BUSY", "剧情暂时繁忙，请稍后再试。"),
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
            "剧情暂时不可用，请稍后再试。",
            context.request_id,
            operation_id or None,
            retryable=True,
        )

    async def status(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_STORY_COMMAND", "剧情线查询不接受参数。", context.request_id)
        try:
            record = await self.repository.get_story_status(
                platform=context.adapter, platform_user_id=context.user_id
            )
        except Exception as exc:
            return self._error(context, "", exc)

        state_labels = {
            "available": "尚未开始",
            "active": "可选择路线",
            "ending_pending": "结局待领取",
            "ended": "已完成",
        }
        lines = ["## 玄天之路", "", f"- **状态**：{state_labels.get(record.status, record.status)}"]
        if record.selected_route:
            branch = BRANCHES[record.selected_route]
            lines.append(f"- **已选路线**：{branch.label}")
            lines.append(f"- **当前节点**：`{record.current_node}`")
        else:
            lines.extend(["", "### 可选路线"])
            for branch in record.branches:
                count = len(branch.evidence_operation_ids)
                readiness = "可选择" if branch.eligible else f"来源 {count}/{branch.required_source_count}"
                lines.append(f"- **{branch.label}**：{branch.source_label}（{readiness}）")
        if record.status == "available":
            lines.extend(["", "> 发送 `开始剧情` 开启玄天之路。"])
        elif record.status == "active":
            lines.extend(["", "> 发送 `选择剧情 <商路|守望|药圃>` 锁定一条路线。"])
        elif record.status == "ending_pending":
            lines.extend(["", "> 发送 `领取剧情结局` 结算结局。"])
        return CommandResult(
            True,
            "STORY_STATUS",
            "\n".join(lines),
            context.request_id,
            data={
                "story_key": record.story_key,
                "story_run_id": record.story_run_id,
                "status": record.status,
                "current_node": record.current_node,
                "selected_route": record.selected_route,
                "ending_key": record.ending_key,
                "completed_nodes": list(record.completed_nodes),
                "branches": [
                    {
                        "key": branch.key,
                        "label": branch.label,
                        "required_source_count": branch.required_source_count,
                        "source_label": branch.source_label,
                        "evidence_operation_ids": list(branch.evidence_operation_ids),
                        "eligible": branch.eligible,
                    }
                    for branch in record.branches
                ],
            },
        )

    async def start(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_STORY_COMMAND", "开始剧情不接受参数。", context.request_id)
        operation_id = self._operation_id(context, "specials.start_story")
        try:
            record = await self.repository.start_story(
                platform=context.adapter,
                platform_user_id=context.user_id,
                operation_id=operation_id,
            )
        except Exception as exc:
            return self._error(context, operation_id, exc)
        return CommandResult(
            True,
            "STORY_STARTED",
            "玄天之路已开启。完成商路、守望或药圃的对应经历后，可以选择一条路线；选择后不可更改。",
            context.request_id,
            operation_id,
            data={
                "story_key": record.story_key,
                "story_run_id": record.story_run_id,
                "status": record.status,
                "idempotent_replay": record.already_completed,
            },
        )

    async def choose(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 1:
            return CommandResult(
                False,
                "INVALID_STORY_COMMAND",
                "请使用 `选择剧情 <商路|守望|药圃>`。",
                context.request_id,
            )
        route_key = resolve_branch(context.command_args[0])
        if route_key is None:
            return self._error(context, "", StoryChoiceRequirementError("unsupported story route"))
        operation_id = self._operation_id(context, "specials.choose_story_node")
        try:
            record = await self.repository.choose_story_route(
                platform=context.adapter,
                platform_user_id=context.user_id,
                route_key=route_key,
                operation_id=operation_id,
            )
        except Exception as exc:
            return self._error(context, operation_id, exc)
        branch = BRANCHES[route_key]
        return CommandResult(
            True,
            "STORY_ROUTE_LOCKED",
            f"已锁定 **{branch.label}** 路线，完成节点：{len(record.completed_nodes)} 个。发送 `领取剧情结局` 领取结局包。",
            context.request_id,
            operation_id,
            data={
                "story_key": record.story_key,
                "story_run_id": record.story_run_id,
                "status": record.status,
                "selected_route": record.selected_route,
                "ending_key": record.ending_key,
                "completed_nodes": list(record.completed_nodes),
                "source_operation_ids": list(record.snapshot.get("choice", {}).get("source_operation_ids", [])),
                "idempotent_replay": record.already_completed,
            },
        )

    async def claim(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_STORY_COMMAND", "领取剧情结局不接受参数。", context.request_id)
        operation_id = self._operation_id(context, "specials.claim_story_ending")
        try:
            record = await self.repository.claim_story_ending(
                platform=context.adapter,
                platform_user_id=context.user_id,
                operation_id=operation_id,
            )
        except Exception as exc:
            return self._error(context, operation_id, exc)
        branch = BRANCHES[record.selected_route or ""]
        replay = "（请求已回放）" if record.already_completed else ""
        return CommandResult(
            True,
            "STORY_ENDING_CLAIMED",
            f"已完成 **{branch.label}** 结局：青石镇名望 +10，收录故事图鉴并解锁居所外观。{replay}",
            context.request_id,
            operation_id,
            data={
                "story_key": record.story_key,
                "story_run_id": record.story_run_id,
                "status": record.status,
                "selected_route": record.selected_route,
                "ending_key": record.ending_key,
                "completed_nodes": list(record.completed_nodes),
                "reward": record.reward,
                "codex_entry_key": branch.codex_entry_key,
                "appearance_key": branch.appearance_key,
                "idempotent_replay": record.already_completed,
            },
        )


__all__ = ["StoryApplication"]
