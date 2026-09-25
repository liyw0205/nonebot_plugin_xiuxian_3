"""Adapter-neutral commands for cross-realm purchase orders."""

from __future__ import annotations

from ...contracts import CommandContext, CommandResult
from ..persistence.errors import (
    ItemBindingActiveError,
    OperationConflictError,
    PlayerNotFoundError,
    PlayerSuspendedError,
    PurchaseBuyerCapacityInsufficientError,
    PurchaseDeliveryExpiredError,
    PurchaseEscrowInsufficientError,
    PurchaseItemForbiddenError,
    PurchaseItemLockedError,
    PurchaseOrderCapError,
    PurchaseOrderExpiredError,
    PurchaseOrderNotFoundError,
    PurchaseOrderStateConflictError,
    PurchasePermissionDeniedError,
    PurchaseSelfMatchError,
    RepositoryBusyError,
)
from .purchase_order_models import PurchaseOrderRecord
from .purchase_order_rules import resolve_purchase_item


class PurchaseOrderApplication:
    def __init__(self, repository):
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
            return resolve_purchase_item(item_key).label
        except ValueError:
            return item_key

    @classmethod
    def _data(cls, record: PurchaseOrderRecord) -> dict[str, object]:
        return {
            "order_id": record.order_id,
            "status": record.status,
            "buyer_player_id": record.buyer_player_id,
            "buyer_platform_user_id": record.buyer_platform_user_id,
            "buyer_dao_name": record.buyer_dao_name,
            "buyer_faction": record.buyer_faction,
            "seller_player_id": record.seller_player_id,
            "seller_platform_user_id": record.seller_platform_user_id,
            "seller_dao_name": record.seller_dao_name,
            "seller_faction": record.seller_faction,
            "item_key": record.item_key,
            "item_label": cls._label(record.item_key),
            "quantity": record.quantity,
            "unit_price": record.unit_price,
            "purchase_fee": record.purchase_fee,
            "fee": record.purchase_fee,
            "total_price": record.total_price,
            "escrow_amount": record.escrow_amount,
            "item_region": record.item_region,
            "item_source_location": record.item_source_location,
            "first_binding_expires_at": record.first_binding_expires_at,
            "alliance_key": record.alliance_key,
            "expires_at": record.expires_at,
            "delivery_deadline": record.delivery_deadline,
            "created_at": record.created_at,
            "transition_notice": record.transition_notice,
            "idempotent_replay": record.already_completed,
        }

    @staticmethod
    def _error(context: CommandContext, operation_id: str, exc: Exception) -> CommandResult:
        mapping = {
            PurchaseOrderCapError: ("PURCHASE_ORDER_CAP", "同时发布的求购单不能超过 3 单。"),
            PurchaseItemForbiddenError: ("PURCHASE_ITEM_FORBIDDEN", "该物品不可求购。"),
            PurchaseEscrowInsufficientError: ("PURCHASE_ESCROW_INSUFFICIENT", "灵石不足，未创建求购单。"),
            PurchaseOrderNotFoundError: ("PURCHASE_ORDER_NOT_FOUND", "求购单不存在。"),
            PurchaseOrderStateConflictError: ("PURCHASE_ORDER_STATE_CONFLICT", "求购单当前不允许此操作。"),
            PurchaseSelfMatchError: ("PURCHASE_SELF_MATCH", "不能匹配自己的求购单。"),
            PurchaseItemLockedError: ("PURCHASE_ITEM_LOCKED", "物品不足或已被其他订单锁定。"),
            ItemBindingActiveError: ("ITEM_BINDING_ACTIVE", "物品首次绑定尚未到期，暂不能匹配。"),
            PurchaseOrderExpiredError: ("PURCHASE_ORDER_EXPIRED", "求购单已过期。"),
            PurchaseDeliveryExpiredError: ("PURCHASE_DELIVERY_EXPIRED", "交付窗口已过，卖方物品锁已释放。"),
            PurchaseBuyerCapacityInsufficientError: ("PURCHASE_BUYER_CAPACITY_INSUFFICIENT", "买方背包容量不足，未发生成交。"),
            PurchasePermissionDeniedError: ("CROSS_REALM_TRADE_PERMISSION_DENIED", "当前地点或阵营声望不满足跨界求购许可。"),
            PlayerNotFoundError: ("PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。"),
            PlayerSuspendedError: ("PLAYER_SUSPENDED", "当前角色暂时不能操作求购。"),
            OperationConflictError: ("LEDGER_CONFLICT", "这次请求编号已经用于其他经济操作。"),
            RepositoryBusyError: ("PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。"),
        }
        for error_type, (code, message) in mapping.items():
            if isinstance(exc, error_type):
                return CommandResult(False, code, message, context.request_id, operation_id, retryable=error_type is RepositoryBusyError)
        return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)

    async def create(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 3:
            return CommandResult(False, "INVALID_PURCHASE_COMMAND", "请使用 `发布求购 物品 数量 单价`。", context.request_id)
        try:
            quantity, unit_price = int(context.command_args[1]), int(context.command_args[2])
        except ValueError:
            return CommandResult(False, "INVALID_PURCHASE_COMMAND", "数量和单价必须是整数。", context.request_id)
        operation_id = self._operation_id(context, "economy.create_purchase_order")
        try:
            record = await self.repository.create_purchase_order(
                platform=context.adapter,
                platform_user_id=context.user_id,
                item_key=context.command_args[0],
                quantity=quantity,
                unit_price=unit_price,
                operation_id=operation_id,
                cross_realm=True,
            )
        except Exception as exc:
            return self._error(context, operation_id, exc)
        return CommandResult(
            True,
            "PURCHASE_ORDER_CREATED",
            f"## 求购单已发布\n\n{self._label(record.item_key)} ×{record.quantity}，单价 {record.unit_price} 灵石。\n\n- **求购号**：`{record.order_id}`\n- **锁定总额**：{record.escrow_amount} 灵石\n- **有效至**：{record.expires_at}",
            context.request_id,
            operation_id,
            data=self._data(record),
        )

    async def list(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_PURCHASE_COMMAND", "求购列表无需附加参数。", context.request_id)
        try:
            records = await self.repository.list_purchase_orders(platform=context.adapter, platform_user_id=context.user_id)
        except Exception as exc:
            return self._error(context, "", exc)
        data = [self._data(record) for record in records]
        if not records:
            return CommandResult(True, "PURCHASE_ORDER_LIST_EMPTY", "当前没有公开求购单。", context.request_id, data={"orders": data})
        lines = ["## 跨界求购", ""]
        for record in records:
            matched = f"，卖方 {record.seller_dao_name}" if record.seller_dao_name else ""
            lines.append(f"- `{record.order_id}` {self._label(record.item_key)} ×{record.quantity}，单价 {record.unit_price}{matched}")
        return CommandResult(True, "PURCHASE_ORDER_LISTED", "\n".join(lines), context.request_id, data={"orders": data})

    async def match(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 1:
            return CommandResult(False, "INVALID_PURCHASE_COMMAND", "请使用 `匹配求购 求购号`。", context.request_id)
        operation_id = self._operation_id(context, "economy.match_purchase_order")
        try:
            record = await self.repository.match_purchase_order(platform=context.adapter, platform_user_id=context.user_id, order_id=context.command_args[0], operation_id=operation_id)
        except Exception as exc:
            return self._error(context, operation_id, exc)
        return CommandResult(True, "PURCHASE_ORDER_MATCHED", f"## 求购单已匹配\n\n请在 10 分钟内发送 `交付求购 {record.order_id}`。", context.request_id, operation_id, data=self._data(record))

    async def deliver(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 1:
            return CommandResult(False, "INVALID_PURCHASE_COMMAND", "请使用 `交付求购 求购号`。", context.request_id)
        operation_id = self._operation_id(context, "economy.deliver_purchase_order")
        try:
            record = await self.repository.deliver_purchase_order(platform=context.adapter, platform_user_id=context.user_id, order_id=context.command_args[0], operation_id=operation_id)
        except Exception as exc:
            return self._error(context, operation_id, exc)
        data = self._data(record)
        if record.transition_notice == "delivery_expired":
            return CommandResult(False, "PURCHASE_DELIVERY_EXPIRED", "交付窗口已过，卖方物品锁已释放，求购单仍可重新匹配。", context.request_id, operation_id, data=data)
        if record.transition_notice == "order_expired":
            return CommandResult(False, "PURCHASE_ORDER_EXPIRED", "求购单已过期，锁定灵石已返还。", context.request_id, operation_id, data=data)
        if record.transition_notice == "delivery_failed":
            return CommandResult(False, "PURCHASE_DELIVERY_FAILED", "卖方物品在交付前失效，订单已关闭并返还买方托管。", context.request_id, operation_id, data=data)
        return CommandResult(True, "PURCHASE_ORDER_SETTLED", f"## 求购单已成交\n\n已交付 {self._label(record.item_key)} ×{record.quantity}，卖方获得 {record.total_price} 灵石。", context.request_id, operation_id, data=data)

    async def cancel(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 1:
            return CommandResult(False, "INVALID_PURCHASE_COMMAND", "请使用 `取消求购 求购号`。", context.request_id)
        operation_id = self._operation_id(context, "economy.cancel_purchase_order")
        try:
            record = await self.repository.cancel_purchase_order(platform=context.adapter, platform_user_id=context.user_id, order_id=context.command_args[0], operation_id=operation_id)
        except Exception as exc:
            return self._error(context, operation_id, exc)
        return CommandResult(True, "PURCHASE_ORDER_CANCELLED", f"求购单 `{record.order_id}` 已取消，锁定灵石已返还。", context.request_id, operation_id, data=self._data(record))

    async def expire(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 1:
            return CommandResult(False, "INVALID_PURCHASE_COMMAND", "请使用 `清理求购 求购号`。", context.request_id)
        operation_id = self._operation_id(context, "economy.expire_purchase_order")
        try:
            record = await self.repository.expire_purchase_order(platform=context.adapter, platform_user_id=context.user_id, order_id=context.command_args[0], operation_id=operation_id)
        except Exception as exc:
            return self._error(context, operation_id, exc)
        return CommandResult(True, "PURCHASE_ORDER_EXPIRED", f"求购单 `{record.order_id}` 已过期，锁定资产已释放。", context.request_id, operation_id, data=self._data(record))


__all__ = ["PurchaseOrderApplication"]
