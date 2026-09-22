"""Application commands for the v0.1 Xuantian mainline."""

from __future__ import annotations

from ...contracts import CommandContext, CommandResult
from ..repository import (
    MainlineAlreadyRunningError,
    MainlineContentClosedError,
    MainlineNotStartedError,
    MainlineRequirementError,
    OperationConflictError,
    PlayerNotFoundError,
    PlayerSuspendedError,
    RepositoryBusyError,
    SQLitePlayerRepository,
)
from .mainline import resolve_mainline


STATUS_LABELS = {
    "locked": "尚未解锁",
    "available": "可开始",
    "running": "进行中",
    "cleared": "已完成，待领取",
    "reward_pending": "奖励结算中",
    "claimed": "已领取",
}

REWARD_LABELS = {
    "spirit_stones": "灵石",
    "local_reputation": "地方名望",
    "service_reputation": "服务信誉",
    "item.herb.spirit_leaf": "灵叶",
    "access.xuantian.outskirts": "近郊通行资格",
    "access.xuantian.spirit_field": "灵泉谷通行资格",
    "access.xuantian.trade_route": "玄天商路资格",
    "access.instance.secret_realm": "秘境试炼资格",
    "codex.place.outskirts": "近郊图鉴记录",
    "codex.observation": "图鉴观察记录",
    "title_key": "称号",
}


class AdventuresMainlineApplication:
    """Coordinate mainline status, start and reward commands."""

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
    def _reward_text(reward: dict[str, int | str]) -> str:
        parts: list[str] = []
        for key, value in reward.items():
            label = REWARD_LABELS.get(key, "奖励")
            if key == "title_key":
                value = "雾中守门人" if value == "title.mist_watcher" else str(value)
                parts.append(f"{label}：{value}")
            elif isinstance(value, int):
                parts.append(f"{label} +{value}")
            else:
                parts.append(f"{label}：{value}")
        return "、".join(parts) or "无"

    @staticmethod
    def _stage_key(args: tuple[str, ...]) -> str | None:
        if len(args) != 1:
            return None
        return resolve_mainline(args[0])

    async def get_status(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_MAINLINE_COMMAND", "查看主线道途无需附加参数。", context.request_id)
        try:
            record = await self.repository.get_mainline_status(
                platform=context.adapter,
                platform_user_id=context.user_id,
            )
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能查看主线道途。", context.request_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, retryable=True)
        lines = [
            "## 主线道途",
            "",
            f"**{self._display_name(record.player)}** · 第 {record.chapter} 章 · {STATUS_LABELS.get(record.status, record.status)}",
            "",
        ]
        stages: list[dict[str, object]] = []
        for item in record.stages:
            lines.append(f"- **第 {item.chapter} 章·{item.stage}关 {item.label}**：{STATUS_LABELS.get(item.status, item.status)}")
            stages.append(
                {
                    "chapter": item.chapter,
                    "stage": item.stage,
                    "key": item.key,
                    "label": item.label,
                    "status": item.status,
                    "completed": item.completed,
                    "claimed": item.claimed,
                }
            )
        lines.extend(
            [
                "",
                "> 可发送 `开始主线 1` 开始当前关卡，完成后发送 `领取主线奖励 1`。",
                "> 章节尚未开放时会保留在主线列表，不会创建运行记录或扣除资源。",
            ]
        )
        return CommandResult(
            True,
            "MAINLINE_STATUS",
            "\n".join(lines),
            context.request_id,
            data={"chapter": record.chapter, "current_stage": record.current_stage, "status": record.status, "stages": stages},
        )

    async def start_stage(self, context: CommandContext) -> CommandResult:
        stage_key = self._stage_key(context.command_args)
        if stage_key is None:
            return CommandResult(False, "INVALID_MAINLINE_COMMAND", "请使用 `开始主线 1`、`开始主线 2` 或 `开始主线 3`。", context.request_id)
        operation_id = self._operation_id(context, "mainline.start_stage")
        try:
            record = await self.repository.start_mainline(
                platform=context.adapter,
                platform_user_id=context.user_id,
                stage_key=stage_key,
                operation_id=operation_id,
            )
        except MainlineContentClosedError:
            return CommandResult(False, "CONTENT_CLOSED", "这条主线关卡尚未开放，当前不会创建运行记录。", context.request_id, operation_id)
        except MainlineRequirementError:
            return CommandResult(False, "MAINLINE_REQUIREMENT_MISSING", "当前境界、引导或前置关卡尚未满足，暂时不能开始这条主线。", context.request_id, operation_id)
        except MainlineAlreadyRunningError:
            return CommandResult(False, "MAINLINE_ALREADY_RUNNING", "这条主线关卡已经在进行中，请先领取当前关卡结果。", context.request_id, operation_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能开始主线。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于其他主线操作，请重新发起。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        return CommandResult(
            True,
            "MAINLINE_STARTED",
            (
                f"## 主线已开始 · {record.label}\n\n"
                f"**{self._display_name(record.player)}**，你已开始第 **{record.stage}** 关。\n\n"
                f"- **章节**：第 {record.chapter} 章\n"
                f"- **状态**：进行中\n"
                f"- **剧情**：{record.description}\n\n"
                "> 当前关卡为自动结算内容，发送 `领取主线奖励 {record.stage}` 完成结算。"
            ),
            context.request_id,
            operation_id,
            data={"stage_key": record.stage_key, "chapter": record.chapter, "stage": record.stage, "first_clear": record.first_clear, "idempotent_replay": record.already_completed},
        )

    async def claim_reward(self, context: CommandContext) -> CommandResult:
        stage_key = self._stage_key(context.command_args)
        if stage_key is None:
            return CommandResult(False, "INVALID_MAINLINE_COMMAND", "请使用 `领取主线奖励 1`、`领取主线奖励 2` 或 `领取主线奖励 3`。", context.request_id)
        operation_id = self._operation_id(context, "mainline.claim_first_clear")
        try:
            record = await self.repository.claim_mainline(
                platform=context.adapter,
                platform_user_id=context.user_id,
                stage_key=stage_key,
                operation_id=operation_id,
            )
        except MainlineContentClosedError:
            return CommandResult(False, "CONTENT_CLOSED", "这条主线关卡尚未开放，当前不会发放奖励。", context.request_id, operation_id)
        except MainlineNotStartedError:
            return CommandResult(False, "MAINLINE_NOT_STARTED", "请先发送 `开始主线 序号`，再领取当前关卡奖励。", context.request_id, operation_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能领取主线奖励。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于其他主线领取，请重新发起。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        reward_kind = "首通奖励" if record.first_clear else "重试奖励"
        return CommandResult(
            True,
            "MAINLINE_REWARD_CLAIMED",
            (
                f"## 主线结算完成 · {record.label}\n\n"
                f"**{self._display_name(record.player)}**完成了第 **{record.stage}** 关，获得 **{reward_kind}**。\n\n"
                f"- **获得**：{self._reward_text(record.reward)}\n\n"
                "> 首通解锁不会重复发放；再次挑战需重新发送 `开始主线 序号`。"
            ),
            context.request_id,
            operation_id,
            data={"stage_key": record.stage_key, "chapter": record.chapter, "stage": record.stage, "reward": record.reward, "first_clear": record.first_clear, "idempotent_replay": record.already_completed},
        )


MainlineApplication = AdventuresMainlineApplication


__all__ = ["AdventuresMainlineApplication", "MainlineApplication"]
