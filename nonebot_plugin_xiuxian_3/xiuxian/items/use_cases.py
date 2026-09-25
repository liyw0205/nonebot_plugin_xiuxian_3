"""Application service for player item effects."""

from __future__ import annotations

from ...contracts import CommandContext, CommandResult
from ..repository import (
    ItemEffectAlreadyActiveError,
    ItemEffectAlreadyPendingError,
    ItemInsufficientError,
    ItemLocationRequiredError,
    ItemNotUsableError,
    OperationConflictError,
    PlayerNotFoundError,
    PlayerSuspendedError,
    RepositoryBusyError,
    SQLitePlayerRepository,
)
from .rules import ITEM_LABELS, resolve_item


class ItemApplication:
    def __init__(self, repository: SQLitePlayerRepository):
        self.repository = repository

    @staticmethod
    def _operation_id(context: CommandContext) -> str:
        if context.operation_id:
            return context.operation_id
        request_key = context.message_id or context.request_id
        return f"items.use:{context.adapter}:{context.user_id}:{request_key}"

    async def use_item(self, context: CommandContext) -> CommandResult:
        if not 1 <= len(context.command_args) <= 2:
            return CommandResult(False, "INVALID_ITEM_COMMAND", "请使用 `使用 <物品>`，阵法可追加地点。", context.request_id)
        try:
            definition = resolve_item(context.command_args[0])
        except ValueError:
            return CommandResult(False, "ITEM_NOT_USABLE", "该物品当前没有可用效果。", context.request_id)
        location_key = None
        if len(context.command_args) == 2:
            location_key = {"雾隐洞天二层": "cave.mist_grotto_2", "雾隐洞天·二层": "cave.mist_grotto_2", "洞天二层": "cave.mist_grotto_2", "cave.mist_grotto_2": "cave.mist_grotto_2"}.get(context.command_args[1], context.command_args[1])
        operation_id = self._operation_id(context)
        try:
            record = await self.repository.use_item(
                platform=context.adapter,
                platform_user_id=context.user_id,
                item_key=definition.key,
                location_key=location_key,
                operation_id=operation_id,
            )
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except ItemInsufficientError:
            return CommandResult(False, "ITEM_INSUFFICIENT", f"缺少{definition.name}，未扣除资源。", context.request_id, operation_id)
        except ItemLocationRequiredError:
            return CommandResult(False, "ITEM_LOCATION_REQUIRED", "迷雾屏障阵只能在雾隐洞天二层布置，且只能绑定该地点。", context.request_id, operation_id)
        except ItemEffectAlreadyActiveError:
            return CommandResult(False, "ITEM_EFFECT_ALREADY_ACTIVE", "该地点已有同类迷雾屏障阵，效果不叠加。", context.request_id, operation_id)
        except ItemEffectAlreadyPendingError:
            return CommandResult(False, "ITEM_EFFECT_ALREADY_PENDING", "已有一份云灵茶效果等待下一次修炼，不能重复消费。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于其他物品操作，请重新发起。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能使用物品。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        if record.item_key == "item.food.cloud_tea":
            message = "## 云灵茶已饮用\n\n下一次修炼会话获得 **状态 +500 bp**；效果已冻结，开始修炼时自动消耗。"
        else:
            message = f"## {record.item_name}已布置\n\n绑定地点：**雾隐洞天二层**\n风险降低：**{record.effect.get('risk_reduction_bp', 0)} bp**\n有效至：{record.effect.get('expires_at', '未知')}。"
        return CommandResult(True, "ITEM_USED", message, context.request_id, operation_id, data={"item_key": record.item_key, "item_name": record.item_name, "quantity": record.quantity, "effect": record.effect, "inventory": record.player.inventory, "idempotent_replay": record.already_completed})


__all__ = ["ItemApplication"]
