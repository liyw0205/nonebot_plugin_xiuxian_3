"""Application commands for fixed cross-realm trades."""

from __future__ import annotations

from ...contracts import CommandContext, CommandResult
from ..repository import (
    CrossRealmTradeCurrencyInsufficientError,
    CrossRealmTradeInputInsufficientError,
    CrossRealmTradePermissionDeniedError,
    OperationConflictError,
    PlayerNotFoundError,
    PlayerSuspendedError,
    RepositoryBusyError,
    SQLitePlayerRepository,
    TradeWeeklyCapError,
)
from .cross_realm_trade_rules import resolve_trade, trade_definition


class CrossRealmTradeApplication:
    """Translate fixed trade transactions into adapter-neutral results."""

    ITEM_LABELS = {
        "item.material.cloud_iron": "云铁",
        "item.herb.spirit_leaf": "灵叶",
        "item.demon_core": "魔核",
        "item.beast_blood": "妖血",
        "item.soul_crystal": "神魂晶",
    }
    FACTION_LABELS = {"demon": "魔", "beast": "妖", "xuantian": "玄天"}

    def __init__(self, repository: SQLitePlayerRepository):
        self.repository = repository

    @staticmethod
    def _operation_id(context: CommandContext) -> str:
        if context.operation_id:
            return context.operation_id
        key = context.message_id or context.request_id
        return f"economy.cross_realm_trade:{context.adapter}:{context.user_id}:{key}"

    @classmethod
    def _items_text(cls, items: dict[str, int]) -> str:
        return "、".join(f"{cls.ITEM_LABELS.get(key, key)} ×{amount}" for key, amount in items.items())

    async def execute(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 1:
            return CommandResult(
                False,
                "INVALID_TRADE_COMMAND",
                "请使用 `跨界贸易 云铁换魔核`。",
                context.request_id,
            )
        trade_key = resolve_trade(context.command_args[0])
        if trade_key is None:
            return CommandResult(False, "TRADE_NOT_FOUND", "当前没有这条固定跨界贸易。", context.request_id)
        definition = trade_definition(trade_key)
        operation_id = self._operation_id(context)
        try:
            record = await self.repository.execute_cross_realm_trade(
                platform=context.adapter,
                platform_user_id=context.user_id,
                trade_key=trade_key,
                operation_id=operation_id,
            )
        except CrossRealmTradePermissionDeniedError:
            return CommandResult(
                False,
                "CROSS_REALM_TRADE_PERMISSION_DENIED",
                f"需在对应三界贸易地点且{self.FACTION_LABELS.get(definition.required_faction, definition.required_faction)}界声望达到 {definition.required_reputation} 才能进行这条贸易，未扣除任何资源。",
                context.request_id,
                operation_id,
            )
        except TradeWeeklyCapError:
            return CommandResult(
                False,
                "TRADE_WEEKLY_CAP",
                "这条贸易本周已达到每角色 5 次上限，未扣除任何资源。",
                context.request_id,
                operation_id,
            )
        except CrossRealmTradeInputInsufficientError:
            return CommandResult(False, "TRADE_INPUT_INSUFFICIENT", f"贸易材料不足，需要 {self._items_text(definition.input_items)}，未扣除灵石。", context.request_id, operation_id)
        except CrossRealmTradeCurrencyInsufficientError:
            return CommandResult(False, "BALANCE_INSUFFICIENT", f"灵石不足，需要 {definition.currency_cost} 灵石，未扣除贸易材料。", context.request_id, operation_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能进行跨界贸易。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "LEDGER_CONFLICT", "这次请求编号已经用于其他贸易操作。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        return CommandResult(
            True,
            "CROSS_REALM_TRADE_COMPLETED",
            (
                f"## {definition.label}已完成\n\n"
                f"- **消耗**：{self._items_text(record.input_items)}、灵石 ×{record.currency_cost}\n"
                f"- **获得**：{self._items_text(record.output_items)}（绑定至 "
                f"{record.binding_expires_at}）\n"
                f"- **本周次数**：已完成，周起始日 {record.week_start}\n\n"
                "> 重复请求不会重复扣除输入。"
            ),
            context.request_id,
            operation_id,
            data={
                "trade_id": record.trade_id,
                "trade_key": record.trade_key,
                "status": record.status,
                "week_start": record.week_start,
                "location_key": record.location_key,
                "input_items": record.input_items,
                "currency_cost": record.currency_cost,
                "output_items": record.output_items,
                "binding_expires_at": record.binding_expires_at,
                "content_version": record.content_version,
                "rule_version": record.rule_version,
                "idempotent_replay": record.already_completed,
            },
        )


__all__ = ["CrossRealmTradeApplication"]
