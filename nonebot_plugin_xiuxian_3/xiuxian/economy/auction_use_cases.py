"""Adapter-neutral commands for the limited weekly auction."""

from __future__ import annotations

from ...contracts import CommandContext, CommandResult
from ..repository import (
    AuctionBidTooLowError,
    AuctionItemLockedError,
    AuctionNotFoundError,
    AuctionSelfBidError,
    AuctionSlotFullError,
    AuctionStateConflictError,
    BalanceInsufficientError,
    ItemBindingActiveError,
    MarketItemForbiddenError,
    MarketPriceInvalidError,
    OperationConflictError,
    PlayerNotFoundError,
    PlayerSuspendedError,
    RepositoryBusyError,
    SQLitePlayerRepository,
)
from .auction_models import AuctionRecord
from .rules import resolve_market_item


class AuctionApplication:
    def __init__(self, repository: SQLitePlayerRepository):
        self.repository = repository

    @staticmethod
    def _operation_id(context: CommandContext, name: str) -> str:
        if context.operation_id:
            return context.operation_id
        key = context.message_id or context.request_id
        return f"{name}:{context.adapter}:{context.user_id}:{key}"

    @staticmethod
    def _label(item_key: str) -> str:
        try:
            return resolve_market_item(item_key).label
        except ValueError:
            return item_key

    @classmethod
    def _data(cls, record: AuctionRecord) -> dict[str, object]:
        return {
            "auction_id": record.auction_id,
            "status": record.status,
            "week_start": record.week_start,
            "seller_platform_user_id": record.seller_platform_user_id,
            "seller_dao_name": record.seller_dao_name,
            "item_key": record.item_key,
            "item_label": cls._label(record.item_key),
            "quantity": record.quantity,
            "starting_bid": record.starting_bid,
            "current_bid": record.current_bid,
            "current_bidder_platform_user_id": record.current_bidder_platform_user_id,
            "ends_at": record.ends_at,
            "settlement_deadline": record.settlement_deadline,
            "created_at": record.created_at,
            "idempotent_replay": record.already_completed,
        }

    @classmethod
    def _error(cls, context: CommandContext, operation_id: str, exc: Exception) -> CommandResult:
        mapping = {
            AuctionSlotFullError: ("AUCTION_SLOT_FULL", "本周拍卖槽位已满，未锁定物品。"),
            AuctionBidTooLowError: ("AUCTION_BID_TOO_LOW", "出价不足，下一价至少比当前价高 5%。"),
            AuctionSelfBidError: ("AUCTION_SELF_BID", "不能竞价自己的拍卖。"),
            AuctionNotFoundError: ("AUCTION_NOT_FOUND", "没有找到这条拍卖。"),
            AuctionStateConflictError: ("AUCTION_STATE_CONFLICT", "拍卖当前不允许执行这个操作。"),
            AuctionItemLockedError: ("AUCTION_ITEM_LOCKED", "拍卖物品锁定已失效，未转移资产。"),
            BalanceInsufficientError: ("BALANCE_INSUFFICIENT", "灵石不足，未锁定出价。"),
            ItemBindingActiveError: ("ITEM_BINDING_ACTIVE", "物品仍在绑定期，不能拍卖。"),
            MarketItemForbiddenError: ("MARKET_ITEM_FORBIDDEN", "该物品不能进入拍卖。"),
            MarketPriceInvalidError: ("AUCTION_INPUT_INVALID", "数量或起拍价不合法。"),
            PlayerNotFoundError: ("PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。"),
            PlayerSuspendedError: ("PLAYER_SUSPENDED", "当前角色暂时不能操作拍卖。"),
            OperationConflictError: ("OPERATION_CONFLICT", "这次请求编号已用于其他拍卖操作。"),
            RepositoryBusyError: ("PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。"),
        }
        for error_type, (code, message) in mapping.items():
            if isinstance(exc, error_type):
                return CommandResult(False, code, message, context.request_id, operation_id, retryable=error_type is RepositoryBusyError)
        return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)

    async def create(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 3:
            return CommandResult(False, "INVALID_AUCTION_COMMAND", "请使用 `发布拍卖 物品 数量 起拍价`。", context.request_id)
        try:
            quantity, starting_bid = int(context.command_args[1]), int(context.command_args[2])
        except ValueError:
            return CommandResult(False, "AUCTION_INPUT_INVALID", "数量和起拍价必须是整数。", context.request_id)
        operation_id = self._operation_id(context, "economy.create_auction")
        try:
            record = await self.repository.create_auction(
                platform=context.adapter, platform_user_id=context.user_id,
                item_key=context.command_args[0], quantity=quantity,
                starting_bid=starting_bid, operation_id=operation_id,
            )
        except Exception as exc:
            return self._error(context, operation_id, exc)
        return CommandResult(True, "AUCTION_CREATED", f"## 拍卖已发布\n\n- **拍卖号**：`{record.auction_id}`\n- **物品**：{self._label(record.item_key)} ×{record.quantity}\n- **起拍价**：{record.starting_bid} 灵石\n- **结束时间**：{record.ends_at}", context.request_id, operation_id, data=self._data(record))

    async def list(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_AUCTION_COMMAND", "拍卖列表无需附加参数。", context.request_id)
        try:
            records = await self.repository.list_auctions(platform=context.adapter, platform_user_id=context.user_id)
        except Exception as exc:
            return self._error(context, "", exc)
        data = [self._data(record) for record in records]
        if not records:
            return CommandResult(True, "AUCTION_LIST_EMPTY", "当前没有进行中的拍卖。", context.request_id, data={"auctions": data})
        lines = ["## 本周拍卖", ""]
        for record in records:
            lines.append(f"- `{record.auction_id}` {self._label(record.item_key)} ×{record.quantity}，当前 {record.current_bid or record.starting_bid} 灵石，结束于 {record.ends_at}")
        return CommandResult(True, "AUCTION_LISTED", "\n".join(lines), context.request_id, data={"auctions": data})

    async def bid(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 2:
            return CommandResult(False, "INVALID_AUCTION_COMMAND", "请使用 `竞价 拍卖号 出价`。", context.request_id)
        try:
            amount = int(context.command_args[1])
        except ValueError:
            return CommandResult(False, "AUCTION_INPUT_INVALID", "出价必须是整数。", context.request_id)
        operation_id = self._operation_id(context, "economy.bid_auction")
        try:
            record = await self.repository.bid_auction(platform=context.adapter, platform_user_id=context.user_id, auction_id=context.command_args[0], bid_amount=amount, operation_id=operation_id)
        except Exception as exc:
            return self._error(context, operation_id, exc)
        return CommandResult(True, "AUCTION_BID_PLACED", f"已出价 {record.current_bid} 灵石，拍卖号 `{record.auction_id}`。", context.request_id, operation_id, data=self._data(record))

    async def settle(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 1:
            return CommandResult(False, "INVALID_AUCTION_COMMAND", "请使用 `结算拍卖 拍卖号`。", context.request_id)
        operation_id = self._operation_id(context, "economy.settle_auction")
        try:
            record = await self.repository.settle_auction(platform=context.adapter, platform_user_id=context.user_id, auction_id=context.command_args[0], operation_id=operation_id)
        except Exception as exc:
            return self._error(context, operation_id, exc)
        if record.status == "expired":
            return CommandResult(False, "AUCTION_SETTLEMENT_EXPIRED", "拍卖结算窗口已过，已按流拍处理并释放锁定资产。", context.request_id, operation_id, data=self._data(record))
        if record.status == "unsold":
            message = "拍卖流拍，物品锁定已释放。"
            code = "AUCTION_UNSOLD"
        else:
            message = f"拍卖已成交，成交价 {record.current_bid} 灵石。"
            code = "AUCTION_SETTLED"
        return CommandResult(True, code, message, context.request_id, operation_id, data=self._data(record))


__all__ = ["AuctionApplication"]
