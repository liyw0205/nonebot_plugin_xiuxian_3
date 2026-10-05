"""Adapter-neutral commands for the void archive."""

from __future__ import annotations

from ...contracts import CommandContext, CommandResult
from ..content import ContentError
from ..persistence.errors import (
    BattleNotReadyError,
    OperationConflictError,
    PlayerNotFoundError,
    PlayerSuspendedError,
    QuestAlreadyCompletedError,
    QuestRequirementError,
    QuestResourceInsufficientError,
    RepositoryBusyError,
    VoidArchiveGuardAlreadySettledError,
    VoidArchiveRouteEvidenceError,
    VoidArchiveTaskAlreadyClaimedError,
    VoidArchiveTaskInvalidError,
    VoidArchiveTaskNotCompleteError,
)
from ..rewards.rules import RewardContentError
from .void_archive_models import VoidArchiveStatusRecord
from .void_archive_repository import VoidArchiveRepositoryMixin
from .presentation import public_event_reward_lines
from .void_archive_rules import resolve_archive_task, void_archive_definition


class VoidArchiveApplication:
    """Expose archive runs and weekly claims to every adapter."""

    def __init__(self, repository: VoidArchiveRepositoryMixin):
        self.repository = repository

    @staticmethod
    def _operation_id(context: CommandContext, name: str) -> str:
        if context.operation_id:
            return context.operation_id
        key = context.message_id or context.request_id
        return f"event.void_archive.{name}:{context.adapter}:{context.user_id}:{key}"

    @staticmethod
    def _error(context: CommandContext, operation_id: str, exc: Exception) -> CommandResult:
        mapping = {
            VoidArchiveRouteEvidenceError: (
                "ARCHIVE_ROUTE_REQUIRED",
                "需要先结算一次 `虚空档案遗迹` 航道，才能挑战档案守卫。",
            ),
            VoidArchiveGuardAlreadySettledError: (
                "ARCHIVE_GUARD_ALREADY_SETTLED",
                "这次档案遗迹航道已经完成守卫结算。",
            ),
            VoidArchiveTaskNotCompleteError: (
                "ARCHIVE_TASK_NOT_COMPLETE",
                "该档案碎片周任务的服务端证据尚未达标。",
            ),
            VoidArchiveTaskAlreadyClaimedError: (
                "ARCHIVE_TASK_ALREADY_CLAIMED",
                "该档案碎片周任务本周已经领取。",
            ),
            VoidArchiveTaskInvalidError: (
                "INVALID_ARCHIVE_TASK",
                "请指定有效的档案碎片任务。",
            ),
            QuestRequirementError: ("QUEST_REQUIREMENT_MISSING", "当前境界不满足档案遗迹前置。"),
            QuestResourceInsufficientError: ("QUEST_RESOURCE_INSUFFICIENT", "任务材料不足。"),
            QuestAlreadyCompletedError: ("QUEST_ALREADY_COMPLETED", "档案遗迹来源本轮已经记录。"),
            PlayerNotFoundError: ("PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。"),
            PlayerSuspendedError: ("PLAYER_SUSPENDED", "当前角色暂时不能执行档案操作。"),
            OperationConflictError: ("OPERATION_CONFLICT", "此事已有安排，请重新起意。"),
            RepositoryBusyError: ("PERSISTENCE_BUSY", "档案簿暂时繁忙，请稍后再试。"),
            ContentError: ("CONTENT_UNAVAILABLE", "档案内容暂不可用，角色状态未改变。"),
            RewardContentError: ("CONTENT_UNAVAILABLE", "档案嘉奖暂不可用，角色状态未改变。"),
        }
        code, message = mapping.get(type(exc), ("PERSISTENCE_ERROR", "档案簿暂时不可用，请稍后再试。"))
        return CommandResult(
            False,
            code,
            message,
            context.request_id,
            operation_id or None,
            retryable=isinstance(exc, RepositoryBusyError),
        )

    @staticmethod
    def _status_data(record: VoidArchiveStatusRecord) -> dict[str, object]:
        return {
            "week_id": record.week_id,
            "week_ends_at": record.week_ends_at,
            "tasks": record.tasks,
            "unlocked": record.unlocked,
            "unlock_expires_at": record.unlock_expires_at,
        }

    async def get_status(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_ARCHIVE_COMMAND", "档案状态无需附加参数。", context.request_id)
        try:
            definition = void_archive_definition(self.repository.content)
            record = await self.repository.get_void_archive_status(
                platform=context.adapter, platform_user_id=context.user_id
            )
        except Exception as exc:
            return self._error(context, "", exc)
        state = "已解锁" if record.unlocked else "未解锁"
        lines = [
            "## 虚空档案",
            "",
            f"**周次**：`{record.week_id}`",
            f"**档案航道**：{state}",
        ]
        status_labels = {"claimed": "已领取", "complete": "待领取", "active": "进行中"}
        for task_definition in definition.tasks:
            task_key = task_definition.key
            task = record.tasks[task_key]
            lines.append(
                f"**{task['name']}**：{task['progress']}/{task['target']} · {status_labels[str(task['status'])]}"
            )
        return CommandResult(
            True,
            "ARCHIVE_STATUS",
            "\n".join(lines),
            context.request_id,
            data=self._status_data(record),
        )

    async def run_archive(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_ARCHIVE_COMMAND", "探索档案遗迹无需附加参数。", context.request_id)
        operation_id = self._operation_id(context, "run")
        try:
            started = await self.repository.start_void_archive_guard(
                platform=context.adapter,
                platform_user_id=context.user_id,
                operation_id=f"{operation_id}:battle",
            )
            resolved = await self._run_battle(started.battle_id, started.round_no)
            record = await self.repository.record_void_archive_run(
                platform=context.adapter,
                platform_user_id=context.user_id,
                battle_id=resolved.battle_id,
                outcome=resolved.outcome,
                operation_id=operation_id,
            )
        except Exception as exc:
            return self._error(context, operation_id, exc)
        outcome = "胜利" if record.outcome == "won" else "失败"
        reward_lines = public_event_reward_lines(record.reward, self.repository.content)
        reward = "\n".join(reward_lines) if reward_lines else "- 无"
        return CommandResult(
            True,
            "ARCHIVE_RUN_SETTLED",
            f"## 档案遗迹守卫战已结算\n\n- **结果**：{outcome}\n- **奖励**：\n{reward}\n\n> 守卫战的胜负只按已结算的战斗记录计入档案。",
            context.request_id,
            operation_id,
            data={
                "run_id": record.run_id,
                "battle_id": record.battle_id,
                "route_session_id": record.route_session_id,
                "outcome": record.outcome,
                "reward": record.reward,
                "idempotent_replay": record.already_completed,
            },
        )

    async def claim_task(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 1:
            return CommandResult(False, "INVALID_ARCHIVE_TASK", "请指定要领取的档案碎片任务。", context.request_id)
        task_ref = context.command_args[0].strip()
        operation_id = self._operation_id(context, "task")
        try:
            record = await self.repository.replay_void_archive_task(
                operation_id=operation_id,
                task_ref=task_ref,
            )
            if record is None:
                try:
                    task_key = resolve_archive_task(task_ref, self.repository.content).key
                except KeyError as exc:
                    raise VoidArchiveTaskInvalidError("unknown archive task") from exc
                record = await self.repository.claim_void_archive_task(
                    platform=context.adapter,
                    platform_user_id=context.user_id,
                    task_key=task_key,
                    operation_id=operation_id,
                )
        except Exception as exc:
            return self._error(context, operation_id, exc)
        reward_lines = list(public_event_reward_lines(record.reward, self.repository.content))
        if record.unlock_activated:
            reward_lines.extend(public_event_reward_lines(record.unlock_reward, self.repository.content))
        reward = "\n".join(reward_lines) if reward_lines else "- 无"
        unlock = "\n\n档案航道资格已激活。" if record.unlock_activated else ""
        return CommandResult(
            True,
            "ARCHIVE_TASK_CLAIMED",
            f"## 档案碎片任务已领取\n\n- **任务**：{record.task_name}\n- **证据**：{record.progress}/{record.target}\n- **奖励**：\n{reward}{unlock}",
            context.request_id,
            operation_id,
            data={
                "week_id": record.week_id,
                "task_key": record.task_key,
                "task_name": record.task_name,
                "progress": record.progress,
                "target": record.target,
                "reward": record.reward,
                "unlock_activated": record.unlock_activated,
                "unlock_reward": record.unlock_reward,
                "unlock_expires_at": record.unlock_expires_at,
                "idempotent_replay": record.already_completed,
            },
        )

    async def _run_battle(self, battle_id: str, completed_round: int):
        turn = None
        for expected_round in range(completed_round + 1, 21):
            turn = await self.repository.run_battle_turn(
                battle_id=battle_id, expected_round=expected_round
            )
            if turn.status not in {"created", "running"}:
                break
        if turn is None or turn.status in {"created", "running"}:
            raise BattleNotReadyError("automatic archive battle did not reach a terminal state")
        return await self.repository.resolve_battle(battle_id=battle_id)


__all__ = ["VoidArchiveApplication"]
