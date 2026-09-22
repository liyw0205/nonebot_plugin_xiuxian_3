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
)
from .rules import CAVE_LOCATION, destination_definition, resolve_destination
from .void_rules import resolve_void_route, void_route_definition

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
            item.replace("qi_gathering", "聚气").replace("qi_sensing", "感气").replace("foundation", "筑基")
            for item in record.missing
        )
        missing = "、".join(missing_labels) if missing_labels else "无"
        message = (
            f"## {definition.label} · 移动预览\n\n"
            f"**{self._display_name(record.player)}**可以查看这条路线。\n\n"
            f"- **预计耗时**：{definition.duration_seconds // 60} 分钟\n"
            f"- **体力消耗**：{definition.stamina_cost}\n"
            f"- **灵石消耗**：{definition.currency_cost}\n"
            f"- **凭证**：{definition.pass_key and '洞天凭证 ×' + str(definition.pass_quantity) or '无'}\n"
            f"- **当前缺少**：{missing}\n\n"
            f"> {'发送 `前往 雾隐洞天` 开始移动。' if record.ready else '满足条件后才可创建移动会话。'}"
        )
        return CommandResult(True, "TRAVEL_PREVIEW", message, context.request_id, data={
            "destination": destination,
            "ready": record.ready,
            "missing": record.missing,
            "duration_seconds": definition.duration_seconds,
            "stamina_cost": definition.stamina_cost,
            "currency_cost": definition.currency_cost,
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
            return CommandResult(False, "LOCATION_LOCKED", "完成入道后才能开始这段移动。", context.request_id, operation_id)
        except WeaknessActiveError:
            return CommandResult(False, "PLAYER_OCCUPIED", "突破虚弱期间不能前往雾隐洞天，请先恢复状态。", context.request_id, operation_id)
        except LocationRequirementError:
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
                "> 已写入位置状态，重复结算不会重复消耗资源。"
            ),
            context.request_id,
            operation_id,
            data={"session_id": record.session_id, "destination": record.destination, "status": record.status,
                  "arrived": record.arrived, "idempotent_replay": record.already_completed},
        )

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
