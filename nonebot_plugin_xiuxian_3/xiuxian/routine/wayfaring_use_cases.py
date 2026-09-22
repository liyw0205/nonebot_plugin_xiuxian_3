"""Application commands for the auditable v0.1 wayfaring pass."""

from __future__ import annotations

from ...contracts import CommandContext, CommandResult
from ..repository import (
    OperationConflictError,
    PlayerNotFoundError,
    PlayerSuspendedError,
    RepositoryBusyError,
    SQLitePlayerRepository,
    WayfaringAlreadyStartedError,
    WayfaringClaimAlreadyExistsError,
    WayfaringLevelInvalidError,
    WayfaringLevelLockedError,
    WayfaringNotStartedError,
    WayfaringPaidTrackInactiveError,
)
from .models import WayfaringClaimRecord, WayfaringStatusRecord
from .wayfaring import WAYFARING_LEVELS, WAYFARING_POINTS_PER_LEVEL


class WayfaringApplication:
    """Coordinate wayfaring commands and adapter-neutral Markdown output."""

    def __init__(self, repository: SQLitePlayerRepository):
        self.repository = repository

    @staticmethod
    def _operation_id(context: CommandContext, name: str) -> str:
        if context.operation_id:
            return context.operation_id
        request_key = context.message_id or context.request_id
        return f"pass.wayfaring.{name}:{context.adapter}:{context.user_id}:{request_key}"

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
            "local_reputation": "地方名望",
            "item.herb.blood_grass": "止血草",
            "item.herb.spirit_leaf": "灵叶",
            "item.mat.wood": "木材",
            "item.mat.array_sand": "阵砂",
            "item.ore.ironstone": "铁石",
            "item.clue.recipe_basic": "配方线索",
            "item.token.spirit_tree_water": "灵木水分券",
            "title.wayfaring.pathfinder": "行卷称号",
            "title.wayfaring.trailblazer": "行卷称号",
            "title.wayfaring.seeker": "行卷称号",
            "title.wayfaring.wayfarer": "行卷称号",
            "title.wayfaring.licensed": "行卷称号",
        }
        return "、".join(
            f"{labels.get(key, '奖励')} ×{value}"
            for key, value in reward.items()
            if value
        ) or "无"

    @staticmethod
    def _status_message(record: WayfaringStatusRecord) -> str:
        status = {
            "active": "进行中",
            "completed": "已完成",
            "closed": "已关闭",
        }.get(record.status, "未开始")
        return "\n".join(
            (
                "## 问道行卷",
                "",
                f"**{WayfaringApplication._display_name(record.player)}**的行卷状态：**{status}**",
                "",
                f"- **周期**：{record.cycle_start} 至 {record.cycle_end}",
                f"- **行卷点**：{record.total_points}/{WAYFARING_LEVELS[-1] * WAYFARING_POINTS_PER_LEVEL}",
                f"- **当前等级**：{record.current_level}/{WAYFARING_LEVELS[-1]}",
                f"- **今日点数**：{record.daily_points}/100",
                f"- **本周点数**：{record.weekly_points}/500",
                f"- **免费奖励**：已领取 {len(record.claimed_free)} 级",
                f"- **付费奖励**：已领取 {len(record.claimed_paid)} 级",
                "",
                "> 发送 `领取行卷 <等级>` 领取免费线；已验证月道契后可领取 `领取行卷 <等级> 付费`。",
            )
        )

    async def get_status(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_WAYFARING_COMMAND", "问道行卷无需附加参数。", context.request_id)
        try:
            record = await self.repository.get_wayfaring_status(
                platform=context.adapter, platform_user_id=context.user_id
            )
        except WayfaringNotStartedError:
            return CommandResult(False, "WAYFARING_NOT_STARTED", "行卷尚未开启，请先发送 `开始行卷`。", context.request_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能查看行卷。", context.request_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, retryable=True)
        return CommandResult(
            True,
            "WAYFARING_STATUS",
            self._status_message(record),
            context.request_id,
            data={
                "status": record.status,
                "cycle_start": record.cycle_start,
                "cycle_end": record.cycle_end,
                "total_points": record.total_points,
                "current_level": record.current_level,
                "daily_points": record.daily_points,
                "weekly_points": record.weekly_points,
                "claimed_free": list(record.claimed_free),
                "claimed_paid": list(record.claimed_paid),
            },
        )

    async def start(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_WAYFARING_COMMAND", "开始行卷无需附加参数。", context.request_id)
        operation_id = self._operation_id(context, "start")
        try:
            record = await self.repository.start_wayfaring(
                platform=context.adapter,
                platform_user_id=context.user_id,
                operation_id=operation_id,
            )
        except WayfaringAlreadyStartedError:
            return CommandResult(False, "WAYFARING_ALREADY_STARTED", "本周期行卷已经开启。", context.request_id, operation_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能开启行卷。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于其他行卷操作，请重新发起。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        return CommandResult(
            True,
            "WAYFARING_STARTED",
            "\n".join(
                (
                    "## 行卷已开启",
                    "",
                    f"**{self._display_name(record.player)}**已踏上本周期问道路程。",
                    f"- **周期**：{record.cycle_start} 至 {record.cycle_end}",
                    f"- **行卷点**：0/{WAYFARING_LEVELS[-1] * WAYFARING_POINTS_PER_LEVEL}",
                    "",
                    "> 发送 `问道行卷` 查看进度。",
                )
            ),
            context.request_id,
            operation_id,
            data={"cycle_start": record.cycle_start, "cycle_end": record.cycle_end, "idempotent_replay": record.already_completed},
        )

    @staticmethod
    def _claim_args(args: tuple[str, ...]) -> tuple[int, str] | None:
        if len(args) not in {1, 2} or not args[0] or not args[0].isascii() or not args[0].isdigit():
            return None
        if len(args[0]) > 1 and args[0].startswith("0"):
            return None
        track = "free"
        if len(args) == 2:
            track = {"免费": "free", "free": "free", "付费": "paid", "高级": "paid", "paid": "paid"}.get(args[1].casefold(), "")
            if not track:
                return None
        return int(args[0]), track

    async def claim_level(self, context: CommandContext) -> CommandResult:
        parsed = self._claim_args(context.command_args)
        if parsed is None:
            return CommandResult(False, "INVALID_WAYFARING_COMMAND", "请使用 `领取行卷 <等级> [免费|付费]`。", context.request_id)
        level, track = parsed
        operation_id = self._operation_id(context, f"claim:{level}:{track}")
        try:
            record = await self.repository.claim_wayfaring_level(
                platform=context.adapter,
                platform_user_id=context.user_id,
                level=level,
                track=track,
                operation_id=operation_id,
            )
        except WayfaringLevelInvalidError:
            return CommandResult(False, "INVALID_WAYFARING_LEVEL", "行卷等级必须是 1 至 30。", context.request_id, operation_id)
        except WayfaringNotStartedError:
            return CommandResult(False, "WAYFARING_NOT_STARTED", "行卷尚未开启，请先发送 `开始行卷`。", context.request_id, operation_id)
        except WayfaringLevelLockedError:
            return CommandResult(False, "WAYFARING_LEVEL_LOCKED", "该等级尚未解锁，先完成更多行卷任务。", context.request_id, operation_id)
        except WayfaringClaimAlreadyExistsError:
            return CommandResult(False, "WAYFARING_ALREADY_CLAIMED", "该等级的这条奖励已经领取过了。", context.request_id, operation_id)
        except WayfaringPaidTrackInactiveError:
            return CommandResult(False, "WAYFARING_PAID_LOCKED", "付费线需要当前有效的 `dao_contract.monthly`。", context.request_id, operation_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能领取行卷奖励。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于其他行卷操作，请重新发起。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        return CommandResult(
            True,
            "WAYFARING_LEVEL_CLAIMED",
            "\n".join(
                (
                    "## 行卷奖励已领取",
                    "",
                    f"**{self._display_name(record.player)}**领取了第 **{record.level}** 级{'付费' if record.track == 'paid' else '免费'}奖励。",
                    f"- **获得**：{self._reward_text(record.reward)}",
                    f"- **行卷点**：{record.total_points}",
                )
            ),
            context.request_id,
            operation_id,
            data={"level": record.level, "track": record.track, "reward": record.reward, "total_points": record.total_points, "idempotent_replay": record.already_completed},
        )


__all__ = ["WayfaringApplication"]
