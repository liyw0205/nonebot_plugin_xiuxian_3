"""Application services for low-tier equipment tempering and refinement."""

from __future__ import annotations

from ...contracts import CommandContext, CommandResult
from ..utils.text import command_link
from ..content import ContentBundle, bundled_content
from ..repository import (
    EquipmentAmbiguousError,
    EquipmentNotOwnedError,
    EquipmentRequirementError,
    EquipmentRepairLocationError,
    EquipmentRepairNotNeededError,
    EquipmentReclamationEquippedError,
    EquipmentFieldRepairNotNeededError,
    EquipmentRepairKitInsufficientError,
    EquipmentTemperingMaxedError,
    OperationConflictError,
    PlayerNotFoundError,
    PlayerStageConflictError,
    PlayerSuspendedError,
    RepositoryBusyError,
    ResourceInsufficientError,
    EquipmentBusyError,
    EquipmentDurabilityZeroError,
    EquipmentSlotBusyError,
    SQLitePlayerRepository,
)
from .equipment_rules import (
    EquipmentDefinition,
    equipment_affix_label,
    equipment_definitions,
    equipment_repair_cost,
    equipment_resource_label,
    equipment_repair_kit,
    refinement_cost,
    refinement_pity_failures,
    refinement_success_bp,
    temper_cost,
    temper_success_bp,
)


class EquipmentApplication:
    """Coordinate equipment growth without starting a battle runtime."""

    def __init__(self, repository: SQLitePlayerRepository):
        self.repository = repository
        self._equipment_definition_cache: tuple[ContentBundle, dict[str, EquipmentDefinition]] | None = None
        self._equipment_preview_cache: tuple[ContentBundle, dict[str, str]] | None = None

    def _equipment_definitions(self, content: ContentBundle) -> dict[str, EquipmentDefinition]:
        cached = self._equipment_definition_cache
        if cached is None or cached[0] is not content:
            definitions = equipment_definitions(content)
            cached = (content, definitions)
            self._equipment_definition_cache = cached
            self._equipment_preview_cache = None
        return cached[1]

    def _equipment_preview_text(self, content: ContentBundle, *, mode: str) -> str:
        definitions = self._equipment_definitions(content)
        cached = self._equipment_preview_cache
        if cached is None or cached[0] is not content:
            cached = (content, {})
            self._equipment_preview_cache = cached
        message = cached[1].get(mode)
        if message is not None:
            return message

        lines = ["## 装备祭炼" if mode == "temper" else "## 灵纹重铸", ""]
        for definition in sorted(definitions.values(), key=lambda item: item.label):
            if mode == "temper":
                lines.append(f"### {definition.label}")
                if definition.min_realm_key:
                    lines.append(
                        f"最低境界：{content.label('realm', definition.min_realm_key)} L{definition.min_layer}"
                    )
                lines.append(f"最高阶数：{definition.max_temper_level}")
                for level in range(1, definition.max_temper_level + 1):
                    costs = temper_cost(level, definition)
                    success_bp = temper_success_bp(level, definition)
                    lines.append(
                        f"- **{level} 阶**：{self._cost_text(costs, content)}，成功率 `{success_bp / 100:.0f}%`。"
                    )
                lines.append("")
            else:
                refinement = definition.growth["refinement"]
                affixes = refinement["affix_pool"]
                results = "、".join(
                    f"**{equipment_affix_label(row['key'], content)} +{row['value']}**"
                    for row in affixes
                )
                lines.extend(
                    [
                        f"### {definition.label}",
                        f"消耗：{self._cost_text(refinement_cost(definition), content)}",
                        f"成功率：`{refinement_success_bp(definition) / 100:.0f}%`；连续失败 {refinement_pity_failures(definition)} 次后必定成功。",
                        f"可能词条：{results}。",
                        "",
                    ]
                )
        lines.append("> 使用 `强化法器 <装备名称>`。" if mode == "temper" else "> 使用 `重铸法器 <装备名称>`。")
        message = "\n".join(lines)
        cached[1][mode] = message
        return message

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

    def _content(self) -> ContentBundle:
        return self.repository.content or bundled_content()

    @staticmethod
    def _slot_label(slot: str) -> str:
        return {"weapon": "法器", "armor": "防具", "accessory": "饰品"}.get(slot, "装备")

    def _cost_text(self, costs: dict[str, int], content: ContentBundle | None = None) -> str:
        content = content or self._content()
        return "、".join(
            f"{equipment_resource_label(resource_key, content)} ×{quantity}"
            for resource_key, quantity in costs.items()
        ) or "无消耗"

    def _affix_text(self, affixes: dict[str, int], content: ContentBundle | None = None) -> str:
        if not affixes:
            return "无"
        content = content or self._content()
        return "、".join(
            f"**{equipment_affix_label(key, content)}** +{value}"
            for key, value in affixes.items()
        )

    async def preview_tempering(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_EQUIPMENT_COMMAND", "法器预览无需附加参数。", context.request_id)
        content = self._content()
        return CommandResult(
            True,
            "EQUIPMENT_TEMPER_PREVIEW",
            self._equipment_preview_text(content, mode="temper"),
            context.request_id,
        )

    async def preview_refinement(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_EQUIPMENT_COMMAND", "重铸预览无需附加参数。", context.request_id)
        content = self._content()
        return CommandResult(
            True,
            "EQUIPMENT_REFINE_PREVIEW",
            self._equipment_preview_text(content, mode="refine"),
            context.request_id,
        )

    async def preview_repair(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 1:
            return CommandResult(
                False,
                "INVALID_EQUIPMENT_REPAIR_COMMAND",
                "请从我的装备中选择具体实例，例如 `装备修复预览 装备编号`。",
                context.request_id,
            )
        try:
            listing = await self.repository.list_equipment(
                platform=context.adapter,
                platform_user_id=context.user_id,
            )
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时无法查看装备。", context.request_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, retryable=True)

        instance_id = context.command_args[0].strip()
        equipment = next((row for row in listing.equipment if row.instance_id == instance_id), None)
        if equipment is None:
            return CommandResult(False, "EQUIPMENT_NOT_OWNED", "没有找到这件可修缮的装备。", context.request_id)
        missing_bp = 10_000 - equipment.durability_bp
        if missing_bp <= 0:
            return CommandResult(False, "EQUIPMENT_REPAIR_NOT_NEEDED", "这件装备耐久充足，无需修缮。", context.request_id)
        content = self._content()
        definition = self._equipment_definitions(content).get(equipment.item_key)
        if definition is None:
            return CommandResult(False, "EQUIPMENT_CONTENT_CLOSED", "这件装备当前没有开放的修缮规则。", context.request_id)
        repair = definition.growth["repair"]
        location_key = str(repair["location_key"])
        costs = equipment_repair_cost(missing_bp, definition)
        inventory = listing.player.inventory
        shortages = {
            key: quantity - (listing.player.spirit_stones if key == "currency.spirit_stone" else int(inventory.get(key, 0)))
            for key, quantity in costs.items()
            if (listing.player.spirit_stones if key == "currency.spirit_stone" else int(inventory.get(key, 0))) < quantity
        }
        at_location = listing.player.location_key == location_key
        lines = ["## 装备修复预览", "", f"装备：**{equipment.label}** · {equipment.instance_id}"]
        lines.append(f"耐久：{equipment.durability_bp / 100:.0f}% → 100%")
        lines.append(f"修缮地点：{content.label('location', location_key)}")
        lines.append(f"消耗：{self._cost_text(costs, content)}")
        if not at_location:
            lines.append(f"请先{command_link('前往青石镇', '前往 青石镇')}。")
        elif shortages:
            lines.append("当前材料或灵石不足：" + self._cost_text(shortages, content) + "。")
        else:
            lines.append(command_link("确认修复装备", f"修复装备 {instance_id}"))
        return CommandResult(
            True,
            "EQUIPMENT_REPAIR_PREVIEW",
            "\n".join(lines),
            context.request_id,
            data={
                "instance_id": equipment.instance_id,
                "durability_before": equipment.durability_bp,
                "durability_after": 10_000,
                "costs": costs,
                "location_key": location_key,
                "at_location": at_location,
                "shortages": shortages,
            },
        )

    async def temper(self, context: CommandContext) -> CommandResult:
        return await self._mutate(context, mode="temper")

    async def refine(self, context: CommandContext) -> CommandResult:
        return await self._mutate(context, mode="refine")

    async def repair(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 1:
            return CommandResult(False, "INVALID_EQUIPMENT_REPAIR_COMMAND", "请指定装备编号，例如 `修复装备 装备编号`。", context.request_id)
        operation_id = self._operation_id(context, "item.repair")
        try:
            record = await self.repository.repair_equipment(
                platform=context.adapter,
                platform_user_id=context.user_id,
                equipment_instance_id=context.command_args[0],
                operation_id=operation_id,
            )
        except ValueError:
            return CommandResult(False, "INVALID_EQUIPMENT", "无法识别这件装备。", context.request_id, operation_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except PlayerStageConflictError:
            return CommandResult(False, "PLAYER_STAGE_CONFLICT", "完成入道后才能修缮装备。", context.request_id, operation_id)
        except EquipmentNotOwnedError:
            return CommandResult(False, "EQUIPMENT_NOT_OWNED", "没有找到这件可修缮的装备。", context.request_id, operation_id)
        except EquipmentRepairNotNeededError:
            return CommandResult(False, "EQUIPMENT_REPAIR_NOT_NEEDED", "这件装备耐久充足，无需修缮。", context.request_id, operation_id)
        except EquipmentRepairLocationError as exc:
            location = self._content().label("location", str(exc))
            return CommandResult(False, "EQUIPMENT_REPAIR_WRONG_LOCATION", f"需前往{location}修缮装备。", context.request_id, operation_id)
        except ResourceInsufficientError:
            return CommandResult(False, "EQUIPMENT_REPAIR_RESOURCE_INSUFFICIENT", "材料或灵石不足，装备未改变。", context.request_id, operation_id)
        except EquipmentBusyError:
            return CommandResult(False, "EQUIPMENT_BUSY", "当前有进行中的行动，暂不能修缮装备。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能修缮装备。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次修缮编号已用于其他请求，请重新发起。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        return CommandResult(
            True,
            "EQUIPMENT_REPAIRED",
            f"## 装备修缮\n\n**{record.equipment.label}** 已恢复至完整耐久。消耗：{self._cost_text(record.costs_spent)}。",
            context.request_id,
            operation_id,
            data={
                "instance_id": record.equipment.instance_id,
                "durability_before": record.durability_before,
                "durability_after": record.durability_after,
                "costs_spent": record.costs_spent,
                "status": record.equipment.status,
                "equipped": record.equipment.equipped,
                "idempotent_replay": record.already_completed,
            },
        )

    async def preview_reclamation(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 1:
            return CommandResult(False, "INVALID_EQUIPMENT_RECLAMATION_COMMAND", "请指定装备编号。", context.request_id)
        try:
            record = await self.repository.preview_equipment_reclamation(
                platform=context.adapter,
                platform_user_id=context.user_id,
                equipment_instance_id=context.command_args[0],
            )
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id)
        except EquipmentNotOwnedError:
            return CommandResult(False, "EQUIPMENT_NOT_OWNED", "没有找到这件可回收的装备。", context.request_id)
        except EquipmentReclamationEquippedError:
            return CommandResult(False, "EQUIPMENT_RECLAMATION_EQUIPPED", "请先卸下这件装备，再预览回收。", context.request_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时无法查看装备。", context.request_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, retryable=True)
        content = self._content()
        yields_text = "、".join(
            f"{equipment_resource_label(key, content)} ×{value}" for key, value in record.yields.items()
        )
        return CommandResult(
            True,
            "EQUIPMENT_RECLAMATION_PREVIEW",
            f"## 旧器回收预览\n\n装备：**{record.equipment.label}** · {record.equipment.instance_id}\n产出：{yields_text}\n\n确认回收：`回收装备 {record.equipment.instance_id}`",
            context.request_id,
            data={"instance_id": record.equipment.instance_id, "yields": record.yields},
        )

    async def reclaim(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 1:
            return CommandResult(False, "INVALID_EQUIPMENT_RECLAMATION_COMMAND", "请指定装备编号。", context.request_id)
        operation_id = self._operation_id(context, "item.reclaim")
        try:
            record = await self.repository.reclaim_equipment(
                platform=context.adapter,
                platform_user_id=context.user_id,
                equipment_instance_id=context.command_args[0],
                operation_id=operation_id,
            )
        except ValueError:
            return CommandResult(False, "INVALID_EQUIPMENT", "无法识别这件装备。", context.request_id, operation_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except PlayerStageConflictError:
            return CommandResult(False, "PLAYER_STAGE_CONFLICT", "完成入道后才能回收装备。", context.request_id, operation_id)
        except EquipmentNotOwnedError:
            return CommandResult(False, "EQUIPMENT_NOT_OWNED", "没有找到这件可回收的装备。", context.request_id, operation_id)
        except EquipmentReclamationEquippedError:
            return CommandResult(False, "EQUIPMENT_RECLAMATION_EQUIPPED", "请先卸下这件装备，再进行回收。", context.request_id, operation_id)
        except EquipmentBusyError:
            return CommandResult(False, "EQUIPMENT_BUSY", "当前有进行中的行动，暂不能回收装备。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次回收编号已用于其他请求，请重新发起。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能回收装备。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        content = self._content()
        yields_text = "、".join(
            f"{equipment_resource_label(key, content)} ×{value}" for key, value in record.yields.items()
        )
        return CommandResult(
            True,
            "EQUIPMENT_RECLAIMED",
            f"## 旧器回收\n\n**{record.equipment.label}** 已归档，获得：{yields_text}。",
            context.request_id,
            operation_id,
            data={
                "instance_id": record.equipment.instance_id,
                "yields": record.yields,
                "status": record.equipment.status,
                "idempotent_replay": record.already_completed,
            },
        )

    async def field_repair(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 1:
            return CommandResult(False, "INVALID_EQUIPMENT_FIELD_REPAIR_COMMAND", "请指定装备编号。", context.request_id)
        operation_id = self._operation_id(context, "item.field_repair")
        try:
            record = await self.repository.field_repair_equipment(
                platform=context.adapter,
                platform_user_id=context.user_id,
                equipment_instance_id=context.command_args[0],
                operation_id=operation_id,
            )
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except PlayerStageConflictError:
            return CommandResult(False, "PLAYER_STAGE_CONFLICT", "完成入道后才能使用野外修缮包。", context.request_id, operation_id)
        except EquipmentNotOwnedError:
            return CommandResult(False, "EQUIPMENT_NOT_OWNED", "没有找到这件可修缮的装备。", context.request_id, operation_id)
        except EquipmentFieldRepairNotNeededError:
            return CommandResult(False, "EQUIPMENT_REPAIR_NOT_NEEDED", "这件装备耐久充足，无需野外修缮。", context.request_id, operation_id)
        except EquipmentRepairKitInsufficientError:
            return CommandResult(False, "EQUIPMENT_REPAIR_KIT_INSUFFICIENT", "缺少野外修缮包，未改变装备。", context.request_id, operation_id)
        except EquipmentBusyError:
            return CommandResult(False, "EQUIPMENT_BUSY", "当前有进行中的行动或战斗，暂不能野外修缮。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次野外修缮编号已用于其他请求，请重新发起。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能野外修缮。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        return CommandResult(
            True,
            "EQUIPMENT_FIELD_REPAIRED",
            f"## 野外修缮\n\n**{record.equipment.label}** 耐久 {record.durability_before / 100:.0f}% → {record.durability_after / 100:.0f}%，消耗 1 个野外修缮包。",
            context.request_id,
            operation_id,
            data={
                "instance_id": record.equipment.instance_id,
                "durability_before": record.durability_before,
                "durability_after": record.durability_after,
                "kit_key": record.kit_key,
                "kit_spent": record.kit_spent,
                "status": record.equipment.status,
                "equipped": record.equipment.equipped,
                "idempotent_replay": record.already_completed,
            },
        )

    async def field_repair_preview(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 1:
            return CommandResult(
                False,
                "INVALID_EQUIPMENT_FIELD_REPAIR_COMMAND",
                "请从我的装备中选择具体实例，例如 `野外修缮预览 装备编号`。",
                context.request_id,
            )
        try:
            listing = await self.repository.list_equipment(
                platform=context.adapter,
                platform_user_id=context.user_id,
            )
            kit_key, kit_amount = equipment_repair_kit(self._content())
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时无法查看装备。", context.request_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, retryable=True)
        instance_id = context.command_args[0].strip()
        equipment = next((row for row in listing.equipment if row.instance_id == instance_id), None)
        if equipment is None:
            return CommandResult(False, "EQUIPMENT_NOT_OWNED", "没有找到这件可修缮的装备。", context.request_id)
        if equipment.durability_bp >= 10_000:
            return CommandResult(False, "EQUIPMENT_REPAIR_NOT_NEEDED", "这件装备耐久充足，无需野外修缮。", context.request_id)
        available = int(listing.player.inventory.get(kit_key, 0))
        after = min(10_000, equipment.durability_bp + kit_amount)
        lines = [
            "## 野外修缮预览",
            "",
            f"装备：**{equipment.label}** · {equipment.instance_id}",
            f"耐久：{equipment.durability_bp / 100:.0f}% → {after / 100:.0f}%",
            f"消耗：{self._content().label('item', kit_key)} ×1（当前 {available}）",
        ]
        if available < 1:
            lines.append("修缮包不足，可在青石镇" + command_link("制作修缮包", "生产预览 野外修缮包") + "。")
        else:
            lines.append(command_link("确认野外修缮", f"野外修缮装备 {instance_id}"))
        return CommandResult(
            True,
            "EQUIPMENT_FIELD_REPAIR_PREVIEW",
            "\n".join(lines),
            context.request_id,
            data={
                "instance_id": instance_id,
                "durability_before": equipment.durability_bp,
                "durability_after": after,
                "kit_key": kit_key,
                "kit_amount": 1,
                "kit_restore_bp": kit_amount,
                "kit_available": available,
            },
        )

    async def list_equipment(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_EQUIPMENT_COMMAND", "查看装备无需附加参数。", context.request_id)
        try:
            record = await self.repository.list_equipment(
                platform=context.adapter,
                platform_user_id=context.user_id,
            )
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时无法查看装备。", context.request_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, retryable=True)
        lines = ["## 我的装备", ""]
        if not record.equipment:
            lines.append("身边还没有可用的法器、防具或饰品。")
        else:
            for equipment in record.equipment:
                state = "已损坏" if equipment.status == "broken" else ("已穿戴" if equipment.equipped else "收纳中")
                line = f"- **{equipment.label}**（{self._slot_label(equipment.slot)}）：{state}，耐久 {equipment.durability_bp / 100:.0f}%"
                if equipment.status == "active":
                    line += " · " + command_link("卸下" if equipment.equipped else "穿戴",
                        f"{'卸下法器' if equipment.equipped else '穿戴法器'} {equipment.instance_id}")
                    if equipment.temper_level < equipment.max_temper_level:
                        line += " · " + command_link("祭炼", f"强化法器 {equipment.instance_id}")
                    line += " · " + command_link("重铸", f"重铸法器 {equipment.instance_id}")
                if equipment.durability_bp < 10_000:
                    line += " · " + command_link("修复预览", f"装备修复预览 {equipment.instance_id}")
                    line += " · " + command_link("野外修缮", f"野外修缮预览 {equipment.instance_id}")
                if not equipment.equipped:
                    line += " · " + command_link("回收预览", f"装备回收预览 {equipment.instance_id}")
                lines.append(line)
        return CommandResult(
            True,
            "EQUIPMENT_LISTED",
            "\n".join(lines),
            context.request_id,
            data={
                "equipment": [
                    {
                        "instance_id": equipment.instance_id,
                        "item_key": equipment.item_key,
                        "label": equipment.label,
                        "slot": equipment.slot,
                        "status": equipment.status,
                        "equipped": equipment.equipped,
                        "durability_bp": equipment.durability_bp,
                        "temper_level": equipment.temper_level,
                        "affixes": equipment.affixes,
                    }
                    for equipment in record.equipment
                ]
            },
        )

    async def equip(self, context: CommandContext) -> CommandResult:
        return await self._set_loadout(context, equipped=True)

    async def unequip(self, context: CommandContext) -> CommandResult:
        return await self._set_loadout(context, equipped=False)

    async def _set_loadout(self, context: CommandContext, *, equipped: bool) -> CommandResult:
        command = "穿戴法器" if equipped else "卸下法器"
        if len(context.command_args) != 1:
            return CommandResult(False, "INVALID_EQUIPMENT_COMMAND", f"请指定目标，例如 `{command} 木纹剑`。", context.request_id)
        operation_name = "item.equip" if equipped else "item.unequip"
        operation_id = self._operation_id(context, operation_name)
        try:
            record = await (
                self.repository.equip_equipment(
                    platform=context.adapter,
                    platform_user_id=context.user_id,
                    equipment_reference=context.command_args[0],
                    operation_id=operation_id,
                )
                if equipped
                else self.repository.unequip_equipment(
                    platform=context.adapter,
                    platform_user_id=context.user_id,
                    equipment_reference=context.command_args[0],
                    operation_id=operation_id,
                )
            )
        except ValueError:
            return CommandResult(False, "INVALID_EQUIPMENT", "无法辨认这件装备。", context.request_id, operation_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except PlayerStageConflictError:
            return CommandResult(False, "PLAYER_STAGE_CONFLICT", "完成入道后才能调整装备。", context.request_id, operation_id)
        except EquipmentNotOwnedError:
            return CommandResult(False, "EQUIPMENT_NOT_OWNED", "你当前没有这件装备。", context.request_id, operation_id)
        except EquipmentAmbiguousError:
            return CommandResult(False, "EQUIPMENT_AMBIGUOUS", f"同名装备不止一件，请从{command_link('我的装备', '我的装备')}选择具体的一件。", context.request_id, operation_id)
        except EquipmentRequirementError:
            return CommandResult(False, "EQUIPMENT_REQUIREMENT_MISSING", "当前境界或道途还不能穿戴这件装备。", context.request_id, operation_id)
        except EquipmentDurabilityZeroError:
            return CommandResult(False, "EQUIPMENT_DURABILITY_ZERO", "这件装备灵力耗尽，修复后才能穿戴。", context.request_id, operation_id)
        except EquipmentSlotBusyError:
            return CommandResult(False, "EQUIP_SLOT_BUSY", "这个装备槽已有装备。", context.request_id, operation_id)
        except EquipmentBusyError:
            return CommandResult(False, "EQUIPMENT_BUSY", "当前正有一段修行事务进行中，暂不能调整装备。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能调整装备。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次装备调整已改作他用，请重新发起。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        action_text = "穿戴" if equipped else "卸下"
        return CommandResult(
            True,
            "EQUIPMENT_EQUIPPED" if equipped else "EQUIPMENT_UNEQUIPPED",
            f"## 装备调整\n\n已{action_text} **{record.equipment.label}**，归入{self._slot_label(record.equipment.slot)}。",
            context.request_id,
            operation_id,
            data={
                "label": record.equipment.label,
                "slot": record.equipment.slot,
                "equipped": record.equipped,
                "idempotent_replay": record.already_completed,
            },
        )

    async def _mutate(self, context: CommandContext, *, mode: str) -> CommandResult:
        if len(context.command_args) != 1:
            command = "强化法器" if mode == "temper" else "重铸法器"
            return CommandResult(False, "INVALID_EQUIPMENT_COMMAND", f"请指定目标，例如 `{command} 木纹剑`。", context.request_id)
        operation_name = "item.tempering" if mode == "temper" else "item.refinement"
        operation_id = self._operation_id(context, operation_name)
        try:
            record = (
                await self.repository.temper_equipment(
                    platform=context.adapter,
                    platform_user_id=context.user_id,
                    equipment_reference=context.command_args[0],
                    operation_id=operation_id,
                )
                if mode == "temper"
                else await self.repository.refine_equipment(
                    platform=context.adapter,
                    platform_user_id=context.user_id,
                    equipment_reference=context.command_args[0],
                    operation_id=operation_id,
                )
            )
        except ValueError:
            return CommandResult(False, "INVALID_EQUIPMENT", "无法识别这件法器。", context.request_id, operation_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except PlayerStageConflictError:
            return CommandResult(False, "PLAYER_STAGE_CONFLICT", "完成入道后才能养成法器。", context.request_id, operation_id)
        except EquipmentNotOwnedError:
            return CommandResult(False, "EQUIPMENT_NOT_OWNED", "你当前没有这件法器。", context.request_id, operation_id)
        except EquipmentRequirementError:
            return CommandResult(False, "EQUIPMENT_REQUIREMENT_MISSING", "当前境界尚未达到这件装备的养成要求。", context.request_id, operation_id)
        except EquipmentAmbiguousError:
            return CommandResult(False, "EQUIPMENT_AMBIGUOUS", f"同名法器不止一件，请从{command_link('我的装备', '我的装备')}选择具体的一件。", context.request_id, operation_id)
        except EquipmentTemperingMaxedError:
            return CommandResult(False, "EQUIPMENT_MAXED", "这件法器已经达到淬炼上限。", context.request_id, operation_id)
        except ResourceInsufficientError:
            return CommandResult(False, "EQUIPMENT_RESOURCE_INSUFFICIENT", "材料或灵石不足，未改变法器。", context.request_id, operation_id)
        except EquipmentBusyError:
            return CommandResult(False, "EQUIPMENT_BUSY", "当前有其他长时行动进行中，请先完成结算。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能养成法器。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次祭炼记录已有异议，请重新起炉。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)

        if mode == "temper":
            message = (
                f"## 法器祭炼\n\n**{self._display_name(record.player)}**的 **{record.equipment.label}**"
                f"从 **{record.from_level} 阶**提升至 **{record.to_level} 阶**。\n\n"
                f"- **结果**：{'成功' if record.success else '失败，等级不变'}\n"
                f"- **判定**：`{record.roll_bp}/{record.success_bp}`\n"
                f"- **消耗**：{self._cost_text(record.costs_spent)}"
            )
            data = {
                "instance_id": record.equipment.instance_id,
                "item_key": record.equipment.item_key,
                "temper_level": record.equipment.temper_level,
                "success": record.success,
                "roll_bp": record.roll_bp,
                "success_bp": record.success_bp,
                "costs_spent": record.costs_spent,
                "idempotent_replay": record.already_completed,
            }
            code = "EQUIPMENT_TEMPERED"
        else:
            message = (
                f"## 灵纹重铸\n\n**{self._display_name(record.player)}**重铸 **{record.equipment.label}**。\n\n"
                f"- **结果**：{'获得新词条' if record.success else '失败，保留旧词条'}\n"
                f"- **词条**：{self._affix_text(record.new_affixes)}\n"
                f"- **连续失败**：`{record.failure_streak_after}`\n"
                f"- **消耗**：{self._cost_text(record.costs_spent)}"
            )
            data = {
                "instance_id": record.equipment.instance_id,
                "item_key": record.equipment.item_key,
                "success": record.success,
                "old_affixes": record.old_affixes,
                "new_affixes": record.new_affixes,
                "failure_streak_after": record.failure_streak_after,
                "roll_bp": record.roll_bp,
                "success_bp": record.success_bp,
                "costs_spent": record.costs_spent,
                "idempotent_replay": record.already_completed,
            }
            code = "EQUIPMENT_REFINED"
        return CommandResult(True, code, message, context.request_id, operation_id, data=data)


__all__ = ["EquipmentApplication"]
