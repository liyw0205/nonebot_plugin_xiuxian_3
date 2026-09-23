"""Application services for personal production."""

from __future__ import annotations

from ...contracts import CommandContext, CommandResult
from ..repository import (
    EndgameRecipeAlreadyCreatedError,
    EndgameRecipeBusyError,
    EndgameRecipeNotFoundError,
    EndgameRecipeNotReadyError,
    EndgameRecipeRequirementError,
    EnergyInsufficientError,
    MaterialInsufficientError,
    OperationConflictError,
    PlayerNotFoundError,
    PlayerStageConflictError,
    PlayerSuspendedError,
    ProductionBusyError,
    ProductionDailyLimitError,
    ProductionExpiredError,
    ProductionNotFoundError,
    ProductionNotReadyError,
    QuestResourceInsufficientError,
    RecipeRequirementError,
    RepositoryBusyError,
    SQLitePlayerRepository,
    ToolDurabilityInsufficientError,
    ToolMissingError,
)
from .endgame_rules import resolve_endgame_recipe
from .rules import item_label, resolve_recipe


class ProductionApplication:
    """Coordinates recipe previews and personal production orders."""

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
    def _recipe_args(args: tuple[str, ...]) -> str | None:
        if len(args) != 1:
            return None
        return resolve_recipe(args[0])

    async def preview_recipe(self, context: CommandContext) -> CommandResult:
        recipe_key = self._recipe_args(context.command_args)
        if recipe_key is None:
            return CommandResult(False, "RECIPE_NOT_FOUND", "请指定配方，例如 `生产预览 疗伤丹`。", context.request_id)
        operation_id = self._operation_id(context, "production.preview")
        try:
            record = await self.repository.preview_production(
                platform=context.adapter,
                platform_user_id=context.user_id,
                recipe_key=recipe_key,
                operation_id=operation_id,
            )
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id)
        except RecipeRequirementError:
            return CommandResult(False, "RECIPE_REQUIREMENT_MISSING", "当前道途、境界或地点不满足这条配方。", context.request_id)
        except PlayerStageConflictError:
            return CommandResult(False, "RECIPE_REQUIREMENT_MISSING", "完成入道后才能进行正式生产。", context.request_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色处于暂停状态，暂时不能查看生产。", context.request_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, retryable=True)
        tool_text = f"- **工具**：{item_label(record.tool_key)}\n" if record.tool_key else ""
        return CommandResult(
            True,
            "RECIPE_PREVIEW",
            (
                f"## {record.recipe_name} · 生产预览\n\n"
                f"- **精力消耗**：{record.energy_cost}\n"
                f"- **预计时长**：{record.duration_seconds} 秒\n"
                f"- **今日次数**：{record.daily_used}/{record.daily_limit}\n"
                f"- **灵石消耗**：{record.currency_cost}\n"
                + tool_text
                + "\n### 所需材料\n\n"
                + "\n".join(f"- **{item_label(key)}** ×{value}" for key, value in record.inputs.items())
                + f"\n\n> 下一步：发送 `开始生产 {record.recipe_name}`，锁定材料并开始。"
            ),
            context.request_id,
            operation_id,
            data={
                "recipe_key": record.recipe_key,
                "recipe_name": record.recipe_name,
                "energy_cost": record.energy_cost,
                "duration_seconds": record.duration_seconds,
                "daily_used": record.daily_used,
                "daily_limit": record.daily_limit,
                "inputs": record.inputs,
                "currency_cost": record.currency_cost,
                "idempotent_replay": False,
            },
        )

    async def start_production(self, context: CommandContext) -> CommandResult:
        recipe_key = self._recipe_args(context.command_args)
        if recipe_key is None:
            return CommandResult(False, "RECIPE_NOT_FOUND", "请指定配方，例如 `开始生产 疗伤丹`。", context.request_id)
        operation_id = self._operation_id(context, "production.start")
        try:
            record = await self.repository.start_production(
                platform=context.adapter,
                platform_user_id=context.user_id,
                recipe_key=recipe_key,
                operation_id=operation_id,
            )
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except PlayerStageConflictError:
            return CommandResult(False, "RECIPE_REQUIREMENT_MISSING", "完成入道后才能进行正式生产。", context.request_id, operation_id)
        except RecipeRequirementError:
            return CommandResult(False, "RECIPE_REQUIREMENT_MISSING", "当前道途、境界或地点不满足这条配方。", context.request_id, operation_id)
        except ToolMissingError:
            return CommandResult(False, "TOOL_MISSING", "缺少该配方要求的生产工具。", context.request_id, operation_id)
        except ToolDurabilityInsufficientError:
            return CommandResult(False, "TOOL_DURABILITY_INSUFFICIENT", "生产工具耐久不足，请更换工具。", context.request_id, operation_id)
        except MaterialInsufficientError:
            return CommandResult(False, "MATERIAL_INSUFFICIENT", "生产材料不足，未扣除任何资源。", context.request_id, operation_id)
        except EnergyInsufficientError:
            return CommandResult(False, "ENERGY_INSUFFICIENT", "精力不足，未扣除任何资源。", context.request_id, operation_id)
        except ProductionBusyError:
            return CommandResult(False, "PRODUCTION_BUSY", "已有生产订单正在进行，请先领取结果。", context.request_id, operation_id)
        except ProductionDailyLimitError:
            return CommandResult(False, "RECIPE_DAILY_CAP", "该配方今日次数已用尽，明日再来。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色处于暂停状态，暂时不能生产。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于其他生产，请重新发起。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        return CommandResult(
            True,
            "PRODUCTION_STARTED",
            (
                f"## 生产已开始\n\n"
                f"**{self._display_name(record.player)}**开始制作 **{record.recipe_name}**。\n\n"
                f"- **精力**：{record.player.energy}/{record.player.energy_max}\n"
                f"- **灵石**：{record.player.spirit_stones}\n"
                "- **状态**：制作中\n\n"
                f"> 下一步：完成后发送 `领取生产`。"
            ),
            context.request_id,
            operation_id,
            data={
                "order_id": record.order_id,
                "recipe_key": record.recipe_key,
                "recipe_name": record.recipe_name,
                "status": record.status,
                "starts_at": record.starts_at,
                "ends_at": record.ends_at,
                "energy": record.player.energy,
                "spirit_stones": record.player.spirit_stones,
                "idempotent_replay": record.already_completed,
            },
        )

    async def complete_production(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_PRODUCTION_COMMAND", "领取生产无需附加参数。", context.request_id)
        operation_id = self._operation_id(context, "production.complete")
        try:
            record = await self.repository.complete_production(
                platform=context.adapter,
                platform_user_id=context.user_id,
                operation_id=operation_id,
            )
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except ProductionNotFoundError:
            return CommandResult(False, "PRODUCTION_NOT_FOUND", "当前没有可领取的生产订单。", context.request_id, operation_id)
        except ProductionNotReadyError:
            return CommandResult(False, "PRODUCTION_NOT_READY", "生产尚未完成，请稍后再来领取。", context.request_id, operation_id)
        except ProductionExpiredError:
            return CommandResult(False, "ORDER_EXPIRED", "生产订单已过期，请发送 `恢复生产` 按原快照结算。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色处于暂停状态，暂时不能领取生产。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于其他领取，请重新发起。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        return self._settlement_result(context, operation_id, record)

    async def recover_production(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_PRODUCTION_COMMAND", "恢复生产无需附加参数。", context.request_id)
        operation_id = self._operation_id(context, "production.recover")
        try:
            record = await self.repository.recover_production(
                platform=context.adapter,
                platform_user_id=context.user_id,
                operation_id=operation_id,
            )
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except ProductionNotFoundError:
            return CommandResult(False, "PRODUCTION_NOT_FOUND", "当前没有需要恢复的生产订单。", context.request_id, operation_id)
        except ProductionNotReadyError:
            return CommandResult(False, "PRODUCTION_NOT_READY", "生产尚未达到恢复时间，请稍后再试。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色处于暂停状态，暂时不能恢复生产。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于其他恢复，请重新发起。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        return self._settlement_result(context, operation_id, record, recovered=True)

    async def start_endgame_recipe(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 1:
            return CommandResult(False, "ENDGAME_RECIPE_CONTEXT_INVALID", "请指定一个终局配方键。", context.request_id)
        recipe_key = resolve_endgame_recipe(context.command_args[0])
        if recipe_key is None:
            return CommandResult(False, "ENDGAME_RECIPE_CONTEXT_INVALID", "未开放该终局配方。", context.request_id)
        operation_id = self._operation_id(context, "endgame.production.start")
        try:
            record = await self.repository.start_endgame_recipe(
                platform=context.adapter,
                platform_user_id=context.user_id,
                recipe_key=recipe_key,
                operation_id=operation_id,
            )
        except EndgameRecipeAlreadyCreatedError:
            return CommandResult(False, "ENDGAME_RECIPE_ALREADY_CREATED", "该终局配方的次数已用尽。", context.request_id, operation_id)
        except EndgameRecipeBusyError:
            return CommandResult(False, "ENDGAME_RECIPE_BUSY", "已有终局配方正在制作，请先结算。", context.request_id, operation_id)
        except EndgameRecipeRequirementError:
            return CommandResult(False, "ENDGAME_RECIPE_CONTEXT_INVALID", "需在道源门制作，并满足境界、试炼、领域及资源前置。", context.request_id, operation_id)
        except QuestResourceInsufficientError:
            return CommandResult(False, "QUEST_RESOURCE_INSUFFICIENT", "世界功勋不足，未扣除资源。", context.request_id, operation_id)
        except MaterialInsufficientError:
            return CommandResult(False, "MATERIAL_INSUFFICIENT", "终局配方材料不足，未扣除资源。", context.request_id, operation_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能制作终局配方。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次操作编号已用于其他请求。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        return CommandResult(
            True,
            "ENDGAME_RECIPE_STARTED",
            f"## 终局配方已开始\n\n**{record.recipe_key}**已建立个人制作会话，预计于 {record.ends_at} 后结算。",
            context.request_id,
            operation_id,
            data={"session_id": record.session_id, "recipe_key": record.recipe_key, "status": record.status, "ends_at": record.ends_at, "idempotent_replay": record.already_completed},
        )

    async def settle_endgame_recipe(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_ENDGAME_RECIPE_COMMAND", "结算终局配方无需附加参数。", context.request_id)
        operation_id = self._operation_id(context, "endgame.production.settle")
        try:
            record = await self.repository.settle_endgame_recipe(
                platform=context.adapter,
                platform_user_id=context.user_id,
                operation_id=operation_id,
            )
        except EndgameRecipeNotFoundError:
            return CommandResult(False, "ENDGAME_RECIPE_NOT_FOUND", "当前没有待结算的终局配方。", context.request_id, operation_id)
        except EndgameRecipeNotReadyError:
            return CommandResult(False, "ENDGAME_RECIPE_NOT_READY", "终局配方尚未完成，请稍后再结算。", context.request_id, operation_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能结算终局配方。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次操作编号已用于其他请求。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        return CommandResult(
            True,
            "ENDGAME_RECIPE_SETTLED",
            f"## 终局配方结算{'成功' if record.success else '失败'}\n\n- **配方**：{record.recipe_key}\n- **产出**：{record.rewards or '无'}\n- **返还**：{record.refunds or '无'}",
            context.request_id,
            operation_id,
            data={"session_id": record.session_id, "recipe_key": record.recipe_key, "success": record.success, "roll_bp": record.roll_bp, "rewards": record.rewards, "refunds": record.refunds, "dao_fruit_progress": record.player.dao_fruit_progress, "ascension_merit": record.player.ascension_merit, "world_merit": record.player.world_merit, "idempotent_replay": record.already_completed},
        )

    def _settlement_result(self, context: CommandContext, operation_id: str, record, *, recovered: bool = False) -> CommandResult:
        result_text = "恢复生产完成" if recovered else "生产完成"
        outcome = "成功" if record.success else "失败"
        outputs = "、".join(f"{item_label(key)} ×{value}" for key, value in record.outputs.items()) or "无成品"
        refunds = "、".join(f"{item_label(key)} ×{value}" for key, value in record.refunds.items()) or "无"
        return CommandResult(
            True,
            "PRODUCTION_RECOVERED" if recovered else "PRODUCTION_COMPLETED",
            (
                f"## {result_text}\n\n"
                f"**{self._display_name(record.player)}**的 **{record.recipe_name}**生产{outcome}。\n\n"
                f"- **质量**：{record.quality_bp}/10000\n"
                f"- **获得**：{outputs}\n"
                f"- **返还材料**：{refunds}\n"
                f"- **剩余精力**：{record.player.energy}/{record.player.energy_max}\n\n"
                "> 下一步：可使用成品，或查看 `我的状态`。"
            ),
            context.request_id,
            operation_id,
            data={
                "order_id": record.order_id,
                "recipe_key": record.recipe_key,
                "status": record.status,
                "quality_bp": record.quality_bp,
                "random_quality_bp": record.random_quality_bp,
                "success": record.success,
                "outputs": record.outputs,
                "refunds": record.refunds,
                "currency_spent": record.currency_spent,
                "tool_durability_bp": record.tool_durability_bp,
                "energy": record.player.energy,
                "inventory": record.player.inventory,
                "idempotent_replay": record.already_completed,
            },
        )


__all__ = ["ProductionApplication"]
