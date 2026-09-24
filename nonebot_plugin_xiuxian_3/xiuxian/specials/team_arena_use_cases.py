"""Application services for asynchronous 2v2 team arena commands."""

from __future__ import annotations

from ...contracts import CommandContext, CommandResult
from ..persistence.errors import (
    OperationConflictError,
    PlayerNotFoundError,
    PlayerSuspendedError,
    RepositoryBusyError,
    TeamArenaBusyError,
    TeamArenaChallengeCapError,
    TeamArenaOpponentUnavailableError,
    TeamArenaPermissionError,
    TeamArenaSnapshotNotFoundError,
    TeamArenaSnapshotRequirementError,
)
from .team_arena_models import TeamArenaMatchRecord, TeamArenaSnapshotRecord
from .team_arena_repository import TeamArenaRepositoryMixin


class TeamArenaApplication:
    """Translate team arena inputs into adapter-neutral DTOs."""

    def __init__(self, repository: TeamArenaRepositoryMixin):
        self.repository = repository

    @staticmethod
    def _operation_id(context: CommandContext, name: str) -> str:
        if context.operation_id:
            return context.operation_id
        return f"{name}:{context.adapter}:{context.user_id}:{context.message_id or context.request_id}"

    @staticmethod
    def _display(value: object) -> str:
        return str(value or "未命名").replace("`", "\\`").replace("*", "\\*").replace("_", "\\_")

    @staticmethod
    def _error(context: CommandContext, operation_id: str, exc: Exception) -> CommandResult:
        errors = {
            PlayerNotFoundError: ("PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。"),
            PlayerSuspendedError: ("PLAYER_SUSPENDED", "当前角色暂时不能进行组队竞技场操作。"),
            TeamArenaSnapshotRequirementError: ("TEAM_ARENA_REQUIREMENT_MISSING", "需要一支已确认的双人队伍，且队伍没有进行中的战斗。"),
            TeamArenaPermissionError: ("TEAM_ARENA_PERMISSION_DENIED", "只有已确认队伍的队长可以操作组队竞技场。"),
            TeamArenaBusyError: ("TEAM_ARENA_BUSY", "队伍当前已有锁定中的会话。"),
            TeamArenaSnapshotNotFoundError: ("TEAM_ARENA_SNAPSHOT_NOT_FOUND", "没有找到可用的组队竞技场快照。"),
            TeamArenaOpponentUnavailableError: ("TEAM_ARENA_OPPONENT_UNAVAILABLE", "当前没有相邻积分段的可挑战队伍。"),
            TeamArenaChallengeCapError: ("TEAM_ARENA_DAILY_CAP", "今日组队竞技场挑战次数已用尽。"),
            OperationConflictError: ("OPERATION_CONFLICT", "这次请求编号已用于其他组队竞技场操作。"),
            RepositoryBusyError: ("PERSISTENCE_BUSY", "组队竞技场簿暂时繁忙，请稍后再试。"),
        }
        for error_type, (code, message) in errors.items():
            if isinstance(exc, error_type):
                return CommandResult(False, code, message, context.request_id, operation_id or None, retryable=error_type is RepositoryBusyError)
        return CommandResult(False, "PERSISTENCE_ERROR", "组队竞技场簿暂时不可用，请稍后再试。", context.request_id, operation_id or None, retryable=True)

    @staticmethod
    def _snapshot_data(record: TeamArenaSnapshotRecord) -> dict[str, object]:
        return {"snapshot_id": record.snapshot_id, "party_id": record.party_id, "status": record.status, "public_summary": dict(record.public_summary), "rating": record.rating, "matchable_at": record.matchable_at, "expires_at": record.expires_at, "idempotent_replay": record.already_completed}

    @staticmethod
    def _match_data(record: TeamArenaMatchRecord) -> dict[str, object]:
        return {"match_id": record.match_id, "mode_key": "arena.team", "outcome": record.outcome, "rounds": record.rounds, "challenger_rating": record.challenger_rating, "defender_rating": record.defender_rating, "opponent_summary": dict(record.opponent_summary), "idempotent_replay": record.already_completed}

    async def publish_snapshot(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_TEAM_ARENA_COMMAND", "发布组队竞技场快照无需附加参数。", context.request_id)
        operation_id = self._operation_id(context, "arena.team.publish")
        try:
            record = await self.repository.publish_team_arena_snapshot(platform=context.adapter, platform_user_id=context.user_id, operation_id=operation_id)
        except Exception as exc:
            return self._error(context, operation_id, exc)
        return CommandResult(True, "TEAM_ARENA_SNAPSHOT_PUBLISHED", f"## 组队竞技场快照已发布\n\n快照 `{record.snapshot_id}` 将在 30 分钟后进入匹配池，有效 7 天。", context.request_id, operation_id, data=self._snapshot_data(record))

    async def list_snapshots(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_TEAM_ARENA_COMMAND", "组队竞技场列表无需附加参数。", context.request_id)
        try:
            records = await self.repository.list_team_arena_snapshots(platform=context.adapter, platform_user_id=context.user_id)
        except Exception as exc:
            return self._error(context, "", exc)
        lines = ["## 组队竞技场匹配池", ""]
        for record in records:
            members = "、".join(self._display(item.get("display_name")) for item in record.public_summary.get("members", []))
            lines.append(f"- `{record.snapshot_id}` · **{members or '双人队伍'}** · 积分 {record.rating}")
        if not records:
            lines.append("当前没有相邻积分段的可挑战队伍。")
        return CommandResult(True, "TEAM_ARENA_SNAPSHOT_LIST", "\n".join(lines), context.request_id, data={"snapshots": [self._snapshot_data(record) for record in records]})

    async def challenge(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) > 1:
            return CommandResult(False, "INVALID_TEAM_ARENA_COMMAND", "挑战组队竞技场最多接收一个快照编号。", context.request_id)
        operation_id = self._operation_id(context, "arena.team.challenge")
        try:
            record = await self.repository.challenge_team_arena(platform=context.adapter, platform_user_id=context.user_id, snapshot_id=context.command_args[0] if context.command_args else None, operation_id=operation_id)
        except Exception as exc:
            return self._error(context, operation_id, exc)
        outcome = {"challenger_won": "胜利", "defender_won": "落败", "draw": "平局"}.get(record.outcome, record.outcome)
        members = "、".join(self._display(item.get("display_name")) for item in record.opponent_summary.get("members", []))
        return CommandResult(True, "TEAM_ARENA_MATCH_SETTLED", f"## 组队竞技场结束\n\n- **结果**：{outcome}\n- **回合**：{record.rounds}/15\n- **对手**：{members or '双人队伍'}\n\n服务器已固定双方队伍快照并保存完整行动回放；本模式不转移玩家资产。", context.request_id, operation_id, data=self._match_data(record))

    async def replay(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) > 1:
            return CommandResult(False, "INVALID_TEAM_ARENA_COMMAND", "组队竞技场回放最多接收一个对局编号。", context.request_id)
        try:
            record = await self.repository.replay_team_arena(platform=context.adapter, platform_user_id=context.user_id, match_id=context.command_args[0] if context.command_args else None)
        except Exception as exc:
            return self._error(context, "", exc)
        return CommandResult(True, "TEAM_ARENA_REPLAY", f"## 组队竞技场行动回放\n\n- **对局**：`{record.match_id}`\n- **结果**：{record.outcome}\n- **回合**：{record.rounds}/15\n- **行动数**：{len(record.actions)}", context.request_id, data={"match_id": record.match_id, "status": record.status, "outcome": record.outcome, "rounds": record.rounds, "snapshot": record.snapshot, "result": record.result, "actions": list(record.actions)})


__all__ = ["TeamArenaApplication"]
