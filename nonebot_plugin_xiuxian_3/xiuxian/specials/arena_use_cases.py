"""Adapter-neutral application services for the asynchronous arena."""

from __future__ import annotations

from ...contracts import CommandContext, CommandResult
from ..persistence.errors import (
    ArenaChallengeCapError,
    ArenaMatchNotFoundError,
    ArenaMatchRequirementError,
    ArenaOpponentUnavailableError,
    ArenaPlayerBusyError,
    ArenaRewardAlreadyClaimedError,
    ArenaRewardNotAvailableError,
    ArenaSnapshotExpiredError,
    ArenaSnapshotNotFoundError,
    ArenaSnapshotRequirementError,
    OperationConflictError,
    PlayerNotFoundError,
    PlayerSuspendedError,
    RepositoryBusyError,
)
from .arena_models import ArenaMatchRecord, ArenaSnapshotRecord
from .arena_repository import ArenaRepositoryMixin


class ArenaApplication:
    """Validate command arguments and render arena DTOs without domain rules."""

    def __init__(self, repository: ArenaRepositoryMixin):
        self.repository = repository

    @staticmethod
    def _operation_id(context: CommandContext, operation_name: str) -> str:
        if context.operation_id:
            return context.operation_id
        key = context.message_id or context.request_id
        return f"{operation_name}:{context.adapter}:{context.user_id}:{key}"

    @staticmethod
    def _display(value: object) -> str:
        text = str(value or "未命名")
        return (
            text.replace("\\", "\\\\")
            .replace("`", "\\`")
            .replace("*", "\\*")
            .replace("_", "\\_")
            .replace("~", "\\~")
        )

    @staticmethod
    def _error(context: CommandContext, operation_id: str, exc: Exception) -> CommandResult:
        errors = {
            PlayerNotFoundError: ("PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。"),
            PlayerSuspendedError: ("PLAYER_SUSPENDED", "当前角色暂时不能进行竞技场操作。"),
            ArenaSnapshotRequirementError: ("ARENA_REQUIREMENT_MISSING", "竞技场需要已入道的 active 修行者。"),
            ArenaPlayerBusyError: ("ARENA_PLAYER_BUSY", "当前角色有未结束的战斗或修行会话，请先结算。"),
            ArenaSnapshotNotFoundError: ("ARENA_SNAPSHOT_NOT_FOUND", "没有找到可用的竞技场快照。"),
            ArenaSnapshotExpiredError: ("ARENA_SNAPSHOT_EXPIRED", "该竞技场快照已经过期或被撤销。"),
            ArenaOpponentUnavailableError: ("ARENA_OPPONENT_UNAVAILABLE", "当前没有相邻积分段的可挑战快照。"),
            ArenaMatchRequirementError: ("ARENA_MATCH_NOT_ALLOWED", "该快照暂不可计分挑战。"),
            ArenaChallengeCapError: ("ARENA_DAILY_CAP", "今日竞技场挑战次数已用尽。"),
            ArenaMatchNotFoundError: ("ARENA_MATCH_NOT_FOUND", "没有找到可查看的竞技场对局。"),
            ArenaRewardAlreadyClaimedError: ("ARENA_RESULT_ALREADY_ACKNOWLEDGED", "这场竞技场结果已经确认。"),
            ArenaRewardNotAvailableError: ("ARENA_RESULT_NOT_AVAILABLE", "当前没有待确认的竞技场结果。"),
            OperationConflictError: ("OPERATION_CONFLICT", "这次请求编号已用于其他竞技场操作。"),
            RepositoryBusyError: ("PERSISTENCE_BUSY", "竞技场簿暂时繁忙，请稍后再试。"),
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
            "竞技场簿暂时不可用，请稍后再试。",
            context.request_id,
            operation_id or None,
            retryable=True,
        )

    @staticmethod
    def _snapshot_data(record: ArenaSnapshotRecord) -> dict[str, object]:
        return {
            "snapshot_id": record.snapshot_id,
            "status": record.status,
            "public_summary": dict(record.public_summary),
            "rating": record.rating,
            "matchable_at": record.matchable_at,
            "expires_at": record.expires_at,
            "idempotent_replay": record.already_completed,
        }

    @staticmethod
    def _match_data(record: ArenaMatchRecord) -> dict[str, object]:
        return {
            "match_id": record.match_id,
            "outcome": record.outcome,
            "rounds": record.rounds,
            "score_counted": record.score_counted,
            "challenger_rating": record.challenger_rating,
            "defender_rating": record.defender_rating,
            "challenger_rating_delta": record.challenger_rating_delta,
            "defender_rating_delta": record.defender_rating_delta,
            "opponent_summary": dict(record.opponent_summary),
            "idempotent_replay": record.already_completed,
        }

    async def publish_snapshot(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_ARENA_COMMAND", "发布竞技场快照无需附加参数。", context.request_id)
        operation_id = self._operation_id(context, "arena.publish")
        try:
            record = await self.repository.publish_arena_snapshot(
                platform=context.adapter, platform_user_id=context.user_id, operation_id=operation_id
            )
        except Exception as exc:
            return self._error(context, operation_id, exc)
        return CommandResult(
            True,
            "ARENA_SNAPSHOT_PUBLISHED",
            f"## 竞技场防守快照已发布\n\n快照 `{record.snapshot_id}` 将在 30 分钟后进入匹配池，有效 7 天。",
            context.request_id,
            operation_id,
            data=self._snapshot_data(record),
        )

    async def revoke_snapshot(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) > 1:
            return CommandResult(False, "INVALID_ARENA_COMMAND", "撤销快照最多接收一个快照编号。", context.request_id)
        operation_id = self._operation_id(context, "arena.revoke")
        try:
            record = await self.repository.revoke_arena_snapshot(
                platform=context.adapter,
                platform_user_id=context.user_id,
                snapshot_id=context.command_args[0] if context.command_args else None,
                operation_id=operation_id,
            )
        except Exception as exc:
            return self._error(context, operation_id, exc)
        return CommandResult(
            True,
            "ARENA_SNAPSHOT_REVOKED",
            f"竞技场快照 `{record.snapshot_id}` 已撤销；已开始的对局仍按原快照结算。",
            context.request_id,
            operation_id,
            data=self._snapshot_data(record),
        )

    async def list_snapshots(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_ARENA_COMMAND", "竞技场快照列表无需附加参数。", context.request_id)
        try:
            records = await self.repository.list_arena_snapshots(
                platform=context.adapter, platform_user_id=context.user_id
            )
        except Exception as exc:
            return self._error(context, "", exc)
        data = {"snapshots": [self._snapshot_data(record) for record in records]}
        lines = ["## 竞技场匹配池", ""]
        if not records:
            lines.append("当前没有相邻积分段的公开快照。")
        else:
            for record in records:
                summary = record.public_summary
                lines.append(
                    f"- `{record.snapshot_id}` · **{self._display(summary.get('display_name'))}** · "
                    f"{summary.get('path_key', '未定道途')} · {summary.get('realm_layer_range', '未知')} · "
                    f"积分 {record.rating}"
                )
        lines.extend(["", "对手仅展示公开道号、道途、境界层数区间与快照摘要。"])
        return CommandResult(True, "ARENA_SNAPSHOT_LIST", "\n".join(lines), context.request_id, data=data)

    async def challenge(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) > 1:
            return CommandResult(False, "INVALID_ARENA_COMMAND", "挑战竞技场最多接收一个快照编号。", context.request_id)
        operation_id = self._operation_id(context, "arena.challenge")
        try:
            record = await self.repository.challenge_arena(
                platform=context.adapter,
                platform_user_id=context.user_id,
                snapshot_id=context.command_args[0] if context.command_args else None,
                operation_id=operation_id,
            )
        except Exception as exc:
            return self._error(context, operation_id, exc)
        outcome = {
            "challenger_won": "胜利",
            "defender_won": "落败",
            "draw": "平局",
        }.get(record.outcome, record.outcome)
        count_text = "计入积分" if record.score_counted else "本次仅作练习，不计入积分（同一快照今日已达 2 场）"
        return CommandResult(
            True,
            "ARENA_MATCH_SETTLED",
            f"## 竞技场异步斗法结束\n\n- **结果**：{outcome}\n- **回合**：{record.rounds}/15\n- **积分**：{count_text}\n- **对手**：{self._display(record.opponent_summary.get('display_name'))}\n\n服务器已固定双方快照并保存完整行动回放。",
            context.request_id,
            operation_id,
            data=self._match_data(record),
        )

    async def replay(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) > 1:
            return CommandResult(False, "INVALID_ARENA_COMMAND", "竞技场回放最多接收一个对局编号。", context.request_id)
        try:
            record = await self.repository.replay_arena(
                platform=context.adapter,
                platform_user_id=context.user_id,
                match_id=context.command_args[0] if context.command_args else None,
            )
        except Exception as exc:
            return self._error(context, "", exc)
        outcome = {"challenger_won": "挑战者胜", "defender_won": "防守者胜", "draw": "平局"}.get(record.outcome, record.outcome)
        lines = ["## 竞技场行动回放", "", f"- **对局**：`{record.match_id}`", f"- **结果**：{outcome}", f"- **回合**：{record.rounds}/15", ""]
        for action in record.actions:
            actor = "挑战者" if action["actor_key"] == "challenger" else "防守者"
            target = "挑战者" if action["target_key"] == "challenger" else "防守者"
            lines.append(f"- 回合 {action['round_no']}：{actor}自动攻击{target}，伤害 {action['damage']}。")
        return CommandResult(
            True,
            "ARENA_REPLAY",
            "\n".join(lines),
            context.request_id,
            data={
                "match_id": record.match_id,
                "status": record.status,
                "outcome": record.outcome,
                "rounds": record.rounds,
                "score_counted": record.score_counted,
                "snapshot": record.snapshot,
                "result": record.result,
                "actions": list(record.actions),
            },
        )

    async def claim_result(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) > 1:
            return CommandResult(False, "INVALID_ARENA_COMMAND", "领取竞技场结果最多接收一个对局编号。", context.request_id)
        operation_id = self._operation_id(context, "arena.claim_result")
        try:
            record = await self.repository.claim_arena_result(
                platform=context.adapter,
                platform_user_id=context.user_id,
                match_id=context.command_args[0] if context.command_args else None,
                operation_id=operation_id,
            )
        except Exception as exc:
            return self._error(context, operation_id, exc)
        return CommandResult(
            True,
            "ARENA_RESULT_ACKNOWLEDGED",
            f"竞技场对局 `{record.match_id}` 的结果已确认。胜负只影响竞技场积分与展示，不转移玩家资产。",
            context.request_id,
            operation_id,
            data={"match_id": record.match_id, "reward": record.reward, "idempotent_replay": record.already_completed},
        )


__all__ = ["ArenaApplication"]
