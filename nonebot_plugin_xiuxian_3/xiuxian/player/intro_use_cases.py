"""Application use cases for the mortal onboarding lessons."""

from __future__ import annotations

from ...contracts import CommandContext, CommandResult
from ..repository import (
    LocationRequiredError,
    OperationConflictError,
    PlayerNotFoundError,
    PlayerStageConflictError,
    PlayerSuspendedError,
    RepositoryBusyError,
    ResourceInsufficientError,
    SQLitePlayerRepository,
)
from .intro_rules import (
    GUIDE_COMMANDS,
    GUIDE_CHOOSE_SERVICE,
    GUIDE_GATHER_BLOOD_GRASS,
    GUIDE_LABELS,
    GUIDE_READ_WORLD,
    SERVICE_LABELS,
    TRAVEL_LABELS,
    resolve_destination,
    resolve_guide,
    resolve_service,
)
from .rules import STAGE_LABELS


class IntroApplication:
    """Coordinates onboarding writes without exposing persistence details."""

    def __init__(self, repository: SQLitePlayerRepository):
        self.repository = repository

    @staticmethod
    def _operation_id(context: CommandContext, operation_name: str) -> str:
        if context.operation_id:
            return context.operation_id
        request_key = context.message_id or context.request_id
        return f"{operation_name}:{context.adapter}:{context.user_id}:{request_key}"

    @staticmethod
    def _invalid_context(context: CommandContext, message: str) -> CommandResult | None:
        try:
            context.validate()
        except ValueError:
            return CommandResult(False, "INVALID_CONTEXT", "无法识别你的平台身份，请稍后重试。", context.request_id)
        if not context.can_write_assets:
            return CommandResult(False, "INVALID_CONTEXT", message, context.request_id)
        return None

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
    def _stage(player) -> str:
        return STAGE_LABELS.get(player.stage, "修行阶段")

    @staticmethod
    def _guide_progress(player) -> str:
        return f"{len(set(player.intro_flags))}/3"

    @staticmethod
    def _guide_hint(player) -> str:
        pending = [key for key in GUIDE_LABELS if key not in set(player.intro_flags)]
        if not pending:
            return "发送 `选择道途 体修`，选择你的首要修行方向。"
        return "、".join(f"`完成引导 {GUIDE_COMMANDS[key]}`" for key in pending)

    async def complete_intro(self, context: CommandContext) -> CommandResult:
        invalid = self._invalid_context(context, "当前事件不允许进行引导结算。")
        if invalid is not None:
            return invalid
        guide_key, service_key, error = self._parse_guide(context.command_args)
        if error:
            return CommandResult(False, "INVALID_GUIDE", error, context.request_id)
        operation_id = self._operation_id(context, "player.complete_intro")
        try:
            record = await self.repository.complete_intro(
                platform=context.adapter,
                platform_user_id=context.user_id,
                guide_key=guide_key,
                service_key=service_key,
                operation_id=operation_id,
            )
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except PlayerStageConflictError:
            return CommandResult(False, "PLAYER_STAGE_CONFLICT", "完成引导需要先完成 `寻仙问道`，且当前阶段必须是凡人。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色处于暂停状态，暂时不能完成引导。", context.request_id, operation_id)
        except LocationRequiredError:
            return CommandResult(False, "LOCATION_REQUIRED", "教学采集需要先发送 `前往近郊`。", context.request_id, operation_id)
        except ResourceInsufficientError as exc:
            resource = "体力" if "stamina" in str(exc) else "精力"
            return CommandResult(False, "RESOURCE_INSUFFICIENT", f"{resource}不足，暂时无法完成这项引导。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求的操作编号已用于其他输入，请重新发起操作。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)

        player = record.player
        if not record.changed:
            message = (
                "## 引导已完成\n\n"
                f"**{self._display_name(player)}**，`{GUIDE_LABELS[guide_key]}`已经记录过了。\n\n"
                f"- **引导进度**：{self._guide_progress(player)}\n"
                f"- **当前阶段**：{self._stage(player)}\n\n"
                f"> 下一步：{self._guide_hint(player)}"
            )
        elif guide_key == GUIDE_READ_WORLD:
            message = (
                "## 世界说明已阅\n\n"
                f"**{self._display_name(player)}**，你已了解玄天界、魔界、妖界与洞天福地。\n\n"
                f"- **引导进度**：{self._guide_progress(player)}\n\n"
                f"> 下一步：{self._guide_hint(player)}"
            )
        elif guide_key == GUIDE_GATHER_BLOOD_GRASS:
            message = (
                "## 教学采集完成\n\n"
                f"**{self._display_name(player)}**，你在玄天近郊采得 **止血草 ×{record.item_quantity}**。\n\n"
                f"- **体力**：{player.stamina}/{player.stamina_max}\n"
                f"- **引导进度**：{self._guide_progress(player)}\n\n"
                f"> 下一步：{self._guide_hint(player)}"
            )
        else:
            service_name = SERVICE_LABELS.get(record.selected_service or service_key or "", "生产")
            message = (
                "## 生产教学已选\n\n"
                f"**{self._display_name(player)}**，你选择了 **{service_name}** 教学。\n\n"
                f"- **精力**：{player.energy}/{player.energy_max}\n"
                f"- **引导进度**：{self._guide_progress(player)}\n\n"
                f"> 下一步：{self._guide_hint(player)}"
            )
        if record.stage_advanced:
            message = message.replace(
                f"> 下一步：{self._guide_hint(player)}",
                "> 三项引导已完成，你已成为求道者。下一步：发送 `选择道途 体修`。",
            )
        return CommandResult(
            True,
            "INTRO_COMPLETED" if record.changed else "INTRO_ALREADY_COMPLETED",
            message,
            context.request_id,
            operation_id,
            data={
                "player_id": player.player_id,
                "dao_name": player.dao_name,
                "guide_key": guide_key,
                "stage": player.stage,
                "stage_advanced": record.stage_advanced,
                "stamina": player.stamina,
                "energy": player.energy,
                "inventory": player.inventory,
                "intro_flags": player.intro_flags,
                "selected_service": player.selected_service,
                "item_quantity": record.item_quantity,
                "idempotent_replay": record.already_completed,
            },
        )

    async def travel_intro(self, context: CommandContext, destination: str) -> CommandResult:
        invalid = self._invalid_context(context, "当前事件不允许进行移动。")
        if invalid is not None:
            return invalid
        destination_key = resolve_destination(destination)
        if destination_key is None:
            return CommandResult(False, "INVALID_DESTINATION", "目前只支持 `前往近郊` 和 `返回新手城`。", context.request_id)
        operation_id = self._operation_id(context, "world.travel_intro")
        try:
            record = await self.repository.travel_player(
                platform=context.adapter,
                platform_user_id=context.user_id,
                destination=destination_key,
                operation_id=operation_id,
            )
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except PlayerStageConflictError:
            return CommandResult(False, "PLAYER_STAGE_CONFLICT", "完成 `寻仙问道` 后才能前往近郊。", context.request_id, operation_id)
        except ResourceInsufficientError:
            return CommandResult(False, "RESOURCE_INSUFFICIENT", "体力不足，暂时无法移动。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色处于暂停状态，暂时不能移动。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求的操作编号已用于其他目的，请重新发起移动。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)

        player = record.player
        destination_name = TRAVEL_LABELS[destination_key]
        if record.changed:
            message = (
                "## 已抵达\n\n"
                f"**{self._display_name(player)}**已抵达 **{destination_name}**。\n\n"
                f"- **体力**：{player.stamina}/{player.stamina_max}\n\n"
                f"> 下一步：发送 `完成引导 采集`，完成教学采集。"
            )
        else:
            message = f"## 已在此处\n\n你当前就在 **{destination_name}**，无需重复移动。"
        return CommandResult(
            True,
            "TRAVEL_COMPLETED" if record.changed else "TRAVEL_ALREADY_COMPLETED",
            message,
            context.request_id,
            operation_id,
            data={
                "player_id": player.player_id,
                "dao_name": player.dao_name,
                "destination": destination_key,
                "stamina": player.stamina,
                "stamina_cost": record.stamina_cost,
                "idempotent_replay": record.already_completed,
            },
        )

    @staticmethod
    def _parse_guide(args: tuple[str, ...]) -> tuple[str, str | None, str | None]:
        if not args or len(args) > 2:
            return "", None, "请使用 `完成引导 阅读`、`完成引导 采集` 或 `完成引导 炼丹/炼器/布阵`。"
        guide_key = resolve_guide(args[0])
        service_key: str | None = None
        if len(args) == 2:
            if guide_key != GUIDE_CHOOSE_SERVICE:
                return "", None, "只有生产教学需要指定炼丹、炼器或布阵。"
            service_key = resolve_service(args[1])
        elif guide_key == GUIDE_CHOOSE_SERVICE:
            service_key = resolve_service(args[0])
        if guide_key is None:
            return "", None, "未知引导，请选择阅读、采集、炼丹、炼器或布阵。"
        if guide_key == GUIDE_CHOOSE_SERVICE and service_key is None:
            return "", None, "生产教学请选择炼丹、炼器或布阵。"
        return guide_key, service_key, None


__all__ = ["IntroApplication"]
