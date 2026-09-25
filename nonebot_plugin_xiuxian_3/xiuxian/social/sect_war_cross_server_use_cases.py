"""Application DTOs and commands for the v0.5 cross-server war."""

from __future__ import annotations

from ...contracts import CommandContext, CommandResult
from ..persistence.errors import (
    CrossServerBranchLockedError,
    CrossServerFortressBuildError,
    CrossServerFortressRequiredError,
    CrossServerRegistrationCapError,
    CrossServerRegistrationClosedError,
    CrossServerRewardAllocationError,
    CrossServerRewardNotAvailableError,
    CrossServerRosterCapError,
    CrossServerSourceInvalidError,
    CrossServerWarNotActiveError,
    OperationConflictError,
    PlayerNotFoundError,
    PlayerSuspendedError,
    RepositoryBusyError,
    SectNotFoundError,
    SectPermissionDeniedError,
    SectWarRequirementError,
)
from .sect_war_cross_server_models import CrossServerFortressRecord, CrossServerRewardRecord, CrossServerWarRecord


class SectWarCrossServerApplication:
    def __init__(self, repository):
        self.repository = repository

    @staticmethod
    def _operation_id(context: CommandContext, name: str) -> str:
        if context.operation_id:
            return context.operation_id
        return f"{name}:{context.adapter}:{context.user_id}:{context.message_id or context.request_id}"

    @staticmethod
    def _error(context: CommandContext, operation_id: str, exc: Exception) -> CommandResult:
        errors = {
            CrossServerFortressRequiredError: ("SECT_FORTRESS_REQUIRED", "需要先建造并维护激活虚空堡垒。"),
            CrossServerFortressBuildError: ("SECT_FORTRESS_BUILD_FAILED", "虚空堡垒建造或维护条件不足。"),
            CrossServerRegistrationClosedError: ("CROSS_SERVER_REGISTRATION_CLOSED", "跨服宗门战当前不在报名窗口。"),
            CrossServerRegistrationCapError: ("CROSS_SERVER_REGISTRATION_CAP", "本周跨服宗门战报名名额已满。"),
            CrossServerRosterCapError: ("CROSS_SERVER_ROSTER_CAP", "实际出战名单不满足 1 至 15 人限制。"),
            CrossServerWarNotActiveError: ("CROSS_SERVER_WAR_NOT_ACTIVE", "跨服宗门战当前不接受此操作。"),
            CrossServerSourceInvalidError: ("CROSS_SERVER_SOURCE_INVALID", "来源 operation 无法作为跨服宗门战积分。"),
            CrossServerBranchLockedError: ("FORTRESS_BRANCH_LOCKED", "战争机关分支已经锁定。"),
            CrossServerRewardNotAvailableError: ("CROSS_SERVER_REWARD_NOT_AVAILABLE", "当前没有可领取的跨服宗门战奖励。"),
            CrossServerRewardAllocationError: ("CROSS_SERVER_REWARD_ALLOCATION_INVALID", "公共奖励箱分配参数无效。"),
            SectWarRequirementError: ("SECT_WAR_REQUIREMENT_MISSING", "宗门等级或公共钱包不满足跨服宗门战前置。"),
            SectPermissionDeniedError: ("SECT_PERMISSION_DENIED", "只有宗主或副宗主可以执行此操作。"),
            SectNotFoundError: ("SECT_NOT_FOUND", "你当前不在有效宗门中。"),
            PlayerNotFoundError: ("PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。"),
            PlayerSuspendedError: ("PLAYER_SUSPENDED", "当前角色暂时不能操作跨服宗门战。"),
            OperationConflictError: ("OPERATION_CONFLICT", "这次请求编号已经用于其他跨服宗门战操作。"),
            RepositoryBusyError: ("PERSISTENCE_BUSY", "跨服宗门战簿暂时繁忙，请稍后再试。"),
            ValueError: ("INVALID_CROSS_SERVER_WAR", "跨服宗门战轮次编号无效。"),
        }
        code, message = errors.get(type(exc), ("PERSISTENCE_ERROR", "跨服宗门战簿暂时不可用，请稍后再试。"))
        return CommandResult(False, code, message, context.request_id, operation_id, retryable=isinstance(exc, RepositoryBusyError))

    @staticmethod
    def _round(args: tuple[str, ...]) -> str | None:
        if not args:
            return None
        value = args[-1]
        return value if value.startswith("sect_war.cross:") else ""

    @staticmethod
    def _war_data(record: CrossServerWarRecord) -> dict[str, object]:
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
            "roster_size": record.roster_size,
            "score": record.score,
            "session_status": record.session_status,
            "engine_hp": record.engine_hp,
            "branch_key": record.branch_key,
            "standings": [{"sect_id": item.sect_id, "sect_name": item.sect_name, "score": item.score, "rank": item.rank, "winner": item.winner} for item in record.standings],
            "idempotent_replay": record.already_completed,
        }

    async def fortress(self, context: CommandContext) -> CommandResult:
        try:
            record = await self.repository.get_void_fortress(platform=context.adapter, platform_user_id=context.user_id)
        except Exception as exc:
            return self._error(context, "", exc)
        return CommandResult(True, "SECT_FORTRESS_STATUS", f"## 虚空堡垒\n\n- **状态**：{record.status}\n- **维护锚**：{record.anchors}\n- **建造结束**：{record.build_ends_at or '已完成'}", context.request_id, data={"status": record.status, "anchors": record.anchors, "build_ends_at": record.build_ends_at, "maintenance_due_at": record.maintenance_due_at})

    async def build_fortress(self, context: CommandContext) -> CommandResult:
        operation_id = self._operation_id(context, "social.sect_war_cross_server.build_fortress")
        try:
            record = await self.repository.build_void_fortress(platform=context.adapter, platform_user_id=context.user_id, operation_id=operation_id)
        except Exception as exc:
            return self._error(context, operation_id, exc)
        return CommandResult(True, "SECT_FORTRESS_BUILDING", "虚空堡垒已进入 48 小时建造状态。", context.request_id, operation_id, data={"status": record.status, "build_ends_at": record.build_ends_at})

    async def maintain_fortress(self, context: CommandContext) -> CommandResult:
        operation_id = self._operation_id(context, "social.sect_war_cross_server.maintain_fortress")
        try:
            record = await self.repository.maintain_void_fortress(platform=context.adapter, platform_user_id=context.user_id, operation_id=operation_id)
        except Exception as exc:
            return self._error(context, operation_id, exc)
        return CommandResult(True, "SECT_FORTRESS_MAINTAINED", "虚空堡垒维护完成。", context.request_id, operation_id, data={"status": record.status, "maintenance_due_at": record.maintenance_due_at})

    async def get(self, context: CommandContext) -> CommandResult:
        round_id = self._round(context.command_args)
        if round_id == "":
            return CommandResult(False, "INVALID_CROSS_SERVER_WAR", "请使用 `跨服宗门战 [轮次]`。", context.request_id)
        try:
            record = await self.repository.get_cross_server_sect_war(platform=context.adapter, platform_user_id=context.user_id, round_id=round_id)
        except Exception as exc:
            return self._error(context, "", exc)
        return CommandResult(True, "CROSS_SERVER_WAR_STATUS", f"## 跨服宗门战 · `{record.round_id}`\n\n- **状态**：{record.status}\n- **战场时间**：{record.starts_at} 至 {record.ends_at}\n- **报名**：{record.registered}\n- **本宗门积分**：{record.score}\n- **战争机关**：{record.engine_hp if record.engine_hp is not None else '未报名'}\n- **分支**：{record.branch_key or '尚未选择'}", context.request_id, data=self._war_data(record))

    async def register(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) > 1:
            return CommandResult(False, "INVALID_CROSS_SERVER_WAR", "请使用 `报名跨服宗门战 [轮次]`。", context.request_id)
        round_id = self._round(context.command_args)
        if context.command_args and round_id is None:
            return CommandResult(False, "INVALID_CROSS_SERVER_WAR", "轮次编号无效。", context.request_id)
        operation_id = self._operation_id(context, "social.sect_war_cross_server.register")
        try:
            record = await self.repository.register_cross_server_sect_war(platform=context.adapter, platform_user_id=context.user_id, round_id=round_id, operation_id=operation_id)
        except Exception as exc:
            return self._error(context, operation_id, exc)
        return CommandResult(True, "CROSS_SERVER_WAR_REGISTERED", f"跨服宗门战报名成功，冻结出战成员 {record.roster_size} 人。", context.request_id, operation_id, data=self._war_data(record))

    async def choose_branch(self, context: CommandContext) -> CommandResult:
        if not context.command_args or context.command_args[0] not in {"repair", "break"}:
            return CommandResult(False, "INVALID_CROSS_SERVER_WAR", "请使用 `跨服宗门战分支 repair|break [轮次]`。", context.request_id)
        operation_id = self._operation_id(context, "social.sect_war_cross_server.choose_branch")
        try:
            record = await self.repository.choose_cross_server_war_branch(platform=context.adapter, platform_user_id=context.user_id, branch_key=context.command_args[0], round_id=self._round(context.command_args[1:]), operation_id=operation_id)
        except Exception as exc:
            return self._error(context, operation_id, exc)
        return CommandResult(True, "CROSS_SERVER_WAR_BRANCH_LOCKED", f"战争机关分支已锁定为 `{context.command_args[0]}`。", context.request_id, operation_id, data=self._war_data(record))

    async def score(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) < 3:
            return CommandResult(False, "INVALID_CROSS_SERVER_WAR", "请使用 `贡献跨服宗门战 占点|击败|摧毁战争机关 目标 来源operation [轮次]`。", context.request_id)
        operation_id = self._operation_id(context, "social.sect_war_cross_server.score")
        round_id = self._round(context.command_args[3:])
        source_index = 2
        if round_id:
            source_index = 2
        try:
            record = await self.repository.record_cross_server_war_score(platform=context.adapter, platform_user_id=context.user_id, action_key=context.command_args[0], target_key=context.command_args[1], source_operation_id=context.command_args[source_index], round_id=round_id, operation_id=operation_id)
        except Exception as exc:
            return self._error(context, operation_id, exc)
        return CommandResult(True, "CROSS_SERVER_WAR_SCORED", "跨服宗门战积分来源已记录。", context.request_id, operation_id, data=self._war_data(record))

    async def claim(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 1 or not context.command_args[0].startswith("sect_war.cross:"):
            return CommandResult(False, "INVALID_CROSS_SERVER_WAR", "请使用 `领取跨服宗门战奖励 <轮次>`。", context.request_id)
        operation_id = self._operation_id(context, "social.sect_war_cross_server.claim")
        try:
            record = await self.repository.claim_cross_server_sect_war_reward(platform=context.adapter, platform_user_id=context.user_id, round_id=context.command_args[0], operation_id=operation_id)
        except Exception as exc:
            return self._error(context, operation_id, exc)
        return CommandResult(True, "CROSS_SERVER_WAR_REWARD_CLAIMED", "虚空功勋已发放。", context.request_id, operation_id, data={"round_id": record.round_id, "sect_id": record.sect_id, "reward": record.reward, "idempotent_replay": record.already_completed})

    async def allocate(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 3:
            return CommandResult(False, "INVALID_CROSS_SERVER_WAR", "请使用 `分配跨服宗门战奖励 <轮次> <成员平台ID> <数量>`。", context.request_id)
        try:
            quantity = int(context.command_args[2])
        except ValueError:
            return CommandResult(False, "INVALID_CROSS_SERVER_WAR", "奖励数量无效。", context.request_id)
        operation_id = self._operation_id(context, "social.sect_war_cross_server.allocate_reward")
        try:
            record = await self.repository.allocate_cross_server_reward(platform=context.adapter, platform_user_id=context.user_id, round_id=context.command_args[0], target_platform=context.adapter, target_platform_user_id=context.command_args[1], quantity=quantity, operation_id=operation_id)
        except Exception as exc:
            return self._error(context, operation_id, exc)
        return CommandResult(True, "CROSS_SERVER_REWARD_ALLOCATED", "公共奖励箱分配已记录。", context.request_id, operation_id, data={"round_id": record.round_id, "sect_id": record.sect_id, "reward": record.reward, "status": record.status, "idempotent_replay": record.already_completed})


__all__ = ["SectWarCrossServerApplication"]
