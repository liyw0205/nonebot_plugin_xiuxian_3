"""Application commands for the v0.1 routine slice."""

from __future__ import annotations

from ...contracts import CommandContext, CommandResult
from ..repository import (
    CheckinAlreadyClaimedError,
    CurrencyInsufficientError,
    OperationConflictError,
    PlayerNotFoundError,
    PlayerSuspendedError,
    RepositoryBusyError,
    ResourceInsufficientError,
    RoutineMakeupDateError,
    RoutineMakeupLimitError,
    RoutineMakeupNotEligibleError,
    SpiritTreeCooldownError,
    SpiritTreeNotReadyError,
    SpiritTreeWateredError,
    SQLitePlayerRepository,
)
from .rules import (
    CHECKIN_ACTIVITY,
    FATE_TICKET,
    TREE_HARVEST_ACTIVITY,
    TREE_SEED,
    TREE_WATER_ACTIVITY,
    parse_iso_date,
)


class RoutineApplication:
    """Coordinates routine commands and Markdown responses."""

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
    def _reward_text(reward: dict[str, int]) -> str:
        labels = {
            "spirit_stones": "灵石",
            "energy": "精力",
            "local_reputation": "地方名望",
            FATE_TICKET: "机缘签",
            TREE_SEED: "灵木种子",
        }
        return "、".join(
            f"{labels.get(key, '奖励')} ×{value}"
            for key, value in reward.items()
            if value
        ) or "无"

    async def claim_daily(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_ROUTINE_COMMAND", "道历问安无需附加参数。", context.request_id)
        operation_id = self._operation_id(context, "routine.checkin.daily")
        try:
            record = await self.repository.claim_daily(
                platform=context.adapter,
                platform_user_id=context.user_id,
                operation_id=operation_id,
            )
        except CheckinAlreadyClaimedError:
            return CommandResult(False, "CHECKIN_ALREADY_CLAIMED", "今日已经问安过了，明日再来。", context.request_id, operation_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能进行道历问安。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于其他道历操作，请重新发起。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        extra = ""
        if FATE_TICKET in record.reward:
            extra = "\n\n> 连续问安七日，额外获得 **机缘签 ×1**。"
        return CommandResult(
            True,
            "DAILY_CHECKIN_CLAIMED",
            (
                "## 道历问安完成\n\n"
                f"**{self._display_name(record.player)}**今日问安已记档。\n\n"
                f"- **连续问安**：{record.consecutive_days} 日\n"
                f"- **获得**：{self._reward_text(record.reward)}\n"
                f"- **精力**：{record.player.energy}/{record.player.energy_max}"
                f"{extra}"
            ),
            context.request_id,
            operation_id,
            data={
                "target_date": record.target_date,
                "reward": record.reward,
                "consecutive_days": record.consecutive_days,
                "idempotent_replay": record.already_completed,
            },
        )

    async def makeup_daily(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 1:
            return CommandResult(False, "INVALID_ROUTINE_COMMAND", "请使用 `补录道历 YYYY-MM-DD`。", context.request_id)
        try:
            target_date = parse_iso_date(context.command_args[0])
        except ValueError:
            return CommandResult(False, "INVALID_MAKEUP_DATE", "只能补录本月最近 3 日内漏掉的道历。", context.request_id)
        operation_id = self._operation_id(context, "routine.makeup.daily")
        try:
            record = await self.repository.makeup_daily(
                platform=context.adapter,
                platform_user_id=context.user_id,
                target_date=target_date.isoformat(),
                operation_id=operation_id,
            )
        except RoutineMakeupNotEligibleError:
            return CommandResult(False, "MAKEUP_NOT_ELIGIBLE", "这一天已经问安或补录过了，不能重复补录。", context.request_id, operation_id)
        except RoutineMakeupDateError:
            return CommandResult(False, "INVALID_MAKEUP_DATE", "只能补录本月最近 3 个已过去的业务日。", context.request_id, operation_id)
        except RoutineMakeupLimitError:
            return CommandResult(False, "MAKEUP_LIMIT_REACHED", "本月补录次数已用尽，最多补录 2 次。", context.request_id, operation_id)
        except CurrencyInsufficientError:
            return CommandResult(False, "RESOURCE_INSUFFICIENT", "补录道历需要 30 灵石，未扣除任何资源。", context.request_id, operation_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能补录道历。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于其他道历操作，请重新发起。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        return CommandResult(
            True,
            "DAILY_CHECKIN_MADE_UP",
            (
                "## 道历补录完成\n\n"
                f"**{self._display_name(record.player)}**已补录 **{record.target_date}**。\n\n"
                f"- **消耗灵石**：{record.spirit_stones_spent}\n"
                f"- **获得**：{self._reward_text(record.reward)}\n\n"
                "> 补录只恢复当天奖励，不计入连续问安。"
            ),
            context.request_id,
            operation_id,
            data={"target_date": record.target_date, "reward": record.reward, "idempotent_replay": record.already_completed},
        )

    async def water_spirit_tree(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_ROUTINE_COMMAND", "浇灌灵木无需附加参数。", context.request_id)
        operation_id = self._operation_id(context, TREE_WATER_ACTIVITY)
        try:
            record = await self.repository.water_spirit_tree(
                platform=context.adapter,
                platform_user_id=context.user_id,
                operation_id=operation_id,
            )
        except SpiritTreeWateredError:
            return CommandResult(False, "SPIRIT_TREE_ALREADY_WATERED", "今日已经浇灌过灵木了，明日再来。", context.request_id, operation_id)
        except SpiritTreeCooldownError:
            return CommandResult(False, "SPIRIT_TREE_COOLDOWN", "灵木正在休养，冷却结束后才能再次培育。", context.request_id, operation_id)
        except ResourceInsufficientError:
            return CommandResult(False, "RESOURCE_INSUFFICIENT", "浇灌灵木需要 2 点精力，未扣除任何资源。", context.request_id, operation_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能培育灵木。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于其他灵木操作，请重新发起。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        status_text = "已成熟，等待收获" if record.status == "ready" else f"已浇灌 {record.water_count}/7 次"
        return CommandResult(
            True,
            "SPIRIT_TREE_WATERED",
            (
                "## 灵木浇灌完成\n\n"
                f"**{self._display_name(record.player)}**的灵木{status_text}。\n\n"
                f"- **消耗精力**：{record.energy_spent}\n"
                f"- **剩余精力**：{record.player.energy}/{record.player.energy_max}\n\n"
                "> 灵木成熟后发送 `收获灵木`。"
            ),
            context.request_id,
            operation_id,
            data={"status": record.status, "water_count": record.water_count, "idempotent_replay": record.already_completed},
        )

    async def harvest_spirit_tree(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_ROUTINE_COMMAND", "收获灵木无需附加参数。", context.request_id)
        operation_id = self._operation_id(context, TREE_HARVEST_ACTIVITY)
        try:
            record = await self.repository.harvest_spirit_tree(
                platform=context.adapter,
                platform_user_id=context.user_id,
                operation_id=operation_id,
            )
        except SpiritTreeNotReadyError:
            return CommandResult(False, "SPIRIT_TREE_NOT_READY", "灵木还未成熟，完成 7 次浇灌后才能收获。", context.request_id, operation_id)
        except SpiritTreeCooldownError:
            return CommandResult(False, "SPIRIT_TREE_COOLDOWN", "灵木正在休养，冷却结束后才能再次培育。", context.request_id, operation_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能收获灵木。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于其他灵木操作，请重新发起。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        return CommandResult(
            True,
            "SPIRIT_TREE_HARVESTED",
            (
                "## 灵木收获完成\n\n"
                f"**{self._display_name(record.player)}**收获了一轮灵木灵蕴。\n\n"
                f"- **获得**：{self._reward_text(record.reward)}\n"
                f"- **灵石**：{record.player.spirit_stones}\n\n"
                "> 灵木进入 24 小时休养，之后可以重新浇灌。"
            ),
            context.request_id,
            operation_id,
            data={"reward": record.reward, "cooldown_until": record.cooldown_until, "idempotent_replay": record.already_completed},
        )


__all__ = ["RoutineApplication"]
