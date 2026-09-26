"""Application services for sect membership."""

from __future__ import annotations

from ...contracts import CommandContext, CommandResult
from ..repository import (
    OperationConflictError,
    PlayerNotFoundError,
    PlayerSuspendedError,
    RepositoryBusyError,
    ResourceInsufficientError,
    SectAlreadyJoinedError,
    SectApplicationExpiredError,
    SectApplicationExistsError,
    SectApplicationNotFoundError,
    SectAssetLockedError,
    SectFullError,
    SectJoinCooldownError,
    SectLeaderCannotLeaveError,
    SectNameInvalidError,
    SectNotFoundError,
    SectPermissionDeniedError,
    SectRequirementError,
    SectContributionInsufficientError,
    SectExchangeDailyCapError,
    SectExchangeInvalidOfferError,
    SectStockInsufficientError,
    SectDailyBuildAlreadyCompletedError,
    SectDailyBuildNotReadyError,
    SectWarehouseFullError,
    SectSupplyItemInvalidError,
    SQLitePlayerRepository,
)
from .sect_exchange_rules import SECT_DONATION_ALIASES, SECT_EXCHANGE_OFFERS, SECT_SUPPLY_RECIPES, resolve_sect_exchange_offer
from .sect_rules import role_label


class SectApplication:
    """Translate sect commands into one adapter-neutral application contract."""

    def __init__(self, repository: SQLitePlayerRepository):
        self.repository = repository

    @staticmethod
    def _operation_id(context: CommandContext, operation_name: str) -> str:
        if context.operation_id:
            return context.operation_id
        request_key = context.message_id or context.request_id
        return f"{operation_name}:{context.adapter}:{context.user_id}:{request_key}"

    @staticmethod
    def _parse_create_args(args: tuple[str, ...]) -> tuple[str, str] | None:
        if not args or len(args) > 13:
            return None
        return args[0], " ".join(args[1:])

    @staticmethod
    def _parse_ref_args(args: tuple[str, ...], *, allow_reason: bool = True) -> tuple[str, str] | None:
        if not args or (not allow_reason and len(args) != 1):
            return None
        return args[0], " ".join(args[1:])

    @staticmethod
    def _parse_review_args(args: tuple[str, ...]) -> tuple[str, bool, str] | None:
        if len(args) < 2:
            return None
        action = args[1].strip().lower()
        if action in {"同意", "批准", "通过", "accept", "approve"}:
            approve = True
        elif action in {"拒绝", "驳回", "reject", "deny"}:
            approve = False
        else:
            return None
        return args[0], approve, " ".join(args[2:])

    @staticmethod
    def _display_name(value: str) -> str:
        return value.replace("\\", "\\\\").replace("`", "\\`").replace("*", "\\*").replace("_", "\\_").replace("~", "\\~")

    async def create_sect(self, context: CommandContext) -> CommandResult:
        parsed = self._parse_create_args(context.command_args)
        if parsed is None:
            return CommandResult(False, "INVALID_SECT", "请使用 `创建宗门 宗门名 [宗旨]`。", context.request_id)
        name, motto = parsed
        operation_id = self._operation_id(context, "social.create_sect")
        try:
            record = await self.repository.create_sect(
                platform=context.adapter,
                platform_user_id=context.user_id,
                name=name,
                motto=motto,
                operation_id=operation_id,
            )
        except SectNameInvalidError:
            return CommandResult(False, "INVALID_SECT", "宗门名或宗旨不符合内容规则，或宗门名已被占用。", context.request_id, operation_id)
        except SectRequirementError:
            return CommandResult(False, "SECT_REQUIREMENT_MISSING", "达到筑基后才能创建宗门。", context.request_id, operation_id)
        except SectAlreadyJoinedError:
            return CommandResult(False, "SECT_ALREADY_JOINED", "你已经加入宗门，不能重复创建。", context.request_id, operation_id)
        except SectJoinCooldownError:
            return CommandResult(False, "SECT_JOIN_COOLDOWN", "离开宗门后的冷却尚未结束。", context.request_id, operation_id)
        except ResourceInsufficientError:
            return CommandResult(False, "CURRENCY_INSUFFICIENT", "创建宗门需要灵石 1000。", context.request_id, operation_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能创建宗门。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于其他宗门操作。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        return CommandResult(
            True,
            "SECT_CREATED",
            f"## 宗门创建成功\n\n**{self._display_name(record.name)}**已建立。\n\n- **宗门号**：`{record.sect_id}`\n- **职位**：宗主\n- **成员**：{record.member_count}/{record.max_members}\n- **建设**：{record.construction}\n\n> 创建费已扣除灵石 1000。",
            context.request_id,
            operation_id,
            data={"sect_id": record.sect_id, "name": record.name, "motto": record.motto, "role": record.role, "member_count": record.member_count, "max_members": record.max_members, "spirit_stones": record.spirit_stones, "idempotent_replay": record.already_completed},
        )

    async def apply_sect(self, context: CommandContext) -> CommandResult:
        parsed = self._parse_ref_args(context.command_args)
        if parsed is None:
            return CommandResult(False, "INVALID_SECT", "请使用 `申请入宗 宗门号或宗门名 [申请说明]`。", context.request_id)
        sect_ref, reason = parsed
        operation_id = self._operation_id(context, "social.apply_sect")
        try:
            record = await self.repository.apply_sect(
                platform=context.adapter,
                platform_user_id=context.user_id,
                sect_ref=sect_ref,
                reason=reason,
                operation_id=operation_id,
            )
        except SectNameInvalidError:
            return CommandResult(False, "INVALID_SECT", "申请说明过长。", context.request_id, operation_id)
        except SectNotFoundError:
            return CommandResult(False, "SECT_NOT_FOUND", "没有找到可申请的宗门。", context.request_id, operation_id)
        except SectAlreadyJoinedError:
            return CommandResult(False, "SECT_ALREADY_JOINED", "你已经加入宗门。", context.request_id, operation_id)
        except SectJoinCooldownError:
            return CommandResult(False, "SECT_JOIN_COOLDOWN", "离开宗门后的冷却尚未结束。", context.request_id, operation_id)
        except SectApplicationExistsError:
            return CommandResult(False, "APPLICATION_EXISTS", "你已经向这个宗门提交过申请。", context.request_id, operation_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能申请入宗。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于其他宗门操作。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        return CommandResult(
            True,
            "SECT_APPLICATION_SUBMITTED",
            f"## 入宗申请已提交\n\n你已向 **{self._display_name(record.sect_name)}** 提交申请。\n\n- **申请号**：`{record.application_id}`\n- **有效至**：{record.expires_at}",
            context.request_id,
            operation_id,
            data={"application_id": record.application_id, "sect_id": record.sect_id, "sect_name": record.sect_name, "status": record.status, "expires_at": record.expires_at, "idempotent_replay": record.already_completed},
        )

    async def list_applications(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_SECT", "宗门申请列表无需附加参数。", context.request_id)
        try:
            records = await self.repository.list_sect_applications(platform=context.adapter, platform_user_id=context.user_id)
        except SectPermissionDeniedError:
            return CommandResult(False, "SECT_PERMISSION_DENIED", "只有长老、副宗主或宗主可以审批入宗申请。", context.request_id)
        except SectNotFoundError:
            return CommandResult(False, "SECT_NOT_FOUND", "你当前不在宗门中。", context.request_id)
        except (PlayerNotFoundError, PlayerSuspendedError):
            return CommandResult(False, "PLAYER_NOT_FOUND", "当前角色不存在或暂时不可用。", context.request_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, retryable=True)
        if not records:
            return CommandResult(True, "SECT_APPLICATIONS_EMPTY", "## 入宗申请\n\n当前没有待审批申请。", context.request_id, data={"applications": []})
        lines = ["## 入宗申请", ""]
        data = []
        for record in records:
            lines.append(f"- `{record.application_id}`：{self._display_name(record.applicant_name)}，申请说明：{record.reason or '未填写'}，截止 {record.expires_at}")
            data.append({"application_id": record.application_id, "applicant_name": record.applicant_name, "reason": record.reason, "expires_at": record.expires_at, "status": record.status})
        return CommandResult(True, "SECT_APPLICATIONS", "\n".join(lines), context.request_id, data={"applications": data})

    async def review_application(self, context: CommandContext) -> CommandResult:
        parsed = self._parse_review_args(context.command_args)
        if parsed is None:
            return CommandResult(False, "INVALID_SECT", "请使用 `审批入宗 申请号 同意|拒绝 [原因]`。", context.request_id)
        application_id, approve, review_reason = parsed
        operation_id = self._operation_id(context, "social.review_sect_application")
        try:
            record = await self.repository.review_sect_application(
                platform=context.adapter,
                platform_user_id=context.user_id,
                application_id=application_id,
                approve=approve,
                review_reason=review_reason,
                operation_id=operation_id,
            )
        except SectPermissionDeniedError:
            return CommandResult(False, "SECT_PERMISSION_DENIED", "只有长老、副宗主或宗主可以审批入宗申请。", context.request_id, operation_id)
        except SectApplicationNotFoundError:
            return CommandResult(False, "APPLICATION_NOT_FOUND", "没有找到待审批的入宗申请。", context.request_id, operation_id)
        except SectApplicationExpiredError:
            return CommandResult(False, "APPLICATION_EXPIRED", "这份入宗申请已经过期。", context.request_id, operation_id)
        except SectFullError:
            return CommandResult(False, "SECT_FULL", "宗门成员已满，暂时不能批准申请。", context.request_id, operation_id)
        except SectAlreadyJoinedError:
            return CommandResult(False, "SECT_ALREADY_JOINED", "申请人已经加入其他宗门。", context.request_id, operation_id)
        except SectJoinCooldownError:
            return CommandResult(False, "SECT_JOIN_COOLDOWN", "申请人的离宗冷却尚未结束。", context.request_id, operation_id)
        except SectNotFoundError:
            return CommandResult(False, "SECT_NOT_FOUND", "宗门不存在或已经关闭。", context.request_id, operation_id)
        except SectNameInvalidError:
            return CommandResult(False, "INVALID_SECT", "审批原因过长。", context.request_id, operation_id)
        except (PlayerNotFoundError, PlayerSuspendedError):
            return CommandResult(False, "PLAYER_NOT_FOUND", "当前角色不存在或暂时不可用。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于其他审批输入。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        verb = "已批准" if record.status == "accepted" else "已拒绝"
        return CommandResult(
            True,
            "SECT_APPLICATION_REVIEWED",
            f"## 入宗申请{verb}\n\n- **申请号**：`{record.application_id}`\n- **申请人**：{self._display_name(record.applicant_name)}\n- **宗门**：{self._display_name(record.sect_name)}",
            context.request_id,
            operation_id,
            data={"application_id": record.application_id, "sect_id": record.sect_id, "status": record.status, "review_reason": record.review_reason, "idempotent_replay": record.already_completed},
        )

    async def leave_sect(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_SECT", "离开宗门无需附加参数。", context.request_id)
        operation_id = self._operation_id(context, "social.leave_sect")
        try:
            record = await self.repository.leave_sect(platform=context.adapter, platform_user_id=context.user_id, operation_id=operation_id)
        except SectNotFoundError:
            return CommandResult(False, "SECT_NOT_FOUND", "你当前不在宗门中。", context.request_id, operation_id)
        except SectLeaderCannotLeaveError:
            return CommandResult(False, "SECT_PERMISSION_DENIED", "宗主必须先完成宗主职位交接，不能直接离宗。", context.request_id, operation_id)
        except SectAssetLockedError:
            return CommandResult(False, "SECT_ASSET_LOCKED", "你有进行中的会话或订单，结算后才能离宗。", context.request_id, operation_id)
        except (PlayerNotFoundError, PlayerSuspendedError):
            return CommandResult(False, "PLAYER_NOT_FOUND", "当前角色不存在或暂时不可用。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于其他离宗输入。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        return CommandResult(
            True,
            "SECT_LEFT",
            f"## 已离开宗门\n\n你已离开 **{self._display_name(record.name)}**，24 小时内不能再次加入宗门。",
            context.request_id,
            operation_id,
            data={"sect_id": record.sect_id, "name": record.name, "status": "left", "idempotent_replay": record.already_completed},
        )

    async def get_profile(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) > 1:
            return CommandResult(False, "INVALID_SECT", "请使用 `我的宗门` 或 `宗门信息 宗门号`。", context.request_id)
        sect_ref = context.command_args[0] if context.command_args else None
        try:
            record = await self.repository.get_sect_profile(platform=context.adapter, platform_user_id=context.user_id, sect_ref=sect_ref)
        except SectNotFoundError:
            return CommandResult(False, "SECT_NOT_FOUND", "没有找到宗门，或你当前不在宗门中。", context.request_id)
        except (PlayerNotFoundError, PlayerSuspendedError):
            return CommandResult(False, "PLAYER_NOT_FOUND", "当前角色不存在或暂时不可用。", context.request_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, retryable=True)
        return CommandResult(
            True,
            "SECT_PROFILE",
            f"## {self._display_name(record.name)}\n\n{record.motto or '宗旨未填写'}\n\n- **宗门号**：`{record.sect_id}`\n- **职位**：{role_label(record.role)}\n- **成员**：{record.member_count}/{record.max_members}\n- **建设**：{record.construction}",
            context.request_id,
            data={"sect_id": record.sect_id, "name": record.name, "motto": record.motto, "role": record.role, "member_count": record.member_count, "max_members": record.max_members, "construction": record.construction},
        )

    async def exchange_shop(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 1:
            return CommandResult(False, "INVALID_SECT_EXCHANGE", "请使用 `宗门商店兑换 筑基护脉丹|金丹护脉丹|云铁|阵砂`。", context.request_id)
        offer = resolve_sect_exchange_offer(context.command_args[0])
        if offer is None:
            return CommandResult(False, "INVALID_SECT_EXCHANGE", "没有这项宗门兑换物。", context.request_id)
        operation_id = self._operation_id(context, "social.sect_exchange")
        try:
            record = await self.repository.exchange_sect_item(
                platform=context.adapter,
                platform_user_id=context.user_id,
                offer_key=offer.key,
                operation_id=operation_id,
            )
        except SectExchangeDailyCapError:
            return CommandResult(False, "SECT_EXCHANGE_DAILY_CAP", "今日宗门兑换次数已用尽。", context.request_id, operation_id)
        except SectStockInsufficientError:
            return CommandResult(False, "SECT_STOCK_INSUFFICIENT", "宗门仓库库存不足，未扣除贡献。", context.request_id, operation_id)
        except SectContributionInsufficientError:
            return CommandResult(False, "SECT_CONTRIBUTION_INSUFFICIENT", "个人宗门贡献不足，未扣除库存。", context.request_id, operation_id)
        except SectExchangeInvalidOfferError:
            return CommandResult(False, "INVALID_SECT_EXCHANGE", "没有这项宗门兑换物。", context.request_id, operation_id)
        except SectNotFoundError:
            return CommandResult(False, "SECT_NOT_FOUND", "你当前不在有效宗门中。", context.request_id, operation_id)
        except (PlayerNotFoundError, PlayerSuspendedError):
            return CommandResult(False, "PLAYER_NOT_FOUND", "当前角色不存在或暂时不可用。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于其他宗门兑换。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        replay = "（重复请求已回放）" if record.already_completed else ""
        return CommandResult(
            True,
            "SECT_EXCHANGE_COMPLETED",
            f"## 宗门兑换成功{replay}\n\n- **物品**：{record.label} ×{record.quantity}\n- **消耗贡献**：{record.contribution_spent}\n- **剩余贡献**：{record.member_contribution}",
            context.request_id,
            operation_id,
            data={
                "offer_key": record.offer_key,
                "item_key": record.item_key,
                "quantity": record.quantity,
                "contribution_spent": record.contribution_spent,
                "member_contribution": record.member_contribution,
                "warehouse_quantity": record.warehouse_quantity,
                "inventory_quantity": record.inventory_quantity,
                "content_version": record.content_version,
                "rule_version": record.rule_version,
                "idempotent_replay": record.already_completed,
            },
        )

    async def shop(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_SECT_EXCHANGE", "请使用 `宗门商店兑换 筑基护脉丹|金丹护脉丹|云铁|阵砂`。", context.request_id)
        lines = ["## 宗门商店", "", "每位成员每日最多兑换 5 次；兑换会同时扣除个人宗门贡献和宗门仓库库存。", ""]
        offers = []
        for offer in SECT_EXCHANGE_OFFERS.values():
            lines.append(f"- **{offer.label}**：贡献 {offer.contribution_cost} → ×{offer.quantity}")
            offers.append({"offer_key": offer.key, "label": offer.label, "contribution_cost": offer.contribution_cost, "item_key": offer.item_key, "quantity": offer.quantity})
        return CommandResult(True, "SECT_SHOP", "\n".join(lines), context.request_id, data={"offers": offers, "daily_cap": 5})

    async def daily_build(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_SECT_SUPPLY", "请使用 `宗门每日建设`。", context.request_id)
        return await self._supply_command(context, "social.sect_daily_build", self.repository.build_sect_daily, {}, "SECT_DAILY_BUILT")

    async def donate(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 2:
            return CommandResult(False, "INVALID_SECT_SUPPLY", "请使用 `宗门捐献 灵石|灵叶|止血草|阵砂|云铁 数量`。", context.request_id)
        item_key = SECT_DONATION_ALIASES.get(context.command_args[0], context.command_args[0])
        if context.command_args[0] == "灵石":
            item_key = "spirit_stones"
        try:
            quantity = int(context.command_args[1])
        except ValueError:
            return CommandResult(False, "INVALID_SECT_SUPPLY", "捐献数量必须为整数。", context.request_id)
        return await self._supply_command(context, "social.sect_donate", self.repository.donate_sect_asset, {"item_key": item_key, "quantity": quantity}, "SECT_DONATED")

    async def procure(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 1:
            return CommandResult(False, "INVALID_SECT_SUPPLY", "请使用 `宗门补给 筑基护脉丹|金丹护脉丹`。", context.request_id)
        offer = resolve_sect_exchange_offer(context.command_args[0])
        if offer is None or offer.key not in SECT_SUPPLY_RECIPES:
            return CommandResult(False, "INVALID_SECT_SUPPLY", "没有这项宗门补给。", context.request_id)
        return await self._supply_command(context, "social.sect_procure", self.repository.procure_sect_stock, {"offer_key": offer.key}, "SECT_STOCK_PROCURED")

    async def _supply_command(self, context: CommandContext, name: str, method, params: dict, code: str) -> CommandResult:
        operation_id = self._operation_id(context, name)
        try:
            record = await method(platform=context.adapter, platform_user_id=context.user_id, operation_id=operation_id, **params)
        except SectDailyBuildNotReadyError:
            return CommandResult(False, "SECT_BUILD_NOT_READY", "今日需要先完成 3 次不同的探索或生产。", context.request_id, operation_id)
        except SectDailyBuildAlreadyCompletedError:
            return CommandResult(False, "SECT_BUILD_ALREADY_COMPLETED", "今日宗门建设已完成。", context.request_id, operation_id)
        except SectPermissionDeniedError:
            return CommandResult(False, "SECT_PERMISSION_DENIED", "只有宗主或副宗主可以补给仓库。", context.request_id, operation_id)
        except SectWarehouseFullError:
            return CommandResult(False, "SECT_WAREHOUSE_FULL", "宗门仓库格位已满。", context.request_id, operation_id)
        except SectStockInsufficientError:
            return CommandResult(False, "SECT_STOCK_INSUFFICIENT", "宗门仓库原料不足。", context.request_id, operation_id)
        except ResourceInsufficientError:
            return CommandResult(False, "RESOURCE_INSUFFICIENT", "原料或灵石不足。", context.request_id, operation_id)
        except (SectSupplyItemInvalidError, SectExchangeInvalidOfferError):
            return CommandResult(False, "INVALID_SECT_SUPPLY", "捐献或补给物品、数量不符合规则。", context.request_id, operation_id)
        except SectNotFoundError:
            return CommandResult(False, "SECT_NOT_FOUND", "你当前不在有效宗门中。", context.request_id, operation_id)
        except (PlayerNotFoundError, PlayerSuspendedError):
            return CommandResult(False, "PLAYER_NOT_FOUND", "当前角色不存在或暂时不可用。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于其他操作。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        label = {"SECT_DAILY_BUILT": "宗门建设完成", "SECT_DONATED": "宗门捐献完成", "SECT_STOCK_PROCURED": "宗门补给完成"}[code]
        return CommandResult(True, code, f"## {label}", context.request_id, operation_id, data=record)


__all__ = ["SectApplication"]
