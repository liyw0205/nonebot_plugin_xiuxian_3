"""Application services for v0.1 skill mastery."""

from __future__ import annotations

from ...contracts import CommandContext, CommandResult
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
    MAX_SKILL_LEVEL,
    SKILL_INSIGHT_RESOURCE,
    SKILL_DEFINITIONS,
    available_skill_keys,
    skill_cost,
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
        lines = [
            "## 神通参悟",
            "",
            "基础攻击与当前首要道途主动技能均可参悟至 3 级；每级效果增加 3%。",
            "",
        ]
        for definition in SKILL_DEFINITIONS.values():
            insight_1, stones_1 = skill_cost(1)
            insight_2, stones_2 = skill_cost(2)
            insight_3, stones_3 = skill_cost(3)
            path = "通用" if definition.path_key is None else definition.path_key
            lines.append(
                f"- **{definition.label}**（{path}）：{definition.description}；费用 `技能心得/灵石 {insight_1}/{stones_1}、{insight_2}/{stones_2}、{insight_3}/{stones_3}`。"
            )
        lines.extend(
            [
                "",
                f"> 技能心得资源键：`{SKILL_INSIGHT_RESOURCE}`。参悟只保存构筑快照，不启动战斗或手动操作入口。",
            ]
        )
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
        lines = [
            "## 我的神通",
            "",
            f"**{self._display_name(record.player)}**的技能心得：`{record.skill_insights}`。",
            "",
        ]
        for key in available_skill_keys(record.player.path_key):
            definition = SKILL_DEFINITIONS[key]
            mastery = mastery_by_key.get(key)
            level = mastery.level if mastery else 0
            lines.append(f"- **{definition.label}**：{level}/{MAX_SKILL_LEVEL} 级")
        return CommandResult(
            True,
            "SKILL_PROFILE",
            "\n".join(lines),
            context.request_id,
            data={
                "skill_insights": record.skill_insights,
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
            return CommandResult(False, "SKILL_NOT_AVAILABLE", "这项神通不属于当前首要道途。", context.request_id, operation_id)
        except SkillAlreadyMaxedError:
            return CommandResult(False, "SKILL_MAXED", "这项神通已经达到当前版本上限。", context.request_id, operation_id)
        except ResourceInsufficientError:
            return CommandResult(False, "SKILL_RESOURCE_INSUFFICIENT", "技能心得或灵石不足，未扣除任何资源。", context.request_id, operation_id)
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
        return CommandResult(
            True,
            "SKILL_TRAINED",
            f"## 神通精进\n\n**{self._display_name(record.player)}**将 **{record.label}** 参悟至 **{record.level} 级**。\n\n- **效果**：`{record.effective_effect.get('value', 0)} bp`\n- **消耗**：技能心得 {record.insight_cost}，灵石 {record.spirit_stone_cost}\n\n> 结果已写入构筑快照，当前战斗运行时仍未开放。",
            context.request_id,
            operation_id,
            data={
                "skill_key": record.skill_key,
                "label": record.label,
                "level": record.level,
                "effective_effect": record.effective_effect,
                "insight_cost": record.insight_cost,
                "spirit_stone_cost": record.spirit_stone_cost,
                "trained_at": record.trained_at,
                "idempotent_replay": record.already_completed,
            },
        )


__all__ = ["SkillApplication"]
