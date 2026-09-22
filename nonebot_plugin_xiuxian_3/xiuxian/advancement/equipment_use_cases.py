"""Application services for low-tier equipment tempering and refinement."""

from __future__ import annotations

from ...contracts import CommandContext, CommandResult
from ..repository import (
    EquipmentAmbiguousError,
    EquipmentNotOwnedError,
    EquipmentTemperingMaxedError,
    OperationConflictError,
    PlayerNotFoundError,
    PlayerStageConflictError,
    PlayerSuspendedError,
    RepositoryBusyError,
    ResourceInsufficientError,
    EquipmentBusyError,
    SQLitePlayerRepository,
)
from .equipment_rules import (
    EQUIPMENT_DEFINITIONS,
    MAX_TEMPER_LEVEL,
    REFINEMENT_MATERIAL,
    TEMPER_COSTS,
    TEMPER_MATERIAL,
    TEMPER_SUCCESS_BP,
)


class EquipmentApplication:
    """Coordinate equipment growth without starting a battle runtime."""

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
    def _item_label(item_key: str) -> str:
        definition = EQUIPMENT_DEFINITIONS.get(item_key)
        return definition.label if definition else item_key

    @staticmethod
    def _material_label(item_key: str) -> str:
        return {"item.ore.ironstone": "铁石"}.get(item_key, item_key)

    @staticmethod
    def _affix_text(affixes: dict[str, int]) -> str:
        labels = {"damage": "伤害", "hp": "气血", "initiative": "先手"}
        if not affixes:
            return "无"
        return "、".join(f"**{labels.get(key, key)}** +{value}" for key, value in affixes.items())

    async def preview_tempering(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_EQUIPMENT_COMMAND", "法器预览无需附加参数。", context.request_id)
        lines = ["## 法器祭炼", "", "木纹剑与棉袍可强化至 3 阶；失败不降级，只损失本次成本。", ""]
        for level in range(1, MAX_TEMPER_LEVEL + 1):
            material, stones = TEMPER_COSTS[level]
            lines.append(
                f"- **{level} 阶**：铁石 ×{material}，灵石 ×{stones}，成功率 `{TEMPER_SUCCESS_BP[level] / 100:.0f}%`。"
            )
        lines.extend(["", "> 使用 `强化法器 木纹剑` 或 `强化法器 棉袍`。"])
        return CommandResult(True, "EQUIPMENT_TEMPER_PREVIEW", "\n".join(lines), context.request_id)

    async def preview_refinement(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_EQUIPMENT_COMMAND", "重铸预览无需附加参数。", context.request_id)
        return CommandResult(
            True,
            "EQUIPMENT_REFINE_PREVIEW",
            "## 灵纹重铸\n\n每次消耗 **铁石 ×2** 与 **灵石 ×30**，随机获得 **伤害 +1**、**气血 +5** 或 **先手 +1**。\n\n失败保留旧词条；连续失败 3 次后，下一次必定获得非空词条。\n\n> 使用 `重铸法器 木纹剑` 或 `重铸法器 棉袍`。",
            context.request_id,
        )

    async def temper(self, context: CommandContext) -> CommandResult:
        return await self._mutate(context, mode="temper")

    async def refine(self, context: CommandContext) -> CommandResult:
        return await self._mutate(context, mode="refine")

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
        except EquipmentAmbiguousError:
            return CommandResult(False, "EQUIPMENT_AMBIGUOUS", "同名法器不止一件，请先处理已有法器。", context.request_id, operation_id)
        except EquipmentTemperingMaxedError:
            return CommandResult(False, "EQUIPMENT_MAXED", "这件法器已经达到当前版本强化上限。", context.request_id, operation_id)
        except ResourceInsufficientError:
            return CommandResult(False, "EQUIPMENT_RESOURCE_INSUFFICIENT", "材料或灵石不足，未改变法器。", context.request_id, operation_id)
        except EquipmentBusyError:
            return CommandResult(False, "EQUIPMENT_BUSY", "当前有其他长时行动进行中，请先完成结算。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能养成法器。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于其他法器操作，请重新发起。", context.request_id, operation_id)
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
                f"- **消耗**：{self._material_label(record.material_key)} ×{record.material_spent}，灵石 ×{record.spirit_stones_spent}"
            )
            data = {
                "instance_id": record.equipment.instance_id,
                "item_key": record.equipment.item_key,
                "temper_level": record.equipment.temper_level,
                "success": record.success,
                "roll_bp": record.roll_bp,
                "success_bp": record.success_bp,
                "material_spent": record.material_spent,
                "spirit_stones_spent": record.spirit_stones_spent,
                "idempotent_replay": record.already_completed,
            }
            code = "EQUIPMENT_TEMPERED"
        else:
            message = (
                f"## 灵纹重铸\n\n**{self._display_name(record.player)}**重铸 **{record.equipment.label}**。\n\n"
                f"- **结果**：{'获得新词条' if record.success else '失败，保留旧词条'}\n"
                f"- **词条**：{self._affix_text(record.new_affixes)}\n"
                f"- **连续失败**：`{record.failure_streak_after}`\n"
                f"- **消耗**：{self._material_label(record.material_key)} ×{record.material_spent}，灵石 ×{record.spirit_stones_spent}"
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
                "material_spent": record.material_spent,
                "spirit_stones_spent": record.spirit_stones_spent,
                "idempotent_replay": record.already_completed,
            }
            code = "EQUIPMENT_REFINED"
        return CommandResult(True, code, message, context.request_id, operation_id, data=data)


__all__ = ["EquipmentApplication"]
