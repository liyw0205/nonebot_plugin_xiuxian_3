"""Adapter-neutral commands for sect-war registration and rewards."""

from __future__ import annotations

from ...contracts import CommandContext, CommandResult
from ..persistence.errors import (
    OperationConflictError,
    PlayerNotFoundError,
    PlayerSuspendedError,
    RepositoryBusyError,
    SectNotFoundError,
    SectWarParticipantCapError,
    SectWarRegistrationClosedError,
    SectWarRequirementError,
    SectWarRewardAlreadyClaimedError,
    SectWarRewardExpiredError,
    SectWarRewardNotEligibleError,
    SectWarRoundNotActiveError,
    SectWarSourceInvalidError,
)
from .sect_war_models import SectWarRecord
from .sect_war_repository import SectWarRepositoryMixin
from .sect_war_rules import SECT_WAR_MEMBER_THRESHOLD


class SectWarApplication:
    """Translate sect-war state transitions into command results."""

    def __init__(self, repository: SectWarRepositoryMixin):
        self.repository = repository

    @staticmethod
    def _operation_id(context: CommandContext, name: str) -> str:
        if context.operation_id:
            return context.operation_id
        key = context.message_id or context.request_id
        return f"{name}:{context.adapter}:{context.user_id}:{key}"

    @staticmethod
    def _round_arg(args: tuple[str, ...]) -> str | None:
        if not args:
            return None
        if len(args) == 1 and args[0].startswith("sect_war:"):
            return args[0]
        return ""

    @staticmethod
    def _error(context: CommandContext, operation_id: str, exc: Exception) -> CommandResult:
        errors = {
            SectWarRegistrationClosedError: ("SECT_WAR_REGISTRATION_CLOSED", "宗门战当前不在报名窗口。"),
            SectWarParticipantCapError: ("SECT_WAR_PARTICIPANT_CAP", "宗门战报名队伍没有可用成员。"),
            SectWarRequirementError: ("SECT_WAR_REQUIREMENT_MISSING", "宗门或角色不满足宗门战前置。"),
            SectWarRoundNotActiveError: ("SECT_WAR_ROUND_NOT_ACTIVE", "宗门战当前不能贡献或领奖。"),
            SectWarSourceInvalidError: ("SECT_WAR_SOURCE_INVALID", "来源 operation 无法作为本轮宗门战贡献。"),
            SectWarRewardNotEligibleError: ("SECT_WAR_REWARD_NOT_ELIGIBLE", f"本轮贡献未达到 {SECT_WAR_MEMBER_THRESHOLD} 分领奖门槛。"),
            SectWarRewardAlreadyClaimedError: ("SECT_WAR_REWARD_ALREADY_CLAIMED", "本轮宗门战奖励已经领取或自动发放。"),
            SectWarRewardExpiredError: ("SECT_WAR_REWARD_EXPIRED", "宗门战领奖窗口已经结束。"),
            SectNotFoundError: ("SECT_NOT_FOUND", "你当前不在有效宗门中。"),
            PlayerNotFoundError: ("PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。"),
            PlayerSuspendedError: ("PLAYER_SUSPENDED", "当前角色暂时不能操作宗门战。"),
            OperationConflictError: ("OPERATION_CONFLICT", "这次请求编号已经用于其他宗门战操作。"),
            RepositoryBusyError: ("PERSISTENCE_BUSY", "宗门战簿暂时繁忙，请稍后再试。"),
        }
        code, message = errors.get(type(exc), ("PERSISTENCE_ERROR", "宗门战簿暂时不可用，请稍后再试。"))
        return CommandResult(False, code, message, context.request_id, operation_id, retryable=isinstance(exc, RepositoryBusyError))

    @staticmethod
    def _data(record: SectWarRecord) -> dict[str, object]:
        return {
            "round_id": record.round_id,
            "status": record.status,
            "registration_open_at": record.registration_open_at,
            "starts_at": record.starts_at,
            "ends_at": record.ends_at,
            "claim_expires_at": record.claim_expires_at,
            "registered": record.registered,
            "sect_id": record.sect_id,
            "sect_name": record.sect_name,
            "participant_count": record.participant_count,
            "player_contribution": record.player_contribution,
            "winner_sect_id": record.winner_sect_id,
            "standings": [
                {"sect_id": item.sect_id, "sect_name": item.sect_name, "score": item.score, "rank": item.rank}
                for item in record.standings
            ],
            "idempotent_replay": record.already_completed,
        }

    async def get(self, context: CommandContext) -> CommandResult:
        round_id = self._round_arg(context.command_args)
        if round_id == "":
            return CommandResult(False, "INVALID_SECT_WAR", "请使用 `宗门战 [轮次]`。", context.request_id)
        try:
            record = await self.repository.get_sect_war(platform=context.adapter, platform_user_id=context.user_id, round_id=round_id)
        except ValueError:
            return CommandResult(False, "INVALID_SECT_WAR", "宗门战轮次编号无效。", context.request_id)
        except Exception as exc:
            return self._error(context, "", exc)
        status = {"scheduled": "报名准备", "open": "报名中", "running": "进行中", "settled": "已结算"}.get(record.status, record.status)
        lines = [f"## 宗门战 · `{record.round_id}`", "", f"**状态**：{status}", f"**战场时间**：{record.starts_at} 至 {record.ends_at}", f"**报名截止**：{record.registration_open_at} 至 {record.starts_at}"]
        if record.registered:
            lines.append(f"**你的宗门**：{record.sect_name}，本宗门个人贡献 {record.player_contribution} 分")
        if record.status == "settled":
            lines.append(f"**领奖截止**：{record.claim_expires_at}")
            lines.extend(f"{item.rank}. {item.sect_name} · {item.score} 分" for item in record.standings)
        return CommandResult(True, "SECT_WAR_STATUS", "\n".join(lines), context.request_id, data=self._data(record))

    async def register(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) > 1 or (context.command_args and not context.command_args[0].startswith("sect_war:")):
            return CommandResult(False, "INVALID_SECT_WAR", "请使用 `报名宗门战 [轮次]`。", context.request_id)
        round_id = context.command_args[0] if context.command_args else None
        operation_id = self._operation_id(context, "social.sect_war.register")
        try:
            record = await self.repository.register_sect_war(platform=context.adapter, platform_user_id=context.user_id, round_id=round_id, operation_id=operation_id)
        except ValueError:
            return CommandResult(False, "INVALID_SECT_WAR", "宗门战轮次编号无效。", context.request_id, operation_id)
        except Exception as exc:
            return self._error(context, operation_id, exc)
        return CommandResult(True, "SECT_WAR_REGISTERED", f"## 宗门战报名成功\n\n- **轮次**：`{record.round_id}`\n- **宗门**：{record.sect_name}\n- **出战成员**：{record.participant_count}", context.request_id, operation_id, data=self._data(record))

    async def contribute(self, context: CommandContext) -> CommandResult:
        if not context.command_args or len(context.command_args) > 3:
            return CommandResult(False, "INVALID_SECT_WAR", "请使用 `贡献宗门战 占点|击败|运输|维修 [来源operation] [轮次]`。", context.request_id)
        action_key = context.command_args[0]
        remaining = list(context.command_args[1:])
        round_id = remaining.pop() if remaining and remaining[-1].startswith("sect_war:") else None
        source_id = remaining[0] if remaining else None
        if len(remaining) > 1:
            return CommandResult(False, "INVALID_SECT_WAR", "来源 operation 或轮次参数无效。", context.request_id)
        operation_id = self._operation_id(context, "social.sect_war.contribute")
        try:
            record = await self.repository.contribute_sect_war(platform=context.adapter, platform_user_id=context.user_id, action_key=action_key, source_operation_id=source_id, round_id=round_id, operation_id=operation_id)
        except ValueError:
            return CommandResult(False, "INVALID_SECT_WAR", "宗门战轮次编号无效。", context.request_id, operation_id)
        except Exception as exc:
            return self._error(context, operation_id, exc)
        return CommandResult(True, "SECT_WAR_CONTRIBUTED", f"本轮宗门战已记录 **{action_key}**，当前个人贡献 {record.player_contribution} 分。", context.request_id, operation_id, data=self._data(record))

    async def claim(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 1 or not context.command_args[0].startswith("sect_war:"):
            return CommandResult(False, "INVALID_SECT_WAR", "请使用 `领取宗门战奖励 <轮次>`。", context.request_id)
        operation_id = self._operation_id(context, "social.sect_war.claim")
        try:
            record = await self.repository.claim_sect_war_reward(platform=context.adapter, platform_user_id=context.user_id, round_id=context.command_args[0], operation_id=operation_id)
        except ValueError:
            return CommandResult(False, "INVALID_SECT_WAR", "宗门战轮次编号无效。", context.request_id, operation_id)
        except Exception as exc:
            return self._error(context, operation_id, exc)
        data = {"round_id": record.round_id, "reward": dict(record.reward), "expired": record.expired, "idempotent_replay": record.already_completed}
        if record.expired:
            return CommandResult(False, "SECT_WAR_REWARD_EXPIRED", "领奖窗口已经结束；符合条件的奖励会按规则自动发放。", context.request_id, operation_id, data=data)
        return CommandResult(True, "SECT_WAR_REWARD_CLAIMED", f"## 宗门战奖励已领取\n\n- **世界功勋**：{record.reward.get('world_merit', 0)}", context.request_id, operation_id, data=data)


__all__ = ["SectWarApplication"]
