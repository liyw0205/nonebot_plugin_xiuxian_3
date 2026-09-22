"""Application services for residence leasing and inspection."""

from __future__ import annotations

from ...contracts import CommandContext, CommandResult
from ..repository import (
    CurrencyInsufficientError,
    OperationConflictError,
    PlayerNotFoundError,
    PlayerStageConflictError,
    PlayerSuspendedError,
    RepositoryBusyError,
    ResidenceAlreadyActiveError,
    ResidenceContentClosedError,
    ResidenceNotFoundError,
    SQLitePlayerRepository,
)
from .rules import residence_definition


class LivelihoodApplication:
    """Coordinate the first residence commands."""

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
        return value.replace("\\", "\\\\").replace("`", "\\`").replace("*", "\\*").replace("_", "\\_").replace("~", "\\~")

    @staticmethod
    def _resolve_args(args: tuple[str, ...]) -> str | None:
        if len(args) > 1:
            return None
        try:
            return residence_definition(args[0] if args else None).key
        except ValueError:
            return None

    async def lease(self, context: CommandContext) -> CommandResult:
        key = self._resolve_args(context.command_args)
        if key is None:
            return CommandResult(False, "INVALID_RESIDENCE", "可用 `租住居所` 或 `租住居所 客房`。", context.request_id)
        operation_id = self._operation_id(context, "livelihood.lease_residence")
        try:
            record = await self.repository.lease_residence(
                platform=context.adapter,
                platform_user_id=context.user_id,
                residence_key=key,
                operation_id=operation_id,
            )
        except ResidenceContentClosedError:
            return CommandResult(False, "LIVELIHOOD_CONTENT_CLOSED", "该居所暂未开放。", context.request_id, operation_id)
        except ResidenceAlreadyActiveError:
            return CommandResult(False, "RESIDENCE_ALREADY_ACTIVE", "你已经有一处有效居所。", context.request_id, operation_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except PlayerStageConflictError:
            return CommandResult(False, "PLAYER_STAGE_CONFLICT", "当前阶段还不能租住居所。", context.request_id, operation_id)
        except CurrencyInsufficientError:
            return CommandResult(False, "CURRENCY_INSUFFICIENT", "灵石不足，无法支付租金。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能租住居所。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于其他居所操作，请重新发起。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        definition = residence_definition(record.residence_key)
        return CommandResult(
            True,
            "RESIDENCE_LEASED",
            (
                "## 居所已登记\n\n"
                f"**{self._display_name(record.player)}**租下了{definition.label}。\n\n"
                f"- **租金**：灵石 {record.rent_cost}\n"
                f"- **有效至**：{record.ends_at}\n"
                "- **用途**：可进行静养闭关与后续居所经营\n\n"
                "> 居所到期后不能开启新的居所玩法；已有快照按原规则结算。"
            ),
            context.request_id,
            operation_id,
            data={"residence_id": record.residence_id, "residence_key": record.residence_key, "status": record.status, "ends_at": record.ends_at, "rent_cost": record.rent_cost, "idempotent_replay": record.already_completed},
        )

    async def get_profile(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_RESIDENCE_COMMAND", "查看居所无需附加参数。", context.request_id)
        try:
            record = await self.repository.get_residence(platform=context.adapter, platform_user_id=context.user_id)
        except ResidenceNotFoundError:
            return CommandResult(False, "RESIDENCE_NOT_FOUND", "你还没有居所，请先发送 `租住居所`。", context.request_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能查看居所。", context.request_id)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, retryable=True)
        definition = residence_definition(record.residence_key)
        return CommandResult(
            True,
            "RESIDENCE_PROFILE",
            f"## 我的居所\n\n**{self._display_name(record.player)}**当前居住在{definition.label}。\n\n- **状态**：{record.status}\n- **有效至**：{record.ends_at}\n- **静养闭关**：可用",
            context.request_id,
            data={"residence_id": record.residence_id, "residence_key": record.residence_key, "status": record.status, "ends_at": record.ends_at},
        )


__all__ = ["LivelihoodApplication"]
