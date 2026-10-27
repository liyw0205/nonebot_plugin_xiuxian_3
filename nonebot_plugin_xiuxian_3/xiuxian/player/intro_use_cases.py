"""Application use cases for the mortal onboarding lessons."""

from __future__ import annotations

from typing import Any

from ...contracts import CommandContext, CommandResult
from ..content import ContentBundle, bundled_content
from ..repository import (
    CultivationBusyError,
    LocationRequiredError,
    LocationRequirementError,
    OperationConflictError,
    PlayerNotFoundError,
    PlayerStageConflictError,
    PlayerSuspendedError,
    RepositoryBusyError,
    ResourceInsufficientError,
    SQLitePlayerRepository,
    WeaknessActiveError,
)
from .intro_rules import (
    SERVICE_LABELS,
    TRAVEL_LABELS,
    guide_commands,
    guide_definition,
    guides_for_stage,
    resolve_destination,
    resolve_guide,
    resolve_service,
)
from .rules import STAGE_LABELS
from ..utils.text import command_link


class IntroApplication:
    """Coordinates onboarding writes without exposing persistence details."""

    def __init__(self, repository: SQLitePlayerRepository, content: ContentBundle | None = None):
        self.repository = repository
        self.content = content or bundled_content()

    def world_intro_text(self) -> str:
        definition = self.content.get("guide", "guide.read_world", include_locked=False)
        body = definition.get("content") if definition else None
        if not isinstance(body, str) or not body.strip():
            raise ValueError("guide.read_world requires non-empty content")
        return body.strip()

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
    def _stage(player) -> str:
        return STAGE_LABELS.get(player.stage, "修行阶段")

    def _guide_definition(self, guide_key: str) -> dict[str, Any] | None:
        try:
            return guide_definition(guide_key, self.content)
        except ValueError:
            return None

    @staticmethod
    def _guide_body(definition: dict[str, Any] | None) -> str:
        if not definition:
            return ""
        body = definition.get("desc")
        return body.strip() if isinstance(body, str) else ""

    def _stage_guides(self, player) -> tuple[dict[str, Any], ...]:
        """The guides the player's current stage may still work on."""

        return guides_for_stage(str(player.stage), self.content)

    def _guide_progress(self, player) -> str:
        # Stage-filtered: a mortal never sees the realm-gated guides counted in
        # their denominator, and a graduated player is measured against their own
        # tier instead of the onboarding trio.
        available = self._stage_guides(player)
        if not available:
            return "0/0"
        completed = set(player.intro_flags)
        done = sum(1 for definition in available if definition["key"] in completed)
        return f"{done}/{len(available)}"

    def _guide_hint(self, player) -> str:
        available = self._stage_guides(player)
        completed = set(player.intro_flags)
        pending = [definition for definition in available if definition["key"] not in completed]
        if not pending:
            # Graduation is only half the onboarding: a mortal or a graduated
            # seeker is still told to declare a path, exactly as before.
            if str(player.stage) in {"mortal", "seeker"}:
                return f"用{command_link('选择道途', '选择道途')}填写自己的修行方向。"
            return f"引导已全部完成，可用{command_link('我的状态', '我的状态')}查看当前进展。"
        definition = pending[0]
        if definition["locations"] and player.location_key not in definition["locations"]:
            label = TRAVEL_LABELS.get(definition["locations"][0], definition["locations"][0])
            destination = "前往近郊" if definition["locations"][0] == "xuantian.outskirts" else f"前往{label}"
            return f"先{command_link(destination, destination)}，再完成{definition['label']}。"
        if definition["options"]:
            return "选择一项生产教学：" + "、".join(
                command_link(f"完成引导 {SERVICE_LABELS[option]}", f"完成引导 {SERVICE_LABELS[option]}")
                for option in definition["options"]
            ) + "。"
        command = f"完成引导 {definition['command']}"
        suffix = "继续凡人引导。" if str(player.stage) == "mortal" else "继续修行。"
        return command_link(command, command) + "，" + suffix

    async def complete_intro(self, context: CommandContext) -> CommandResult:
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
            return CommandResult(False, "PLAYER_NOT_FOUND", f"还没有角色，先{command_link('开始修仙', '开始修仙')}。", context.request_id, operation_id)
        except PlayerStageConflictError:
            return CommandResult(False, "PLAYER_STAGE_CONFLICT", f"凡人引导在寻仙后、入道前进行；{command_link('我的状态', '我的状态')}可查看当前阶段与下一步。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色处于暂停状态，暂时不能完成引导。", context.request_id, operation_id)
        except LocationRequiredError:
            return CommandResult(False, "LOCATION_REQUIRED", f"教学采集在玄天近郊，先{command_link('前往近郊', '前往近郊')}。", context.request_id, operation_id)
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
        definition = self._guide_definition(guide_key)
        label = definition["label"] if definition else guide_key
        if not record.changed:
            message = (
                "## 引导已完成\n\n"
                f"**{self._display_name(player)}**，`{label}`已经记录过了。\n\n"
                f"- **引导进度**：{self._guide_progress(player)}\n"
                f"- **当前阶段**：{self._stage(player)}\n\n"
                f"> 下一步：{self._guide_hint(player)}"
            )
        elif guide_key == "guide.read_world":
            message = (
                "## 修仙世界\n\n"
                f"{self.world_intro_text()}\n\n"
                "---\n\n"
                "## 世界说明已阅\n\n"
                f"**{self._display_name(player)}**，你已了解玄天界、魔界、妖界与洞天福地。\n\n"
                f"- **引导进度**：{self._guide_progress(player)}\n\n"
                f"> 下一步：{self._guide_hint(player)}"
            )
        elif guide_key == "guide.gather_blood_grass":
            message = (
                "## 教学采集完成\n\n"
                f"**{self._display_name(player)}**，你在玄天近郊采得 **止血草 ×{record.item_quantity}**。\n\n"
                f"- **体力**：{player.stamina}/{player.stamina_max}\n"
                f"- **引导进度**：{self._guide_progress(player)}\n\n"
                f"> 下一步：{self._guide_hint(player)}"
            )
        elif guide_key == "guide.choose_service":
            service_name = SERVICE_LABELS.get(record.selected_service or service_key or "", "生产")
            message = (
                "## 生产教学已选\n\n"
                f"**{self._display_name(player)}**，你选择了 **{service_name}** 教学。\n\n"
                f"- **精力**：{player.energy}/{player.energy_max}\n"
                f"- **引导进度**：{self._guide_progress(player)}\n\n"
                f"> 下一步：{self._guide_hint(player)}"
            )
        else:
            body = self._guide_body(definition)
            lead = f"\n\n{body}\n\n" if body else "\n\n"
            message = (
                f"## {label}已记录\n"
                f"{lead}"
                f"- **当前阶段**：{self._stage(player)}\n"
                f"- **引导进度**：{self._guide_progress(player)}\n\n"
                f"> 下一步：{self._guide_hint(player)}"
            )
        if record.stage_advanced:
            message = message.replace(
                f"> 下一步：{self._guide_hint(player)}",
                f"三项引导已完成，你已成为求道者。{self._guide_hint(player)}",
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
        destination_key = resolve_destination(destination)
        if destination_key is None:
            return CommandResult(False, "INVALID_DESTINATION", "目前支持 `前往近郊`、`前往灵泉谷` 和 `返回新手城`。", context.request_id)
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
        except LocationRequirementError:
            return CommandResult(False, "LOCATION_REQUIREMENT_MISSING", "前往灵泉谷需要满足境界、教学和来源地点条件。", context.request_id, operation_id)
        except CultivationBusyError:
            return CommandResult(False, "TRAVEL_BUSY", "修炼进行中不能移动，请先结算或取消修炼。", context.request_id, operation_id)
        except WeaknessActiveError:
            return CommandResult(False, "TRAVEL_BUSY", "突破虚弱期间不能移动，请先恢复状态。", context.request_id, operation_id)
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
            next_step = (
                "发送 `开始修炼 灵泉`，在灵泉谷吸纳灵气。"
                if destination_key == "xuantian.spirit_field"
                else "发送 `完成引导 采集`，完成教学采集。"
            )
            message = (
                "## 已抵达\n\n"
                f"**{self._display_name(player)}**已抵达 **{destination_name}**。\n\n"
                f"- **体力**：{player.stamina}/{player.stamina_max}\n\n"
                f"> 下一步：{next_step}"
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

    def _parse_guide(self, args: tuple[str, ...]) -> tuple[str, str | None, str | None]:
        commands = guide_commands(self.content)
        hints = "、".join(f"`完成引导 {command}`" for command in sorted(set(commands.values())))
        if not args or len(args) > 2:
            return "", None, f"请使用 {hints}。"
        guide_key = resolve_guide(args[0], self.content)
        definition = self._guide_definition(guide_key) if guide_key else None
        options = tuple(definition["options"]) if definition else ()
        needs_service = bool(options)
        service_key: str | None = None
        if len(args) == 2:
            if not needs_service:
                return "", None, "只有生产教学需要指定炼丹、炼器或布阵。"
            service_key = resolve_service(args[1])
        elif needs_service:
            service_key = resolve_service(args[0])
        if guide_key is None:
            return "", None, f"未知引导，请选择 {hints}。"
        if needs_service and service_key is None:
            names = "、".join(SERVICE_LABELS[option] for option in options)
            return "", None, f"生产教学请选择{names}。"
        return guide_key, service_key, None


__all__ = ["IntroApplication"]
