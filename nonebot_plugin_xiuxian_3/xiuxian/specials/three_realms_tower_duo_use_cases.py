"""Adapter-neutral commands for the three-realms tower duo slice."""

from __future__ import annotations

from ...contracts import CommandContext, CommandResult
from ..persistence.errors import (
    OperationConflictError,
    PartyBattleRequirementError,
    PartyNotFoundError,
    ResourceInsufficientError,
    TowerAlreadyClaimedError,
    TowerFloorLockedError,
    TowerQuotaError,
    TowerRequirementError,
    TowerRewardNotAvailableError,
    TowerStartFailedError,
)
from .three_realms_tower_duo_rules import MAX_FLOOR


class ThreeRealmsTowerDuoApplication:
    def __init__(self, repository):
        self.repository = repository

    @staticmethod
    def _operation_id(context: CommandContext, name: str) -> str:
        return context.operation_id or f"{name}:{context.adapter}:{context.user_id}:{context.message_id or context.request_id}"

    @staticmethod
    def _error(context, operation_id, exc):
        mapping = {
            PartyNotFoundError: ("THREE_REALMS_TOWER_DUO_PARTY_REQUIRED", "请先创建并确认三界塔双人队伍。"),
            PartyBattleRequirementError: ("THREE_REALMS_TOWER_DUO_REQUIREMENT_MISSING", "双人塔队伍或战斗状态不满足要求。"),
            TowerRequirementError: ("THREE_REALMS_TOWER_DUO_REQUIREMENT_MISSING", "两名成员的境界、地点或重建名望不足。"),
            TowerFloorLockedError: ("THREE_REALMS_TOWER_DUO_FLOOR_LOCKED", "请先由两名成员依次领取上一层奖励。"),
            TowerQuotaError: ("THREE_REALMS_TOWER_DUO_WEEKLY_CAP", "本层本 UTC 周双人挑战次数已达上限。"),
            ResourceInsufficientError: ("RESOURCE_INSUFFICIENT", "两名成员都需要至少 12 点体力。"),
            TowerStartFailedError: ("THREE_REALMS_TOWER_DUO_START_FAILED", "自动战未能启动，双方体力已退回。"),
            TowerRewardNotAvailableError: ("THREE_REALMS_TOWER_DUO_REWARD_NOT_AVAILABLE", "当前没有待领取的双人塔奖励。"),
            TowerAlreadyClaimedError: ("THREE_REALMS_TOWER_DUO_REWARD_ALREADY_CLAIMED", "双人塔奖励已经领取。"),
            OperationConflictError: ("OPERATION_CONFLICT", "这次请求编号已用于其他双人塔操作。"),
        }
        for kind, value in mapping.items():
            if isinstance(exc, kind):
                return CommandResult(False, value[0], value[1], context.request_id, operation_id)
        return CommandResult(False, "PERSISTENCE_ERROR", "双人塔暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)

    async def challenge(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 1 or not context.command_args[0].isdigit() or not 1 <= int(context.command_args[0]) <= MAX_FLOOR:
            return CommandResult(False, "INVALID_THREE_REALMS_TOWER_DUO_COMMAND", f"请使用 `挑战三界塔双人 <1-{MAX_FLOOR}>`。", context.request_id)
        operation_id = self._operation_id(context, "specials.start_three_realms_tower_duo")
        try:
            record = await self.repository.start_three_realms_tower_duo(platform=context.adapter, platform_user_id=context.user_id, floor_no=int(context.command_args[0]), operation_id=operation_id)
        except Exception as exc:
            return self._error(context, operation_id, exc)
        return CommandResult(True, "THREE_REALMS_TOWER_DUO_SETTLED", f"## 三界塔双人第 {record.floor_no} 层\n\n- **结果**：{'胜利' if record.outcome == 'won' else '失败'}\n- **奖励**：胜利后两名成员分别领取\n\n> 服务端已冻结双方境界、阵营、声望、污染、血脉、技能和属性快照。", context.request_id, operation_id, data={"duo_run_id": record.duo_run_id, "party_id": record.party_id, "battle_id": record.battle_id, "floor_no": record.floor_no, "status": record.status, "outcome": record.outcome, "first_clear_by_player": record.first_clear_by_player, "reward_by_player": record.reward_by_player})

    async def claim_reward(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_THREE_REALMS_TOWER_DUO_COMMAND", "领取双人塔奖励无需附加参数。", context.request_id)
        operation_id = self._operation_id(context, "specials.claim_three_realms_tower_duo_reward")
        try:
            record = await self.repository.claim_three_realms_tower_duo_reward(platform=context.adapter, platform_user_id=context.user_id, operation_id=operation_id)
        except Exception as exc:
            return self._error(context, operation_id, exc)
        return CommandResult(True, "THREE_REALMS_TOWER_DUO_REWARD_CLAIMED", f"## 三界塔双人第 {record.floor_no} 层奖励\n\n- **首通**：{'是' if record.first_clear else '否'}\n- **奖励**：{record.reward or '无'}", context.request_id, operation_id, data={"duo_run_id": record.duo_run_id, "run_id": record.run_id, "floor_no": record.floor_no, "first_clear": record.first_clear, "reward": record.reward, "idempotent_replay": record.already_completed})


__all__ = ["ThreeRealmsTowerDuoApplication"]
