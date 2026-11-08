"""Adapter-neutral application services for the asynchronous arena."""

from __future__ import annotations

from ...contracts import CommandAction, CommandContext, CommandResult
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
    ArenaSeasonAlreadyClaimedError,
    ArenaSeasonClaimExpiredError,
    ArenaSeasonNotClosedError,
    ArenaSeasonNotFoundError,
    ArenaSeasonRankOutOfBoardError,
    ArenaSnapshotRequirementError,
    ThreeRealmsArenaRequirementError,
    OperationConflictError,
    PlayerNotFoundError,
    PlayerSuspendedError,
    RepositoryBusyError,
)
from .arena_models import ArenaMatchRecord, ArenaSnapshotRecord
from .arena_repository import ArenaRepositoryMixin
from .arena_rules import ARENA_MODE_KEY, ARENA_PRACTICE_MODE_KEY, ARENA_RANK_MODE_KEY
from .three_realms_arena_rules import THREE_REALMS_ARENA_MODE_KEY
from ..utils.text import command_link


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
            ThreeRealmsArenaRequirementError: ("THREE_REALMS_ARENA_REQUIREMENT_MISSING", "三界竞技场需要元婴 L1 与三界竞技许可。"),
            ArenaPlayerBusyError: ("ARENA_PLAYER_BUSY", "当前角色有未结束的战斗或修行会话，请先结算。"),
            ArenaSnapshotNotFoundError: ("ARENA_SNAPSHOT_NOT_FOUND", "没有找到可用的竞技场快照。"),
            ArenaSnapshotExpiredError: ("ARENA_SNAPSHOT_EXPIRED", "该竞技场快照已经过期或被撤销。"),
            ArenaOpponentUnavailableError: ("ARENA_OPPONENT_UNAVAILABLE", "当前没有相邻积分段的可挑战快照。"),
            ArenaMatchRequirementError: ("ARENA_MATCH_NOT_ALLOWED", "该快照暂不可计分挑战。"),
            ArenaChallengeCapError: ("ARENA_DAILY_CAP", "今日竞技场挑战次数已用尽。"),
            ArenaMatchNotFoundError: ("ARENA_MATCH_NOT_FOUND", "没有找到可查看的竞技场对局。"),
            ArenaRewardAlreadyClaimedError: ("ARENA_RESULT_ALREADY_ACKNOWLEDGED", "这场竞技场结果已经确认。"),
            ArenaRewardNotAvailableError: ("ARENA_RESULT_NOT_AVAILABLE", "当前没有待确认的竞技场结果。"),
            OperationConflictError: ("OPERATION_CONFLICT", "此事已有安排，请重新起意。"),
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
            "mode_key": record.mode_key,
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
            "mode_key": record.mode_key,
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
        return await self._publish_snapshot(context, mode_key=ARENA_MODE_KEY, label="竞技场")

    async def publish_three_realms_snapshot(self, context: CommandContext) -> CommandResult:
        return await self._publish_snapshot(context, mode_key=THREE_REALMS_ARENA_MODE_KEY, label="三界竞技场")

    async def _publish_snapshot(self, context: CommandContext, *, mode_key: str, label: str) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_ARENA_COMMAND", "发布竞技场快照无需附加参数。", context.request_id)
        operation_id = self._operation_id(context, f"{mode_key}.publish")
        try:
            record = await self.repository.publish_arena_snapshot(
                platform=context.adapter,
                platform_user_id=context.user_id,
                operation_id=operation_id,
                mode_key=mode_key,
            )
        except Exception as exc:
            return self._error(context, operation_id, exc)
        return CommandResult(
            True,
            "ARENA_SNAPSHOT_PUBLISHED",
            f"## {label}防守快照已发布\n\n快照 `{record.snapshot_id}` 将在 30 分钟后进入匹配池，有效 7 天。",
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
        return await self._list_snapshots(context, mode_key=ARENA_MODE_KEY, title="竞技场匹配池")

    async def list_three_realms_snapshots(self, context: CommandContext) -> CommandResult:
        return await self._list_snapshots(context, mode_key=THREE_REALMS_ARENA_MODE_KEY, title="三界竞技场匹配池")

    async def _list_snapshots(self, context: CommandContext, *, mode_key: str, title: str) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_ARENA_COMMAND", "竞技场快照列表无需附加参数。", context.request_id)
        try:
            records = await self.repository.list_arena_snapshots(
                platform=context.adapter, platform_user_id=context.user_id, mode_key=mode_key
            )
        except Exception as exc:
            return self._error(context, "", exc)
        data = {"snapshots": [self._snapshot_data(record) for record in records]}
        lines = [f"## {title}", ""]
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

    async def challenge(self, context: CommandContext, *, mode_key: str = ARENA_MODE_KEY) -> CommandResult:
        if len(context.command_args) > 1:
            return CommandResult(False, "INVALID_ARENA_COMMAND", "挑战竞技场最多接收一个快照编号。", context.request_id)
        operation_id = self._operation_id(context, "arena.challenge")
        try:
            record = await self.repository.challenge_arena(
                platform=context.adapter,
                platform_user_id=context.user_id,
                snapshot_id=context.command_args[0] if context.command_args else None,
                operation_id=operation_id,
                mode_key=mode_key,
                request_id=context.request_id,
            )
        except Exception as exc:
            return self._error(context, operation_id, exc)
        outcome = {
            "challenger_won": "胜利",
            "defender_won": "落败",
            "draw": "平局",
        }.get(record.outcome, record.outcome)
        count_text = "计入积分" if record.score_counted else "本次仅作练习，不计入积分（同一快照今日已达 2 场）"
        mode_label = {
            ARENA_MODE_KEY: "切磋",
            ARENA_RANK_MODE_KEY: "排位",
            ARENA_PRACTICE_MODE_KEY: "练习",
            THREE_REALMS_ARENA_MODE_KEY: "三界",
        }.get(mode_key, mode_key)
        return CommandResult(
            True,
            "ARENA_MATCH_SETTLED",
            f"## 竞技场{mode_label}结束\n\n- **结果**：{outcome}\n- **回合**：{record.rounds}/15\n- **积分**：{count_text}\n- **对手**：{self._display(record.opponent_summary.get('display_name'))}\n\n服务器已固定双方快照并保存完整行动回放。",
            context.request_id,
            operation_id,
            data=self._match_data(record),
        )

    async def challenge_three_realms(self, context: CommandContext) -> CommandResult:
        return await self.challenge(context, mode_key=THREE_REALMS_ARENA_MODE_KEY)

    async def grant_practice_consent(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 2:
            return CommandResult(
                False,
                "INVALID_ARENA_COMMAND",
                "请使用 `允许竞技场练习 <快照编号> <对手用户标识>`。",
                context.request_id,
            )
        operation_id = self._operation_id(context, "arena.practice_consent")
        try:
            await self.repository.grant_arena_practice_consent(
                platform=context.adapter,
                platform_user_id=context.user_id,
                snapshot_id=context.command_args[0],
                challenger_identity=context.command_args[1],
                operation_id=operation_id,
            )
        except Exception as exc:
            return self._error(context, operation_id, exc)
        return CommandResult(
            True,
            "ARENA_PRACTICE_CONSENT_GRANTED",
            "已允许指定道友使用该快照进行竞技场练习；练习不计积分，也不转移玩家资产。",
            context.request_id,
            operation_id,
            data={"snapshot_id": context.command_args[0], "idempotent_replay": False},
        )

    async def practice(self, context: CommandContext) -> CommandResult:
        return await self.challenge(context, mode_key=ARENA_PRACTICE_MODE_KEY)

    async def rank(self, context: CommandContext) -> CommandResult:
        return await self.challenge(context, mode_key=ARENA_RANK_MODE_KEY)

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



    async def season(self, context: CommandContext) -> CommandResult:
        """Show the weekly board, my placement and whether a claim is waiting."""

        if len(context.command_args) > 1:
            return CommandResult(
                False, "INVALID_ARENA_COMMAND", "竞技场赛季最多接收一个周次。", context.request_id
            )
        week = context.command_args[0] if context.command_args else None
        try:
            board = await self.repository.arena_season_board(
                platform=context.adapter, platform_user_id=context.user_id, week=week
            )
        except ArenaSeasonNotFoundError:
            return CommandResult(
                False, "ARENA_SEASON_NOT_FOUND", "找不到这一周的竞技场赛季。", context.request_id
            )
        except Exception as exc:  # noqa: BLE001 - mapped by the shared handler
            return self._error(context, "", exc)

        state = "已结束" if board["closed"] else "进行中"
        lines = [
            "## 竞技场周赛季",
            "",
            f"- **周期**：{board['starts_at'][:10]} → {board['ends_at'][:10]}（{state}）",
        ]
        mine = board.get("mine")
        if mine is None:
            lines.append("- **我的名次**：本周尚未计入排位对战")
        else:
            lines.append(
                f"- **我的名次**：第 {mine['rank']} 名 · 积分 {mine['rating']} · "
                f"{mine['wins']} 胜 {mine['losses']} 负 {mine['draws']} 平"
            )
            reward = mine.get("reward") or {}
            parts = []
            if reward.get("spirit_stones"):
                parts.append(f"灵石 {reward['spirit_stones']}")
            if reward.get("local_reputation"):
                parts.append(f"本地名望 {reward['local_reputation']}")
            items = [key for key in reward if key.startswith("item.")]
            if items:
                parts.append(f"物品 {len(items)} 件")
            if parts:
                lines.append(f"- **该名次奖励**：{' · '.join(parts)}")
        previous = board.get("previous") or {}
        previous_mine = previous.get("mine")
        if previous_mine:
            lines.append(
                f"- **上周名次**：第 {previous_mine['rank']} 名 · 积分 {previous_mine['rating']}"
            )
        top = board.get("board") or []
        if top:
            lines.append("")
            lines.append("**本周前五**")
            lines.extend(
                f"- 第 {entry['rank']} 名 · 积分 {entry['rating']} · {entry['wins']} 胜"
                for entry in top[:5]
            )
        claimable_now = bool(board["claimable"])
        claimable_previous = bool(previous.get("claimable"))
        lines.append("")
        if claimable_now or claimable_previous:
            target = "本周" if claimable_now else "上周"
            lines.append(f"{target}名次奖励已可领取，名次与奖励已冻结。")
            lines.append(command_link(f"领取{target}竞技奖励", "领取竞技场赛季奖励"))
        elif board["claimed"]:
            lines.append("本周奖励已领取。")
        elif previous.get("claimed") and previous_mine:
            lines.append("上周奖励已领取。")
        elif previous.get("claim_expired"):
            lines.append("上周领奖期已过，名次已转为展示记录。")
        elif previous_mine:
            lines.append("上周名次不在奖励名额内。")
        else:
            lines.append("本周结算后可按名次领取奖励。")
        actions = (
            (CommandAction("领取周榜奖励", "领取竞技场赛季奖励", enter=True),)
            if (claimable_now or claimable_previous)
            else ()
        )
        return CommandResult(
            True,
            "ARENA_SEASON",
            "\n".join(lines),
            context.request_id,
            data=board,
            actions=actions,
        )

    async def claim_season(self, context: CommandContext) -> CommandResult:
        """Claim the frozen payout of a closed week."""

        if len(context.command_args) > 1:
            return CommandResult(
                False, "INVALID_ARENA_COMMAND", "领取赛季奖励最多接收一个周次。", context.request_id
            )
        week = context.command_args[0] if context.command_args else None
        operation_id = self._operation_id(context, "arena.claim_season")
        try:
            payload = await self.repository.claim_arena_season_reward(
                platform=context.adapter,
                platform_user_id=context.user_id,
                week=week,
                operation_id=operation_id,
            )
        except ArenaSeasonNotClosedError:
            return CommandResult(
                False, "ARENA_SEASON_OPEN", "这一周的赛季尚未结束，结算后才能领取。", context.request_id, operation_id
            )
        except ArenaSeasonRankOutOfBoardError:
            return CommandResult(
                False, "ARENA_SEASON_RANK_OUT_OF_BOARD", "本周名次不在奖励名额内。", context.request_id, operation_id
            )
        except ArenaSeasonAlreadyClaimedError:
            return CommandResult(
                False, "ARENA_SEASON_ALREADY_CLAIMED", "本周竞技奖励已经领取过了。", context.request_id, operation_id
            )
        except ArenaSeasonClaimExpiredError:
            return CommandResult(
                False,
                "ARENA_SEASON_CLAIM_EXPIRED",
                "该周领奖期已过，名次只保留为展示记录。",
                context.request_id,
                operation_id,
            )
        except ArenaSeasonNotFoundError:
            return CommandResult(
                False, "ARENA_SEASON_NOT_FOUND", "找不到这一周的竞技场赛季。", context.request_id, operation_id
            )
        except Exception as exc:  # noqa: BLE001
            return self._error(context, operation_id, exc)
        reward = payload.get("reward") or {}
        parts = []
        if reward.get("spirit_stones"):
            parts.append(f"灵石 {reward['spirit_stones']}")
        if reward.get("local_reputation"):
            parts.append(f"本地名望 {reward['local_reputation']}")
        items = [key for key in reward if key.startswith("item.")]
        if items:
            parts.append(f"物品 {len(items)} 件")
        lines = [
            "## 周榜奖励已领取",
            "",
            f"- **周次**：{payload['week_key']}",
            f"- **名次**：第 {payload['rank']} 名",
            f"- **所得**：{' · '.join(parts) if parts else '本周无额外所得'}",
        ]
        if payload.get("title_key"):
            lines.append("- **称号**：周榜魁首")
        lines.append("")
        lines.append(command_link("再看竞技场赛季", "竞技场赛季"))
        return CommandResult(
            True,
            "ARENA_SEASON_CLAIMED",
            "\n".join(lines),
            context.request_id,
            operation_id,
            data=payload,
            actions=(CommandAction("再看竞技场赛季", "竞技场赛季", enter=True),),
        )

__all__ = ["ArenaApplication"]
