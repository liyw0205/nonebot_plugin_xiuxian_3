"""Application services for the v0.1 retreat slice."""

from __future__ import annotations

from ...contracts import CommandContext, CommandResult
from ..repository import (
    OperationConflictError,
    PlayerNotFoundError,
    PlayerStageConflictError,
    PlayerSuspendedError,
    RepositoryBusyError,
    ResourceInsufficientError,
    ResidenceRequiredError,
    RetreatBusyError,
    RetreatContentClosedError,
    RetreatExpiredError,
    RetreatNotFoundError,
    RetreatNotReadyError,
    RetreatAlreadySettledError,
    RetreatDailyLimitError,
    SQLitePlayerRepository,
)
from .rules import RETREAT_BASIC, RETREAT_RESTFUL, retreat_definition


class AdvancementApplication:
    """Coordinate retreat commands without exposing persistence details."""

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
    def _resolve_key(args: tuple[str, ...]) -> str | None:
        if len(args) > 1:
            return None
        try:
            return retreat_definition(args[0] if args else None).key
        except ValueError:
            return None

    async def preview(self, context: CommandContext) -> CommandResult:
        key = self._resolve_key(context.command_args)
        if key is None:
            return CommandResult(False, "INVALID_RETREAT_MODE", "可用 `闭关预览`、`闭关预览 基础` 或 `闭关预览 静养`。", context.request_id)
        definition = retreat_definition(key)
        lines = [
            f"## {definition.label}预览",
            "",
            f"**方式**：{definition.description}",
            f"- **时长**：{definition.duration_seconds // 3600} 小时",
            f"- **精力**：{definition.energy_cost}",
            f"- **每日次数**：{definition.daily_limit}",
        ]
        if definition.required_item:
            lines.append("- **消耗**：粗糙灵米 ×1、基础引气诀权限")
            lines.append("- **收益**：境内修为 80–120（25% / 50% / 25%）")
        else:
            lines.append("- **前置**：有效居所")
            lines.append("- **收益**：精力 +8，不增加修为")
        lines.extend(["", "> 结算最多按 8 小时累计；超过 24 小时请使用 `恢复闭关`。"])
        return CommandResult(True, "RETREAT_PREVIEW", "\n".join(lines), context.request_id, data={"retreat_key": key})

    async def start(self, context: CommandContext) -> CommandResult:
        key = self._resolve_key(context.command_args)
        if key is None:
            return CommandResult(False, "INVALID_RETREAT_MODE", "可用 `开始闭关`、`开始闭关 基础` 或 `开始闭关 静养`。", context.request_id)
        operation_id = self._operation_id(context, "progression.start_retreat")
        try:
            record = await self.repository.start_retreat(
                platform=context.adapter,
                platform_user_id=context.user_id,
                retreat_key=key,
                operation_id=operation_id,
            )
        except RetreatContentClosedError:
            return CommandResult(False, "CONTENT_CLOSED", "该闭关方式尚未开放。", context.request_id, operation_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except PlayerStageConflictError:
            return CommandResult(False, "PLAYER_STAGE_CONFLICT", "完成入道后才能进行基础闭关。", context.request_id, operation_id)
        except ResidenceRequiredError:
            return CommandResult(False, "RESIDENCE_REQUIRED", "静养闭关需要先发送 `租住居所`。", context.request_id, operation_id)
        except RetreatBusyError:
            return CommandResult(False, "RETREAT_BUSY", "当前已有闭关或其他长时会话，请先完成结算。", context.request_id, operation_id)
        except RetreatDailyLimitError:
            return CommandResult(False, "RETREAT_DAILY_LIMIT", "该闭关方式今日次数已用尽。", context.request_id, operation_id)
        except ResourceInsufficientError:
            return CommandResult(False, "RESOURCE_INSUFFICIENT", "精力或闭关所需物资不足。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能进行闭关。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于其他闭关操作，请重新发起。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)

        definition = retreat_definition(record.retreat_key)
        cost = "、".join(f"{key} ×{value}" for key, value in record.item_cost.items()) or "无"
        return CommandResult(
            True,
            "RETREAT_STARTED",
            (
                f"## {definition.label}已开始\n\n"
                f"**{self._display_name(record.player)}**已进入闭关状态。\n\n"
                f"- **精力消耗**：{record.energy_cost}\n"
                f"- **额外消耗**：{cost}\n"
                f"- **预计完成**：{record.ends_at}\n\n"
                "> 完成后发送 `结算闭关`；超过 24 小时请发送 `恢复闭关`。"
            ),
            context.request_id,
            operation_id,
            data={
                "session_id": record.session_id,
                "retreat_key": record.retreat_key,
                "status": record.status,
                "starts_at": record.starts_at,
                "ends_at": record.ends_at,
                "energy_cost": record.energy_cost,
                "item_cost": record.item_cost,
                "idempotent_replay": record.already_completed,
            },
        )

    async def settle(self, context: CommandContext, *, recover: bool = False) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_RETREAT_COMMAND", "闭关结算无需附加参数。", context.request_id)
        operation_name = "progression.recover_retreat" if recover else "progression.settle_retreat"
        operation_id = self._operation_id(context, operation_name)
        try:
            record = await self.repository.settle_retreat(
                platform=context.adapter,
                platform_user_id=context.user_id,
                operation_id=operation_id,
                recover=recover,
            )
        except RetreatNotFoundError:
            return CommandResult(False, "RETREAT_NOT_FOUND", "当前没有可结算的闭关。", context.request_id, operation_id)
        except RetreatNotReadyError:
            return CommandResult(False, "RETREAT_NOT_READY", "闭关尚未完成，请稍后再来。", context.request_id, operation_id)
        except RetreatExpiredError:
            return CommandResult(False, "RETREAT_EXPIRED", "闭关已超过普通结算窗口，请发送 `恢复闭关`。", context.request_id, operation_id)
        except RetreatAlreadySettledError:
            return CommandResult(False, "RETREAT_ALREADY_SETTLED", "这场闭关已经结算过，不能重复领取。", context.request_id, operation_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能结算闭关。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于其他闭关结算，请重新发起。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)

        definition = retreat_definition(record.retreat_key)
        if "cultivation" in record.result:
            result_text = f"境内修为 +{record.result['cultivation']}"
        else:
            result_text = f"精力 +{record.result.get('energy', 0)}（不超过上限）"
        title = "闭关恢复完成" if recover else "闭关结算完成"
        return CommandResult(
            True,
            "RETREAT_RECOVERED" if recover else "RETREAT_SETTLED",
            (
                f"## {title}\n\n"
                f"**{self._display_name(record.player)}**完成{definition.label}。\n\n"
                f"- **获得**：{result_text}\n"
                f"- **累计周期**：{record.cycles}\n"
                f"- **精力**：{record.player.energy}/{record.player.energy_max}\n"
                f"- **境内修为**：{record.player.cultivation}\n\n"
                "> 本次结算依据闭关开始时的快照，重复请求只回放原结果。"
            ),
            context.request_id,
            operation_id,
            data={
                "session_id": record.session_id,
                "retreat_key": record.retreat_key,
                "status": record.status,
                "result": record.result,
                "cycles": record.cycles,
                "expired": record.expired,
                "idempotent_replay": record.already_completed,
            },
        )


__all__ = ["AdvancementApplication"]
