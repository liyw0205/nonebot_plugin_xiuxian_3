"""Application services for residence leasing and inspection."""

from __future__ import annotations

import logging

from ...contracts import CommandAction, CommandContext, CommandResult
from ..content import ContentError, bundled_content
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
    CommissionRequirementError,
    CommissionStockExhaustedError,
    CurrencyInsufficientError,
    FieldPlotAlreadyHarvestedError,
    FieldPlotBusyError,
    FieldPlotNotFoundError,
    FieldPlotNotReadyError,
    FieldPlotSlotError,
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
    RestBlockedError,
    RestDailyLimitError,
    RestNotFoundError,
    RestNotNeededError,
    RestNotReadyError,
    SQLitePlayerRepository,
    ResourceInsufficientError,
    StorageCapacityError,
    StorageItemNotFoundError,
    StorageQuantityError,
    TradePermitContentClosedError,
    TradePermitRequirementError,
)
from .rules import resolve_commission_key, crop_definitions, residence_definitions
from ..utils.text import command_link
from .trade_permit_rules import resolve_trade_permit
from ..items.rules import item_aliases, item_records

_BLOCK_LABELS = {
    "rest": "静养",
    "travel": "赶路",
    "retreat": "闭关",
    "cultivation": "修炼",
    "production": "生产",
    "exploration": "探索",
    "battle": "战斗",
}

logger = logging.getLogger(__name__)


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

    def _resolve_args(self, args: tuple[str, ...]) -> str | None:
        if len(args) > 1:
            return None
        return args[0].strip() if args else ""

    def _resolve_crop(self, args: tuple[str, ...]) -> tuple[str, int | None, str] | None:
        values = list(args)
        if not values:
            return "", None, ""
        if len(values) > 3:
            return None
        crop = values[0].strip()
        if len(values) == 1:
            return crop, None, ""
        raw_slot = values[1].strip()
        if not raw_slot.isascii() or not raw_slot.isdecimal():
            return (crop, None, raw_slot) if len(values) == 2 else None
        if len(raw_slot) > 10:
            return None
        slot = int(raw_slot)
        return (crop, slot, values[2] if len(values) == 3 else "") if slot >= 1 else None

    @staticmethod
    def _field_error(context: CommandContext, operation_id: str, exc: Exception, command: str) -> CommandResult:
        errors = {
            CropContentClosedError: ("LIVELIHOOD_CONTENT_CLOSED", "作物或照料方案不可用"),
            ResidenceRequiredError: ("RESIDENCE_REQUIRED", "播种需要有效居所"),
            ResidencePlotRequiredError: ("RESIDENCE_REQUIRED", "居所不支持该作物"),
            FieldPlotSlotError: ("INVALID_FIELD_SLOT", "田垄不在可用范围内"),
            FieldPlotBusyError: ("FIELD_PLOT_BUSY", "田垄已有作物，请先收获"),
            CropDailyLimitError: ("CROP_DAILY_LIMIT", "该作物今日播种次数已用尽"),
            ResourceInsufficientError: ("RESOURCE_INSUFFICIENT", "种子或精力不足"),
            PlayerNotFoundError: ("PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`"),
            PlayerSuspendedError: ("PLAYER_SUSPENDED", "角色暂时不能经营灵田"),
            FieldPlotNotFoundError: ("FIELD_PLOT_NOT_FOUND", "当前没有符合条件的灵田"),
            FieldPlotNotReadyError: ("PLOT_NOT_READY" if command == "灵田收获" else "PLOT_MAINTENANCE_MISSED", "尚未成熟" if command == "灵田收获" else "当前没有尚需照料的生长作物"),
            FieldPlotWitheredError: ("PLOT_WITHERED", "作物已枯萎，不能维护或收获，可重新播种"),
            FieldPlotAlreadyHarvestedError: ("FIELD_PLOT_ALREADY_HARVESTED", "这块田已经收获过了"),
            OperationConflictError: ("OPERATION_CONFLICT", "同一请求已用于不同的灵田安排"),
            RepositoryBusyError: ("PERSISTENCE_BUSY", "灵田事务繁忙，请稍后重试"),
        }
        for kind, (code, message) in errors.items():
            if isinstance(exc, kind):
                return CommandResult(False, code, f"{message}：{exc}。", context.request_id, operation_id or None,
                                     retryable=kind is RepositoryBusyError,
                                     data={"reason": str(exc), "subject": " ".join(context.command_args) or "本人灵田"})
        logger.error("field command failed command=%s adapter=%s request=%s operation=%s args=%r",
                     command, context.adapter, context.request_id, operation_id, context.command_args,
                     exc_info=(type(exc), exc, exc.__traceback__))
        raise exc

    async def preview_field(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) > 1:
            return CommandResult(False, "INVALID_CROP", "可发送 `灵田预览` 或 `灵田预览 止血草`。", context.request_id,
                                 data={"reason": "预览只接受一个作物参数", "subject": " ".join(context.command_args)})
        try:
            content = self.repository.content or bundled_content()
            crops = crop_definitions(content)
            residences = residence_definitions(content)
            selector = context.command_args[0] if context.command_args else ""
            selected = [crop for crop in crops.values() if not selector or selector in (crop.key, crop.label, *crop.aliases)]
            if not selected:
                raise CropContentClosedError(f"没有开放作物：{selector}")
            lines = ["灵田筹划", ""]
            data = []
            for crop in selected:
                homes = "、".join(f"{residences[key].label}（青石镇名望 {residences[key].required_local_reputation}，租金 {residences[key].rent_cost} 灵石）" for key in crop.residence_keys) or "任一有灵田的有效居所"
                lines.extend([f"**{crop.label}** · {homes}",
                              f"种子：{content.label('item', crop.seed_key)} ×{crop.seed_quantity}；每日最多 {crop.daily_limit} 次。",
                              f"常规：{crop.growth_seconds // 3600} 小时，播种精力 {crop.maintenance_energy}，照料 {crop.required_maintenance} 次（每次 {crop.maintenance_energy} 精力），收割窗口 24 小时。"])
                entry = {"crop_key": crop.key, "seed_key": crop.seed_key, "residence_keys": crop.residence_keys, "daily_limit": crop.daily_limit, "plans": []}
                if crop.cultivation:
                    source = crop.cultivation["seed_source"]
                    lines.append(f"种源：{command_link(source['command'], source['command'])}，依来源门槛完成并结算；换种须充分照料后收获。" if source['kind'] == 'crop_plan' else f"种源：{command_link(source['command'], source['command'])}，依来源地点与境界门槛取得并结算。")
                    for plan in crop.cultivation["plans"]:
                        lines.extend([f"**{plan['name']}**：{plan['desc']}",
                                      f"成熟 {plan['growth_seconds'] // 3600} 小时；播种精力 {plan['plant_energy']}；照料 {plan['required_maintenance']} 次 ×{plan['maintenance_energy']} 精力；收割窗口 {plan['harvest_window_seconds'] // 3600} 小时。"])
                        for event in plan["events"]:
                            def rewards(field):
                                return "、".join(f"{content.label('item', key)} ×{quantity}" for key, quantity in event[field].items())
                            lines.append(f"{event['name']}（权重 {event['weight']}）：照料齐 {rewards('harvest')}；不足 {rewards('unmaintained_harvest')}。")
                        lines.append(command_link("播种 " + plan["name"], f"灵田播种 {crop.label} {plan['name']}"))
                        entry["plans"].append(plan)
                    uses = [(content.label("recipe", key), f"生产预览 {key}") for key in crop.cultivation["recipe_keys"]]
                    uses += [(content.label("livelihood", key), f"接取委托 {key}") for key in crop.cultivation["commission_keys"]]
                    lines.append("用途：" + "、".join(command_link(name, command) for name, command in uses))
                    entry["seed_source"] = source
                lines.append("")
                data.append(entry)
            return CommandResult(True, "FIELD_PREVIEW", "\n".join(lines).rstrip(), context.request_id, data={"crops": data})
        except Exception as exc:
            return self._field_error(context, "", exc, "灵田预览")

    @staticmethod
    def _resolve_plot_index(args: tuple[str, ...]) -> tuple[bool, int | None]:
        values = list(args)
        if not values:
            return True, None
        if len(values) > 1:
            return False, None
        raw_slot = values[0].strip()
        if not raw_slot.isascii() or not raw_slot.isdecimal() or len(raw_slot) > 10:
            return False, None
        slot = int(raw_slot)
        if slot < 1:
            return False, None
        return True, slot

    def _resolve_storage_args(self, args: tuple[str, ...]) -> tuple[str, int] | None:
        values = list(args)
        if not values or len(values) > 2:
            return None
        name = values[0].strip()
        if not name:
            return None
        quantity = 1
        if len(values) == 2:
            raw_quantity = values[1].strip()
            if not raw_quantity.isdigit():
                return None
            quantity = int(raw_quantity)
            if quantity < 1:
                return None
        try:
            key = item_aliases(self.repository.content).get(name, name)
        except ContentError:
            return None
        return key, quantity

    def _resolve_commission(self, args: tuple[str, ...], *, required: bool = True) -> str | None:
        if len(args) > 1:
            return None
        if not args and not required:
            return None
        try:
            return resolve_commission_key(args[0] if args else None, self.repository.content)
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
            return CommandResult(False, "OPERATION_CONFLICT", "此事已有安排，请重新起意。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        return CommandResult(
            True,
            "RESIDENCE_LEASED",
            (
                "## 居所已登记\n\n"
                f"**{self._display_name(record.player)}**租下了{record.label}。\n\n"
                f"- **租金**：灵石 {record.rent_cost}\n"
                f"- **有效至**：{record.ends_at}\n"
                "- **用途**：可进行静养闭关与后续居所经营\n\n"
                "> 居所到期后不能开启新的居所玩法；已有快照按原规则结算。"
            ),
            context.request_id,
            operation_id,
            data={"residence_id": record.residence_id, "residence_key": record.residence_key, "status": record.status, "ends_at": record.ends_at, "rent_cost": record.rent_cost, "idempotent_replay": record.already_completed},
        )

    async def issue_trade_permit(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 1:
            return CommandResult(False, "INVALID_TRADE_PERMIT", "请使用 `申请贸易许可 魔界|妖界`。", context.request_id)
        try:
            definition = resolve_trade_permit(context.command_args[0])
        except ValueError:
            return CommandResult(False, "TRADE_PERMIT_NOT_FOUND", "仅可申请魔界或妖界贸易许可。", context.request_id)
        operation_id = self._operation_id(context, "livelihood.issue_trade_permit")
        try:
            record = await self.repository.issue_trade_permit(
                platform=context.adapter,
                platform_user_id=context.user_id,
                permit_key=definition.key,
                operation_id=operation_id,
            )
        except TradePermitContentClosedError:
            return CommandResult(False, "TRADE_PERMIT_CONTENT_CLOSED", "该贸易许可暂未开放。", context.request_id, operation_id)
        except TradePermitRequirementError:
            return CommandResult(False, "TRADE_PERMIT_REQUIREMENT_MISSING", "请先完成对应三界引导并达到阵营声望 80。", context.request_id, operation_id)
        except CurrencyInsufficientError:
            return CommandResult(False, "CURRENCY_INSUFFICIENT", "申请贸易许可需要灵石 500。", context.request_id, operation_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能申请贸易许可。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "此事已有安排，请重新起意。", context.request_id, operation_id)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "许可记录暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        state = "已有有效许可，本次未重复扣费" if record.already_active else f"已扣除灵石 {record.cost}"
        return CommandResult(
            True,
            "TRADE_PERMIT_ISSUED" if not record.already_active else "TRADE_PERMIT_ACTIVE",
            f"{definition.label}{'仍然有效' if record.already_active else '已签发'}。{state}；有效至 {record.expires_at}。",
            context.request_id,
            operation_id,
            data={
                "permit_id": record.permit_id,
                "permit_key": record.permit_key,
                "issued_at": record.issued_at,
                "expires_at": record.expires_at,
                "cost": record.cost,
                "already_active": record.already_active,
                "idempotent_replay": record.already_completed,
            },
        )

    async def get_profile(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_RESIDENCE_COMMAND", "查看居所无需附加参数。", context.request_id)
        try:
            record = await self.repository.get_residence(platform=context.adapter, platform_user_id=context.user_id)
            rest = await self.repository.get_rest_summary(platform=context.adapter, platform_user_id=context.user_id)
            storage = await self.repository.get_storage(platform=context.adapter, platform_user_id=context.user_id)
        except ResidenceNotFoundError:
            return CommandResult(False, "RESIDENCE_NOT_FOUND", "你还没有居所，请先发送 `租住居所`。", context.request_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能查看居所。", context.request_id)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, retryable=True)
        lines = [
            "## 我的居所",
            "",
            f"**{self._display_name(record.player)}**当前居住在{record.label}。",
            "",
            f"- **状态**：{record.status}",
            f"- **有效至**：{record.ends_at}",
            f"- **休整位**：{rest['rest_slots']}（今日休整 {rest['used_today']}/{rest['daily_limit']}）",
        ]
        if rest["running_until"]:
            lines.append(f"- **静养中**：将于 {rest['running_until']} 结束")
        lines.append("- **静养闭关**：可发送 `休整`，结束后 `结算休整`")
        lines.append(f"- **物资箱**：{storage.used_slots}/{storage.capacity} 格")
        return CommandResult(
            True,
            "RESIDENCE_PROFILE",
            "\n".join(lines),
            context.request_id,
            data={
                "residence_id": record.residence_id,
                "residence_key": record.residence_key,
                "status": record.status,
                "ends_at": record.ends_at,
                "rest_slots": rest["rest_slots"],
                "rest_used_today": rest["used_today"],
                "rest_daily_limit": rest["daily_limit"],
                "rest_running_until": rest["running_until"],
                "storage_capacity": storage.capacity,
                "storage_used_slots": storage.used_slots,
            },
        )

    async def rest(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_REST_COMMAND", "静养无需附加参数。", context.request_id)
        operation_id = self._operation_id(context, "livelihood.rest")
        try:
            record = await self.repository.start_rest(
                platform=context.adapter,
                platform_user_id=context.user_id,
                operation_id=operation_id,
            )
        except ResidenceRequiredError:
            return CommandResult(False, "RESIDENCE_REQUIRED", "静养需要先租住有效居所。", context.request_id, operation_id)
        except ResidencePlotRequiredError:
            return CommandResult(False, "RESIDENCE_REQUIRED", "当前居所没有休整位。", context.request_id, operation_id)
        except RestNotNeededError:
            return CommandResult(False, "REST_NOT_NEEDED", "体力与精力都已充盈，无需静养。", context.request_id, operation_id)
        except RestDailyLimitError:
            return CommandResult(False, "REST_DAILY_LIMIT", "今日休整次数已用尽，明日再来。", context.request_id, operation_id)
        except RestBlockedError as exc:
            label = _BLOCK_LABELS.get(exc.reason, "其他事务")
            return CommandResult(False, "REST_BLOCKED", f"你正在{label}，稍后再静养。", context.request_id, operation_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能静养。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "此事已有安排，请重新起意。", context.request_id, operation_id)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        return CommandResult(
            True,
            "REST_STARTED",
            (
                f"## 开始静养\n\n在{record.residence_label}静养片刻。\n\n"
                f"- **结束时间**：{record.ends_at}\n"
                f"- **今日休整**：{record.used_today}/{record.daily_limit}"
            ),
            context.request_id,
            operation_id,
            data={
                "rest_id": record.rest_id,
                "residence_key": record.residence_key,
                "status": record.status,
                "starts_at": record.starts_at,
                "ends_at": record.ends_at,
                "daily_limit": record.daily_limit,
                "used_today": record.used_today,
                "idempotent_replay": record.already_completed,
            },
        )

    async def settle_rest(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_REST_COMMAND", "结算静养无需附加参数。", context.request_id)
        operation_id = self._operation_id(context, "livelihood.rest_settle")
        try:
            record = await self.repository.settle_rest(
                platform=context.adapter,
                platform_user_id=context.user_id,
                operation_id=operation_id,
            )
        except RestNotFoundError:
            return CommandResult(False, "REST_NOT_FOUND", "当前没有进行中的静养。", context.request_id, operation_id)
        except RestNotReadyError:
            return CommandResult(False, "REST_NOT_READY", "静养尚未结束，请稍后再来。", context.request_id, operation_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能结算静养。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "此事已有安排，请重新起意。", context.request_id, operation_id)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        return CommandResult(
            True,
            "REST_SETTLED",
            (
                f"## 静养结束\n\n"
                f"- **恢复体力**：+{record.restored_stamina}\n"
                f"- **恢复精力**：+{record.restored_energy}\n"
                f"- **今日休整**：{record.used_today}/{record.daily_limit}"
            ),
            context.request_id,
            operation_id,
            data={
                "rest_id": record.rest_id,
                "status": record.status,
                "restored_stamina": record.restored_stamina,
                "restored_energy": record.restored_energy,
                "idempotent_replay": record.already_completed,
            },
        )

    async def deposit_storage(self, context: CommandContext) -> CommandResult:
        resolved = self._resolve_storage_args(context.command_args)
        if resolved is None:
            return CommandResult(False, "INVALID_STORAGE_COMMAND", "可用 `存入居所 止血草 3` 指定物品与数量。", context.request_id)
        item_key, quantity = resolved
        if item_key not in item_records(self.repository.content):
            return CommandResult(False, "ITEM_NOT_FOUND", "没有找到这件物品。", context.request_id)
        operation_id = self._operation_id(context, "livelihood.deposit_storage")
        try:
            record = await self.repository.deposit_storage(
                platform=context.adapter,
                platform_user_id=context.user_id,
                item_key=item_key,
                quantity=quantity,
                operation_id=operation_id,
            )
        except ResidenceRequiredError:
            return CommandResult(False, "RESIDENCE_REQUIRED", "存入居所需要先租住有效居所。", context.request_id, operation_id)
        except StorageCapacityError:
            return CommandResult(False, "STORAGE_FULL", "物资箱格数已满，先取回一些物品。", context.request_id, operation_id)
        except ResourceInsufficientError:
            return CommandResult(False, "RESOURCE_INSUFFICIENT", "行囊中的数量不足。", context.request_id, operation_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能存取物资。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "此事已有安排，请重新起意。", context.request_id, operation_id)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        return CommandResult(
            True,
            "STORAGE_DEPOSITED",
            (
                f"## 已存入居所\n\n"
                f"- **物品**：{record.label} ×{record.quantity}\n"
                f"- **物资箱**：{record.label} ×{record.stored_quantity}\n"
                f"- **格数**：{record.used_slots}/{record.capacity}"
            ),
            context.request_id,
            operation_id,
            data={
                "item_key": record.item_key,
                "quantity": record.quantity,
                "stored_quantity": record.stored_quantity,
                "used_slots": record.used_slots,
                "capacity": record.capacity,
                "idempotent_replay": record.already_completed,
            },
        )

    async def withdraw_storage(self, context: CommandContext) -> CommandResult:
        resolved = self._resolve_storage_args(context.command_args)
        if resolved is None:
            return CommandResult(False, "INVALID_STORAGE_COMMAND", "可用 `取回居所 止血草 3` 指定物品与数量。", context.request_id)
        item_key, quantity = resolved
        if item_key not in item_records(self.repository.content):
            return CommandResult(False, "ITEM_NOT_FOUND", "没有找到这件物品。", context.request_id)
        operation_id = self._operation_id(context, "livelihood.withdraw_storage")
        try:
            record = await self.repository.withdraw_storage(
                platform=context.adapter,
                platform_user_id=context.user_id,
                item_key=item_key,
                quantity=quantity,
                operation_id=operation_id,
            )
        except StorageItemNotFoundError:
            return CommandResult(False, "STORAGE_ITEM_NOT_FOUND", "物资箱里没有这件物品。", context.request_id, operation_id)
        except StorageQuantityError:
            return CommandResult(False, "STORAGE_QUANTITY_INSUFFICIENT", "取回数量超过物资箱库存。", context.request_id, operation_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能存取物资。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "此事已有安排，请重新起意。", context.request_id, operation_id)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        return CommandResult(
            True,
            "STORAGE_WITHDRAWN",
            (
                f"## 已取回物资\n\n"
                f"- **物品**：{record.label} ×{record.quantity}\n"
                f"- **物资箱剩余**：{record.label} ×{record.stored_quantity}\n"
                f"- **格数**：{record.used_slots}/{record.capacity}"
            ),
            context.request_id,
            operation_id,
            data={
                "item_key": record.item_key,
                "quantity": record.quantity,
                "stored_quantity": record.stored_quantity,
                "used_slots": record.used_slots,
                "capacity": record.capacity,
                "idempotent_replay": record.already_completed,
            },
        )

    async def get_storage(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_STORAGE_COMMAND", "查看物资箱无需附加参数。", context.request_id)
        try:
            record = await self.repository.get_storage(
                platform=context.adapter,
                platform_user_id=context.user_id,
            )
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能查看物资箱。", context.request_id)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, retryable=True)
        lines = ["## 我的物资箱", "", f"- **格数**：{record.used_slots}/{record.capacity}"]
        if record.items:
            lines.append("")
            lines.extend(f"- {item.label} ×{item.quantity}" for item in record.items)
        else:
            lines.append("- **内容**：空")
        return CommandResult(
            True,
            "STORAGE_PROFILE",
            "\n".join(lines),
            context.request_id,
            data={
                "capacity": record.capacity,
                "used_slots": record.used_slots,
                "items": [
                    {"item_key": item.item_key, "label": item.label, "quantity": item.quantity}
                    for item in record.items
                ],
            },
        )

    async def plant(self, context: CommandContext) -> CommandResult:
        resolved = self._resolve_crop(context.command_args)
        if resolved is None:
            return CommandResult(False, "INVALID_CROP", "可发送 `灵田播种 止血草 缓养`，或 `灵田播种 云纹稻 2 精耕`。", context.request_id,
                                 data={"reason": "播种参数应为作物、可选田垄和可选方案", "subject": " ".join(context.command_args)})
        crop_key, plot_index, plan_value = resolved
        operation_id = self._operation_id(context, "livelihood.plant")
        try:
            record = await self.repository.plant_plot(
                platform=context.adapter,
                platform_user_id=context.user_id,
                crop_key=crop_key,
                operation_id=operation_id,
                plot_index=plot_index,
                plan_value=plan_value,
            )
        except Exception as exc:
            return self._field_error(context, operation_id, exc, "灵田播种")
        narrative = record.cultivation["event"]["start_text"] + "\n\n" if record.cultivation else ""
        return CommandResult(
            True,
            "FIELD_PLOT_PLANTED",
            f"灵田已播种\n\n{narrative}第 {record.plot_index} 垄 · **{record.crop_label}** · {record.cultivation.get('plan_name', '常规')}\n成熟：{record.harvest_at}\n收割截止：{record.wither_at}\n照料：需要 {record.required_maintenance} 次",
            context.request_id,
            operation_id,
            data={"plot_id": record.plot_id, "plot_index": record.plot_index, "crop_key": record.crop_key, "status": record.status, "harvest_at": record.harvest_at, "wither_at": record.wither_at, "cultivation": record.cultivation, "maintenance_count": record.maintenance_count, "required_maintenance": record.required_maintenance, "idempotent_replay": record.already_completed},
            actions=(CommandAction("照料", f"灵田维护 {record.plot_index}", enter=True), CommandAction("田间状态", "我的灵田", enter=True)),
        )

    async def maintain(self, context: CommandContext) -> CommandResult:
        valid, plot_index = self._resolve_plot_index(context.command_args)
        if not valid:
            return CommandResult(False, "INVALID_FIELD_SLOT", "可发送 `灵田维护` 或 `灵田维护 2` 指定田垄。", context.request_id,
                                 data={"reason": "田垄号应为正整数", "subject": " ".join(context.command_args)})
        operation_id = self._operation_id(context, "livelihood.maintain_plot")
        try:
            record = await self.repository.maintain_plot(
                platform=context.adapter,
                platform_user_id=context.user_id,
                operation_id=operation_id,
                plot_index=plot_index,
            )
        except Exception as exc:
            return self._field_error(context, operation_id, exc, "灵田维护")
        narrative = record.cultivation["event"]["maintenance_text"] + "\n\n" if record.cultivation else ""
        return CommandResult(
            True,
            "FIELD_PLOT_MAINTAINED",
            f"灵田维护完成\n\n{narrative}第 {record.plot_index} 垄已完成 1 次维护，还需 {max(0, record.required_maintenance - record.maintenance_count)} 次。",
            context.request_id,
            operation_id,
            data={"plot_id": record.plot_id, "plot_index": record.plot_index, "status": record.status, "maintenance_count": record.maintenance_count, "required_maintenance": record.required_maintenance, "idempotent_replay": record.already_completed},
        )

    async def harvest(self, context: CommandContext) -> CommandResult:
        valid, plot_index = self._resolve_plot_index(context.command_args)
        if not valid:
            return CommandResult(False, "INVALID_FIELD_SLOT", "可发送 `灵田收获` 或 `灵田收获 2` 指定田垄。", context.request_id,
                                 data={"reason": "田垄号应为正整数", "subject": " ".join(context.command_args)})
        operation_id = self._operation_id(context, "livelihood.harvest")
        try:
            record = await self.repository.harvest_plot(
                platform=context.adapter,
                platform_user_id=context.user_id,
                operation_id=operation_id,
                plot_index=plot_index,
            )
        except Exception as exc:
            return self._field_error(context, operation_id, exc, "灵田收获")
        items = "、".join(f"{record.harvest_labels[key]} ×{value}" for key, value in record.harvest.items()) or "无"
        maintained = record.maintenance_count >= record.required_maintenance
        narrative = (record.cultivation["event"]["complete_text" if maintained else "fallback_text"] + "\n\n") if record.cultivation else ""
        uses = "\n用途：" + "、".join(command_link(use["name"], use["command"]) for use in record.cultivation["uses"]) if record.cultivation else ""
        return CommandResult(
            True,
            "FIELD_PLOT_HARVESTED",
            f"灵田收获完成\n\n{narrative}第 {record.plot_index} 垄 · {'照料充分' if maintained else '照料不足'}\n收获：{items}\n地方名望：+{record.local_reputation_delta}{uses}",
            context.request_id,
            operation_id,
            data={"plot_id": record.plot_id, "plot_index": record.plot_index, "status": record.status, "harvest": record.harvest, "maintained": maintained, "cultivation": record.cultivation, "local_reputation_delta": record.local_reputation_delta, "idempotent_replay": record.already_completed},
        )

    async def get_plot_profile(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_FIELD_PLOT_COMMAND", "查看灵田无需附加参数。", context.request_id,
                                 data={"reason": "查看灵田不接受参数", "subject": " ".join(context.command_args)})
        try:
            primary = await self.repository.get_field_plot(
                platform=context.adapter,
                platform_user_id=context.user_id,
            )
            plot_count, records = await self.repository.get_field_plots(
                platform=context.adapter,
                platform_user_id=context.user_id,
            )
        except Exception as exc:
            return self._field_error(context, "", exc, "我的灵田")
        state_labels = {"growing": "生长中", "harvestable": "待收获", "harvested": "已收获", "withered": "已枯萎"}
        by_slot = {record.plot_index: record for record in records}
        slots = sorted(set(by_slot) | set(range(1, plot_count + 1)))
        lines = ["我的灵田", ""]
        payload = []
        actions = []
        for slot in slots:
            record = by_slot.get(slot)
            if record is None:
                lines.append(f"- **第 {slot} 垄**：空闲")
                payload.append({"plot_index": slot, "status": "idle"})
                continue
            label = record.crop_label if record.crop_key else "无"
            line = (
                f"- **第 {slot} 垄**：{label} · {state_labels[record.status]} · "
                f"维护 {record.maintenance_count}/{record.required_maintenance} · "
                f"预计成熟 {record.harvest_at or '无'}"
            )
            lines.append(line)
            if record.cultivation:
                lines.append(f"{record.cultivation['plan_name']} · {record.cultivation['event']['name']}\n{record.cultivation['event']['start_text']}")
            lines.append(f"收割截止：{record.wither_at}")
            if record.status == "growing" and record.maintenance_count < record.required_maintenance and len(actions) < 2:
                actions.append(CommandAction(f"照料第{slot}垄", f"灵田维护 {slot}", enter=True))
            elif record.status == "harvestable" and len(actions) < 2:
                actions.append(CommandAction(f"收获第{slot}垄", f"灵田收获 {slot}", enter=True))
            elif record.status in {"harvested", "withered"}:
                lines.append(command_link("重新筹划", f"灵田预览 {record.crop_key}"))
            payload.append(
                {
                    "plot_index": slot,
                    "plot_id": record.plot_id,
                    "crop_key": record.crop_key,
                    "status": record.status,
                    "harvest_at": record.harvest_at,
                    "maintenance_count": record.maintenance_count,
                    "required_maintenance": record.required_maintenance,
                    "wither_at": record.wither_at,
                    "cultivation": record.cultivation,
                }
            )
        return CommandResult(
            True,
            "FIELD_PLOT_PROFILE",
            "\n".join(lines),
            context.request_id,
            data={
                "plot_id": primary.plot_id,
                "plot_count": plot_count,
                "crop_key": primary.crop_key,
                "status": primary.status,
                "harvest_at": primary.harvest_at,
                "maintenance_count": primary.maintenance_count,
                "required_maintenance": primary.required_maintenance,
                "plots": payload,
            },
            actions=tuple(actions),
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
        lines = ["## 今日委托", ""]
        data = []
        content = self.repository.content or bundled_content()
        for record in records:
            inputs = "、".join(f"{content.label('item', key)} ×{value}" for key, value in record.inputs.items())
            state = (
                "已交付" if record.delivered else "已接取" if record.accepted
                else "待接取" if record.status == "published" else "已过期"
            )
            lines.extend(
                [
                    f"### {record.label}",
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
        operation_id = self._operation_id(context, "livelihood.accept_commission")
        try:
            replay = await self.repository.replay_commission_accept(
                platform=context.adapter,
                platform_user_id=context.user_id,
                operation_id=operation_id,
                request_args=context.command_args,
            )
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "仙缘簿中已记有另一项委托，请重新传讯。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        if replay is not None:
            return self._accepted_commission_result(context, operation_id, replay)
        key = self._resolve_commission(context.command_args)
        if key is None:
            return CommandResult(False, "INVALID_COMMISSION", "请使用 `接取委托 <订单名>`，订单名可从 `城镇委托` 查询。", context.request_id)
        try:
            record = await self.repository.accept_commission(
                platform=context.adapter,
                platform_user_id=context.user_id,
                commission_key=key,
                operation_id=operation_id,
                request_args=context.command_args,
            )
        except CommissionNotFoundError:
            return CommandResult(False, "LIVELIHOOD_CONTENT_CLOSED", "该城镇委托今天未开放。", context.request_id, operation_id)
        except CommissionRequirementError:
            return CommandResult(False, "COMMISSION_REQUIREMENT_MISSING", "境界或云城名望尚未达到该订单要求。", context.request_id, operation_id)
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
            return CommandResult(False, "OPERATION_CONFLICT", "仙缘簿中已记有另一项委托，请重新传讯。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        return self._accepted_commission_result(context, operation_id, record)

    async def deliver_commission(self, context: CommandContext) -> CommandResult:
        operation_id = self._operation_id(context, "livelihood.deliver_commission")
        try:
            replay = await self.repository.replay_commission_deliver(
                platform=context.adapter,
                platform_user_id=context.user_id,
                operation_id=operation_id,
                request_args=context.command_args,
            )
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "仙缘簿中已记有另一项委托，请重新传讯。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        if replay is not None:
            return self._delivered_commission_result(context, operation_id, replay)
        key = self._resolve_commission(context.command_args, required=False)
        if len(context.command_args) > 1 or (context.command_args and key is None):
            return CommandResult(False, "INVALID_COMMISSION", "可用 `交付委托 [订单名]`。", context.request_id)
        try:
            record = await self.repository.deliver_commission(
                platform=context.adapter,
                platform_user_id=context.user_id,
                commission_key=key,
                operation_id=operation_id,
                request_args=context.command_args,
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
            return CommandResult(False, "OPERATION_CONFLICT", "仙缘簿中已记有另一项委托，请重新传讯。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        return self._delivered_commission_result(context, operation_id, record)

    def _accepted_commission_result(self, context: CommandContext, operation_id: str, record) -> CommandResult:
        inputs = "、".join(
            f"{record.input_labels[key]} ×{value}" for key, value in record.inputs.items()
        )
        return CommandResult(
            True,
            "COMMISSION_ACCEPTED",
            f"## 委托已接取\n\n**{record.label}**已记入委托簿，备齐所需物品即可交付。\n\n- **需求**：{inputs}\n- **截止**：{record.expires_at}\n- **剩余库存**：{record.stock_remaining}",
            context.request_id,
            operation_id,
            data={"claim_id": record.claim_id, "commission_id": record.commission_id, "commission_key": record.commission_key, "status": record.status, "stock_remaining": record.stock_remaining, "idempotent_replay": record.already_completed},
        )

    @staticmethod
    def _delivered_commission_result(context: CommandContext, operation_id: str, record) -> CommandResult:
        return CommandResult(
            True,
            "COMMISSION_DELIVERED",
            f"## 委托已交付\n\n**{record.label}**已交清，酬劳收入囊中。\n\n- **灵石**：+{record.reward_stones}\n- **地方名望**：{record.local_reputation:+d}\n- **服务信誉**：{record.service_reputation:+d}",
            context.request_id,
            operation_id,
            data={"commission_id": record.commission_id, "commission_key": record.commission_key, "status": record.status, "reward_stones": record.reward_stones, "local_reputation": record.local_reputation, "service_reputation": record.service_reputation, "idempotent_replay": record.already_completed},
        )


__all__ = ["LivelihoodApplication"]
