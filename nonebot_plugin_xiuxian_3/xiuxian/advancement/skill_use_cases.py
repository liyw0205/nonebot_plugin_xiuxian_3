"""Application services for skill mastery."""

from __future__ import annotations

from ...contracts import CommandContext, CommandResult
from ..content import bundled_content
from ..utils.assets import inventory_amount
from ..repository import (
    OperationConflictError,
    PlayerNotFoundError,
    PlayerStageConflictError,
    PlayerSuspendedError,
    RepositoryBusyError,
    ResourceInsufficientError,
    SkillAlreadyMaxedError,
    SkillBusyError,
    SkillNotAvailableError,
    SQLitePlayerRepository,
)
from .skill_rules import (
    available_skill_keys,
    skill_cost,
    skill_definitions,
    skill_mastery_rules,
    skill_resource_definition,
)


class SkillApplication:
    """Coordinate skill mastery without opening a battle runtime."""

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

    async def preview(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_SKILL_COMMAND", "神通预览无需附加参数。", context.request_id)
        content = self.repository.content or bundled_content()
        definitions = skill_definitions(content)
        skill_mastery_rules(content)
        lines = [
            "## 神通参悟",
            "",
            "各项神通均可依自身参悟规则精进。",
            "",
        ]
        for definition in definitions.values():
            if definition.status != "active":
                continue
            costs = []
            for level in sorted(definition.level_costs):
                resource_costs = skill_cost(level, definition)
                details = "、".join(
                    f"{content.label('resource', key)} {amount}"
                    for key, amount in resource_costs.items()
                )
                costs.append(f"{level}级 {details}")
            path = "通用" if definition.path_key is None else content.label("path", definition.path_key)
            requirement = (
                f"，{content.label('realm', definition.min_realm_key)} L{definition.min_layer} 起可参悟"
                if definition.min_realm_key
                else ""
            )
            lines.append(
                f"- **{definition.label}**（{path} · {definition.style_label}{requirement}，上限 {definition.max_level} 级）：{definition.description}；费用 {'；'.join(costs)}。"
            )
            if definition.acquisition_item_key:
                item_name = content.label("item", definition.acquisition_item_key)
                lines.append(f"  - 首次参悟需持有：{item_name}。")
        return CommandResult(True, "SKILL_PREVIEW", "\n".join(lines), context.request_id)

    async def profile(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_SKILL_COMMAND", "查看神通无需附加参数。", context.request_id)
        try:
            record = await self.repository.get_skill_profile(
                platform=context.adapter,
                platform_user_id=context.user_id,
            )
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id)
        except PlayerStageConflictError:
            return CommandResult(False, "PLAYER_STAGE_CONFLICT", "完成入道后才能查看神通。", context.request_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能查看神通。", context.request_id)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, retryable=True)

        mastery_by_key = {item.skill_key: item for item in record.skills}
        content = self.repository.content or bundled_content()
        mastery_rules = skill_mastery_rules(content)
        insight_resource = skill_resource_definition(mastery_rules["insight_resource_key"], content)
        lines = [
            "## 我的神通",
            "",
            f"**{self._display_name(record.player)}**的{insight_resource['name']}：`{record.insight_balance}`。",
            "",
        ]
        definitions = skill_definitions(content)
        display_inventory = dict(record.player.inventory)
        for definition in definitions.values():
            if definition.acquisition_item_key:
                display_inventory.setdefault(definition.acquisition_item_key, 1)
        for key in available_skill_keys(
            record.player.path_key,
            content,
            realm_key=record.player.realm_key,
            realm_layer=record.player.realm_layer,
            inventory=display_inventory,
            mastered_keys=tuple(item.skill_key for item in record.skills),
        ):
            definition = definitions[key]
            mastery = mastery_by_key.get(key)
            level = mastery.level if mastery else 0
            locked = (
                definition.acquisition_item_key
                and mastery is None
                and inventory_amount(record.player.inventory, definition.acquisition_item_key) <= 0
            )
            status = (
                f"未获{content.label('item', definition.acquisition_item_key)}"
                if locked
                else f"{level}/{definition.max_level} 级"
            )
            lines.append(f"- **{definition.label}**（{definition.style_label}）：{status}")
        return CommandResult(
            True,
            "SKILL_PROFILE",
            "\n".join(lines),
            context.request_id,
            data={
                "insight_balance": record.insight_balance,
                "skills": [
                    {
                        "skill_key": item.skill_key,
                        "label": item.label,
                        "level": item.level,
                        "max_level": item.max_level,
                        "effective_effect": item.effective_effect,
                        "trained_at": item.trained_at,
                    }
                    for item in record.skills
                ],
            },
        )

    async def train(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 1:
            return CommandResult(
                False,
                "INVALID_SKILL_COMMAND",
                "请指定要参悟的技能，例如 `参悟神通 基础攻击`。",
                context.request_id,
            )
        operation_id = self._operation_id(context, "skill.train")
        try:
            record = await self.repository.train_skill(
                platform=context.adapter,
                platform_user_id=context.user_id,
                skill_reference=context.command_args[0],
                operation_id=operation_id,
            )
        except ValueError:
            return CommandResult(False, "INVALID_SKILL", "无法识别这项神通。", context.request_id, operation_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except PlayerStageConflictError:
            return CommandResult(False, "PLAYER_STAGE_CONFLICT", "完成入道后才能参悟神通。", context.request_id, operation_id)
        except SkillNotAvailableError:
            return CommandResult(False, "SKILL_NOT_AVAILABLE", "这项神通尚未满足道途、境界或传承条件。", context.request_id, operation_id)
        except SkillAlreadyMaxedError:
            return CommandResult(False, "SKILL_MAXED", "这项神通已经达到参悟上限。", context.request_id, operation_id)
        except ResourceInsufficientError:
            return CommandResult(False, "SKILL_RESOURCE_INSUFFICIENT", "参悟所需资源不足，未扣除任何资源。", context.request_id, operation_id)
        except SkillBusyError:
            return CommandResult(False, "SKILL_BUSY", "当前有其他长时会话进行中，请先完成结算。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能参悟神通。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于其他神通操作，请重新发起。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        content = self.repository.content or bundled_content()
        definition = skill_definitions(content)[record.skill_key]
        effect_values = []
        for field in definition.effect_deltas:
            value = record.effective_effect[field]
            if field.endswith("_bp") or (field == "value" and str(definition.effect.get("type", "")).endswith("_bp")):
                effect_values.append(f"{int(value) / 100:g}%")
            else:
                effect_values.append(str(value))
        resource_costs = "、".join(
            f"{content.label('resource', key)} {amount}"
            for key, amount in record.resource_costs.items()
        )
        return CommandResult(
            True,
            "SKILL_TRAINED",
            f"## 神通精进\n\n**{self._display_name(record.player)}**将 **{record.label}** 参悟至 **{record.level} 级**。\n\n- **效果数值**：{'、'.join(effect_values)}\n- **消耗**：{resource_costs}\n\n> 参悟结果已记入神通。",
            context.request_id,
            operation_id,
            data={
                "skill_key": record.skill_key,
                "label": record.label,
                "level": record.level,
                "effective_effect": record.effective_effect,
                "resource_costs": dict(record.resource_costs),
                "trained_at": record.trained_at,
                "idempotent_replay": record.already_completed,
            },
        )


__all__ = ["SkillApplication"]
