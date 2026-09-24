"""Commands for the v0.6 dao echoes mainline."""

from __future__ import annotations

from ...contracts import CommandContext, CommandResult
from ..persistence.errors import (
    MainlineAlreadyRunningError,
    MainlineContentClosedError,
    MainlineNotStartedError,
    MainlineRequirementError,
    OperationConflictError,
    PlayerNotFoundError,
    PlayerSuspendedError,
    RepositoryBusyError,
)
from ..repository import SQLitePlayerRepository
from .dao_echoes import DAO_ECHOES_LANE_LABELS, dao_echoes_definition, resolve_dao_echoes_lane


class DaoEchoesApplication:
    def __init__(self, repository: SQLitePlayerRepository):
        self.repository = repository

    @staticmethod
    def _operation_id(context: CommandContext, operation_name: str) -> str:
        if context.operation_id:
            return context.operation_id
        request_key = context.message_id or context.request_id
        return f"{operation_name}:{context.adapter}:{context.user_id}:{request_key}"

    @staticmethod
    def _args(context: CommandContext) -> tuple[str, int] | None:
        if len(context.command_args) != 2:
            return None
        lane = resolve_dao_echoes_lane(context.command_args[0])
        try:
            definition = dao_echoes_definition(lane or "", context.command_args[1])
        except ValueError:
            return None
        return definition.lane, definition.stage

    async def get_status(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_DAO_ECHOES_COMMAND", "查看道源主线无需附加参数。", context.request_id)
        try:
            record = await self.repository.get_dao_echoes_status(
                platform=context.adapter,
                platform_user_id=context.user_id,
            )
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能查看道源主线。", context.request_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, retryable=True)
        lines = ["## 三界回响", ""]
        lanes: list[dict[str, object]] = []
        for item in record.lanes:
            next_text = f"，下一关 {item.next_stage:02d}" if item.next_stage is not None else "，本线已完成"
            lines.append(f"- **{DAO_ECHOES_LANE_LABELS[item.lane]}**：{item.completed}/{item.total}{next_text}")
            lanes.append(
                {
                    "lane": item.lane,
                    "label": DAO_ECHOES_LANE_LABELS[item.lane],
                    "completed": item.completed,
                    "total": item.total,
                    "next_stage": item.next_stage,
                }
            )
        lines.extend(
            [
                "",
                "> 使用 `开始道源主线 建设者|见证者|远行者 序号` 开始一关，完成后领取对应奖励。",
            ]
        )
        return CommandResult(
            True,
            "DAO_ECHOES_STATUS",
            "\n".join(lines),
            context.request_id,
            data={
                "story_key": "story.mainline.dao_echoes",
                "lanes": lanes,
                "stages": [
                    {
                        "key": stage.key,
                        "chapter": stage.chapter,
                        "stage": stage.stage,
                        "label": stage.label,
                        "status": stage.status,
                        "claimed": stage.claimed,
                    }
                    for stage in record.stages
                ],
            },
        )

    async def start_stage(self, context: CommandContext) -> CommandResult:
        args = self._args(context)
        if args is None:
            return CommandResult(
                False,
                "INVALID_DAO_ECHOES_COMMAND",
                "请使用 `开始道源主线 建设者|见证者|远行者 序号`。",
                context.request_id,
            )
        lane, stage = args
        operation_id = self._operation_id(context, "dao_echoes.start_stage")
        try:
            record = await self.repository.start_dao_echoes_stage(
                platform=context.adapter,
                platform_user_id=context.user_id,
                lane=lane,
                stage=stage,
                operation_id=operation_id,
            )
        except MainlineContentClosedError:
            return CommandResult(False, "CONTENT_CLOSED", "这条道源主线关卡尚未开放。", context.request_id, operation_id)
        except MainlineRequirementError:
            return CommandResult(False, "DAO_ECHOES_REQUIREMENT_MISSING", "需要炼虚 L10，且先完成本线前一关。", context.request_id, operation_id)
        except MainlineAlreadyRunningError:
            return CommandResult(False, "MAINLINE_ALREADY_RUNNING", "这条关卡已经在进行中，请先领取结果。", context.request_id, operation_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能开始道源主线。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于其他主线操作，请重新发起。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        return CommandResult(
            True,
            "DAO_ECHOES_STAGE_STARTED",
            f"## {record.label}\n\n{record.description}\n\n领取 `领取道源主线奖励 {lane} {stage}` 完成这一关。",
            context.request_id,
            operation_id,
            data={
                "story_key": record.story_key,
                "stage_key": record.stage_key,
                "lane": lane,
                "stage": stage,
                "first_clear": record.first_clear,
                "idempotent_replay": record.already_completed,
            },
        )

    async def claim_reward(self, context: CommandContext) -> CommandResult:
        args = self._args(context)
        if args is None:
            return CommandResult(
                False,
                "INVALID_DAO_ECHOES_COMMAND",
                "请使用 `领取道源主线奖励 建设者|见证者|远行者 序号`。",
                context.request_id,
            )
        lane, stage = args
        operation_id = self._operation_id(context, "dao_echoes.claim_stage")
        try:
            record = await self.repository.claim_dao_echoes_stage(
                platform=context.adapter,
                platform_user_id=context.user_id,
                lane=lane,
                stage=stage,
                operation_id=operation_id,
            )
        except MainlineContentClosedError:
            return CommandResult(False, "CONTENT_CLOSED", "这条道源主线关卡尚未开放。", context.request_id, operation_id)
        except MainlineNotStartedError:
            return CommandResult(False, "MAINLINE_NOT_STARTED", "请先开始这条道源主线关卡。", context.request_id, operation_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能领取道源主线奖励。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于其他主线领取，请重新发起。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        if record.first_clear:
            flag = next(iter(record.reward), "")
            reward_text = f"图鉴旗标 `{flag}`"
        else:
            reward_text = "无额外奖励"
        return CommandResult(
            True,
            "DAO_ECHOES_STAGE_CLAIMED",
            f"## 三界回响已记录 · {record.label}\n\n本关记入故事与档案，获得{reward_text}。",
            context.request_id,
            operation_id,
            data={
                "story_key": record.story_key,
                "stage_key": record.stage_key,
                "lane": lane,
                "stage": stage,
                "first_clear": record.first_clear,
                "reward": record.reward,
                "idempotent_replay": record.already_completed,
            },
        )


__all__ = ["DaoEchoesApplication"]
