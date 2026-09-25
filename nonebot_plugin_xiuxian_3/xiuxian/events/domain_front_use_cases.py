"""Adapter-neutral application operations for the domain-front slice."""

from __future__ import annotations

from ...contracts import CommandContext, CommandResult
from ..persistence.errors import (
    DomainCrackActiveError,
    DomainCoreFragmentInsufficientError,
    DomainCoreRedeemAlreadyUsedError,
    DomainCoreRedeemRequirementError,
    DomainEventAlreadyJoinedError,
    DomainEventParticipantCapError,
    DomainEventRequirementError,
    DomainEventRewardAlreadyClaimedError,
    DomainEventRewardNotEligibleError,
    DomainEventRoundNotActiveError,
    DomainEventSourceInvalidError,
    DomainSeasonRankingNotFinalizedError,
    DomainSeasonRewardAlreadyClaimedError,
    DomainSeasonRewardExpiredError,
    DomainSeasonRewardNotEligibleError,
    OperationConflictError,
    PlayerNotFoundError,
    PlayerSuspendedError,
    RepositoryBusyError,
    ResourceInsufficientError,
)
from .domain_front_models import DomainFrontRecord, DomainFrontSeasonRecord
from .domain_front_repository import DomainFrontRepositoryMixin
from .domain_front_rules import ACTION_VALUES


class DomainFrontApplication:
    """Expose the same domain-front contract to QQ, OneBot, and tests."""

    def __init__(self, repository: DomainFrontRepositoryMixin):
        self.repository = repository

    @staticmethod
    def _operation_id(context: CommandContext, name: str) -> str:
        if context.operation_id:
            return context.operation_id
        key = context.message_id or context.request_id
        return f"event.domain_front.{name}:{context.adapter}:{context.user_id}:{key}"

    @staticmethod
    def _error(context: CommandContext, operation_id: str, exc: Exception) -> CommandResult:
        mapping: dict[type[Exception], tuple[str, str]] = {
            DomainCrackActiveError: ("DOMAIN_CRACK_ACTIVE", "领域裂痕尚未恢复，暂时不能参加领域前线。"),
            DomainEventRequirementError: ("DOMAIN_EVENT_REQUIREMENT_MISSING", "需要化神、已选领域、宗门等级 4，并位于领域前线。"),
            DomainEventParticipantCapError: ("EVENT_PARTICIPANT_CAP", "本轮宗门参战人数已达到 20 人上限。"),
            DomainEventAlreadyJoinedError: ("EVENT_ALREADY_JOINED", "你已经加入本轮领域前线。"),
            DomainEventRoundNotActiveError: ("EVENT_NOT_ACTIVE", "当前领域前线轮次不接受这个操作。"),
            DomainEventSourceInvalidError: ("EVENT_CONTRIBUTION_SOURCE_INVALID", "没有找到属于你的已结算领域前线来源 operation。"),
            DomainEventRewardNotEligibleError: ("EVENT_CONTRIBUTION_INSUFFICIENT", "个人领域前线贡献尚未达到 100。"),
            DomainEventRewardAlreadyClaimedError: ("EVENT_REWARD_ALREADY_CLAIMED", "本轮领域前线奖励已经领取。"),
            DomainSeasonRankingNotFinalizedError: ("DOMAIN_SEASON_NOT_FINALIZED", "领域战赛季尚未结束，排名还没有冻结。"),
            DomainSeasonRewardNotEligibleError: ("DOMAIN_SEASON_REWARD_NOT_ELIGIBLE", "该赛季没有可领取的领域战奖励。"),
            DomainSeasonRewardAlreadyClaimedError: ("DOMAIN_SEASON_REWARD_ALREADY_CLAIMED", "该赛季领域战奖励已经领取。"),
            DomainSeasonRewardExpiredError: ("DOMAIN_SEASON_REWARD_EXPIRED", "领域战赛季领奖窗口已经结束。"),
            DomainCoreRedeemRequirementError: ("DOMAIN_CORE_REDEEM_NOT_AVAILABLE", "领域核心只能在已结束且已冻结的领域赛季中兑换。"),
            DomainCoreRedeemAlreadyUsedError: ("DOMAIN_CORE_REDEEM_ALREADY_USED", "本赛季已经兑换过领域核心。"),
            DomainCoreFragmentInsufficientError: ("DOMAIN_CORE_FRAGMENT_INSUFFICIENT", "兑换领域核心需要 20 个领域核心碎片。"),
            ResourceInsufficientError: ("STAMINA_INSUFFICIENT", "加入领域前线需要 20 点体力。"),
            PlayerNotFoundError: ("PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。"),
            PlayerSuspendedError: ("PLAYER_SUSPENDED", "当前角色暂时不能执行领域前线操作。"),
            OperationConflictError: ("OPERATION_CONFLICT", "这次请求编号已经用于其他输入。"),
            RepositoryBusyError: ("PERSISTENCE_BUSY", "领域前线簿暂时繁忙，请稍后再试。"),
        }
        code, message = mapping.get(type(exc), ("PERSISTENCE_ERROR", "领域前线簿暂时不可用，请稍后再试。"))
        return CommandResult(False, code, message, context.request_id, operation_id, retryable=isinstance(exc, RepositoryBusyError))

    @staticmethod
    def _record_data(record: DomainFrontRecord) -> dict[str, object]:
        return {
            "round_id": record.round_id,
            "activity_id": record.activity_id,
            "status": record.status,
            "activity_starts_at": record.activity_starts_at,
            "activity_ends_at": record.activity_ends_at,
            "starts_at": record.starts_at,
            "ends_at": record.ends_at,
            "claim_expires_at": record.claim_expires_at,
            "total_contribution": record.total_contribution,
            "player_contribution": record.player_contribution,
            "participant": record.participant,
            "sect_id": record.sect_id,
            "domain_key": record.domain_key,
            "winner_domain": record.winner_domain,
            "success": record.success,
            "reward": dict(record.reward),
            "idempotent_replay": record.already_completed,
        }

    async def get_domain_front(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) > 1:
            return CommandResult(False, "INVALID_DOMAIN_EVENT_COMMAND", "请使用 `领域前线 [轮次]`。", context.request_id)
        round_id = context.command_args[0] if context.command_args else None
        try:
            record = await self.repository.get_domain_front(platform=context.adapter, platform_user_id=context.user_id, round_id=round_id)
        except ValueError:
            return CommandResult(False, "INVALID_DOMAIN_EVENT_COMMAND", "轮次编号无效。", context.request_id)
        except Exception as exc:
            return self._error(context, "", exc)
        status = "进行中" if record.status in {"open", "running"} else "已结算"
        message = (
            f"## 领域前线\n\n**状态**：{status}\n**轮次**：`{record.round_id}`\n"
            f"**活动窗口**：{record.activity_starts_at} 至 {record.activity_ends_at}\n"
            f"**本轮窗口**：{record.starts_at} 至 {record.ends_at}\n"
            f"**全服贡献**：{record.total_contribution}\n**个人贡献**：{record.player_contribution}\n"
            f"**参战**：{'是' if record.participant else '否'}"
        )
        return CommandResult(True, "DOMAIN_EVENT_STATUS", message, context.request_id, data=self._record_data(record))

    async def join_domain_front(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_DOMAIN_EVENT_COMMAND", "加入领域前线无需附加参数。", context.request_id)
        operation_id = self._operation_id(context, "join")
        try:
            record = await self.repository.join_domain_front(platform=context.adapter, platform_user_id=context.user_id, operation_id=operation_id)
        except Exception as exc:
            return self._error(context, operation_id, exc)
        return CommandResult(True, "DOMAIN_EVENT_JOINED", f"已加入领域前线本轮 ` {record.round_id}`，冻结参战快照并消耗体力 20。", context.request_id, operation_id, data=self._record_data(record))

    async def start_domain_front_battle(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_DOMAIN_EVENT_COMMAND", "开始领域战不接受额外参数。", context.request_id)
        operation_id = self._operation_id(context, "battle")
        try:
            payload = await self.repository.start_domain_front_battle(platform=context.adapter, platform_user_id=context.user_id, operation_id=operation_id)
        except Exception as exc:
            return self._error(context, operation_id, exc)
        return CommandResult(True, "DOMAIN_BATTLE_SETTLED", "领域战已由服务器自动结算为胜利；发送 `贡献领域前线 战斗` 投影 100 点贡献。", context.request_id, operation_id, data={**payload, "idempotent_replay": bool(payload.get("idempotent_replay", False))})

    async def create_domain_front_point(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) > 1:
            return CommandResult(False, "INVALID_DOMAIN_EVENT_COMMAND", "请使用 `占点领域前线 [分钟]`。", context.request_id)
        try:
            minutes = int(context.command_args[0]) if context.command_args else 1
        except ValueError:
            return CommandResult(False, "INVALID_DOMAIN_EVENT_COMMAND", "占点分钟必须是 1 至 30 的整数。", context.request_id)
        if not 1 <= minutes <= 30:
            return CommandResult(False, "INVALID_DOMAIN_EVENT_COMMAND", "占点分钟必须是 1 至 30 的整数。", context.request_id)
        operation_id = self._operation_id(context, "point")
        try:
            payload = await self.repository.create_domain_front_point(platform=context.adapter, platform_user_id=context.user_id, minutes=minutes, operation_id=operation_id)
        except Exception as exc:
            return self._error(context, operation_id, exc)
        return CommandResult(True, "DOMAIN_POINT_SETTLED", f"已记录领域前线占点 {minutes} 分钟；发送 `贡献领域前线 占点` 投影 {payload['contribution']} 点贡献。", context.request_id, operation_id, data={**payload, "idempotent_replay": bool(payload.get("idempotent_replay", False))})

    async def contribute_domain_front(self, context: CommandContext) -> CommandResult:
        if not context.command_args or len(context.command_args) > 2:
            return CommandResult(False, "INVALID_DOMAIN_EVENT_COMMAND", "请使用 `贡献领域前线 战斗|占点 [来源operation]`。", context.request_id)
        action = ACTION_VALUES.get(context.command_args[0], context.command_args[0])
        source = context.command_args[1] if len(context.command_args) == 2 else None
        operation_id = self._operation_id(context, "contribute")
        try:
            record = await self.repository.record_domain_front_contribution(platform=context.adapter, platform_user_id=context.user_id, action_key=action, source_operation_id=source, operation_id=operation_id)
        except Exception as exc:
            return self._error(context, operation_id, exc)
        return CommandResult(True, "DOMAIN_EVENT_CONTRIBUTION_RECORDED", f"领域前线贡献已记录，本轮个人贡献 {record.player_contribution}。", context.request_id, operation_id, data=self._record_data(record))

    async def claim_domain_front_reward(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 1:
            return CommandResult(False, "INVALID_DOMAIN_EVENT_COMMAND", "请使用 `领取领域前线奖励 <轮次>`。", context.request_id)
        operation_id = self._operation_id(context, "claim")
        try:
            record = await self.repository.claim_domain_front_reward(platform=context.adapter, platform_user_id=context.user_id, round_id=context.command_args[0], operation_id=operation_id)
        except Exception as exc:
            return self._error(context, operation_id, exc)
        return CommandResult(True, "DOMAIN_EVENT_REWARD_CLAIMED", "领域前线奖励已发放：领域核心碎片 +5，世界功勋 +100。", context.request_id, operation_id, data={"round_id": record.round_id, "reward": dict(record.reward), "idempotent_replay": record.already_completed})

    @staticmethod
    def _season_data(record: DomainFrontSeasonRecord) -> dict[str, object]:
        return {"season_id": record.season_id, "status": record.status, "starts_at": record.starts_at, "ends_at": record.ends_at, "claim_expires_at": record.claim_expires_at, "frozen_at": record.frozen_at, "standings": [{"rank": item.rank, "anonymous_label": item.anonymous_label, "score": item.score, "achieved_at": item.achieved_at, "reward": dict(item.reward)} for item in record.standings], "personal": ({"rank": record.personal.rank, "anonymous_label": record.personal.anonymous_label, "score": record.personal.score, "achieved_at": record.personal.achieved_at, "reward": dict(record.personal.reward)} if record.personal else None)}

    async def get_domain_war_season(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) > 1:
            return CommandResult(False, "INVALID_DOMAIN_SEASON_COMMAND", "请使用 `领域赛季 [赛季编号]`。", context.request_id)
        season_id = context.command_args[0] if context.command_args else None
        try:
            record = await self.repository.get_domain_war_season(platform=context.adapter, platform_user_id=context.user_id, season_id=season_id)
        except ValueError:
            return CommandResult(False, "INVALID_DOMAIN_SEASON_COMMAND", "赛季编号无效。", context.request_id)
        except Exception as exc:
            return self._error(context, "", exc)
        status = "已冻结" if record.status == "frozen" else "进行中"
        lines = [f"## 领域战赛季 · {record.season_id}", "", f"**状态**：{status}", f"**赛季时间**：{record.starts_at} 至 {record.ends_at}"]
        if record.status == "frozen":
            lines.append(f"**领奖截止**：{record.claim_expires_at}")
            lines.extend(f"{item.rank}. {item.anonymous_label} · {item.score} 分" for item in record.standings)
        return CommandResult(True, "DOMAIN_SEASON_RANKING", "\n".join(lines), context.request_id, data=self._season_data(record))

    async def claim_domain_war_reward(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 1:
            return CommandResult(False, "INVALID_DOMAIN_SEASON_COMMAND", "请使用 `领取领域赛季奖励 <赛季编号>`。", context.request_id)
        operation_id = self._operation_id(context, "season_claim")
        try:
            record = await self.repository.claim_domain_war_reward(platform=context.adapter, platform_user_id=context.user_id, season_id=context.command_args[0], operation_id=operation_id)
        except ValueError:
            return CommandResult(False, "INVALID_DOMAIN_SEASON_COMMAND", "赛季编号无效。", context.request_id, operation_id)
        except Exception as exc:
            return self._error(context, operation_id, exc)
        return CommandResult(True, "DOMAIN_SEASON_REWARD_CLAIMED", f"领域战赛季第 {record.rank} 名奖励已发放。", context.request_id, operation_id, data={"season_id": record.season_id, "rank": record.rank, "reward": dict(record.reward), "idempotent_replay": record.already_completed})

    async def redeem_domain_core(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 1:
            return CommandResult(False, "INVALID_DOMAIN_SEASON_COMMAND", "请使用 `兑换领域核心 <赛季编号>`。", context.request_id)
        operation_id = self._operation_id(context, "redeem_domain_core")
        try:
            record = await self.repository.redeem_domain_core(
                platform=context.adapter,
                platform_user_id=context.user_id,
                season_id=context.command_args[0],
                operation_id=operation_id,
            )
        except ValueError:
            return CommandResult(False, "INVALID_DOMAIN_SEASON_COMMAND", "赛季编号无效。", context.request_id, operation_id)
        except Exception as exc:
            return self._error(context, operation_id, exc)
        return CommandResult(
            True,
            "DOMAIN_CORE_REDEEMED",
            "已消耗 20 个领域核心碎片，兑换领域核心 +1。",
            context.request_id,
            operation_id,
            data={
                "season_id": record.season_id,
                "item_key": record.item_key,
                "quantity": record.quantity,
                "idempotent_replay": record.already_completed,
            },
        )


__all__ = ["DomainFrontApplication"]
