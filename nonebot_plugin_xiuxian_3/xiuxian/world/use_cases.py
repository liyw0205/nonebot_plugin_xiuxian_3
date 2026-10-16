"""Application commands for previewing and completing world movement."""

from __future__ import annotations

from datetime import datetime

from ...contracts import CommandContext, CommandResult
from ..content import bundled_content
from ..utils.assets import inventory_amount
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
    BeastIntroAlreadyCompletedError,
    BeastIntroRequirementError,
    CloudBoatBusyError,
    CloudBoatNotFoundError,
    CloudBoatNotReadyError,
    CloudFareInsufficientError,
    CloudRouteLockedError,
    DemonIntroAlreadyCompletedError,
    DemonIntroRequirementError,
    EventNotActiveError,
    FactionReputationInsufficientError,
    TravelRouteNotFoundError,
)
from .rules import (
    destination_definition,
    destination_location_is_open,
    meets_realm,
    resolve_destination,
)
from .cloud_rules import cloud_route_for_destination, resolve_cloud_route
from .void_rules import resolve_void_route


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

    def _destination(self, args: tuple[str, ...]) -> str | None:
        if len(args) != 1:
            return None
        return resolve_destination(args[0], self.repository.content)

    def _destination_label(self, destination: str) -> str:
        content = self.repository.content or bundled_content()
        return content.label("location", destination, fallback=destination)

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
        definition = destination_definition(destination, self.repository.content, source=record.source)
        travel_content = self.repository.content or bundled_content()
        destination_cloud_route = cloud_route_for_destination(destination, travel_content)
        ordinary_route_available = definition.route_available
        cloud_route = destination_cloud_route if not ordinary_route_available else None
        if cloud_route is not None:
            missing_cloud: list[str] = []
            if record.source not in cloud_route.source_locations:
                missing_cloud.append("云舟登船地点")
            if not meets_realm(
                record.player.realm_key,
                record.player.realm_layer,
                cloud_route.required_realm,
                cloud_route.required_layer,
            ):
                missing_cloud.append("境界要求")
            if cloud_route.pass_key and inventory_amount(record.player.inventory, cloud_route.pass_key) < cloud_route.pass_quantity:
                missing_cloud.append("通行物品")
            if cloud_route.required_quest and not await self.repository.cloud_route_quest_completed(
                platform=context.adapter,
                platform_user_id=context.user_id,
                quest_key=cloud_route.required_quest,
            ):
                missing_cloud.append("任务权限")
            if record.player.stamina < cloud_route.stamina_cost:
                missing_cloud.append("体力")
            if record.player.spirit_stones < cloud_route.currency_cost:
                missing_cloud.append("灵石")
            missing_labels = tuple(missing_cloud)
        else:
            missing_labels = tuple(
                item.replace("qi_gathering", "聚气")
                .replace("qi_sensing", "感气")
                .replace("foundation", "筑基")
                .replace("golden_core", "金丹")
                .replace("nascent_soul", "元婴")
                .replace("soul_transformation", "化神")
                .replace("void_refining", "炼虚")
                .replace("dao_union", "合道")
                .replace("ascension_ready", "飞升候选")
                .replace("remained_in_world", "留界")
                .replace("当前状态", "当前终局状态")
                for item in record.missing
            )
        missing = "、".join(missing_labels) if missing_labels else "无"
        if cloud_route is not None:
            cloud_pass_label = ITEM_LABELS.get(cloud_route.pass_key or "", "通行物品")
            pass_summary = (
                f"{cloud_pass_label} ×{cloud_route.pass_quantity}"
                if cloud_route.pass_key
                else "无"
            )
            duration_summary = f"{cloud_route.duration_seconds // 60} 分钟（云舟）"
            stamina_summary = f"{cloud_route.stamina_cost}（云舟）"
            currency_summary = f"{cloud_route.currency_cost}（云舟）"
            source_labels = "、".join(
                travel_content.label("location", key, fallback=key)
                for key in cloud_route.source_locations
            )
            route_summary = (
                f"**{self._display_name(record.player)}**不能通过普通移动抵达此地；请使用云舟专用航线。"
            )
            next_action = (
                f"发送 `登上云舟 {cloud_route.command_name}` 开始航程。"
                if not missing_labels
                else "满足显示的云舟条件后再开始航程。"
            )
        else:
            pass_label = ITEM_LABELS.get(record.pass_key or "", "通行物品")
            pass_summary = (
                f"{pass_label} ×{record.pass_quantity}"
                if record.pass_key
                else "无" if ordinary_route_available else "无可行路线"
            )
            duration_summary = (
                f"{definition.duration_seconds // 60} 分钟"
                if ordinary_route_available
                else "无可行路线"
            )
            stamina_summary = str(definition.stamina_cost) if ordinary_route_available else "无可行路线"
            currency_summary = str(definition.currency_cost) if ordinary_route_available else "无可行路线"
            route_summary = (
                f"**{self._display_name(record.player)}**可以查看这条路线。"
                if ordinary_route_available
                else f"**{self._display_name(record.player)}**当前位置没有通往此地的路线。"
            )
            next_action = (
                f"发送 `前往 {definition.label}` 开始移动。"
                if record.ready
                else "满足条件后才可创建移动会话。"
            )
        source_summary = (
            f"- **云舟起航地点**：{source_labels}\n"
            if cloud_route is not None
            else ""
        )
        message = (
            f"## {definition.label} · 移动预览\n\n"
            f"{route_summary}\n\n"
            f"{source_summary}"
            f"- **预计耗时**：{duration_summary}\n"
            f"- **体力消耗**：{stamina_summary}\n"
            f"- **灵石消耗**：{currency_summary}\n"
            f"- **通行物品**：{pass_summary}\n"
            f"- **当前缺少**：{missing}\n\n"
            f"> {next_action}"
        )
        return CommandResult(True, "TRAVEL_PREVIEW", message, context.request_id, data={
            "destination": destination,
            "ready": record.ready if cloud_route is None else False,
            "route_available": ordinary_route_available,
            "missing": missing_labels,
            "duration_seconds": definition.duration_seconds if ordinary_route_available else None,
            "stamina_cost": definition.stamina_cost if ordinary_route_available else None,
            "currency_cost": definition.currency_cost if ordinary_route_available else None,
            "pass_key": record.pass_key if ordinary_route_available else None,
            "pass_quantity": record.pass_quantity if ordinary_route_available else 0,
            "travel_mode": "cloud_boat" if cloud_route is not None else "ordinary",
            "dedicated_route_key": cloud_route.key if cloud_route is not None else None,
            "dedicated_route_ready": bool(cloud_route is not None and not missing_labels),
            "dedicated_route_duration_seconds": cloud_route.duration_seconds if cloud_route is not None else None,
            "dedicated_route_stamina_cost": cloud_route.stamina_cost if cloud_route is not None else None,
            "dedicated_route_currency_cost": cloud_route.currency_cost if cloud_route is not None else None,
            "required_dao_fruit_progress": definition.required_dao_fruit_progress,
            "daily_start_limit": definition.daily_start_limit,
            "required_endgame_status": definition.required_endgame_status,
            "required_intro_flag": definition.required_intro_flag,
            "consume_pass_on_arrival": definition.consume_pass_on_arrival,
            "required_faction": definition.required_faction,
            "required_faction_reputation": definition.required_faction_reputation,
            "requires_selected_domain": definition.requires_selected_domain,
        })

    async def start_travel(self, context: CommandContext, destination: str | None = None) -> CommandResult:
        destination = destination or (self._destination(context.command_args) or "")
        if not destination:
            return CommandResult(False, "INVALID_DESTINATION", "请使用 `前往 雾隐洞天`。", context.request_id)
        resolved = resolve_destination(destination, self.repository.content)
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
        except EventNotActiveError:
            return CommandResult(False, "EVENT_NOT_ACTIVE", "魔界战线当前未开放行路。", context.request_id, operation_id)
        except TravelRouteNotFoundError:
            if resolved in {"cave.mist_grotto_2", "demon.abyss_gate"}:
                return CommandResult(False, "LOCATION_REQUIREMENT_MISSING", "当前境界、来源地点或凭证不满足进入条件。", context.request_id, operation_id)
            if resolved == "dao.origin_gate":
                return CommandResult(False, "DAO_ORIGIN_REQUIREMENT_MISSING", "需从虚空档案遗迹、道统服务处或天劫台出发；需合道六层、道果进度 470，并支付 2 枚道果碎片与体力；每日限入一次。", context.request_id, operation_id)
            if resolved == "tribulation.sky_terrace":
                return CommandResult(False, "TRIBULATION_TERRACE_REQUIREMENT_MISSING", "需达到渡劫 L3 并持有 1 张天劫凭证；常规入口为道源门，飞升候选可由飞升路返回。", context.request_id, operation_id)
            if resolved == "ascension.heaven_path":
                return CommandResult(False, "ASCENSION_REQUIREMENT_MISSING", "需处于飞升候选状态并从天劫台启程；终局战胜利后已直接抵达飞升路。", context.request_id, operation_id)
            if resolved == "ascension.left_world_hall":
                return CommandResult(False, "ENDING_STATE_REQUIRED", "需先完成留界结局，并从飞升路出发。", context.request_id, operation_id)
            return CommandResult(False, "TRAVEL_ROUTE_INVALID", "当前位置没有通往该地点的公开路线，未扣除任何资源。", context.request_id, operation_id)
        except FactionReputationInsufficientError:
            definition = destination_definition(resolved, self.repository.content)
            required_faction = definition.required_faction
            faction_label = {"demon": "魔界", "beast": "妖界"}.get(required_faction, "对应阵营")
            return CommandResult(
                False,
                "FACTION_REPUTATION_INSUFFICIENT",
                f"{faction_label}声望不足，当前路线要求 {definition.required_faction_reputation}；本次未扣除体力或灵石。",
                context.request_id,
                operation_id,
            )
        except LocationRequirementError:
            if not destination_location_is_open(resolved, self.repository.content):
                return CommandResult(
                    False,
                    "LOCATION_LOCKED",
                    "此地尚未开放，未扣除任何资源。",
                    context.request_id,
                    operation_id,
                )
            if resolved == "xuantian.domain_front":
                return CommandResult(
                    False,
                    "DOMAIN_FRONT_REQUIREMENT_MISSING",
                    "需达到化神 L1、已选择领域，并从青石镇直接抵达；本次未扣除资源。",
                    context.request_id,
                    operation_id,
                )
            if resolved == "dao.origin_gate":
                return CommandResult(
                    False,
                    "DAO_ORIGIN_REQUIREMENT_MISSING",
                    "需从虚空档案遗迹、道统服务处或天劫台出发；需合道六层、道果进度 470，并支付 2 枚道果碎片与体力；每日限入一次。",
                    context.request_id,
                    operation_id,
                )
            if resolved == "tribulation.sky_terrace":
                return CommandResult(
                    False,
                    "TRIBULATION_TERRACE_REQUIREMENT_MISSING",
                    "需达到渡劫 L3 并持有 1 张天劫凭证；常规入口为道源门，飞升候选可由飞升路返回。",
                    context.request_id,
                    operation_id,
                )
            if resolved == "ascension.heaven_path":
                return CommandResult(
                    False,
                    "ASCENSION_REQUIREMENT_MISSING",
                    "需处于飞升候选状态并从天劫台启程；终局战胜利后已直接抵达飞升路。",
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
            return CommandResult(False, "OPERATION_CONFLICT", "此事已有安排，请重新起意。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        label = self._destination_label(record.destination)
        duration_seconds = max(
            0,
            int((datetime.fromisoformat(record.ends_at) - datetime.fromisoformat(record.starts_at)).total_seconds()),
        )
        return CommandResult(
            True,
            "TRAVEL_STARTED",
            (
                f"## 正在前往 {label}\n\n"
                f"**{self._display_name(record.player)}**已开始移动。\n\n"
                f"- **预计耗时**：{duration_seconds // 60} 分钟\n"
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
            return CommandResult(False, "OPERATION_CONFLICT", "此事已有安排，请重新起意。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        label = self._destination_label(record.destination)
        arrival_pass = (
            f"{ITEM_LABELS.get(record.pass_key or '', '通行物品')} ×{record.pass_quantity}已在抵达时消耗。"
            if record.pass_consumed
            else ""
        )
        return CommandResult(
            True,
            "TRAVEL_COMPLETED",
            (
                f"## 已抵达 {label}\n\n"
                f"**{self._display_name(record.player)}**已抵达目的地。\n\n"
                f"- **当前位置**：{label}\n"
                f"- **体力**：{record.player.stamina}/{record.player.stamina_max}\n"
                f"- **灵石**：{record.player.spirit_stones}\n\n"
                f"> 已写入位置状态，重复结算不会重复消耗资源。{arrival_pass}"
            ),
            context.request_id,
            operation_id,
            data={"session_id": record.session_id, "destination": record.destination, "status": record.status,
                  "arrived": record.arrived, "pass_consumed": record.pass_consumed,
                  "idempotent_replay": record.already_completed},
        )

    async def board_cloud_boat(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 1:
            content = self.repository.content or bundled_content()
            route_hints = "、".join(
                str(row["command_name"])
                for row in content.list("world_cloud_route", include_locked=False)
            )
            message = f"请指定云舟航线：{route_hints}。" if route_hints else "当前没有开放的云舟航线。"
            return CommandResult(False, "INVALID_CLOUD_ROUTE", message, context.request_id)
        route_key = resolve_cloud_route(
            context.command_args[0], self.repository.content, include_locked=True
        )
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
            return CommandResult(False, "CLOUD_ROUTE_LOCKED", "当前境界、任务或机缘条件不满足这条云舟航线，未扣除资源。", context.request_id, operation_id)
        except LocationRequirementError:
            return CommandResult(False, "CLOUD_ROUTE_LOCKED", "请先抵达玄天界·云城或对应云舟终点，未扣除资源。", context.request_id, operation_id)
        except AdvancedCavePassMissingError:
            return CommandResult(False, "ADVANCED_CAVE_PASS_MISSING", "缺少雾隐洞天二层凭证，未扣除云舟费用。", context.request_id, operation_id)
        except CloudFareInsufficientError:
            return CommandResult(False, "CLOUD_FARE_INSUFFICIENT", "灵石不足，未扣除体力或凭证。", context.request_id, operation_id)
        except ResourceInsufficientError:
            return CommandResult(False, "CLOUD_FARE_INSUFFICIENT", "体力不足，未扣除灵石或凭证。", context.request_id, operation_id)
        except CloudBoatBusyError:
            return CommandResult(False, "TRAVEL_BUSY", "已有移动、修炼、生产或云舟行程，请先完成后再试。", context.request_id, operation_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色处于暂停状态，暂时不能乘坐云舟。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "此事已有安排，请重新起意。", context.request_id, operation_id)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        travel_content = self.repository.content or bundled_content()
        route_row = travel_content.get("world_cloud_route", record.route_key, include_locked=True)
        route_label = (
            str(route_row["name"])
            if route_row is not None
            and route_row.get("status") in {"active", "open"}
            and isinstance(route_row.get("name"), str)
            else travel_content.label("location", record.destination, fallback=record.route_key)
        )
        duration_seconds = max(
            0,
            int((datetime.fromisoformat(record.ends_at) - datetime.fromisoformat(record.starts_at)).total_seconds()),
        )
        pass_label = ITEM_LABELS.get(record.pass_key or "", "通行物品")
        return CommandResult(
            True,
            "CLOUD_BOAT_STARTED",
            f"## {route_label}已起航\n\n- **耗时**：{duration_seconds // 60} 分钟\n- **体力**：-{record.stamina_cost}\n- **灵石**：-{record.currency_cost}\n- **凭证**：{pass_label} ×{record.pass_quantity if record.pass_key else 0}\n\n> 抵达后发送 `结算云舟`。航路与费用已经定下，重复请求不会重复扣费。",
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
            return CommandResult(False, "OPERATION_CONFLICT", "此事已有安排，请重新起意。", context.request_id, operation_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        travel_content = self.repository.content or bundled_content()
        destination_label = travel_content.label("location", record.destination, fallback=record.destination)
        return CommandResult(
            True,
            "CLOUD_BOAT_ARRIVED",
            f"## 已抵达{destination_label}\n\n航线已写入位置状态，凭证只扣除一次，重复结算不会重复移动。",
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
            return CommandResult(False, "OPERATION_CONFLICT", "此事已有安排，请重新起意。", context.request_id, operation_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        return CommandResult(
            True,
            "CLOUD_BOAT_RECOVERED",
            "## 云舟已恢复抵达\n\n已按登舟时定下的航路和费用抵达，不会再次扣除资源。",
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
            return CommandResult(False, "DEMON_INTRO_STONES_INSUFFICIENT", "当前灵石不足，未写入魔界入口资格。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "此事已有安排，请重新起意。", context.request_id, operation_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        return CommandResult(True, "DEMON_INTRO_ACCEPTED", "## 魔界引导已完成\n\n已记录污染与契约风险说明，获得魔界入口资格与相应声望。魔界核心区、战斗和魔核掉落仍未开放。", context.request_id, operation_id, data={"quest_key": record.quest_key, "status": record.status, "reward": record.reward, "idempotent_replay": record.already_completed})

    async def read_beast_history(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_BEAST_HISTORY", "阅读妖界史无需附加参数。", context.request_id)
        operation_id = self._operation_id(context, "world.read_beast_history")
        try:
            record = await self.repository.read_beast_history(
                platform=context.adapter, platform_user_id=context.user_id, operation_id=operation_id
            )
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "此事已有安排，请重新起意。", context.request_id, operation_id)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        return CommandResult(
            True,
            "BEAST_HISTORY_RECORDED",
            "## 妖界史已阅\n\n已记下妖族源流。完成一次近郊探索后，可继续完成妖界引导。",
            context.request_id,
            operation_id,
            data={"quest_key": record.quest_key, "component_key": record.component_key, "idempotent_replay": record.already_completed},
        )

    async def complete_beast_intro(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_BEAST_INTRO", "完成妖界引导无需附加参数。", context.request_id)
        operation_id = self._operation_id(context, "world.complete_beast_intro")
        try:
            record = await self.repository.complete_beast_intro(
                platform=context.adapter, platform_user_id=context.user_id, operation_id=operation_id
            )
        except BeastIntroRequirementError:
            return CommandResult(False, "BEAST_INTRO_REQUIREMENT_MISSING", "需达到筑基、阅读妖界史并完成一次近郊探索；未扣除灵石。", context.request_id, operation_id)
        except BeastIntroAlreadyCompletedError:
            return CommandResult(False, "BEAST_INTRO_ALREADY_COMPLETED", "妖界引导已经完成，入口资格不会重复发放。", context.request_id, operation_id)
        except ResourceInsufficientError:
            return CommandResult(False, "BEAST_INTRO_STONES_INSUFFICIENT", "当前灵石不足，未写入妖界入口资格。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "此事已有安排，请重新起意。", context.request_id, operation_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        return CommandResult(
            True,
            "BEAST_INTRO_COMPLETED",
            "## 妖界引导已完成\n\n获得万兽山入口资格与相应声望，未发放妖血或开放妖界核心区。",
            context.request_id,
            operation_id,
            data={"quest_key": record.quest_key, "status": record.status, "reward": record.reward, "idempotent_replay": record.already_completed},
        )

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
            return CommandResult(False, "OPERATION_CONFLICT", "此事已有安排，请重新起意。", context.request_id, operation_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        return CommandResult(True, "ARRAY_HALL_AUTHORIZED", "## 阵堂权限已确认\n\n可以继续调用布阵学习或阵材委托用例；本次只扣除 3 点体力，不自动创建生产订单。", context.request_id, operation_id, data={"status": record.status, "permission": record.permission, "action": record.action, "idempotent_replay": record.already_completed})

    async def enter_void_route(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 1:
            content = self.repository.content or bundled_content()
            route_hints = "、".join(
                str(row["aliases"][0] if row["aliases"] else row["name"])
                for row in content.list("world_void_route", include_locked=False)
            )
            message = (
                f"请指定虚空航道：{route_hints}。"
                if route_hints
                else "当前没有开放的虚空航道。"
            )
            return CommandResult(False, "INVALID_VOID_ROUTE", message, context.request_id)
        route_key = resolve_void_route(
            context.command_args[0], self.repository.content, include_locked=True
        )
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
            if route_key == "void.archive_ruins":
                message = "化神角色须先完成三次界壁试炼，或先达到炼虚 L1；未扣除资源。"
            elif route_key == "void.sect_fortress":
                message = "需要加入有效的 5 级宗门才能进入虚空堡垒航道，未扣除资源。"
            elif route_key == "void.void_market":
                message = "需要虚空功勋达到 1000 才能进入虚空集市航道，未扣除资源。"
            else:
                message = "需要炼虚 L1 才能进入虚空航道，未扣除资源。"
            return CommandResult(False, "VOID_ROUTE_LOCKED", message, context.request_id, operation_id)
        except VoidInstabilityActiveError:
            return CommandResult(False, "VOID_INSTABILITY_ACTIVE", "虚空不稳定期间不能进入这条高风险航道，未扣除资源。", context.request_id, operation_id)
        except VoidAnchorInsufficientError:
            return CommandResult(False, "VOID_ANCHOR_INSUFFICIENT", "虚空锚不足，未扣除任何资源。", context.request_id, operation_id)
        except ResourceInsufficientError:
            return CommandResult(False, "RESOURCE_INSUFFICIENT", "体力不足，未扣除虚空锚。", context.request_id, operation_id)
        except VoidTravelBusyError:
            return CommandResult(False, "VOID_TRAVEL_BUSY", "已有行动或虚空航道会话，请先完成后再试。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "此事已有安排，请重新起意。", context.request_id, operation_id)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        travel_content = self.repository.content or bundled_content()
        route_row = travel_content.get("world_void_route", record.route_key, include_locked=True)
        route_label = (
            str(route_row["name"])
            if route_row is not None
            and route_row.get("status") in {"active", "open"}
            and isinstance(route_row.get("name"), str)
            else record.route_key
        )
        return CommandResult(True, "VOID_ROUTE_STARTED", f"## 已进入{route_label}\n\n- **虚空锚**：-{record.anchor_cost}\n- **体力**：{record.player.stamina}/{record.player.stamina_max}\n- **预计抵达**：{record.ends_at}\n\n> 抵达后发送 `结算虚空航道`。", context.request_id, operation_id, data={"session_id": record.session_id, "route_key": record.route_key, "anchor_cost": record.anchor_cost, "stamina_cost": record.stamina_cost, "space_resistance_bp": record.space_resistance_bp, "storm_roll_bp": record.storm_roll_bp, "ends_at": record.ends_at, "idempotent_replay": record.already_completed})

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
            return CommandResult(False, "OPERATION_CONFLICT", "此事已有安排，请重新起意。", context.request_id, operation_id)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        reward = "、".join(f"{key} ×{value}" for key, value in record.reward.items()) or "无"
        storm = "遭遇虚空风暴，额外损失锚 %d" % record.extra_anchor_lost if record.storm else "航行平稳"
        return CommandResult(True, "VOID_ROUTE_SETTLED", f"## 虚空航道已结算\n\n- **收获**：{reward}\n- **航况**：{storm}\n- **虚空锚**：{inventory_amount(record.player.inventory, 'item.void_anchor')}\n\n> 航道快照和随机结果已固定，重复结算不会重复发放。", context.request_id, operation_id, data={"session_id": record.session_id, "route_key": record.route_key, "reward": record.reward, "storm": record.storm, "extra_anchor_lost": record.extra_anchor_lost, "idempotent_replay": record.already_completed})


__all__ = ["WorldApplication"]
