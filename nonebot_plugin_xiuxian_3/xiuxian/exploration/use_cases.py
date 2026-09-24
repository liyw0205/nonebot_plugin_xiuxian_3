"""Application commands for v0.1 exploration sessions."""

from __future__ import annotations

from ...contracts import CommandContext, CommandResult
from ..repository import (
    ExplorationBusyError,
    ExplorationCombatPendingError,
    ExplorationNotFoundError,
    ExplorationNotReadyError,
    ExplorationQuotaExhaustedError,
    LocationRequirementError,
    OperationConflictError,
    PlayerNotFoundError,
    PlayerStageConflictError,
    PlayerSuspendedError,
    RepositoryBusyError,
    ResourceInsufficientError,
    SQLitePlayerRepository,
)
from ..player.rules import LOCATION_LABELS
from .rules import exploration_definition, resolve_exploration_mode


ITEM_LABELS = {
    "item.herb.blood_grass": "止血草",
    "item.ore.ironstone": "铁石",
    "item.herb.spirit_leaf": "灵叶",
    "item.mat.array_sand": "阵砂",
}


class ExplorationApplication:
    """Coordinates exploration session writes and Markdown responses."""

    def __init__(self, repository: SQLitePlayerRepository):
        self.repository = repository

    @staticmethod
    def _operation_id(context: CommandContext, operation_name: str) -> str:
        if context.operation_id:
            return context.operation_id
        request_key = context.message_id or context.request_id
        return f"{operation_name}:{context.adapter}:{context.user_id}:{request_key}"

    @staticmethod
    def _display_name(player) -> str:
        value = player.dao_name or "未命名"
        return (
            value.replace("\\", "\\\\")
            .replace("`", "\\`")
            .replace("*", "\\*")
            .replace("_", "\\_")
            .replace("~", "\\~")
        )

    @staticmethod
    def _mode(args: tuple[str, ...]) -> str | None:
        if len(args) != 1:
            return None
        return resolve_exploration_mode(args[0])

    @staticmethod
    def _location_text(location_key: str) -> str:
        return LOCATION_LABELS.get(location_key, "未知地点")

    async def start_exploration(self, context: CommandContext) -> CommandResult:
        mode_key = self._mode(context.command_args)
        if mode_key is None:
            return CommandResult(
                False,
                "INVALID_EXPLORATION_MODE",
                "请使用 `开始探索 近郊采集`、`开始探索 短历练`、`开始探索 灵泉采集` 或 `开始探索 雾隐洞天探索`。",
                context.request_id,
            )
        operation_id = self._operation_id(context, "exploration.start")
        try:
            record = await self.repository.start_exploration(
                platform=context.adapter,
                platform_user_id=context.user_id,
                mode_key=mode_key,
                operation_id=operation_id,
            )
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色处于暂停状态，暂时不能探索。", context.request_id, operation_id)
        except PlayerStageConflictError:
            return CommandResult(False, "EXPLORATION_REQUIREMENT_MISSING", "完成入道后才能开始探索。", context.request_id, operation_id)
        except LocationRequirementError:
            return CommandResult(False, "EXPLORATION_LOCATION_FORBIDDEN", "当前地点或境界不满足这项探索。", context.request_id, operation_id)
        except ExplorationBusyError:
            return CommandResult(False, "EXPLORATION_BUSY", "当前已有移动、修炼、生产、突破或探索会话。", context.request_id, operation_id)
        except ExplorationQuotaExhaustedError:
            return CommandResult(False, "EXPLORATION_QUOTA_EXHAUSTED", "这项探索今日次数已用尽。", context.request_id, operation_id)
        except ResourceInsufficientError:
            return CommandResult(False, "RESOURCE_INSUFFICIENT", "体力不足，未扣除任何资源。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于其他探索输入，请重新发起。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        definition = exploration_definition(record.mode_key)
        return CommandResult(
            True,
            "EXPLORATION_STARTED",
            (
                f"## {definition.label}已开始\n\n"
                f"**{self._display_name(record.player)}**已锁定探索会话。\n\n"
                f"- **地点**：{self._location_text(definition.location_key)}\n"
                f"- **预计耗时**：{definition.duration_seconds // 60 if definition.duration_seconds >= 60 else definition.duration_seconds} {'分钟' if definition.duration_seconds >= 60 else '秒'}\n"
                f"- **体力**：{record.player.stamina}/{record.player.stamina_max}\n"
                f"- **今日上限**：{definition.daily_limit} 次\n\n"
                "> 完成后发送 `结算探索`；准备期间不能移动、修炼、生产、突破或再次探索。"
            ),
            context.request_id,
            operation_id,
            data={
                "exploration_id": record.exploration_id,
                "mode_key": record.mode_key,
                "status": record.status,
                "ends_at": record.ends_at,
                "stamina_cost": record.stamina_cost,
                "idempotent_replay": record.already_completed,
            },
        )

    async def settle_exploration(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_EXPLORATION_COMMAND", "结算探索无需附加参数。", context.request_id)
        operation_id = self._operation_id(context, "exploration.settle")
        try:
            record = await self.repository.settle_exploration(
                platform=context.adapter,
                platform_user_id=context.user_id,
                operation_id=operation_id,
            )
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except ExplorationNotFoundError:
            return CommandResult(False, "EXPLORATION_NOT_FOUND", "当前没有等待结算的探索。", context.request_id, operation_id)
        except ExplorationNotReadyError:
            return CommandResult(False, "EXPLORATION_NOT_READY", "探索尚未完成，请稍后再来结算。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色处于暂停状态，暂时不能结算探索。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于其他探索结算，请重新发起。", context.request_id, operation_id)
        except ExplorationCombatPendingError:
            return CommandResult(
                False,
                "EXPLORATION_COMBAT_PENDING",
                "探索遭遇战仍在自动回合中，奖励已冻结，请稍后重试结算。",
                context.request_id,
                operation_id,
                retryable=True,
            )
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        definition = exploration_definition(record.mode_key)
        if record.status == "combat_pending":
            return CommandResult(
                False,
                "EXPLORATION_COMBAT_PENDING",
                (
                    f"## {definition.label}遭遇战斗\n\n"
                    f"**{self._display_name(record.player)}**在探索中触发了战斗遭遇。\n\n"
                    "> 自动回合战斗正在恢复，探索奖励已冻结；请稍后重试结算。"
                ),
                context.request_id,
                operation_id,
                data={"exploration_id": record.exploration_id, "status": record.status, "battle_id": record.battle_id, "idempotent_replay": record.already_completed},
            )
        if record.status == "expired":
            return CommandResult(
                False,
                "EXPLORATION_EXPIRED",
                f"## 探索已过期\n\n**{self._display_name(record.player)}**的 **{definition.label}** 超过了结算窗口，本次不发放奖励。",
                context.request_id,
                operation_id,
                data={"exploration_id": record.exploration_id, "status": record.status, "idempotent_replay": record.already_completed},
            )
        reward_lines = []
        for key, quantity in record.result.items():
            if key == "cultivation":
                reward_lines.append(f"境内修为 +{quantity}")
            elif key == "spirit_stones":
                reward_lines.append(f"灵石 ×{quantity}")
            else:
                reward_lines.append(f"{ITEM_LABELS.get(key, '探索材料')} ×{quantity}")
        battle_text = f"- **遭遇战**：{'胜利' if record.battle_outcome == 'won' else '失败'}\n" if record.battle_outcome else ""
        return CommandResult(
            True,
            "EXPLORATION_SETTLED",
            (
                f"## {definition.label}完成\n\n"
                f"**{self._display_name(record.player)}**已完成探索。\n\n"
                f"{battle_text}"
                f"- **探索收获**：{'、'.join(reward_lines) or '无'}\n"
                f"- **体力**：{record.player.stamina}/{record.player.stamina_max}\n"
                f"- **灵石**：{record.player.spirit_stones}\n\n"
                "> 结果按开始时的规则快照结算，重复结算不会重复发放。"
            ),
            context.request_id,
            operation_id,
            data={
                "exploration_id": record.exploration_id,
                "mode_key": record.mode_key,
                "status": record.status,
                "result": record.result,
                "battle_id": record.battle_id,
                "battle_outcome": record.battle_outcome,
                "idempotent_replay": record.already_completed,
            },
        )

    async def cancel_exploration(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_EXPLORATION_COMMAND", "取消探索无需附加参数。", context.request_id)
        operation_id = self._operation_id(context, "exploration.cancel")
        try:
            record = await self.repository.cancel_exploration(
                platform=context.adapter,
                platform_user_id=context.user_id,
                operation_id=operation_id,
            )
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except ExplorationNotFoundError:
            return CommandResult(False, "EXPLORATION_NOT_SETTLEABLE", "当前探索已经进入运行阶段，不能取消。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色处于暂停状态，暂时不能取消探索。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于其他探索取消，请重新发起。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        return CommandResult(
            True,
            "EXPLORATION_CANCELLED",
            (
                "## 探索已取消\n\n"
                f"**{self._display_name(record.player)}**取消了尚未运行的探索。\n\n"
                f"- **返还体力**：{record.result.get('stamina_refund', 0)}\n"
                f"- **体力**：{record.player.stamina}/{record.player.stamina_max}"
            ),
            context.request_id,
            operation_id,
            data={"exploration_id": record.exploration_id, "status": record.status, "stamina_refund": record.result.get("stamina_refund", 0), "idempotent_replay": record.already_completed},
        )


__all__ = ["ExplorationApplication"]
