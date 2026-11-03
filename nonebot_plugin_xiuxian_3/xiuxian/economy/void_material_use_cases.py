"""Application commands for 虚空物资寄售 (``market.void_material``)."""

from __future__ import annotations

from ...contracts import CommandAction, CommandContext, CommandResult
from ..content import ContentBundle, bundled_content
from ..repository import (
    OperationConflictError,
    PlayerNotFoundError,
    PlayerSuspendedError,
    RepositoryBusyError,
    SQLitePlayerRepository,
    VoidMaterialAdmissionError,
    VoidMaterialFundsError,
    VoidMaterialLimitError,
    VoidMaterialNotFoundError,
    VoidMaterialOwnListingError,
    VoidMaterialStateError,
    VoidMaterialStockError,
)
from ..utils.text import command_link

BOARD_COMMAND = "虚空寄售"
LIST_COMMAND = "寄售物资"
BUY_COMMAND = "购入寄售"
CANCEL_COMMAND = "撤下寄售"


class VoidMaterialApplication:
    """Translate consignment-market commands into adapter-neutral results."""

    def __init__(self, repository: SQLitePlayerRepository):
        self.repository = repository

    def _content(self) -> ContentBundle:
        content = getattr(self.repository, "content", None)
        return content if content is not None else bundled_content()

    def _label(self, kind: str, key: str) -> str:
        try:
            return str(self._content().label(kind, key))
        except KeyError:
            return key

    @staticmethod
    def _operation_id(context: CommandContext, suffix: str) -> str:
        if context.operation_id:
            return context.operation_id
        key = context.message_id or context.request_id
        return f"economy.void_material.{suffix}:{context.adapter}:{context.user_id}:{key}"

    def _admission_text(self, record) -> str:
        return (
            f"炼虚 L{record.admission_layer} 或 {record.admission_merit} 虚空功勋"
        )

    async def board(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(
                False, "INVALID_VOID_MARKET_COMMAND", "虚空寄售不带参数。", context.request_id
            )
        try:
            record = await self.repository.void_material_board(
                platform=context.adapter, platform_user_id=context.user_id
            )
        except PlayerNotFoundError:
            return CommandResult(
                False, "PLAYER_NOT_FOUND", "尚未登记，先发送“开始修仙”。", context.request_id
            )
        except RepositoryBusyError:
            return CommandResult(
                False, "REPOSITORY_BUSY", "仓储繁忙，请稍后再试。", context.request_id, retryable=True
            )
        lines = [f"## {record.name}", "", f"> {record.description}", ""]
        lines.append(f"- **准入**：{self._admission_text(record)}")
        if not record.qualified:
            lines.append(f"- **尚缺**：{'、'.join(record.missing)}")
        lines.append(
            f"- **规则**：挂单 {record.listing_hours} 小时，成交手续费 {record.fee_bp / 100:.0f}%，"
            f"同时最多 {record.max_listings} 单（当前 {record.own_listings} 单）"
        )
        if record.allowed_item_keys:
            lines.append(
                "- **可寄售**："
                + "、".join(self._label("item", key) for key in record.allowed_item_keys)
            )
        lines.append("")
        if not record.listings:
            lines.append("当前没有在售物资。")
        else:
            lines.append("**在售**")
            for index, listing in enumerate(record.listings, start=1):
                lines.append(
                    f"- {index}. **{listing.item_label}** ×{listing.quantity} · "
                    f"单价 {listing.unit_price} 灵石 · 卖家 {listing.seller_label} · "
                    f"止于 {listing.expires_at}"
                )
        actions: tuple[CommandAction, ...] = ()
        if record.qualified and record.listings:
            first = record.listings[0]
            lines.append("")
            lines.append(
                f"> 点{command_link(BUY_COMMAND, f'{BUY_COMMAND} 1')}可买下第一单，"
                "或直接发送 `购入寄售 <序号>`。"
            )
            actions = (CommandAction("购入第一单", f"{BUY_COMMAND} 1"),)
        elif record.qualified:
            lines.append("")
            # Keep the nested quotes distinct: Python 3.11 rejects a same-quote
            # nested f-string inside an f-string expression.
            sample_label = self._label("item", record.allowed_item_keys[0])
            sample_command = f"{LIST_COMMAND} {sample_label} 1 100"
            lines.append(
                f"> 用{command_link(LIST_COMMAND, sample_command)} 挂出第一单。"
            )
        return CommandResult(
            True,
            "VOID_MATERIAL_BOARD",
            "\n".join(lines),
            context.request_id,
            data={
                "qualified": record.qualified,
                "missing": list(record.missing),
                "fee_bp": record.fee_bp,
                "listing_hours": record.listing_hours,
                "max_listings": record.max_listings,
                "own_listings": record.own_listings,
                "listings": [
                    {
                        "listing_id": item.listing_id,
                        "item_key": item.item_key,
                        "quantity": item.quantity,
                        "unit_price": item.unit_price,
                        "seller": item.seller_label,
                        "expires_at": item.expires_at,
                    }
                    for item in record.listings
                ],
            },
            actions=actions,
        )

    async def list_item(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 3:
            return CommandResult(
                False,
                "INVALID_VOID_MARKET_COMMAND",
                "用法：寄售物资 <物品> <数量> <单价>，例如“寄售物资 空青晶 2 100”。",
                context.request_id,
            )
        item_text, quantity_text, price_text = context.command_args
        try:
            quantity = int(quantity_text)
            unit_price = int(price_text)
        except ValueError:
            return CommandResult(
                False, "INVALID_VOID_MARKET_COMMAND", "数量与单价必须是整数。", context.request_id
            )
        item_key = self._resolve_item(item_text)
        if item_key is None:
            return CommandResult(
                False, "VOID_MARKET_ITEM_FORBIDDEN", "这不是可寄售的虚空物资。", context.request_id
            )
        try:
            record = await self.repository.list_void_material(
                platform=context.adapter,
                platform_user_id=context.user_id,
                item_key=item_key,
                quantity=quantity,
                unit_price=unit_price,
                operation_id=self._operation_id(context, "list"),
            )
        except PlayerNotFoundError:
            return CommandResult(
                False, "PLAYER_NOT_FOUND", "尚未登记，先发送“开始修仙”。", context.request_id
            )
        except PlayerSuspendedError:
            return CommandResult(
                False, "PLAYER_SUSPENDED", "当前状态不允许寄售。", context.request_id
            )
        except VoidMaterialAdmissionError:
            return CommandResult(
                False,
                "VOID_MARKET_ADMISSION",
                "需炼虚 L1 或 500 虚空功勋才能寄售。",
                context.request_id,
            )
        except VoidMaterialStateError:
            return CommandResult(
                False, "VOID_MARKET_ITEM_FORBIDDEN", "该物品不可寄售。", context.request_id
            )
        except VoidMaterialLimitError:
            return CommandResult(
                False, "VOID_MARKET_LIMIT", "同时挂单已达上限。", context.request_id
            )
        except VoidMaterialStockError:
            return CommandResult(
                False, "VOID_MARKET_NOT_ENOUGH_ITEMS", "背包中的数量不足。", context.request_id
            )
        except OperationConflictError:
            return CommandResult(
                False, "LEDGER_CONFLICT", "同一条指令的输入不一致，已拒绝。", context.request_id
            )
        except RepositoryBusyError:
            return CommandResult(
                False, "REPOSITORY_BUSY", "仓储繁忙，请稍后再试。", context.request_id, retryable=True
            )
        return CommandResult(
            True,
            "VOID_MATERIAL_LISTED",
            "\n".join(
                [
                    f"## {record.item_label}",
                    "",
                    f"已寄售 {record.quantity} 件，单价 {record.unit_price} 灵石，"
                    f"止于 {record.expires_at}。",
                    "",
                    "> 寄售期间物资已被锁定，售出或撤下前不可使用。",
                ]
            ),
            context.request_id,
            data={
                "listing_id": record.listing_id,
                "item_key": record.item_key,
                "quantity": record.quantity,
                "unit_price": record.unit_price,
                "expires_at": record.expires_at,
            },
            actions=(CommandAction("查看寄售", BOARD_COMMAND),),
        )

    async def buy(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 1:
            return CommandResult(
                False, "INVALID_VOID_MARKET_COMMAND", "用法：购入寄售 <序号>。", context.request_id
            )
        try:
            index = int(context.command_args[0])
        except ValueError:
            return CommandResult(
                False, "INVALID_VOID_MARKET_COMMAND", "序号必须是整数。", context.request_id
            )
        try:
            board = await self.repository.void_material_board(
                platform=context.adapter, platform_user_id=context.user_id
            )
        except PlayerNotFoundError:
            return CommandResult(
                False, "PLAYER_NOT_FOUND", "尚未登记，先发送“开始修仙”。", context.request_id
            )
        if index < 1 or index > len(board.listings):
            return CommandResult(
                False, "VOID_MARKET_NOT_FOUND", "没有这一单。", context.request_id
            )
        listing = board.listings[index - 1]
        try:
            trade = await self.repository.buy_void_material(
                platform=context.adapter,
                platform_user_id=context.user_id,
                listing_id=listing.listing_id,
                operation_id=self._operation_id(context, "buy"),
            )
        except VoidMaterialOwnListingError:
            return CommandResult(
                False, "VOID_MARKET_OWN_LISTING", "不能买下自己的寄售。", context.request_id
            )
        except VoidMaterialFundsError:
            return CommandResult(
                False, "VOID_MARKET_INSUFFICIENT", "灵石不足。", context.request_id
            )
        except VoidMaterialNotFoundError:
            return CommandResult(
                False, "VOID_MARKET_NOT_FOUND", "这一单已结束。", context.request_id
            )
        except OperationConflictError:
            return CommandResult(
                False, "LEDGER_CONFLICT", "同一条指令的输入不一致，已拒绝。", context.request_id
            )
        except RepositoryBusyError:
            return CommandResult(
                False, "REPOSITORY_BUSY", "仓储繁忙，请稍后再试。", context.request_id, retryable=True
            )
        return CommandResult(
            True,
            "VOID_MATERIAL_BOUGHT",
            "\n".join(
                [
                    "## 成交",
                    "",
                    f"买下 {self._label('item', trade.item_key)} ×{trade.quantity}，"
                    f"付 {trade.gross} 灵石；卖家净得 {trade.net}（手续费 {trade.fee}）。",
                ]
            ),
            context.request_id,
            data={
                "trade_id": trade.trade_id,
                "item_key": trade.item_key,
                "quantity": trade.quantity,
                "gross": trade.gross,
                "fee": trade.fee,
                "net": trade.net,
                "already_completed": trade.already_completed,
            },
            actions=(CommandAction("查看寄售", BOARD_COMMAND),),
        )

    async def cancel(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 1:
            return CommandResult(
                False, "INVALID_VOID_MARKET_COMMAND", "用法：撤下寄售 <序号>。", context.request_id
            )
        try:
            index = int(context.command_args[0])
        except ValueError:
            return CommandResult(
                False, "INVALID_VOID_MARKET_COMMAND", "序号必须是整数。", context.request_id
            )
        try:
            board = await self.repository.void_material_board(
                platform=context.adapter, platform_user_id=context.user_id
            )
        except PlayerNotFoundError:
            return CommandResult(
                False, "PLAYER_NOT_FOUND", "尚未登记，先发送“开始修仙”。", context.request_id
            )
        if index < 1 or index > len(board.listings):
            return CommandResult(
                False, "VOID_MARKET_NOT_FOUND", "没有这一单。", context.request_id
            )
        listing = board.listings[index - 1]
        try:
            record = await self.repository.cancel_void_material(
                platform=context.adapter,
                platform_user_id=context.user_id,
                listing_id=listing.listing_id,
                operation_id=self._operation_id(context, "cancel"),
            )
        except VoidMaterialNotFoundError:
            return CommandResult(
                False, "VOID_MARKET_STATE", "只有自己的在售单可以撤下。", context.request_id
            )
        except OperationConflictError:
            return CommandResult(
                False, "LEDGER_CONFLICT", "同一条指令的输入不一致，已拒绝。", context.request_id
            )
        except RepositoryBusyError:
            return CommandResult(
                False, "REPOSITORY_BUSY", "仓储繁忙，请稍后再试。", context.request_id, retryable=True
            )
        return CommandResult(
            True,
            "VOID_MATERIAL_CANCELLED",
            "\n".join(
                [
                    f"## {record.item_label}",
                    "",
                    f"已撤下，{record.quantity} 件退回背包。",
                ]
            ),
            context.request_id,
            data={
                "listing_id": record.listing_id,
                "item_key": record.item_key,
                "quantity": record.quantity,
            },
            actions=(CommandAction("查看寄售", BOARD_COMMAND),),
        )

    def _resolve_item(self, value: str) -> str | None:
        content = self._content()
        if content.get("item", value, include_locked=False) is not None:
            return value
        for item_key in content.list("item", include_locked=False):
            key = str(item_key.get("key", ""))
            if not key:
                continue
            label = str(item_key.get("name", ""))
            aliases = item_key.get("aliases") or []
            if value == label or value in aliases:
                return key
        return None