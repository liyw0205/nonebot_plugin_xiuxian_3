"""Application commands for previewing and completing world movement."""

from __future__ import annotations

from ...contracts import CommandContext, CommandResult
from ..repository import (
    CurrencyInsufficientError,
    LocationRequirementError,
    OperationConflictError,
    PlayerNotFoundError,
    PlayerStageConflictError,
    PlayerSuspendedError,
    RepositoryBusyError,
    ResourceInsufficientError,
    TravelBusyError,
    TravelNotFoundError,
    TravelNotReadyError,
    WeaknessActiveError,
    SQLitePlayerRepository,
    VoidAnchorInsufficientError,
    VoidInstabilityActiveError,
    VoidRouteLockedError,
    VoidTravelBusyError,
    VoidRouteNotFoundError,
    VoidRouteNotReadyError,
    AdvancedCavePassMissingError,
    ArrayHallPermissionDeniedError,
    CloudBoatBusyError,
    CloudBoatNotFoundError,
    CloudBoatNotReadyError,
    CloudFareInsufficientError,
    CloudRouteLockedError,
    DemonIntroAlreadyCompletedError,
    DemonIntroRequirementError,
)
from .rules import CAVE_LOCATION, destination_definition, resolve_destination
from .cloud_rules import cloud_route_definition, resolve_cloud_route
from .void_rules import resolve_void_route, void_route_definition


ITEM_LABELS = {
    "item.cave_pass_basic": "雾隐洞天凭证",
    "item.dao_fruit_fragment": "道果碎片",
    "item.tribulation_token": "天劫凭证",
    "item.ascension_certificate": "飞升凭证",
    "item.cave_pass_advanced": "雾隐洞天二层凭证",
}


class WorldApplication:
    """Coordinates movement commands while keeping adapter text out of storage."""

    def __init__(self, repository: SQLitePlayerRepository):
        self.repository = repository

    @staticmethod
    def _operation_id(context: CommandContext, name: str) -> str:
        if context.operation_id:
            return context.operation_id
        request_key = context.message_id or context.request_id
        return f"{name}:{context.adapter}:{context.user_id}:{request_key}"

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
    def _destination(args: tuple[str, ...]) -> str | None:
        if len(args) != 1:
            return None
        return resolve_destination(args[0])

    async def preview_travel(self, context: CommandContext) -> CommandResult:
        destination = self._destination(context.command_args)
        if destination is None:
            return CommandResult(False, "INVALID_DESTINATION", "请使用 `移动预览 雾隐洞天`。", context.request_id)
        try:
            record = await self.repository.preview_travel(
                platform=context.adapter,
                platform_user_id=context.user_id,
                destination=destination,
            )
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id)
        except LocationRequirementError:
            # The preview repository returns a normal record with missing gates;
            # this branch is reserved for an unknown or closed destination.
            return CommandResult(False, "LOCATION_NOT_FOUND", "暂时没有这个地点。", context.request_id)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, retryable=True)
        definition = destination_definition(destination)
        missing_labels = tuple(
            item.replace("qi_gathering", "聚气")
            .replace("qi_sensing", "感气")
            .replace("foundation", "筑基")
            .replace("dao_union", "合道")
            .replace("ascension_ready", "飞升候选")
            .replace("remained_in_world", "留界")
            .replace("当前状态", "当前终局状态")
            for item in record.missing
        )
        missing = "、".join(missing_labels) if missing_labels else "无"
        pass_label = ITEM_LABELS.get(definition.pass_key or "", "通行物品")
        pass_summary = f"{pass_label} ×{definition.pass_quantity}" if definition.pass_key else "无"
        message = (
            f"## {definition.label} · 移动预览\n\n"
            f"**{self._display_name(record.player)}**可以查看这条路线。\n\n"
            f"- **预计耗时**：{definition.duration_seconds // 60} 分钟\n"
            f"- **体力消耗**：{definition.stamina_cost}\n"
            f"- **灵石消耗**：{definition.currency_cost}\n"
            f"- **通行物品**：{pass_summary}\n"
            f"- **当前缺少**：{missing}\n\n"
            f"> {'发送 `前往 ' + definition.label + '` 开始移动。' if record.ready else '满足条件后才可创建移动会话。'}"
        )
        return CommandResult(True, "TRAVEL_PREVIEW", message, context.request_id, data={
            "destination": destination,
            "ready": record.ready,
            "missing": record.missing,
            "duration_seconds": definition.duration_seconds,
            "stamina_cost": definition.stamina_cost,
            "currency_cost": definition.currency_cost,
            "pass_key": definition.pass_key,
            "pass_quantity": definition.pass_quantity,
            "required_dao_fruit_progress": definition.required_dao_fruit_progress,
            "daily_start_limit": definition.daily_start_limit,
            "required_endgame_status": definition.required_endgame_status,
            "required_intro_flag": definition.required_intro_flag,
            "consume_pass_on_arrival": definition.consume_pass_on_arrival,
        })

    async def start_travel(self, context: CommandContext, destination: str | None = None) -> CommandResult:
        destination = destination or (self._destination(context.command_args) or "")
        if not destination:
            return CommandResult(False, "INVALID_DESTINATION", "请使用 `前往 雾隐洞天`。", context.request_id)
        resolved = resolve_destination(destination)
        if resolved is None:
            return CommandResult(False, "LOCATION_NOT_FOUND", "暂时没有这个地点。", context.request_id)
        operation_id = self._operation_id(context, "world.start_travel")
        try:
            record = await self.repository.start_travel(
                platform=context.adapter,
                platform_user_id=context.user_id,
                destination=resolved,
                operation_id=operation_id,
            )
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色处于暂停状态，暂时不能移动。", context.request_id, operation_id)
        except PlayerStageConflictError:
            return CommandResult(False, "LOCATION_LOCKED", "当前状态不能开始这段移动。", context.request_id, operation_id)
        except WeaknessActiveError:
            return CommandResult(False, "PLAYER_OCCUPIED", "当前处于突破虚弱，暂时不能移动，请先恢复状态。", context.request_id, operation_id)
        except LocationRequirementError:
            if resolved == "dao.origin_gate":
                return CommandResult(
                    False,
                    "DAO_ORIGIN_REQUIREMENT_MISSING",
                    "需从虚空档案遗迹出发，并满足合道六层、道果进度、体力和道果碎片条件；道源门每日限入一次。",
                    context.request_id,
                    operation_id,
                )
            if resolved == "tribulation.sky_terrace":
                return CommandResult(
                    False,
                    "TRIBULATION_TERRACE_REQUIREMENT_MISSING",
                    "需从道源门出发、达到渡劫 L3 并持有 1 张天劫凭证；本次未扣除资源。",
                    context.request_id,
                    operation_id,
                )
            if resolved == "ascension.heaven_path":
                return CommandResult(
                    False,
                    "ASCENSION_REQUIREMENT_MISSING",
                    "需处于飞升候选状态、从天劫台出发并持有飞升凭证；凭证将在抵达飞升路时消耗。",
                    context.request_id,
                    operation_id,
                )
            if resolved == "ascension.left_world_hall":
                return CommandResult(
                    False,
                    "ENDING_STATE_REQUIRED",
                    "需先完成留界结局，并从飞升路出发。",
                    context.request_id,
                    operation_id,
                )
            return CommandResult(False, "LOCATION_REQUIREMENT_MISSING", "当前境界、来源地点或凭证不满足进入条件。", context.request_id, operation_id)
        except TravelBusyError:
            return CommandResult(False, "TRAVEL_BUSY", "已有移动、修炼、生产或突破会话，请先完成后再试。", context.request_id, operation_id)
        except ResourceInsufficientError:
            return CommandResult(False, "TRAVEL_RESOURCE_INSUFFICIENT", "体力不足，未扣除任何资源。", context.request_id, operation_id)
        except CurrencyInsufficientError:
            return CommandResult(False, "TRAVEL_RESOURCE_INSUFFICIENT", "灵石不足，未扣除任何资源。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于其他移动输入，请重新发起。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        definition = destination_definition(record.destination)
        return CommandResult(
            True,
            "TRAVEL_STARTED",
            (
                f"## 正在前往 {definition.label}\n\n"
                f"**{self._display_name(record.player)}**已开始移动。\n\n"
                f"- **预计耗时**：{definition.duration_seconds // 60} 分钟\n"
                f"- **体力**：{record.player.stamina}/{record.player.stamina_max}\n"
                f"- **灵石**：{record.player.spirit_stones}\n\n"
                "> 到达后发送 `结算移动`。移动期间不能修炼、生产、突破或再次移动。"
            ),
            context.request_id,
            operation_id,
            data={"session_id": record.session_id, "destination": record.destination, "status": record.status,
                  "ends_at": record.ends_at, "idempotent_replay": record.already_completed},
        )

    async def settle_travel(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_TRAVEL_COMMAND", "结算移动无需附加参数。", context.request_id)
        operation_id = self._operation_id(context, "world.settle_travel")
        try:
            record = await self.repository.settle_travel(
                platform=context.adapter,
                platform_user_id=context.user_id,
                operation_id=operation_id,
            )
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except TravelNotFoundError:
            return CommandResult(False, "TRAVEL_NOT_FOUND", "当前没有等待结算的移动。", context.request_id, operation_id)
        except TravelNotReadyError:
            return CommandResult(False, "TRAVEL_NOT_READY", "移动尚未到达，请稍后再来结算。", context.request_id, operation_id)
        except LocationRequirementError:
            return CommandResult(False, "TRAVEL_PASS_INSUFFICIENT", "抵达所需凭证不足，位置和移动状态均未改变。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色处于暂停状态，暂时不能结算移动。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于其他移动结算，请重新发起。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        definition = destination_definition(record.destination)
        return CommandResult(
            True,
            "TRAVEL_COMPLETED",
            (
                f"## 已抵达 {definition.label}\n\n"
                f"**{self._display_name(record.player)}**已抵达目的地。\n\n"
                f"- **当前位置**：{definition.label}\n"
                f"- **体力**：{record.player.stamina}/{record.player.stamina_max}\n"
                f"- **灵石**：{record.player.spirit_stones}\n\n"
                f"> 已写入位置状态，重复结算不会重复消耗资源。{('飞升凭证已在抵达时消耗。' if record.pass_consumed else '')}"
            ),
            context.request_id,
            operation_id,
            data={"session_id": record.session_id, "destination": record.destination, "status": record.status,
                  "arrived": record.arrived, "pass_consumed": record.pass_consumed,
                  "idempotent_replay": record.already_completed},
        )

    async def board_cloud_boat(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 1:
            return CommandResult(False, "INVALID_CLOUD_ROUTE", "请指定云舟航线：洞天二层、魔界引导或返回云城。", context.request_id)
        route_key = resolve_cloud_route(context.command_args[0])
        if route_key is None:
            return CommandResult(False, "CLOUD_ROUTE_LOCKED", "暂时没有这条云舟航线。", context.request_id)
        operation_id = self._operation_id(context, "world.board_cloud_boat")
        try:
            record = await self.repository.board_cloud_boat(
                platform=context.adapter,
                platform_user_id=context.user_id,
                route_key=route_key,
                operation_id=operation_id,
            )
        except CloudRouteLockedError:
            return CommandResult(False, "CLOUD_ROUTE_LOCKED", "当前境界、任务或版本条件不满足这条云舟航线，未扣除资源。", context.request_id, operation_id)
        except LocationRequirementError:
            return CommandResult(False, "CLOUD_ROUTE_LOCKED", "请先抵达玄天界·云城或对应云舟终点，未扣除资源。", context.request_id, operation_id)
        except AdvancedCavePassMissingError:
            return CommandResult(False, "ADVANCED_CAVE_PASS_MISSING", "缺少雾隐洞天二层凭证，未扣除云舟费用。", context.request_id, operation_id)
        except CloudFareInsufficientError:
            return CommandResult(False, "CLOUD_FARE_INSUFFICIENT", "灵石不足，未扣除体力或凭证。", context.request_id, operation_id)
        except ResourceInsufficientError:
            return CommandResult(False, "CLOUD_FARE_INSUFFICIENT", "体力不足，未扣除灵石或凭证。", context.request_id, operation_id)
        except CloudBoatBusyError:
            return CommandResult(False, "TRAVEL_BUSY", "已有移动、修炼、生产或云舟会话，请先完成后再试。", context.request_id, operation_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色处于暂停状态，暂时不能乘坐云舟。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于其他云舟操作，请重新发起。", context.request_id, operation_id)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        definition = cloud_route_definition(record.route_key)
        pass_label = ITEM_LABELS.get(record.pass_key or "", "通行物品")
        return CommandResult(
            True,
            "CLOUD_BOAT_STARTED",
            f"## {definition.label}已起航\n\n- **耗时**：{definition.duration_seconds // 60} 分钟\n- **体力**：-{record.stamina_cost}\n- **灵石**：-{record.currency_cost}\n- **凭证**：{pass_label} ×{record.pass_quantity if record.pass_key else 0}\n\n> 抵达后发送 `结算云舟`。航线版本和费用已冻结，重复请求不会重复扣费。",
            context.request_id,
            operation_id,
            data={"session_id": record.session_id, "route_key": record.route_key, "destination": record.destination, "status": record.status, "ends_at": record.ends_at, "idempotent_replay": record.already_completed},
        )

    async def settle_cloud_boat(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_CLOUD_ROUTE", "结算云舟无需附加参数。", context.request_id)
        operation_id = self._operation_id(context, "world.settle_cloud_boat")
        try:
            record = await self.repository.settle_cloud_boat(
                platform=context.adapter, platform_user_id=context.user_id, operation_id=operation_id
            )
        except CloudBoatNotFoundError:
            return CommandResult(False, "CLOUD_BOAT_NOT_FOUND", "当前没有等待结算的云舟。", context.request_id, operation_id)
        except CloudBoatNotReadyError:
            return CommandResult(False, "CLOUD_BOAT_NOT_READY", "云舟尚未抵达，请稍后再来结算。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于其他云舟结算，请重新发起。", context.request_id, operation_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        definition = cloud_route_definition(record.route_key)
        return CommandResult(
            True,
            "CLOUD_BOAT_ARRIVED",
            f"## 已抵达{definition.destination}\n\n航线已写入位置状态，凭证只扣除一次，重复结算不会重复移动。",
            context.request_id,
            operation_id,
            data={"session_id": record.session_id, "route_key": record.route_key, "destination": record.destination, "status": record.status, "arrived": record.arrived, "idempotent_replay": record.already_completed},
        )

    async def recover_cloud_boat(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_CLOUD_ROUTE", "恢复云舟无需附加参数。", context.request_id)
        operation_id = self._operation_id(context, "world.recover_cloud_boat")
        try:
            record = await self.repository.recover_cloud_boat(
                platform=context.adapter, platform_user_id=context.user_id, operation_id=operation_id
            )
        except CloudBoatNotFoundError:
            return CommandResult(False, "CLOUD_BOAT_NOT_FOUND", "当前没有可恢复的云舟。", context.request_id, operation_id)
        except CloudBoatNotReadyError:
            return CommandResult(False, "CLOUD_BOAT_NOT_READY", "云舟尚未超过 24 小时恢复窗口。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于其他云舟恢复，请重新发起。", context.request_id, operation_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        return CommandResult(
            True,
            "CLOUD_BOAT_RECOVERED",
            "## 云舟已恢复抵达\n\n已按创建时冻结的航线和费用写入位置，不会再次扣除资源。",
            context.request_id,
            operation_id,
            data={"session_id": record.session_id, "route_key": record.route_key, "destination": record.destination, "status": record.status, "arrived": record.arrived, "idempotent_replay": record.already_completed},
        )

    async def accept_demon_intro(self, context: CommandContext) -> CommandResult:
        if context.command_args and context.command_args not in (("确认",), ("确认风险",)):
            return CommandResult(False, "INVALID_DEMON_INTRO", "魔界引导只需发送 `接受魔界引导` 或 `接受魔界引导 确认风险`。", context.request_id)
        operation_id = self._operation_id(context, "world.accept_demon_intro")
        try:
            record = await self.repository.accept_demon_intro(
                platform=context.adapter, platform_user_id=context.user_id, operation_id=operation_id
            )
        except DemonIntroRequirementError:
            return CommandResult(False, "DEMON_INTRO_REQUIREMENT_MISSING", "需先乘坐云舟抵达魔界深渊门，并确认风险说明；未扣除灵石。", context.request_id, operation_id)
        except DemonIntroAlreadyCompletedError:
            return CommandResult(False, "DEMON_INTRO_ALREADY_COMPLETED", "魔界引导已经完成，入口资格不会重复发放。", context.request_id, operation_id)
        except ResourceInsufficientError:
            return CommandResult(False, "DEMON_INTRO_STONES_INSUFFICIENT", "提交魔界引导需要 100 灵石，未写入入口资格。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于其他魔界引导操作，请重新发起。", context.request_id, operation_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        return CommandResult(True, "DEMON_INTRO_ACCEPTED", "## 魔界引导已完成\n\n已记录污染与契约风险说明，获得魔界入口资格和 20 点魔界声望。魔界核心区、战斗和魔核掉落仍未开放。", context.request_id, operation_id, data={"quest_key": record.quest_key, "status": record.status, "reward": record.reward, "idempotent_replay": record.already_completed})

    async def use_array_hall(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_ARRAY_HALL", "使用阵堂无需附加参数。", context.request_id)
        operation_id = self._operation_id(context, "world.use_array_hall")
        try:
            record = await self.repository.use_array_hall(
                platform=context.adapter, platform_user_id=context.user_id, operation_id=operation_id
            )
        except ArrayHallPermissionDeniedError:
            return CommandResult(False, "ARRAY_HALL_PERMISSION_DENIED", "阵堂需要聚气境，并且是宗门成员或持有阵法教学邀请；可先申请加入宗门或等待邀请。", context.request_id, operation_id)
        except ResourceInsufficientError:
            return CommandResult(False, "ARRAY_HALL_STAMINA_INSUFFICIENT", "使用阵堂需要 3 点体力，未产生学习或生产结果。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于其他阵堂操作，请重新发起。", context.request_id, operation_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        return CommandResult(True, "ARRAY_HALL_AUTHORIZED", "## 阵堂权限已确认\n\n可以继续调用布阵学习或阵材委托用例；本次只扣除 3 点体力，不自动创建生产订单。", context.request_id, operation_id, data={"status": record.status, "permission": record.permission, "action": record.action, "idempotent_replay": record.already_completed})

    async def enter_void_route(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 1:
            return CommandResult(False, "INVALID_VOID_ROUTE", "请使用 `进入虚空航道 第一航道`。", context.request_id)
        route_key = resolve_void_route(context.command_args[0])
        if route_key is None:
            return CommandResult(False, "VOID_ROUTE_LOCKED", "暂时没有这条虚空航道。", context.request_id)
        operation_id = self._operation_id(context, "world.enter_void_route")
        try:
            record = await self.repository.start_void_route(
                platform=context.adapter, platform_user_id=context.user_id, route_key=route_key, operation_id=operation_id
            )
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except VoidRouteLockedError:
            return CommandResult(False, "VOID_ROUTE_LOCKED", "需要炼虚 L1 才能进入虚空航道，未扣除资源。", context.request_id, operation_id)
        except VoidInstabilityActiveError:
            return CommandResult(False, "VOID_INSTABILITY_ACTIVE", "虚空不稳定期间不能进入这条高风险航道，未扣除资源。", context.request_id, operation_id)
        except VoidAnchorInsufficientError:
            return CommandResult(False, "VOID_ANCHOR_INSUFFICIENT", "虚空锚不足，未扣除任何资源。", context.request_id, operation_id)
        except ResourceInsufficientError:
            return CommandResult(False, "RESOURCE_INSUFFICIENT", "体力不足，未扣除虚空锚。", context.request_id, operation_id)
        except VoidTravelBusyError:
            return CommandResult(False, "VOID_TRAVEL_BUSY", "已有行动或虚空航道会话，请先完成后再试。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于其他航道操作，请重新发起。", context.request_id, operation_id)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        definition = void_route_definition(record.route_key)
        return CommandResult(True, "VOID_ROUTE_STARTED", f"## 已进入{definition.label}\n\n- **虚空锚**：-{record.anchor_cost}\n- **体力**：{record.player.stamina}/{record.player.stamina_max}\n- **预计抵达**：{record.ends_at}\n\n> 抵达后发送 `结算虚空航道`。", context.request_id, operation_id, data={"session_id": record.session_id, "route_key": record.route_key, "anchor_cost": record.anchor_cost, "stamina_cost": record.stamina_cost, "space_resistance_bp": record.space_resistance_bp, "storm_roll_bp": record.storm_roll_bp, "ends_at": record.ends_at, "idempotent_replay": record.already_completed})

    async def settle_void_route(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_VOID_ROUTE", "结算虚空航道无需附加参数。", context.request_id)
        operation_id = self._operation_id(context, "world.settle_void_route")
        try:
            record = await self.repository.settle_void_route(platform=context.adapter, platform_user_id=context.user_id, operation_id=operation_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except VoidRouteNotFoundError:
            return CommandResult(False, "VOID_ROUTE_NOT_FOUND", "当前没有等待结算的虚空航道。", context.request_id, operation_id)
        except VoidRouteNotReadyError:
            return CommandResult(False, "VOID_ROUTE_NOT_READY", "航道尚未抵达，请稍后再来结算。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于其他航道结算，请重新发起。", context.request_id, operation_id)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        reward = "、".join(f"{key} ×{value}" for key, value in record.reward.items()) or "无"
        storm = "遭遇虚空风暴，额外损失锚 %d" % record.extra_anchor_lost if record.storm else "航行平稳"
        return CommandResult(True, "VOID_ROUTE_SETTLED", f"## 虚空航道已结算\n\n- **收获**：{reward}\n- **航况**：{storm}\n- **虚空锚**：{record.player.inventory.get('item.void_anchor', 0)}\n\n> 航道快照和随机结果已固定，重复结算不会重复发放。", context.request_id, operation_id, data={"session_id": record.session_id, "route_key": record.route_key, "reward": record.reward, "storm": record.storm, "extra_anchor_lost": record.extra_anchor_lost, "idempotent_replay": record.already_completed})


__all__ = ["WorldApplication"]
