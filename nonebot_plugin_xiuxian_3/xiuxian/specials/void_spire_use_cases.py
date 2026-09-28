"""Adapter-neutral use cases for the open void-spire tower slice."""

from __future__ import annotations

from ...contracts import CommandContext, CommandResult
from ..routine.rules import HONOR_TITLES
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
from .void_spire_repository import VoidSpireRepositoryMixin
from .codex_rules import ENTRY_DEFINITIONS
from .void_spire_rules import DESIGN_MAX_FLOOR, MAX_FLOOR


class VoidSpireApplication:
    def __init__(self, repository: VoidSpireRepositoryMixin):
        self.repository = repository

    @staticmethod
    def _operation_id(context: CommandContext, name: str) -> str:
        if context.operation_id:
            return context.operation_id
        key = context.message_id or context.request_id
        return f"{name}:{context.adapter}:{context.user_id}:{key}"

    @staticmethod
    def _reward_text(reward: dict[str, int]) -> str:
        labels = {
            "item.mat.array_sand": "阵砂",
            "spirit_stones": "灵石",
            "local.void_supply": "虚空补给名望",
        }
        return "、".join(f"{labels.get(key, key)} +{value}" for key, value in reward.items()) or "无"

    @staticmethod
    def _error(context: CommandContext, operation_id: str, exc: Exception) -> CommandResult:
        errors = {
            PlayerNotFoundError: ("PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。"),
            PlayerSuspendedError: ("PLAYER_SUSPENDED", "当前角色暂时不能挑战虚空塔。"),
            TowerRequirementError: ("VOID_SPIRE_REQUIREMENT_MISSING", "1–30 层需要炼虚 L1 或虚空补给名望 600；31–60 层需要合道 L1 或道统服务名望 700。未扣体力。"),
            TowerBusyError: ("VOID_SPIRE_BUSY", "当前角色已有进行中的行动或待领取虚空塔奖励。"),
            TowerFloorLockedError: ("VOID_SPIRE_FLOOR_LOCKED", "请先领取上一层虚空塔首通奖励。"),
            TowerQuotaError: ("VOID_SPIRE_WEEKLY_LIMIT", "本周虚空塔挑战次数已用尽。"),
            TowerNotFoundError: ("VOID_SPIRE_RUN_NOT_FOUND", "没有找到虚空塔记录。"),
            TowerNotReadyError: ("VOID_SPIRE_NOT_READY", "自动战斗尚未完成，请稍后重试。"),
            TowerStartFailedError: ("VOID_SPIRE_START_FAILED", "自动战未能启动，入场体力已退回。请用新消息重新挑战。"),
            TowerRewardNotAvailableError: ("VOID_SPIRE_REWARD_NOT_AVAILABLE", "当前没有待领取的虚空塔奖励。"),
            TowerAlreadyClaimedError: ("VOID_SPIRE_REWARD_CLAIMED", "虚空塔奖励已经领取。"),
            ResourceInsufficientError: ("RESOURCE_INSUFFICIENT", "体力不足，未扣除任何资源。"),
            BattleBusyError: ("VOID_SPIRE_BUSY", "当前角色已有进行中的战斗或其他行动。"),
            BattleRequirementError: ("VOID_SPIRE_REQUIREMENT_MISSING", "当前状态不满足虚空塔挑战条件。"),
            OperationConflictError: ("OPERATION_CONFLICT", "这次请求编号已用于其他虚空塔操作。"),
            RepositoryBusyError: ("PERSISTENCE_BUSY", "虚空塔暂时繁忙，请稍后再试。"),
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
            "虚空塔暂时不可用，请稍后再试。",
            context.request_id,
            operation_id or None,
            retryable=True,
        )

    async def preview(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_VOID_SPIRE_COMMAND", "虚空塔查询不接受参数。", context.request_id)
        try:
            record = await self.repository.preview_void_spire(
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
        next_floor = "已完成当前开放楼层" if record.highest_floor >= MAX_FLOOR else str(record.next_floor)
        message = (
            "## 虚空塔\n\n"
            f"- **已开放**：1-{MAX_FLOOR}/{DESIGN_MAX_FLOOR} 层\n"
            f"- **最高首通**：{record.highest_floor}/{MAX_FLOOR} 层\n"
            f"- **下一层**：{next_floor}\n"
            f"- **入场体力**：{record.stamina_cost}\n"
            f"- **本周次数**：{record.weekly_used}/{record.weekly_limit}\n"
            f"- **虚空补给名望**：{record.supply_reputation}\n"
            f"- **道统服务名望**：{record.dao_service_reputation}\n"
            f"- **当前状态**：{state}\n\n"
            "> 发送 `挑战虚空塔 <层数>` 挑战，胜利后发送 `领取虚空塔奖励`。"
        )
        return CommandResult(
            True,
            "VOID_SPIRE_PREVIEW",
            message,
            context.request_id,
            data={
                "tower_key": "tower.void_spire",
                "highest_floor": record.highest_floor,
                "next_floor": record.next_floor,
                "active_floor": record.active_floor,
                "active_status": record.active_status,
                "stamina_cost": record.stamina_cost,
                "weekly_limit": record.weekly_limit,
                "weekly_used": record.weekly_used,
                "supply_reputation": record.supply_reputation,
                "dao_service_reputation": record.dao_service_reputation,
            },
        )

    async def challenge(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 1 or not context.command_args[0].isdigit():
            return CommandResult(False, "INVALID_VOID_SPIRE_COMMAND", f"请使用 `挑战虚空塔 <1-{MAX_FLOOR}>`。", context.request_id)
        floor_no = int(context.command_args[0])
        if not 1 <= floor_no <= MAX_FLOOR:
            return CommandResult(False, "INVALID_VOID_SPIRE_COMMAND", f"当前开放楼层范围为 1 至 {MAX_FLOOR}；{MAX_FLOOR + 1}-{DESIGN_MAX_FLOOR} 尚未开放。", context.request_id)
        operation_id = self._operation_id(context, "specials.start_void_spire")
        try:
            record = await self.repository.start_void_spire_run(
                platform=context.adapter,
                platform_user_id=context.user_id,
                floor_no=floor_no,
                operation_id=operation_id,
            )
        except Exception as exc:
            return self._error(context, operation_id, exc)
        if record.status == "aborted":
            return CommandResult(
                False,
                "VOID_SPIRE_START_FAILED",
                "自动战未能启动，入场体力已退回。请用新消息重新挑战。",
                context.request_id,
                operation_id,
            )
        if record.status == "reward_pending":
            result_text, next_action = "胜利", "发送 `领取虚空塔奖励` 领取本层奖励。"
        elif record.status == "lost":
            result_text, next_action = "失败", "本次没有奖励；次数已经计入本周限制。"
        elif record.status == "claimed":
            result_text, next_action = "已完成", "这条请求已处理。"
        else:
            result_text, next_action = record.status, "请稍后重试查看结果。"
        return CommandResult(
            True,
            "VOID_SPIRE_CHALLENGE_SETTLED",
            f"## 虚空塔第 {floor_no} 层\n\n- **路线**：{record.route_key}\n- **结果**：{result_text}\n- **首通**：{'是' if record.first_clear and record.outcome == 'won' else '否'}\n- **自动战**：`{record.battle_id or '未创建'}`\n\n> {next_action}",
            context.request_id,
            operation_id,
            data={
                "run_id": record.run_id,
                "tower_key": record.tower_key,
                "floor_no": record.floor_no,
                "route_key": record.route_key,
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
            return CommandResult(False, "INVALID_VOID_SPIRE_COMMAND", "领取虚空塔奖励不接受参数。", context.request_id)
        operation_id = self._operation_id(context, "specials.claim_void_spire_reward")
        try:
            record = await self.repository.claim_void_spire_reward(
                platform=context.adapter, platform_user_id=context.user_id, operation_id=operation_id
            )
        except Exception as exc:
            return self._error(context, operation_id, exc)
        discoveries = "、".join(
            ENTRY_DEFINITIONS[key].label for key in record.discoveries if key in ENTRY_DEFINITIONS
        ) or "无"
        title = next(
            (
                definition.label for definition in HONOR_TITLES
                if record.first_clear and definition.source_event == f"specials.void_spire.floor.{record.floor_no}"
            ),
            None,
        )
        title_line = f"\n- **展示称号**：{title}" if title else ""
        return CommandResult(
            True,
            "VOID_SPIRE_REWARD_CLAIMED",
            f"## 虚空塔第 {record.floor_no} 层奖励\n\n- **路线**：{record.route_key}\n- **首通**：{'是' if record.first_clear else '否'}\n- **领取**：{self._reward_text(record.reward)}\n- **图鉴**：{discoveries}{title_line}\n\n> 同一 operation 重放不会重复发奖。",
            context.request_id,
            operation_id,
            data={
                "run_id": record.run_id,
                "floor_no": record.floor_no,
                "route_key": record.route_key,
                "first_clear": record.first_clear,
                "reward": record.reward,
                "discoveries": record.discoveries,
                "title": title,
                "idempotent_replay": record.already_completed,
            },
        )


__all__ = ["VoidSpireApplication"]
