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
from .story_rules import resolve_branch, story_definition


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
        lines = [
            f"## {record.name}",
            "",
            record.description,
            "",
            f"- **状态**：{state_labels.get(record.status, record.status)}",
        ]
        if record.selected_route:
            branch = next(item for item in record.branches if item.key == record.selected_route)
            lines.append(f"- **已选路线**：{branch.label}")
        else:
            lines.extend(["", "### 可选路线"])
            for branch in record.branches:
                count = len(branch.evidence_operation_ids)
                readiness = (
                    "已具备选择资格"
                    if branch.eligible
                    else f"尚需 {branch.required_source_count - count} 项经历"
                )
                lines.append(
                    f"- **{branch.label}**：{branch.description}；{branch.source_label}，{readiness}。"
                )
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
            f"{record.name}已开启。完成相应经历后，可从{'、'.join(branch.label for branch in record.branches)}中选择一段过往；选择后不可更改。",
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
            try:
                labels = "|".join(
                    branch.label for branch in story_definition(self.repository.content).branches
                )
            except Exception as exc:
                return self._error(context, "", exc)
            return CommandResult(
                False,
                "INVALID_STORY_COMMAND",
                f"请使用 `选择剧情 <{labels}>`。",
                context.request_id,
            )
        operation_id = self._operation_id(context, "specials.choose_story_node")
        try:
            route_key = resolve_branch(context.command_args[0], self.repository.content)
            if route_key is None:
                raise StoryChoiceRequirementError("unsupported story route")
            record = await self.repository.choose_story_route(
                platform=context.adapter,
                platform_user_id=context.user_id,
                route_key=route_key,
                operation_id=operation_id,
            )
        except Exception as exc:
            return self._error(context, operation_id, exc)
        branch = next(item for item in record.branches if item.key == route_key)
        return CommandResult(
            True,
            "STORY_ROUTE_LOCKED",
            f"已选定 **{branch.label}** 这段经历，记下了 {len(record.completed_nodes)} 段过往。发送 `领取剧情结局` 领取结局嘉奖。",
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
        choice = record.snapshot.get("choice", {})
        branch = choice["branch"]
        reputation_name = str(choice["reputation_name"])
        reputation_gain = int(record.reward.get("local_reputation", 0))
        reputation_text = (
            f"{reputation_name}名望 +{reputation_gain}"
            if reputation_gain
            else f"{reputation_name}名望已达上限"
        )
        replay = "（请求已回放）" if record.already_completed else ""
        return CommandResult(
            True,
            "STORY_ENDING_CLAIMED",
            f"已完成 **{branch['label']}** 结局：{reputation_text}，收录故事并解锁居所外观。{replay}",
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
                "codex_entry_key": choice["codex_entry_key"],
                "appearance_key": choice["appearance_key"],
                "idempotent_replay": record.already_completed,
            },
        )


__all__ = ["StoryApplication"]
