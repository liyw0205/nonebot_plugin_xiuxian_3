"""Application services for the first short-haul livelihood route."""

from __future__ import annotations

from ...contracts import CommandContext, CommandResult
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
    RouteNotFoundError,
    RouteNotReadyError,
    RouteQuotaError,
    SQLitePlayerRepository,
)
from .route_rules import (
    ROUTE_NEW_TOWN_OUTSKIRTS,
    cargo_label,
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

    @staticmethod
    def _parse_route_args(args: tuple[str, ...]) -> tuple[str, str, int] | None:
        values = list(args)
        route_key = ROUTE_NEW_TOWN_OUTSKIRTS
        if values and resolve_route(values[0]) is not None and resolve_cargo(values[0]) is None:
            route_key = resolve_route(values.pop(0)) or route_key
        if len(values) > 2:
            return None
        cargo_key = resolve_cargo(values[0]) if values else resolve_cargo("止血草")
        if cargo_key is None:
            return None
        quantity = 1
        if len(values) == 2:
            try:
                quantity = int(values[1])
            except ValueError:
                return None
        return route_key, cargo_key, quantity

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
        parsed = self._parse_route_args(context.command_args)
        if parsed is None:
            return CommandResult(False, "INVALID_ROUTE", "请使用 `运输预览 止血草 [数量]`。", context.request_id)
        route_key, cargo_key, quantity = parsed
        try:
            record = await self.repository.preview_route(
                platform=context.adapter,
                platform_user_id=context.user_id,
                route_key=route_key,
                cargo_key=cargo_key,
                cargo_quantity=quantity,
            )
        except RouteContentClosedError:
            return CommandResult(False, "LIVELIHOOD_CONTENT_CLOSED", "该运输路线或货物暂未开放。", context.request_id)
        except RouteCargoRequirementError:
            return CommandResult(False, "ROUTE_CARGO_LOCKED", "货物数量无效，或货值超过这条路线的上限。", context.request_id)
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
                f"- **货物**：{cargo_label(record.cargo_key)} ×{record.cargo_quantity}\n"
                f"- **货值**：{record.cargo_value} 灵石\n"
                f"- **体力消耗**：{record.stamina_cost}\n"
                f"- **基础耗时**：{record.duration_seconds // 60} 分钟\n"
                f"- **今日次数**：{record.daily_used}/{record.daily_limit}\n"
                f"- **当前缺少**：{missing}\n\n"
                f"> {'发送 `开始运输 ' + cargo_label(record.cargo_key) + '` 开始。' if record.ready else '满足条件后才可锁定货物。'}"
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
            },
        )

    async def start_route(self, context: CommandContext) -> CommandResult:
        parsed = self._parse_route_args(context.command_args)
        if parsed is None:
            return CommandResult(False, "INVALID_ROUTE", "请使用 `开始运输 止血草 [数量]`。", context.request_id)
        route_key, cargo_key, quantity = parsed
        operation_id = self._operation_id(context, "livelihood.start_route")
        try:
            record = await self.repository.start_route(
                platform=context.adapter,
                platform_user_id=context.user_id,
                route_key=route_key,
                cargo_key=cargo_key,
                cargo_quantity=quantity,
                operation_id=operation_id,
            )
        except RouteContentClosedError:
            return CommandResult(False, "LIVELIHOOD_CONTENT_CLOSED", "该运输路线或货物暂未开放。", context.request_id, operation_id)
        except RouteCargoRequirementError:
            return CommandResult(False, "ROUTE_CARGO_LOCKED", "货物不足或货值超过路线限制，未扣除任何资源。", context.request_id, operation_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except PlayerStageConflictError:
            return CommandResult(False, "ROUTE_REQUIREMENT_MISSING", "完成入道后才能开始运输。", context.request_id, operation_id)
        except RouteLocationRequirementError:
            return CommandResult(False, "ROUTE_LOCATION_REQUIRED", "请先回到青石镇再开始这条运输。", context.request_id, operation_id)
        except RouteQuotaError:
            return CommandResult(False, "ROUTE_QUOTA_EXHAUSTED", "今日运输次数已用尽。", context.request_id, operation_id)
        except RouteBusyError:
            return CommandResult(False, "ROUTE_BUSY", "已有移动、修炼、生产或其他会话正在进行。", context.request_id, operation_id)
        except ResourceInsufficientError:
            return CommandResult(False, "ROUTE_RESOURCE_INSUFFICIENT", "体力不足，未扣除货物或其他资源。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能开始运输。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于其他运输输入。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        delay_text = f"，可能延误 {record.delay_seconds // 60} 分钟" if record.delay_seconds else ""
        return CommandResult(
            True,
            "ROUTE_STARTED",
            (
                f"## 运输已开始\n\n**{self._display_name(record.player)}**锁定了"
                f"**{cargo_label(record.cargo_key)} ×{record.cargo_quantity}**。\n\n"
                f"- **路线**：{record.route_name}\n- **体力**：{record.player.stamina}/{record.player.stamina_max}\n"
                f"- **预计抵达**：{record.arrives_at}{delay_text}\n\n> 抵达后发送 `结算运输 {record.route_id}`。"
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
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能结算运输。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于其他运输结算。", context.request_id, operation_id)
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
                f"- **已交付货物**：{cargo_label(record.cargo_key)} ×{record.cargo_quantity}"
            ),
            context.request_id,
            operation_id,
            data={
                "route_id": record.route_id,
                "route_key": record.route_key,
                "status": record.status,
                "reward_stones": record.reward_stones,
                "local_reputation_delta": record.local_reputation_delta,
                "delay_seconds": record.delay_seconds,
                "cargo": record.cargo,
                "idempotent_replay": record.already_completed,
            },
        )


__all__ = ["RouteApplication"]
