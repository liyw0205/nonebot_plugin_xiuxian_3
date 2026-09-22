"""Application services for the first player-to-player service orders."""

from __future__ import annotations

from ...contracts import CommandContext, CommandResult
from ..repository import (
    OperationConflictError,
    PlayerNotFoundError,
    PlayerSuspendedError,
    ResourceInsufficientError,
    RepositoryBusyError,
    ServiceAlreadySettledError,
    ServiceDailyLimitError,
    ServiceExpiredError,
    ServiceLocationConflictError,
    ServiceNotFoundError,
    ServiceOrderConflictError,
    ServiceReputationInsufficientError,
    ServiceRequirementError,
    ServiceSelfAcceptError,
    SQLitePlayerRepository,
)
from .service_rules import service_definition


class ServiceApplication:
    """Translate service-order commands into one shared application contract."""

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
    def _parse_publish_args(args: tuple[str, ...]) -> tuple[str | None, int | None]:
        if not args or len(args) > 2:
            return None, None
        try:
            service_key = service_definition(args[0]).key
        except ValueError:
            return None, None
        if len(args) == 1:
            return service_key, None
        try:
            reward = int(args[1])
        except ValueError:
            return None, None
        return service_key, reward

    @staticmethod
    def _parse_order_id(args: tuple[str, ...], *, optional: bool = False) -> str | None:
        if not args and optional:
            return None
        if len(args) != 1 or not args[0].strip():
            return ""
        return args[0].strip()

    async def publish_service(self, context: CommandContext) -> CommandResult:
        service_key, reward = self._parse_publish_args(context.command_args)
        if service_key is None:
            return CommandResult(False, "INVALID_SERVICE", "请使用 `发布服务 教学采集协助` 或 `发布服务 烹饪服务 [报酬]`。", context.request_id)
        operation_id = self._operation_id(context, "livelihood.publish_service")
        try:
            record = await self.repository.publish_service(
                platform=context.adapter,
                platform_user_id=context.user_id,
                service_key=service_key,
                reward_stones=reward,
                operation_id=operation_id,
            )
        except ServiceRequirementError:
            return CommandResult(False, "INVALID_SERVICE", "服务类型或报酬不符合当前内容规则。", context.request_id, operation_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能发布服务。", context.request_id, operation_id)
        except ResourceInsufficientError:
            return CommandResult(False, "CURRENCY_INSUFFICIENT", "灵石不足，无法锁定服务报酬。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于其他服务操作。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        return CommandResult(
            True,
            "SERVICE_PUBLISHED",
            (
                f"## 服务已发布\n\n**{record.service_name}**已发布，报酬为灵石 {record.reward_stones}。\n\n"
                f"- **订单号**：`{record.order_id}`\n- **有效至**：{record.expires_at}\n\n"
                "> 报酬已锁定；接取后还会锁定承接者的材料与体力/精力。"
            ),
            context.request_id,
            operation_id,
            data={
                "order_id": record.order_id,
                "service_key": record.service_key,
                "status": record.status,
                "reward_stones": record.reward_stones,
                "expires_at": record.expires_at,
                "idempotent_replay": record.already_completed,
            },
        )

    async def accept_service(self, context: CommandContext) -> CommandResult:
        order_id = self._parse_order_id(context.command_args)
        if not order_id:
            return CommandResult(False, "INVALID_SERVICE_ORDER", "请使用 `接取服务 订单号`。", context.request_id)
        operation_id = self._operation_id(context, "livelihood.accept_service")
        try:
            record = await self.repository.accept_service(
                platform=context.adapter,
                platform_user_id=context.user_id,
                order_id=order_id,
                operation_id=operation_id,
            )
        except ServiceNotFoundError:
            return CommandResult(False, "SERVICE_NOT_FOUND", "服务订单不存在或已不属于可接取状态。", context.request_id, operation_id)
        except ServiceSelfAcceptError:
            return CommandResult(False, "SERVICE_ORDER_CONFLICT", "不能接取自己发布的服务。", context.request_id, operation_id)
        except ServiceOrderConflictError:
            return CommandResult(False, "SERVICE_ORDER_CONFLICT", "服务订单已经被接取或不再开放。", context.request_id, operation_id)
        except ServiceExpiredError:
            return CommandResult(False, "SERVICE_EXPIRED", "服务订单已经过期。", context.request_id, operation_id)
        except ServiceReputationInsufficientError:
            return CommandResult(False, "SERVICE_REPUTATION_INSUFFICIENT", "服务信誉不足，暂不能承接该服务。", context.request_id, operation_id)
        except ServiceLocationConflictError:
            return CommandResult(False, "SERVICE_LOCATION_CONFLICT", "你和委托人不在同一地点。", context.request_id, operation_id)
        except ServiceRequirementError:
            return CommandResult(False, "SERVICE_REQUIREMENT_MISSING", "尚未完成该服务要求的教学。", context.request_id, operation_id)
        except ServiceDailyLimitError:
            return CommandResult(False, "SERVICE_DAILY_LIMIT", "该服务今日承接次数已用尽。", context.request_id, operation_id)
        except ResourceInsufficientError:
            return CommandResult(False, "RESOURCE_INSUFFICIENT", "承接该服务所需的体力、精力或材料不足。", context.request_id, operation_id)
        except (PlayerNotFoundError, PlayerSuspendedError):
            return CommandResult(False, "PLAYER_NOT_FOUND", "当前角色不存在或暂时不可用。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于其他服务操作。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        return CommandResult(
            True,
            "SERVICE_ACCEPTED",
            f"## 服务已接取\n\n你已接取 **{record.service_name}**。\n\n- **订单号**：`{record.order_id}`\n- **状态**：承接中\n- **截止**：{record.expires_at}\n\n> 完成后发送 `结算服务 {record.order_id}`。",
            context.request_id,
            operation_id,
            data={"order_id": record.order_id, "service_key": record.service_key, "status": record.status, "idempotent_replay": record.already_completed},
        )

    async def cancel_service(self, context: CommandContext) -> CommandResult:
        order_id = self._parse_order_id(context.command_args)
        if not order_id:
            return CommandResult(False, "INVALID_SERVICE_ORDER", "请使用 `取消服务 订单号`。", context.request_id)
        operation_id = self._operation_id(context, "livelihood.cancel_service")
        try:
            record = await self.repository.cancel_service(
                platform=context.adapter,
                platform_user_id=context.user_id,
                order_id=order_id,
                operation_id=operation_id,
            )
        except ServiceNotFoundError:
            return CommandResult(False, "SERVICE_NOT_FOUND", "服务订单不存在或不是你发布的订单。", context.request_id, operation_id)
        except ServiceOrderConflictError:
            return CommandResult(False, "SERVICE_ORDER_CONFLICT", "只有尚未被接取的服务订单可以取消。", context.request_id, operation_id)
        except (PlayerNotFoundError, PlayerSuspendedError):
            return CommandResult(False, "PLAYER_NOT_FOUND", "当前角色不存在或暂时不可用。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于其他服务操作。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        return CommandResult(
            True,
            "SERVICE_CANCELLED",
            f"## 服务已取消\n\n订单 `{record.order_id}` 已取消，锁定报酬灵石 {record.reward_stones} 已退回。",
            context.request_id,
            operation_id,
            data={
                "order_id": record.order_id,
                "service_key": record.service_key,
                "status": record.status,
                "refund_stones": record.reward_stones,
                "idempotent_replay": record.already_completed,
            },
        )

    async def settle_service(self, context: CommandContext) -> CommandResult:
        order_id = self._parse_order_id(context.command_args, optional=True)
        if order_id == "":
            return CommandResult(False, "INVALID_SERVICE_ORDER", "请使用 `结算服务 [订单号]`。", context.request_id)
        operation_id = self._operation_id(context, "livelihood.settle_service")
        try:
            record = await self.repository.settle_service(
                platform=context.adapter,
                platform_user_id=context.user_id,
                order_id=order_id,
                operation_id=operation_id,
            )
        except ServiceNotFoundError:
            return CommandResult(False, "SERVICE_NOT_FOUND", "没有可结算的服务订单。", context.request_id, operation_id)
        except ServiceAlreadySettledError:
            return CommandResult(False, "SERVICE_ALREADY_SETTLED", "该服务订单已经结算过了。", context.request_id, operation_id)
        except ServiceOrderConflictError:
            return CommandResult(False, "SERVICE_ORDER_CONFLICT", "该服务订单当前不能结算。", context.request_id, operation_id)
        except (PlayerNotFoundError, PlayerSuspendedError):
            return CommandResult(False, "PLAYER_NOT_FOUND", "当前角色不存在或暂时不可用。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于其他服务操作。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        if record.status == "delivered":
            return CommandResult(
                True,
                "SERVICE_SETTLED",
                f"## 服务已完成\n\n**{record.service_name}**交付成功。\n\n- **承接报酬**：灵石 +{record.provider_payment}\n- **交付物**：{self._items(record.outputs)}",
                context.request_id,
                operation_id,
                data=self._settlement_data(record),
            )
        code = "SERVICE_EXPIRED" if record.status == "expired" else "SERVICE_FAILED"
        return CommandResult(
            True,
            code,
            f"## 服务未完成\n\n**{record.service_name}**按失败快照结算。\n\n- **委托人退回**：灵石 {record.publisher_refund}\n- **承接者退回材料**：{self._items(record.provider_refunds)}\n- **退回体力**：{record.stamina_refund}",
            context.request_id,
            operation_id,
            data=self._settlement_data(record),
        )

    @staticmethod
    def _items(items: dict[str, int]) -> str:
        return "、".join(f"{key} ×{value}" for key, value in items.items()) or "无"

    @staticmethod
    def _settlement_data(record) -> dict:
        return {
            "order_id": record.order_id,
            "service_key": record.service_key,
            "status": record.status,
            "reward_stones": record.reward_stones,
            "provider_payment": record.provider_payment,
            "publisher_refund": record.publisher_refund,
            "platform_fee": record.platform_fee,
            "outputs": record.outputs,
            "provider_refunds": record.provider_refunds,
            "stamina_refund": record.stamina_refund,
            "idempotent_replay": record.already_completed,
        }


__all__ = ["ServiceApplication"]
