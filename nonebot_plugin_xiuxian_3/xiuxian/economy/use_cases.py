"""Adapter-neutral commands for the fixed-price player market."""

from __future__ import annotations

from ...contracts import CommandContext, CommandResult
from ..repository import (
    BalanceInsufficientError,
    MarketBuyerCapacityInsufficientError,
    MarketItemForbiddenError,
    MarketItemLockedError,
    MarketOrderAlreadySettledError,
    MarketOrderExpiredError,
    MarketOrderLimitError,
    MarketOrderNotFoundError,
    MarketOrderNotListedError,
    MarketPriceInvalidError,
    MarketSelfTradeError,
    OperationConflictError,
    PlayerNotFoundError,
    PlayerSuspendedError,
    RepositoryBusyError,
    SQLitePlayerRepository,
)
from .rules import resolve_market_item


class EconomyApplication:
    """Translate market transitions into shared command results."""

    def __init__(self, repository: SQLitePlayerRepository):
        self.repository = repository

    @staticmethod
    def _operation_id(context: CommandContext, name: str) -> str:
        if context.operation_id:
            return context.operation_id
        key = context.message_id or context.request_id
        return f"{name}:{context.adapter}:{context.user_id}:{key}"

    @staticmethod
    def _parse_int(value: str) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _item_label(item_key: str) -> str:
        try:
            return resolve_market_item(item_key).label
        except ValueError:
            return item_key

    @staticmethod
    def _data(record, *, idempotent: bool | None = None) -> dict[str, object]:
        return {
            "order_id": record.order_id,
            "status": record.status,
            "seller_player_id": record.seller_player_id,
            "seller_platform_user_id": record.seller_platform_user_id,
            "seller_dao_name": record.seller_dao_name,
            "buyer_player_id": record.buyer_player_id,
            "buyer_platform_user_id": record.buyer_platform_user_id,
            "item_key": record.item_key,
            "item_label": EconomyApplication._item_label(record.item_key),
            "quantity": record.quantity,
            "remaining_quantity": record.remaining_quantity,
            "unit_price": record.unit_price,
            "listing_fee": record.listing_fee,
            "trade_fee": record.trade_fee,
            "total_price": record.total_price,
            "expires_at": record.expires_at,
            "idempotent_replay": record.already_completed if idempotent is None else idempotent,
        }

    @staticmethod
    def _record_result(context: CommandContext, operation_id: str, code: str, message: str, record) -> CommandResult:
        return CommandResult(True, code, message, context.request_id, operation_id, data=EconomyApplication._data(record))

    @staticmethod
    def _error(context: CommandContext, operation_id: str, exc: Exception) -> CommandResult:
        messages = {
            MarketItemForbiddenError: ("MARKET_ITEM_FORBIDDEN", "该物品不可交易。"),
            MarketPriceInvalidError: ("PRICE_OUT_OF_RANGE", "数量需为 1-99，单价需为 1-100000 灵石。"),
            MarketItemLockedError: ("MARKET_ITEM_LOCKED", "物品不足或已被其他订单锁定。"),
            BalanceInsufficientError: ("BALANCE_INSUFFICIENT", "灵石余额不足。"),
            MarketOrderLimitError: ("MARKET_ORDER_LIMIT", "同时上架订单不能超过 10 单。"),
            MarketOrderNotFoundError: ("ORDER_NOT_FOUND", "摆摊订单不存在。"),
            MarketOrderExpiredError: ("MARKET_ORDER_EXPIRED", "摆摊订单已过期。"),
            MarketOrderAlreadySettledError: ("ORDER_ALREADY_SETTLED", "摆摊订单已经完成或关闭。"),
            MarketOrderNotListedError: ("MARKET_ORDER_NOT_LISTED", "摆摊订单当前不可操作。"),
            MarketBuyerCapacityInsufficientError: ("MARKET_BUYER_CAPACITY_INSUFFICIENT", "背包容量不足，未发生成交。"),
            MarketSelfTradeError: ("MARKET_SELF_TRADE", "不能购买自己的摆摊订单。"),
            PlayerNotFoundError: ("PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。"),
            PlayerSuspendedError: ("PLAYER_SUSPENDED", "当前角色暂时不能操作经济功能。"),
            OperationConflictError: ("LEDGER_CONFLICT", "这次请求编号已经用于其他经济操作。"),
        }
        code, message = messages.get(type(exc), ("PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。"))
        return CommandResult(False, code, message, context.request_id, operation_id, retryable=isinstance(exc, RepositoryBusyError))

    async def create_market_order(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 3:
            return CommandResult(False, "INVALID_MARKET_COMMAND", "请使用 `发布摆摊 物品 数量 单价`。", context.request_id)
        item_key, quantity, unit_price = context.command_args
        quantity_value = self._parse_int(quantity)
        price_value = self._parse_int(unit_price)
        if quantity_value is None or price_value is None:
            return CommandResult(False, "PRICE_OUT_OF_RANGE", "数量和单价必须是整数。", context.request_id)
        operation_id = self._operation_id(context, "economy.create_market_order")
        try:
            record = await self.repository.create_market_order(
                platform=context.adapter, platform_user_id=context.user_id, item_key=item_key,
                quantity=quantity_value, unit_price=price_value, operation_id=operation_id,
            )
        except (RepositoryBusyError, Exception) as exc:
            if not isinstance(exc, (RepositoryBusyError, MarketItemForbiddenError, MarketPriceInvalidError, MarketItemLockedError, BalanceInsufficientError, MarketOrderLimitError, PlayerNotFoundError, PlayerSuspendedError, OperationConflictError)):
                return self._error(context, operation_id, exc)
            return self._error(context, operation_id, exc)
        return self._record_result(context, operation_id, "MARKET_ORDER_CREATED", f"## 摆摊已发布\n\n{self._item_label(record.item_key)} × {record.quantity}，单价 {record.unit_price} 灵石。\n\n- **订单号**：`{record.order_id}`\n- **上架费**：{record.listing_fee} 灵石（已回收）\n- **有效至**：{record.expires_at}", record)

    async def buy_market_order(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) not in {1, 2}:
            return CommandResult(False, "INVALID_MARKET_COMMAND", "请使用 `购买摆摊 订单号 [数量]`。", context.request_id)
        order_id = context.command_args[0]
        quantity = None if len(context.command_args) == 1 else self._parse_int(context.command_args[1])
        if len(context.command_args) == 2 and quantity is None:
            return CommandResult(False, "PRICE_OUT_OF_RANGE", "购买数量必须是整数。", context.request_id)
        operation_id = self._operation_id(context, "economy.buy_market_order")
        try:
            record = await self.repository.buy_market_order(platform=context.adapter, platform_user_id=context.user_id, order_id=order_id, quantity=quantity, operation_id=operation_id)
        except Exception as exc:
            return self._error(context, operation_id, exc)
        return self._record_result(context, operation_id, "MARKET_ORDER_PURCHASED", f"## 摆摊成交\n\n你购买了 {self._item_label(record.item_key)} × {record.quantity - record.remaining_quantity}。\n\n- **订单号**：`{record.order_id}`\n- **订单状态**：{record.status}\n- **剩余数量**：{record.remaining_quantity}", record)

    async def cancel_market_order(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 1:
            return CommandResult(False, "INVALID_MARKET_COMMAND", "请使用 `取消摆摊 订单号`。", context.request_id)
        operation_id = self._operation_id(context, "economy.cancel_market_order")
        try:
            record = await self.repository.cancel_market_order(platform=context.adapter, platform_user_id=context.user_id, order_id=context.command_args[0], operation_id=operation_id)
        except Exception as exc:
            return self._error(context, operation_id, exc)
        return self._record_result(context, operation_id, "MARKET_ORDER_CANCELLED", f"## 摆摊已取消\n\n订单 `{record.order_id}` 已取消，物品锁已释放，上架费不退。", record)

    async def expire_market_order(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 1:
            return CommandResult(False, "INVALID_MARKET_COMMAND", "请使用 `清理摆摊 订单号`。", context.request_id)
        operation_id = self._operation_id(context, "economy.expire_market_order")
        try:
            record = await self.repository.expire_market_order(platform=context.adapter, platform_user_id=context.user_id, order_id=context.command_args[0], operation_id=operation_id)
        except Exception as exc:
            return self._error(context, operation_id, exc)
        return self._record_result(context, operation_id, "MARKET_ORDER_EXPIRED", f"## 摆摊已过期\n\n订单 `{record.order_id}` 已关闭，物品锁已释放。", record)

    async def list_market_orders(self, context: CommandContext) -> CommandResult:
        try:
            records = await self.repository.list_market_orders(platform=context.adapter, platform_user_id=context.user_id)
        except Exception as exc:
            return self._error(context, "", exc)
        if not records:
            return CommandResult(True, "MARKET_LIST_EMPTY", "当前没有可购买的摆摊订单。", context.request_id, data={"orders": []})
        lines = ["## 摆摊列表", ""]
        data = []
        for record in records:
            lines.append(f"- `{record.order_id}` {self._item_label(record.item_key)} × {record.remaining_quantity}，单价 {record.unit_price}，摊主 {record.seller_dao_name}")
            data.append(self._data(record))
        return CommandResult(True, "MARKET_LISTED", "\n".join(lines), context.request_id, data={"orders": data})


__all__ = ["EconomyApplication"]
