"""Application services for the first cultivation progression slice."""

from __future__ import annotations

from ...contracts import CommandContext, CommandResult
from ..repository import (
    CultivationBusyError,
    CultivationNotFoundError,
    CultivationNotReadyError,
    OperationConflictError,
    PlayerNotFoundError,
    PlayerStageConflictError,
    PlayerSuspendedError,
    RealmCultivationInsufficientError,
    RealmLayerInvalidError,
    RepositoryBusyError,
    ResourceInsufficientError,
    SQLitePlayerRepository,
)
from .rules import (
    BREATHING_DURATION_SECONDS,
    MODE_BREATHING,
    can_advance_layer,
    next_layer_threshold,
)


class ProgressionApplication:
    """Coordinates cultivation sessions and layer advancement."""

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
    def _invalid_context(context: CommandContext) -> CommandResult | None:
        try:
            context.validate()
        except ValueError:
            return CommandResult(False, "INVALID_CONTEXT", "无法识别你的平台身份，请稍后重试。", context.request_id)
        if not context.can_write_assets:
            return CommandResult(False, "INVALID_CONTEXT", "当前事件不允许进行修炼结算。", context.request_id)
        return None

    async def start_cultivation(self, context: CommandContext) -> CommandResult:
        invalid = self._invalid_context(context)
        if invalid is not None:
            return invalid
        if context.command_args and context.command_args != ("调息",):
            return CommandResult(False, "INVALID_CULTIVATION_MODE", "目前只支持 `开始修炼` 或 `开始修炼 调息`。", context.request_id)
        operation_id = self._operation_id(context, "progression.start_cultivation")
        try:
            record = await self.repository.start_cultivation(
                platform=context.adapter,
                platform_user_id=context.user_id,
                mode_key=MODE_BREATHING,
                operation_id=operation_id,
            )
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except PlayerStageConflictError:
            return CommandResult(False, "PLAYER_STAGE_CONFLICT", "完成入道后才能开始修炼。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色处于暂停状态，暂时不能修炼。", context.request_id, operation_id)
        except CultivationBusyError:
            return CommandResult(False, "CULTIVATION_BUSY", "你已经有一场修炼正在进行，请先结算或取消。", context.request_id, operation_id)
        except ResourceInsufficientError:
            return CommandResult(False, "RESOURCE_INSUFFICIENT", "体力不足，暂时无法开始修炼。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求的操作编号已用于其他修炼，请重新发起。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)

        player = record.player
        message = (
            "## 修炼已开始\n\n"
            f"**{self._display_name(player)}**已开始调息修炼。\n\n"
            f"- **消耗体力**：{record.stamina_cost}\n"
            f"- **剩余体力**：{player.stamina}/{player.stamina_max}\n"
            f"- **预计时长**：{BREATHING_DURATION_SECONDS // 60} 分钟\n\n"
            "> 下一步：修炼结束后发送 `结算修炼`；也可以发送 `取消修炼` 返还体力。"
        )
        return CommandResult(
            True,
            "CULTIVATION_STARTED" if not record.already_completed else "CULTIVATION_STARTED",
            message,
            context.request_id,
            operation_id,
            data={
                "dao_name": player.dao_name,
                "session_id": record.session_id,
                "mode_key": record.mode_key,
                "status": record.status,
                "stamina": player.stamina,
                "stamina_cost": record.stamina_cost,
                "ends_at": record.ends_at,
                "idempotent_replay": record.already_completed,
            },
        )

    async def settle_cultivation(self, context: CommandContext) -> CommandResult:
        invalid = self._invalid_context(context)
        if invalid is not None:
            return invalid
        if context.command_args:
            return CommandResult(False, "INVALID_CULTIVATION_COMMAND", "结算修炼无需附加参数。", context.request_id)
        operation_id = self._operation_id(context, "progression.settle_cultivation")
        try:
            record = await self.repository.settle_cultivation(
                platform=context.adapter,
                platform_user_id=context.user_id,
                operation_id=operation_id,
            )
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except CultivationNotFoundError:
            return CommandResult(False, "CULTIVATION_NOT_FOUND", "当前没有可结算的修炼。", context.request_id, operation_id)
        except CultivationNotReadyError:
            return CommandResult(False, "CULTIVATION_NOT_READY", "修炼尚未结束，请稍后再来结算。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色处于暂停状态，暂时不能结算修炼。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求的操作编号已用于其他结算，请重新发起。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)

        player = record.player
        threshold = next_layer_threshold(player.realm_key, player.realm_layer)
        next_step = "发送 `晋升境界`，尝试进入下一层。" if threshold is not None and player.cultivation >= threshold else "继续发送 `开始修炼`，积累境内修为。"
        message = (
            "## 修炼结算完成\n\n"
            f"**{self._display_name(player)}**获得 **修为 ×{record.cultivation_gain}**。\n\n"
            f"- **境界**：感气 L{player.realm_layer}\n"
            f"- **境内修为**：{player.cultivation}/{threshold or '混元'}\n"
            f"- **总修为**：{player.total_cultivation}\n"
            f"- **体力**：{player.stamina}/{player.stamina_max}\n\n"
            f"> 下一步：{next_step}"
        )
        return CommandResult(
            True,
            "CULTIVATION_SETTLED",
            message,
            context.request_id,
            operation_id,
            data={
                "dao_name": player.dao_name,
                "session_id": record.session_id,
                "cultivation_gain": record.cultivation_gain,
                "cultivation": player.cultivation,
                "total_cultivation": player.total_cultivation,
                "realm_key": player.realm_key,
                "realm_layer": player.realm_layer,
                "stamina": player.stamina,
                "idempotent_replay": record.already_completed,
            },
        )

    async def cancel_cultivation(self, context: CommandContext) -> CommandResult:
        invalid = self._invalid_context(context)
        if invalid is not None:
            return invalid
        if context.command_args:
            return CommandResult(False, "INVALID_CULTIVATION_COMMAND", "取消修炼无需附加参数。", context.request_id)
        operation_id = self._operation_id(context, "progression.cancel_cultivation")
        try:
            record = await self.repository.cancel_cultivation(
                platform=context.adapter,
                platform_user_id=context.user_id,
                operation_id=operation_id,
            )
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except CultivationNotFoundError:
            return CommandResult(False, "CULTIVATION_NOT_FOUND", "当前没有可取消的修炼。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色处于暂停状态，暂时不能取消修炼。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求的操作编号已用于其他取消操作，请重新发起。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        player = record.player
        return CommandResult(
            True,
            "CULTIVATION_CANCELLED",
            (
                "## 修炼已取消\n\n"
                f"**{self._display_name(player)}**收回了本次修炼消耗的体力。\n\n"
                f"- **返还体力**：{record.stamina_refund}\n"
                f"- **体力**：{player.stamina}/{player.stamina_max}\n\n"
                "> 下一步：准备好后可再次发送 `开始修炼`。"
            ),
            context.request_id,
            operation_id,
            data={
                "dao_name": player.dao_name,
                "stamina": player.stamina,
                "stamina_refund": record.stamina_refund,
                "idempotent_replay": record.already_completed,
            },
        )

    async def advance_layer(self, context: CommandContext) -> CommandResult:
        invalid = self._invalid_context(context)
        if invalid is not None:
            return invalid
        if context.command_args:
            return CommandResult(False, "INVALID_LAYER", "晋升境界无需附加层数，系统会按当前进度逐层晋升。", context.request_id)
        operation_id = self._operation_id(context, "progression.advance_layer")
        try:
            record = await self.repository.advance_layer(
                platform=context.adapter,
                platform_user_id=context.user_id,
                operation_id=operation_id,
            )
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except PlayerStageConflictError:
            return CommandResult(False, "PLAYER_STAGE_CONFLICT", "完成入道后才能晋升境界。", context.request_id, operation_id)
        except CultivationBusyError:
            return CommandResult(False, "CULTIVATION_BUSY", "修炼尚未结算，暂时不能晋升境界。", context.request_id, operation_id)
        except RealmLayerInvalidError:
            return CommandResult(False, "REALM_LAYER_INVALID", "当前境界已经是感气混元，不能继续晋升。", context.request_id, operation_id)
        except RealmCultivationInsufficientError:
            return CommandResult(False, "REALM_CULTIVATION_INSUFFICIENT", "境内修为尚未达到下一层门槛，继续修炼后再来。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色处于暂停状态，暂时不能晋升。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求的操作编号已用于其他晋升，请重新发起。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        player = record.player
        threshold = next_layer_threshold(player.realm_key, player.realm_layer)
        message = (
            "## 境界晋升\n\n"
            f"**{self._display_name(player)}**已进入 **感气 L{player.realm_layer}**。\n\n"
            f"- **境内修为**：{player.cultivation}/{threshold or '混元'}\n"
            f"- **总修为**：{player.total_cultivation}\n\n"
            "> 下一步：继续 `开始修炼`，逐层稳固修为。"
        )
        return CommandResult(
            True,
            "REALM_LAYER_ADVANCED",
            message,
            context.request_id,
            operation_id,
            data={
                "dao_name": player.dao_name,
                "realm_key": player.realm_key,
                "realm_layer": player.realm_layer,
                "cultivation": player.cultivation,
                "total_cultivation": player.total_cultivation,
                "idempotent_replay": record.already_completed,
            },
        )

    async def recover_resources(self, context: CommandContext) -> CommandResult:
        invalid = self._invalid_context(context)
        if invalid is not None:
            return invalid
        if context.command_args:
            return CommandResult(False, "INVALID_RECOVERY_COMMAND", "恢复状态无需附加参数。", context.request_id)
        operation_id = self._operation_id(context, "player.recover_resources")
        try:
            record = await self.repository.recover_resources(
                platform=context.adapter,
                platform_user_id=context.user_id,
                operation_id=operation_id,
            )
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色处于暂停状态，暂时不能恢复资源。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求的操作编号已用于其他恢复，请重新发起。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        player = record.player
        message = (
            "## 状态恢复完成\n\n"
            f"**{self._display_name(player)}**的体力与精力已按时间恢复。\n\n"
            f"- **体力**：{player.stamina}/{player.stamina_max}\n"
            f"- **精力**：{player.energy}/{player.energy_max}\n"
            f"- **恢复周期**：{record.periods} 个\n"
        )
        if not record.changed:
            message += "\n> 当前资源已满，或距离下一次恢复还不足 30 分钟。"
        return CommandResult(
            True,
            "RESOURCES_RECOVERED" if record.changed else "RESOURCES_ALREADY_FULL",
            message,
            context.request_id,
            operation_id,
            data={
                "dao_name": player.dao_name,
                "stamina": player.stamina,
                "stamina_max": player.stamina_max,
                "energy": player.energy,
                "energy_max": player.energy_max,
                "recovered_stamina": record.recovered_stamina,
                "recovered_energy": record.recovered_energy,
                "periods": record.periods,
                "idempotent_replay": record.already_completed,
            },
        )


__all__ = ["ProgressionApplication"]
