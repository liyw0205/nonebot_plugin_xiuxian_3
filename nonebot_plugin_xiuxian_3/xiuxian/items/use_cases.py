"""Application service for player item effects."""

from __future__ import annotations

from datetime import datetime

from ...contracts import CommandContext, CommandResult
from ..content import bundled_content, resolve_content_key
from ..repository import (
    ItemEffectAlreadyActiveError,
    ItemEffectAlreadyPendingError,
    ItemCooldownError,
    ItemInsufficientError,
    ItemReservedError,
    ItemLocationRequiredError,
    ItemNotUsableError,
    OperationConflictError,
    PlayerNotFoundError,
    PlayerSuspendedError,
    RepositoryBusyError,
    SQLitePlayerRepository,
)
from .models import ItemUseRecord
from .rules import resolve_item


class ItemApplication:
    def __init__(self, repository: SQLitePlayerRepository):
        self.repository = repository

    @staticmethod
    def _operation_id(context: CommandContext) -> str:
        if context.operation_id:
            return context.operation_id
        request_key = context.message_id or context.request_id
        return f"items.use:{context.adapter}:{context.user_id}:{request_key}"

    @staticmethod
    def _percent(value_bp: int) -> str:
        whole, fraction = divmod(value_bp, 100)
        if fraction == 0:
            return str(whole)
        return f"{whole}.{fraction:02d}".rstrip("0")

    @staticmethod
    def _resource_key(value: str, resources: tuple[str, ...]) -> str | None:
        labels = {"stamina": "体力", "energy": "精力", "void_power": "虚力"}
        normalized = (value or "").strip()
        for resource in resources:
            if normalized in {resource, labels[resource]}:
                return resource
        return None

    @staticmethod
    def _resource_prompt(resources: tuple[str, ...]) -> str:
        labels = {"stamina": "体力", "energy": "精力", "void_power": "虚力"}
        return "、".join(labels[resource] for resource in resources)

    def _result(self, context: CommandContext, operation_id: str, record: ItemUseRecord) -> CommandResult:
        effect = record.effect
        if effect.get("type") == "restore_choice":
            resource = {"stamina": "体力", "energy": "精力", "void_power": "虚力"}[effect["resource"]]
            message = (
                f"## {record.item_name}已用\n\n"
                f"{resource}恢复 **{int(effect['restored'])}**。"
            )
        elif effect.get("type") == "grant_intro_flags":
            message = f"## {record.item_name}已登记\n\n矿区授权已记入仙缘簿，无需继续携带许可。境界与地点门槛仍须满足。"
        elif effect.get("type") == "next_cultivation_state_bonus_bp":
            message = (
                f"## {record.item_name}已饮尽\n\n一缕清灵仍在经脉间流转，"
                f"下一次修炼所得修为提高 **{self._percent(int(effect['state_bp_bonus']))}%**。"
            )
        else:
            expires_at = datetime.fromisoformat(str(effect["expires_at"]))
            expires_label = expires_at.astimezone().strftime("%Y年%m月%d日 %H:%M")
            message = (
                f"## {record.item_name}已布下\n\n屏障笼罩{effect['location_name']}，探索途中遭遇战斗的机会"
                f"降低 **{self._percent(int(effect['risk_reduction_bp']))}%**，"
                f"将持续到 {expires_label}。"
            )
        return CommandResult(
            True,
            "ITEM_USED",
            message,
            context.request_id,
            operation_id,
            data={
                "item_key": record.item_key,
                "item_name": record.item_name,
                "quantity": record.quantity,
                "effect": effect,
                "inventory": record.player.inventory,
                "idempotent_replay": record.already_completed,
            },
        )

    async def use_item(self, context: CommandContext) -> CommandResult:
        if not 1 <= len(context.command_args) <= 2:
            return CommandResult(False, "INVALID_ITEM_COMMAND", "请写明物品；食物还需选择体力或精力。", context.request_id)
        operation_id = self._operation_id(context)
        try:
            replay = await self.repository.replay_item_use(
                platform=context.adapter,
                platform_user_id=context.user_id,
                operation_id=operation_id,
                request_args=context.command_args,
            )
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这道操作已承载另一番心意，请换一枚新的传讯凭证。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        if replay is not None:
            return self._result(context, operation_id, replay)

        content = self.repository.content or bundled_content()
        try:
            definition = resolve_item(context.command_args[0], content)
        except ValueError:
            return CommandResult(False, "ITEM_NOT_USABLE", "该物品当前没有可用效果。", context.request_id)
        location_key = None
        if definition.effect_type == "restore_choice":
            if len(context.command_args) != 2:
                return CommandResult(
                    False,
                    "ITEM_CHOICE_REQUIRED",
                    f"请在{self._resource_prompt(definition.resources)}之间选择一项恢复。",
                    context.request_id,
                )
            location_key = self._resource_key(context.command_args[1], definition.resources)
            if location_key is None:
                return CommandResult(
                    False,
                    "ITEM_CHOICE_INVALID",
                    f"这份灵食只能调养{self._resource_prompt(definition.resources)}。",
                    context.request_id,
                )
        elif len(context.command_args) == 2:
            if definition.effect_type != "exploration_risk_reduction_bp":
                return CommandResult(False, "INVALID_ITEM_COMMAND", "这件物品无需指定地点。", context.request_id)
            try:
                location_key = resolve_content_key(content, "location", context.command_args[1])
            except ValueError:
                location_key = context.command_args[1].strip()
        try:
            record = await self.repository.use_item(
                platform=context.adapter,
                platform_user_id=context.user_id,
                item_key=definition.key,
                location_key=location_key,
                operation_id=operation_id,
                request_args=context.command_args,
            )
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except ItemInsufficientError:
            return CommandResult(False, "ITEM_INSUFFICIENT", f"缺少{definition.name}，未扣除资源。", context.request_id, operation_id)
        except ItemNotUsableError:
            return CommandResult(False, "ITEM_NOT_USABLE", "尚未开启该资源，未消耗物品。", context.request_id, operation_id)
        except ItemReservedError:
            return CommandResult(False, "ITEM_RESERVED", f"{definition.name}已托付给交易，暂不能使用。", context.request_id, operation_id)
        except ItemLocationRequiredError:
            target = (
                content.label("location", definition.location_key)
                if definition.location_key
                else "指定地点"
            )
            return CommandResult(False, "ITEM_LOCATION_REQUIRED", f"{definition.name}只能在{target}布置，并绑定该处灵机。", context.request_id, operation_id)
        except ItemEffectAlreadyActiveError:
            message = (
                f"{definition.name}已登记，矿区授权无需重复办理。"
                if definition.effect_type == "grant_intro_flags"
                else f"{definition.name}已在此处生效，不能重复布置。"
            )
            return CommandResult(False, "ITEM_EFFECT_ALREADY_ACTIVE", message, context.request_id, operation_id)
        except ItemEffectAlreadyPendingError:
            return CommandResult(False, "ITEM_EFFECT_ALREADY_PENDING", f"已有一份{definition.name}药力在经脉中流转，不能重复饮用。", context.request_id, operation_id)
        except ItemCooldownError:
            return CommandResult(False, "ITEM_COOLDOWN", "这份灵食的药力尚未散尽，请稍候再用。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这道操作已承载另一番心意，请换一枚新的传讯凭证。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能使用物品。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        return self._result(context, operation_id, record)


__all__ = ["ItemApplication"]
