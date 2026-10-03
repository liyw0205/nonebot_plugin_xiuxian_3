"""Application services for the first short-haul livelihood route."""

from __future__ import annotations

from ...contracts import CommandContext, CommandResult
from ..content import ContentError
from ..repository import (
    OperationConflictError,
    PlayerNotFoundError,
    PlayerStageConflictError,
    PlayerSuspendedError,
    RepositoryBusyError,
    ResourceInsufficientError,
    RouteAlreadySettledError,
    RouteBusyError,
    RouteCargoRequirementError,
    RouteContentClosedError,
    RouteLocationRequirementError,
    RouteMountNotFoundError,
    RouteMountRequirementError,
    RouteNotFoundError,
    RouteNotReadyError,
    RouteQuotaError,
    SQLitePlayerRepository,
)
from .route_rules import (
    ROUTE_NEW_TOWN_OUTSKIRTS,
    resolve_cargo,
    resolve_route,
)


class RouteApplication:
    """Translate route commands into the shared application contract."""

    def __init__(self, repository: SQLitePlayerRepository):
        self.repository = repository

    @staticmethod
    def _operation_id(context: CommandContext, operation_name: str) -> str:
        if context.operation_id:
            return context.operation_id
        request_key = context.message_id or context.request_id
        return f"{operation_name}:{context.adapter}:{context.user_id}:{request_key}"

    def _parse_route_args(self, args: tuple[str, ...]) -> tuple[str, str | None, int, str | None] | None:
        values = list(args)
        content = self.repository.content
        route_key = ROUTE_NEW_TOWN_OUTSKIRTS
        if values:
            selected_route = resolve_route(values[0], content)
            if selected_route is not None:
                route_key = selected_route
                values.pop(0)
        if len(values) > 3:
            return None
        cargo_key = None
        quantity = 1
        quantity_given = False
        mount_ref: str | None = None
        for value in values:
            selected_cargo = resolve_cargo(value, route_key, content) if cargo_key is None else None
            if cargo_key is None and selected_cargo is not None:
                cargo_key = selected_cargo
                continue
            try:
                parsed_quantity = int(value)
            except ValueError:
                parsed_quantity = None
            if parsed_quantity is not None and not quantity_given:
                quantity = parsed_quantity
                quantity_given = True
                continue
            if mount_ref is None and value.strip():
                mount_ref = value.strip()
                continue
            return None
        return route_key, cargo_key, quantity, mount_ref

    @staticmethod
    def _parse_route_id(args: tuple[str, ...]) -> str | None:
        if not args:
            return None
        if len(args) != 1 or not args[0].strip():
            return ""
        return args[0].strip()

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

    async def preview_route(self, context: CommandContext) -> CommandResult:
        try:
            parsed = self._parse_route_args(context.command_args)
        except ContentError:
            return CommandResult(False, "LIVELIHOOD_CONTENT_CLOSED", "该运输路线或货物暂未开放。", context.request_id)
        if parsed is None:
            return CommandResult(False, "INVALID_ROUTE", "请使用 `运输预览 止血草 [数量] [灵骑名称或编号]`。", context.request_id)
        route_key, cargo_key, quantity, mount_ref = parsed
        try:
            record = await self.repository.preview_route(
                platform=context.adapter,
                platform_user_id=context.user_id,
                route_key=route_key,
                cargo_key=cargo_key,
                cargo_quantity=quantity,
                mount_ref=mount_ref,
            )
        except RouteContentClosedError:
            return CommandResult(False, "LIVELIHOOD_CONTENT_CLOSED", "该运输路线或货物暂未开放。", context.request_id)
        except RouteCargoRequirementError:
            return CommandResult(False, "ROUTE_CARGO_LOCKED", "货物数量无效，或货值超过这条路线的上限。", context.request_id)
        except RouteMountNotFoundError:
            return CommandResult(False, "ROUTE_MOUNT_NOT_FOUND", "没有找到这只灵骑。", context.request_id)
        except RouteMountRequirementError:
            return CommandResult(False, "ROUTE_MOUNT_UNAVAILABLE", "这只灵骑尚未待命，或耐力不足以随行。", context.request_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能查看运输。", context.request_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, retryable=True)
        missing = "、".join(record.missing) if record.missing else "无"
        return CommandResult(
            True,
            "ROUTE_PREVIEW",
            (
                f"## {record.route_name} · 运输预览\n\n"
                f"- **货物**：{record.cargo_name} ×{record.cargo_quantity}\n"
                f"- **货值**：{record.cargo_value} 灵石\n"
                f"- **体力消耗**：{record.stamina_cost}\n"
                f"- **基础耗时**：{record.duration_seconds // 60} 分钟\n"
                + (f"- **随行灵骑**：{record.mount_name}（等级 {record.mount_level}，耐力 {record.mount_stamina}）\n" if record.mount_name else "")
                + f"- **今日次数**：{record.daily_used}/{record.daily_limit}\n"
                f"- **当前缺少**：{missing}\n\n"
                f"> {'发送 `开始运输 ' + record.cargo_name + '` 开始。' if record.ready else '满足条件后才可运送货物。'}"
            ),
            context.request_id,
            data={
                "route_key": record.route_key,
                "cargo_key": record.cargo_key,
                "cargo_quantity": record.cargo_quantity,
                "cargo_value": record.cargo_value,
                "duration_seconds": record.duration_seconds,
                "daily_used": record.daily_used,
                "daily_limit": record.daily_limit,
                "ready": record.ready,
                "missing": record.missing,
                "mount_instance_id": record.mount_instance_id,
                "mount_name": record.mount_name,
                "mount_level": record.mount_level,
                "mount_stamina": record.mount_stamina,
                "mount_stamina_cost": record.mount_stamina_cost,
            },
        )

    async def start_route(self, context: CommandContext) -> CommandResult:
        operation_id = self._operation_id(context, "livelihood.start_route")
        try:
            parsed = self._parse_route_args(context.command_args)
        except ContentError:
            return CommandResult(False, "LIVELIHOOD_CONTENT_CLOSED", "该运输路线或货物暂未开放。", context.request_id, operation_id)
        if parsed is None:
            return CommandResult(False, "INVALID_ROUTE", "请使用 `开始运输 止血草 [数量] [灵骑名称或编号]`。", context.request_id)
        route_key, cargo_key, quantity, mount_ref = parsed
        try:
            record = await self.repository.start_route(
                platform=context.adapter,
                platform_user_id=context.user_id,
                route_key=route_key,
                cargo_key=cargo_key,
                cargo_quantity=quantity,
                operation_id=operation_id,
                mount_ref=mount_ref,
            )
        except RouteContentClosedError:
            return CommandResult(False, "LIVELIHOOD_CONTENT_CLOSED", "该运输路线或货物暂未开放。", context.request_id, operation_id)
        except RouteCargoRequirementError:
            return CommandResult(False, "ROUTE_CARGO_LOCKED", "货物不足或货值超过路线限制，未扣除任何资源。", context.request_id, operation_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except PlayerStageConflictError:
            return CommandResult(False, "ROUTE_REQUIREMENT_MISSING", "当前修行阶段尚不能踏上这条商路。", context.request_id, operation_id)
        except RouteLocationRequirementError:
            return CommandResult(False, "ROUTE_LOCATION_REQUIRED", "请先抵达这条商路的起点再运送货物。", context.request_id, operation_id)
        except RouteMountNotFoundError:
            return CommandResult(False, "ROUTE_MOUNT_NOT_FOUND", "没有找到这只灵骑。", context.request_id, operation_id)
        except RouteMountRequirementError:
            return CommandResult(False, "ROUTE_MOUNT_UNAVAILABLE", "这只灵骑尚未待命，或耐力不足以随行。", context.request_id, operation_id)
        except RouteQuotaError:
            return CommandResult(False, "ROUTE_QUOTA_EXHAUSTED", "今日运输次数已用尽。", context.request_id, operation_id)
        except RouteBusyError:
            return CommandResult(False, "ROUTE_BUSY", "正忙于赶路、修炼或其他事务，暂不能运送货物。", context.request_id, operation_id)
        except ResourceInsufficientError:
            return CommandResult(False, "ROUTE_RESOURCE_INSUFFICIENT", "体力不足，未扣除货物或其他资源。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能开始运输。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次传讯与先前托运的货物不符，请重新传讯。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        delay_text = f"，可能延误 {record.delay_seconds // 60} 分钟" if record.delay_seconds else ""
        return CommandResult(
            True,
            "ROUTE_STARTED",
            (
                f"## 运输已开始\n\n**{self._display_name(record.player)}**带上"
                f"**{record.cargo_name} ×{record.cargo_quantity}**，踏上商路。\n\n"
                f"- **路线**：{record.route_name}\n- **体力**：{record.player.stamina}/{record.player.stamina_max}\n"
                f"- **预计抵达**：{record.arrives_at}{delay_text}\n"
                + (f"- **随行灵骑**：{record.mount_name}（等级 {record.mount_level}）\n" if record.mount_name else "")
                + "\n> 抵达后发送 `结算运输`。"
            ),
            context.request_id,
            operation_id,
            data={
                "route_id": record.route_id,
                "route_key": record.route_key,
                "cargo_key": record.cargo_key,
                "cargo_quantity": record.cargo_quantity,
                "cargo_value": record.cargo_value,
                "status": record.status,
                "starts_at": record.starts_at,
                "arrives_at": record.arrives_at,
                "reward_stones": record.reward_stones,
                "delay_seconds": record.delay_seconds,
                "mount_instance_id": record.mount_instance_id,
                "mount_name": record.mount_name,
                "mount_level": record.mount_level,
                "idempotent_replay": record.already_completed,
            },
        )

    async def settle_route(self, context: CommandContext) -> CommandResult:
        route_id = self._parse_route_id(context.command_args)
        if route_id == "":
            return CommandResult(False, "INVALID_ROUTE", "请使用 `结算运输 [路线号]`。", context.request_id)
        operation_id = self._operation_id(context, "livelihood.settle_route")
        try:
            record = await self.repository.settle_route(
                platform=context.adapter,
                platform_user_id=context.user_id,
                route_id=route_id,
                operation_id=operation_id,
            )
        except RouteNotFoundError:
            return CommandResult(False, "ROUTE_NOT_FOUND", "没有可结算的运输路线。", context.request_id, operation_id)
        except RouteNotReadyError:
            return CommandResult(False, "ROUTE_NOT_READY", "运输尚未抵达，请稍后再来结算。", context.request_id, operation_id)
        except RouteAlreadySettledError:
            return CommandResult(False, "ROUTE_ALREADY_SETTLED", "这条运输路线已经结算过了。", context.request_id, operation_id)
        except RouteMountNotFoundError:
            return CommandResult(False, "ROUTE_MOUNT_NOT_FOUND", "随行灵骑的踪迹已无法核验，运输未结算。", context.request_id, operation_id)
        except RouteMountRequirementError:
            return CommandResult(False, "ROUTE_MOUNT_UNAVAILABLE", "随行灵骑的状态不对，运输未结算。", context.request_id, operation_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能结算运输。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次传讯与先前运抵的货物不符，请重新传讯。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        return CommandResult(
            True,
            "ROUTE_SETTLED",
            (
                f"## 运输已完成\n\n**{record.route_name}**已抵达。\n\n"
                f"- **获得灵石**：+{record.reward_stones}\n"
                f"- **地方名望**：+{record.local_reputation_delta}\n"
                f"- **已交付货物**：{record.cargo_name} ×{record.cargo_quantity}"
                + (f"\n- **灵骑**：{record.mount_name}获得运输经验 {record.mount_experience}。" if record.mount_name else "")
            ),
            context.request_id,
            operation_id,
            data={
                "route_id": record.route_id,
                "route_key": record.route_key,
                "status": record.status,
                "reward_stones": record.reward_stones,
                "local_reputation_delta": record.local_reputation_delta,
                "local_reputation_before": record.local_reputation_before,
                "local_reputation_after": record.local_reputation_after,
                "delay_seconds": record.delay_seconds,
                "cargo": record.cargo,
                "mount_instance_id": record.mount_instance_id,
                "mount_name": record.mount_name,
                "mount_experience": record.mount_experience,
                "mount_level_after": record.mount_level_after,
                "idempotent_replay": record.already_completed,
            },
        )


__all__ = ["RouteApplication"]
