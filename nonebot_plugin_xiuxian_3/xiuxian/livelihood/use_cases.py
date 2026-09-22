"""Application services for residence leasing and inspection."""

from __future__ import annotations

from ...contracts import CommandContext, CommandResult
from ..repository import (
    CropContentClosedError,
    CropDailyLimitError,
    CommissionAlreadyAcceptedError,
    CommissionAlreadyDeliveredError,
    CommissionExpiredError,
    CommissionMaterialInsufficientError,
    CommissionNotAcceptedError,
    CommissionNotFoundError,
    CommissionQuotaError,
    CommissionStockExhaustedError,
    CurrencyInsufficientError,
    FieldPlotAlreadyHarvestedError,
    FieldPlotBusyError,
    FieldPlotNotFoundError,
    FieldPlotNotReadyError,
    FieldPlotWitheredError,
    LocalReputationInsufficientError,
    OperationConflictError,
    PlayerNotFoundError,
    PlayerStageConflictError,
    PlayerSuspendedError,
    RepositoryBusyError,
    ResidenceAlreadyActiveError,
    ResidenceContentClosedError,
    ResidenceNotFoundError,
    ResidencePlotRequiredError,
    ResidenceRequiredError,
    SQLitePlayerRepository,
    ResourceInsufficientError,
)
from .rules import commission_definition, crop_definition, residence_definition


class LivelihoodApplication:
    """Coordinate the first residence commands."""

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
        return value.replace("\\", "\\\\").replace("`", "\\`").replace("*", "\\*").replace("_", "\\_").replace("~", "\\~")

    @staticmethod
    def _resolve_args(args: tuple[str, ...]) -> str | None:
        if len(args) > 1:
            return None
        try:
            return residence_definition(args[0] if args else None).key
        except ValueError:
            return None

    @staticmethod
    def _resolve_crop(args: tuple[str, ...]) -> str | None:
        if len(args) > 1:
            return None
        try:
            return crop_definition(args[0] if args else None).key
        except ValueError:
            return None

    @staticmethod
    def _resolve_commission(args: tuple[str, ...], *, required: bool = True) -> str | None:
        if len(args) > 1:
            return None
        if not args and not required:
            return None
        try:
            return commission_definition(args[0] if args else None).key
        except ValueError:
            return None

    async def lease(self, context: CommandContext) -> CommandResult:
        key = self._resolve_args(context.command_args)
        if key is None:
            return CommandResult(False, "INVALID_RESIDENCE", "可用 `租住居所` 或 `租住居所 客房`。", context.request_id)
        operation_id = self._operation_id(context, "livelihood.lease_residence")
        try:
            record = await self.repository.lease_residence(
                platform=context.adapter,
                platform_user_id=context.user_id,
                residence_key=key,
                operation_id=operation_id,
            )
        except ResidenceContentClosedError:
            return CommandResult(False, "LIVELIHOOD_CONTENT_CLOSED", "该居所暂未开放。", context.request_id, operation_id)
        except ResidenceAlreadyActiveError:
            return CommandResult(False, "RESIDENCE_ALREADY_ACTIVE", "你已经有一处有效居所。", context.request_id, operation_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except PlayerStageConflictError:
            return CommandResult(False, "PLAYER_STAGE_CONFLICT", "当前阶段还不能租住居所。", context.request_id, operation_id)
        except CurrencyInsufficientError:
            return CommandResult(False, "CURRENCY_INSUFFICIENT", "灵石不足，无法支付租金。", context.request_id, operation_id)
        except LocalReputationInsufficientError:
            return CommandResult(False, "LOCAL_REPUTATION_INSUFFICIENT", "地方名望不足，暂不能租住该居所。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能租住居所。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于其他居所操作，请重新发起。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        definition = residence_definition(record.residence_key)
        return CommandResult(
            True,
            "RESIDENCE_LEASED",
            (
                "## 居所已登记\n\n"
                f"**{self._display_name(record.player)}**租下了{definition.label}。\n\n"
                f"- **租金**：灵石 {record.rent_cost}\n"
                f"- **有效至**：{record.ends_at}\n"
                "- **用途**：可进行静养闭关与后续居所经营\n\n"
                "> 居所到期后不能开启新的居所玩法；已有快照按原规则结算。"
            ),
            context.request_id,
            operation_id,
            data={"residence_id": record.residence_id, "residence_key": record.residence_key, "status": record.status, "ends_at": record.ends_at, "rent_cost": record.rent_cost, "idempotent_replay": record.already_completed},
        )

    async def get_profile(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_RESIDENCE_COMMAND", "查看居所无需附加参数。", context.request_id)
        try:
            record = await self.repository.get_residence(platform=context.adapter, platform_user_id=context.user_id)
        except ResidenceNotFoundError:
            return CommandResult(False, "RESIDENCE_NOT_FOUND", "你还没有居所，请先发送 `租住居所`。", context.request_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能查看居所。", context.request_id)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, retryable=True)
        definition = residence_definition(record.residence_key)
        return CommandResult(
            True,
            "RESIDENCE_PROFILE",
            f"## 我的居所\n\n**{self._display_name(record.player)}**当前居住在{definition.label}。\n\n- **状态**：{record.status}\n- **有效至**：{record.ends_at}\n- **静养闭关**：可用",
            context.request_id,
            data={"residence_id": record.residence_id, "residence_key": record.residence_key, "status": record.status, "ends_at": record.ends_at},
        )

    async def plant(self, context: CommandContext) -> CommandResult:
        crop_key = self._resolve_crop(context.command_args)
        if crop_key is None:
            return CommandResult(False, "INVALID_CROP", "可用 `灵田播种` 或 `灵田播种 止血草`。", context.request_id)
        operation_id = self._operation_id(context, "livelihood.plant")
        try:
            record = await self.repository.plant_plot(
                platform=context.adapter,
                platform_user_id=context.user_id,
                crop_key=crop_key,
                operation_id=operation_id,
            )
        except CropContentClosedError:
            return CommandResult(False, "LIVELIHOOD_CONTENT_CLOSED", "该作物暂未开放。", context.request_id, operation_id)
        except ResidenceRequiredError:
            return CommandResult(False, "RESIDENCE_REQUIRED", "播种需要先租住有效居所。", context.request_id, operation_id)
        except ResidencePlotRequiredError:
            return CommandResult(False, "RESIDENCE_REQUIRED", "当前居所没有可用灵田。", context.request_id, operation_id)
        except FieldPlotBusyError:
            return CommandResult(False, "FIELD_PLOT_BUSY", "灵田已有作物，请先收获。", context.request_id, operation_id)
        except CropDailyLimitError:
            return CommandResult(False, "CROP_DAILY_LIMIT", "该作物今日播种次数已用尽。", context.request_id, operation_id)
        except ResourceInsufficientError:
            return CommandResult(False, "RESOURCE_INSUFFICIENT", "种子或精力不足，无法播种。", context.request_id, operation_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能经营灵田。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于其他灵田操作。", context.request_id, operation_id)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        return CommandResult(
            True,
            "FIELD_PLOT_PLANTED",
            f"## 灵田已播种\n\n已种下**{crop_definition(record.crop_key).label}**。\n\n- **预计成熟**：{record.harvest_at}\n- **维护**：需要 {record.required_maintenance} 次\n- **状态**：生长中",
            context.request_id,
            operation_id,
            data={"plot_id": record.plot_id, "crop_key": record.crop_key, "status": record.status, "harvest_at": record.harvest_at, "maintenance_count": record.maintenance_count, "required_maintenance": record.required_maintenance, "idempotent_replay": record.already_completed},
        )

    async def maintain(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_FIELD_PLOT_COMMAND", "灵田维护无需附加参数。", context.request_id)
        operation_id = self._operation_id(context, "livelihood.maintain_plot")
        try:
            record = await self.repository.maintain_plot(
                platform=context.adapter,
                platform_user_id=context.user_id,
                operation_id=operation_id,
            )
        except FieldPlotNotFoundError:
            return CommandResult(False, "FIELD_PLOT_NOT_FOUND", "当前没有可维护的灵田。", context.request_id, operation_id)
        except FieldPlotNotReadyError:
            return CommandResult(False, "PLOT_MAINTENANCE_MISSED", "当前不在灵田维护阶段。", context.request_id, operation_id)
        except FieldPlotWitheredError:
            return CommandResult(False, "PLOT_WITHERED", "灵田作物已经枯萎。", context.request_id, operation_id)
        except ResourceInsufficientError:
            return CommandResult(False, "RESOURCE_INSUFFICIENT", "精力不足，无法维护灵田。", context.request_id, operation_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于其他灵田操作。", context.request_id, operation_id)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        return CommandResult(
            True,
            "FIELD_PLOT_MAINTAINED",
            f"## 灵田维护完成\n\n已完成 1 次维护，还需 {max(0, record.required_maintenance - record.maintenance_count)} 次。",
            context.request_id,
            operation_id,
            data={"plot_id": record.plot_id, "status": record.status, "maintenance_count": record.maintenance_count, "required_maintenance": record.required_maintenance, "idempotent_replay": record.already_completed},
        )

    async def harvest(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_FIELD_PLOT_COMMAND", "灵田收获无需附加参数。", context.request_id)
        operation_id = self._operation_id(context, "livelihood.harvest")
        try:
            record = await self.repository.harvest_plot(
                platform=context.adapter,
                platform_user_id=context.user_id,
                operation_id=operation_id,
            )
        except FieldPlotNotFoundError:
            return CommandResult(False, "FIELD_PLOT_NOT_FOUND", "当前没有可收获的灵田。", context.request_id, operation_id)
        except FieldPlotAlreadyHarvestedError:
            return CommandResult(False, "FIELD_PLOT_ALREADY_HARVESTED", "这块灵田已经收获过了。", context.request_id, operation_id)
        except FieldPlotNotReadyError:
            return CommandResult(False, "PLOT_NOT_READY", "作物尚未成熟，请稍后再来。", context.request_id, operation_id)
        except FieldPlotWitheredError:
            return CommandResult(False, "PLOT_WITHERED", "灵田作物已经枯萎，无法收获。", context.request_id, operation_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于其他灵田操作。", context.request_id, operation_id)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        items = "、".join(f"{key} ×{value}" for key, value in record.harvest.items()) or "无"
        return CommandResult(
            True,
            "FIELD_PLOT_HARVESTED",
            f"## 灵田收获完成\n\n- **收获**：{items}\n- **地方名望**：+{record.local_reputation_delta}\n- **状态**：已收获",
            context.request_id,
            operation_id,
            data={"plot_id": record.plot_id, "status": record.status, "harvest": record.harvest, "local_reputation_delta": record.local_reputation_delta, "idempotent_replay": record.already_completed},
        )

    async def get_plot_profile(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_FIELD_PLOT_COMMAND", "查看灵田无需附加参数。", context.request_id)
        try:
            record = await self.repository.get_field_plot(
                platform=context.adapter,
                platform_user_id=context.user_id,
            )
        except FieldPlotNotFoundError:
            return CommandResult(False, "FIELD_PLOT_NOT_FOUND", "当前还没有灵田记录。", context.request_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, retryable=True)
        label = crop_definition(record.crop_key).label if record.crop_key else "无"
        return CommandResult(
            True,
            "FIELD_PLOT_PROFILE",
            f"## 我的灵田\n\n- **作物**：{label}\n- **状态**：{record.status}\n- **维护**：{record.maintenance_count}/{record.required_maintenance}\n- **预计成熟**：{record.harvest_at or '无'}",
            context.request_id,
            data={"plot_id": record.plot_id, "crop_key": record.crop_key, "status": record.status, "harvest_at": record.harvest_at, "maintenance_count": record.maintenance_count, "required_maintenance": record.required_maintenance},
        )

    async def list_commissions(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_COMMISSION_COMMAND", "查看城镇委托无需附加参数。", context.request_id)
        try:
            records = await self.repository.list_commissions(
                platform=context.adapter,
                platform_user_id=context.user_id,
            )
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能查看城镇委托。", context.request_id)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, retryable=True)
        lines = ["## 今日城镇委托", ""]
        data = []
        for record in records:
            inputs = "、".join(f"{key} ×{value}" for key, value in record.inputs.items())
            state = "已交付" if record.delivered else "已接取" if record.accepted else record.status
            lines.extend(
                [
                    f"### {record.label}",
                    f"- **指令键**：`{record.commission_key}`",
                    f"- **需求**：{inputs}",
                    f"- **报酬**：灵石 {record.reward_stones}；名望 +{record.local_reputation}；信誉 +{record.service_reputation}",
                    f"- **库存**：{record.stock_remaining}/{record.stock_total}",
                    f"- **状态**：{state}；截止 {record.expires_at}",
                    "",
                ]
            )
            data.append(
                {
                    "commission_id": record.commission_id,
                    "commission_key": record.commission_key,
                    "label": record.label,
                    "status": record.status,
                    "stock_remaining": record.stock_remaining,
                    "stock_total": record.stock_total,
                    "accepted": record.accepted,
                    "delivered": record.delivered,
                    "expires_at": record.expires_at,
                }
            )
        return CommandResult(True, "COMMISSION_LIST", "\n".join(lines).rstrip(), context.request_id, data={"commissions": data})

    async def accept_commission(self, context: CommandContext) -> CommandResult:
        key = self._resolve_commission(context.command_args)
        if key is None:
            return CommandResult(False, "INVALID_COMMISSION", "可用 `接取委托 止血草供应`、`接取委托 工具修缮` 或 `接取委托 灵米饭供应`。", context.request_id)
        operation_id = self._operation_id(context, "livelihood.accept_commission")
        try:
            record = await self.repository.accept_commission(
                platform=context.adapter,
                platform_user_id=context.user_id,
                commission_key=key,
                operation_id=operation_id,
            )
        except CommissionNotFoundError:
            return CommandResult(False, "LIVELIHOOD_CONTENT_CLOSED", "该城镇委托今天未开放。", context.request_id, operation_id)
        except CommissionExpiredError:
            return CommandResult(False, "COMMISSION_EXPIRED", "该城镇委托已过期。", context.request_id, operation_id)
        except CommissionStockExhaustedError:
            return CommandResult(False, "COMMISSION_STOCK_EXHAUSTED", "该城镇委托的全服库存已耗尽。", context.request_id, operation_id)
        except CommissionAlreadyAcceptedError:
            return CommandResult(False, "COMMISSION_ALREADY_ACCEPTED", "你已经接取过这项城镇委托。", context.request_id, operation_id)
        except CommissionQuotaError:
            return CommandResult(False, "COMMISSION_QUOTA_EXHAUSTED", "今日最多接取两项城镇委托。", context.request_id, operation_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能接取城镇委托。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于其他城镇委托操作。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        return CommandResult(
            True,
            "COMMISSION_ACCEPTED",
            f"## 委托已接取\n\n**{record.label}**已登记。交付时才会检查并扣除物品。\n\n- **需求**：{'、'.join(f'{key} ×{value}' for key, value in record.inputs.items())}\n- **截止**：{record.expires_at}\n- **剩余库存**：{record.stock_remaining}",
            context.request_id,
            operation_id,
            data={"claim_id": record.claim_id, "commission_id": record.commission_id, "commission_key": record.commission_key, "status": record.status, "stock_remaining": record.stock_remaining, "idempotent_replay": record.already_completed},
        )

    async def deliver_commission(self, context: CommandContext) -> CommandResult:
        key = self._resolve_commission(context.command_args, required=False)
        if len(context.command_args) > 1 or (context.command_args and key is None):
            return CommandResult(False, "INVALID_COMMISSION", "可用 `交付委托 [止血草供应]`。", context.request_id)
        operation_id = self._operation_id(context, "livelihood.deliver_commission")
        try:
            record = await self.repository.deliver_commission(
                platform=context.adapter,
                platform_user_id=context.user_id,
                commission_key=key,
                operation_id=operation_id,
            )
        except CommissionNotAcceptedError:
            return CommandResult(False, "COMMISSION_NOT_ACCEPTED", "没有可交付的城镇委托。", context.request_id, operation_id)
        except CommissionAlreadyDeliveredError:
            return CommandResult(False, "COMMISSION_ALREADY_DELIVERED", "这项城镇委托已经交付过了。", context.request_id, operation_id)
        except CommissionExpiredError:
            return CommandResult(False, "COMMISSION_EXPIRED", "该城镇委托已过期，未扣除物品。", context.request_id, operation_id)
        except CommissionMaterialInsufficientError:
            return CommandResult(False, "RESOURCE_INSUFFICIENT", "交付所需物品不足，未扣除任何物品。", context.request_id, operation_id)
        except CommissionNotFoundError:
            return CommandResult(False, "LIVELIHOOD_CONTENT_CLOSED", "该城镇委托不存在。", context.request_id, operation_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能交付城镇委托。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于其他城镇委托操作。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        return CommandResult(
            True,
            "COMMISSION_DELIVERED",
            f"## 委托已交付\n\n**{record.label}**结算完成。\n\n- **灵石**：+{record.reward_stones}\n- **地方名望**：+{record.local_reputation}\n- **服务信誉**：+{record.service_reputation}",
            context.request_id,
            operation_id,
            data={"commission_id": record.commission_id, "commission_key": record.commission_key, "status": record.status, "reward_stones": record.reward_stones, "local_reputation": record.local_reputation, "service_reputation": record.service_reputation, "idempotent_replay": record.already_completed},
        )


__all__ = ["LivelihoodApplication"]
