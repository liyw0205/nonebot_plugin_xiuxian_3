"""Adapter-neutral commands for the v0.3 three-realms tower."""

from __future__ import annotations

from ...contracts import CommandContext, CommandResult
from ..persistence.errors import (
    BattleBusyError,
    BattleRequirementError,
    OperationConflictError,
    PlayerNotFoundError,
    PlayerSuspendedError,
    RepositoryBusyError,
    ResourceInsufficientError,
    TowerAlreadyClaimedError,
    TowerBusyError,
    TowerFloorLockedError,
    TowerNotFoundError,
    TowerNotReadyError,
    TowerQuotaError,
    TowerRequirementError,
    TowerRewardNotAvailableError,
    TowerStartFailedError,
)
from .three_realms_tower_repository import ThreeRealmsTowerRepositoryMixin
from .three_realms_tower_rules import MAX_FLOOR, WEEKLY_ATTEMPT_LIMIT


class ThreeRealmsTowerApplication:
    def __init__(self, repository: ThreeRealmsTowerRepositoryMixin):
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
            PlayerSuspendedError: ("PLAYER_SUSPENDED", "当前角色暂时不能挑战三界塔。"),
            TowerRequirementError: ("THREE_REALMS_TOWER_REQUIREMENT_MISSING", "当前楼层的境界、重建名望或主线许可不足，未扣除体力。"),
            TowerBusyError: ("THREE_REALMS_TOWER_BUSY", "当前角色已有进行中的行动或待领取塔层奖励。"),
            TowerFloorLockedError: ("THREE_REALMS_TOWER_FLOOR_LOCKED", "请先依次通关并领取上一层奖励。"),
            TowerQuotaError: ("THREE_REALMS_TOWER_WEEKLY_CAP", f"本层本 UTC 周挑战次数已达 {WEEKLY_ATTEMPT_LIMIT} 次。"),
            TowerNotFoundError: ("THREE_REALMS_TOWER_RUN_NOT_FOUND", "没有找到三界塔记录。"),
            TowerNotReadyError: ("THREE_REALMS_TOWER_NOT_READY", "自动战斗尚未完成，请稍后重试。"),
            TowerStartFailedError: ("THREE_REALMS_TOWER_START_FAILED", "自动战未能启动，入场体力已退回。请用新消息重新挑战。"),
            TowerRewardNotAvailableError: ("THREE_REALMS_TOWER_REWARD_NOT_AVAILABLE", "当前没有待领取的三界塔奖励。"),
            TowerAlreadyClaimedError: ("THREE_REALMS_TOWER_REWARD_ALREADY_CLAIMED", "三界塔奖励已经领取。"),
            ResourceInsufficientError: ("RESOURCE_INSUFFICIENT", "体力不足，未扣除任何资源。"),
            BattleBusyError: ("THREE_REALMS_TOWER_BUSY", "当前角色已有进行中的战斗或其他行动。"),
            BattleRequirementError: ("THREE_REALMS_TOWER_REQUIREMENT_MISSING", "当前境界或状态不满足挑战条件。"),
            OperationConflictError: ("OPERATION_CONFLICT", "这次请求编号已用于其他三界塔操作。"),
            RepositoryBusyError: ("PERSISTENCE_BUSY", "三界塔暂时繁忙，请稍后再试。"),
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
            "三界塔暂时不可用，请稍后再试。",
            context.request_id,
            operation_id or None,
            retryable=True,
        )

    async def preview(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_THREE_REALMS_TOWER_COMMAND", "三界塔查询不接受参数。", context.request_id)
        try:
            record = await self.repository.preview_three_realms_tower(
                platform=context.adapter, platform_user_id=context.user_id
            )
        except Exception as exc:
            return self._error(context, "", exc)
        if record.active_status == "reward_pending":
            state = f"第 {record.active_floor} 层胜利，奖励待领取"
        elif record.active_status == "battle_running":
            state = f"第 {record.active_floor} 层自动战斗中"
        else:
            state = "无进行中的塔层"
        return CommandResult(
            True,
            "THREE_REALMS_TOWER_PREVIEW",
            "## 三界塔\n\n"
            f"- **最高首通**：{record.highest_floor}/{MAX_FLOOR} 层\n"
            f"- **下一层**：{record.next_floor}\n"
            f"- **入场体力**：{record.stamina_cost}\n"
            f"- **本 UTC 周本层次数**：{record.weekly_used}/{record.weekly_limit}\n"
            f"- **当前状态**：{state}\n\n"
            "> 发送 `挑战三界塔 <层数>` 挑战，胜利后发送 `领取三界塔奖励`。",
            context.request_id,
            data={
                "tower_key": "tower.three_realms",
                "highest_floor": record.highest_floor,
                "next_floor": record.next_floor,
                "active_floor": record.active_floor,
                "active_status": record.active_status,
                "stamina_cost": record.stamina_cost,
                "weekly_limit": record.weekly_limit,
                "weekly_used": record.weekly_used,
            },
        )

    async def challenge(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 1 or not context.command_args[0].isdigit():
            return CommandResult(
                False,
                "INVALID_THREE_REALMS_TOWER_COMMAND",
                f"请使用 `挑战三界塔 <1-{MAX_FLOOR}>`。",
                context.request_id,
            )
        floor_no = int(context.command_args[0])
        if not 1 <= floor_no <= MAX_FLOOR:
            return CommandResult(
                False,
                "INVALID_THREE_REALMS_TOWER_COMMAND",
                f"三界塔楼层范围为 1 至 {MAX_FLOOR}。",
                context.request_id,
            )
        operation_id = self._operation_id(context, "specials.start_three_realms_tower")
        try:
            record = await self.repository.start_three_realms_tower_run(
                platform=context.adapter,
                platform_user_id=context.user_id,
                floor_no=floor_no,
                operation_id=operation_id,
            )
        except Exception as exc:
            return self._error(context, operation_id, exc)
        if record.status == "aborted":
            return self._error(context, operation_id, TowerStartFailedError("battle start failed"))
        if record.status == "reward_pending":
            result_text = "胜利"
            next_action = "发送 `领取三界塔奖励` 领取本层奖励。"
        elif record.status == "lost":
            result_text = "失败"
            next_action = "本次没有奖励；失败会计入本周本层次数。"
        elif record.status == "claimed":
            result_text = "已完成"
            next_action = "这条请求已处理。"
        else:
            result_text = record.status
            next_action = "请稍后重试查看结果。"
        return CommandResult(
            True,
            "THREE_REALMS_TOWER_CHALLENGE_SETTLED",
            f"## 三界塔第 {floor_no} 层\n\n"
            f"- **结果**：{result_text}\n"
            f"- **首通**：{'是' if record.first_clear and record.outcome == 'won' else '否'}\n"
            f"- **自动战**：`{record.battle_id or '未创建'}`\n\n> {next_action}",
            context.request_id,
            operation_id,
            data={
                "run_id": record.run_id,
                "tower_key": record.tower_key,
                "floor_no": record.floor_no,
                "status": record.status,
                "battle_id": record.battle_id,
                "outcome": record.outcome,
                "reason": record.reason,
                "first_clear": record.first_clear and record.outcome == "won",
                "reward": record.reward,
                "idempotent_replay": record.already_completed,
            },
        )

    async def claim_reward(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(
                False,
                "INVALID_THREE_REALMS_TOWER_COMMAND",
                "领取三界塔奖励不接受参数。",
                context.request_id,
            )
        operation_id = self._operation_id(context, "specials.claim_three_realms_tower_reward")
        try:
            record = await self.repository.claim_three_realms_tower_reward(
                platform=context.adapter,
                platform_user_id=context.user_id,
                operation_id=operation_id,
            )
        except Exception as exc:
            return self._error(context, operation_id, exc)
        reward_text = "、".join(
            f"{'灵石' if key == 'spirit_stones' else '阵砂'} +{value}"
            for key, value in record.reward.items()
        ) or "无"
        return CommandResult(
            True,
            "THREE_REALMS_TOWER_REWARD_CLAIMED",
            f"## 三界塔第 {record.floor_no} 层奖励\n\n"
            f"- **首通**：{'是' if record.first_clear else '否'}\n"
            f"- **阵营快照**：{record.faction}\n"
            f"- **领取**：{reward_text}\n\n> 同一 operation 重放不会重复发奖。",
            context.request_id,
            operation_id,
            data={
                "run_id": record.run_id,
                "floor_no": record.floor_no,
                "first_clear": record.first_clear,
                "faction": record.faction,
                "reward": record.reward,
                "idempotent_replay": record.already_completed,
            },
        )


__all__ = ["ThreeRealmsTowerApplication"]
