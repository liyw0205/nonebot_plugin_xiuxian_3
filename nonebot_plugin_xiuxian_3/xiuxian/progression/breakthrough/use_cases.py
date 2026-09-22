"""Application commands for previewing and resolving breakthroughs."""

from __future__ import annotations

from datetime import datetime, timezone

from ....contracts import CommandContext, CommandResult
from ...repository import (
    BreakthroughBusyError,
    BreakthroughNotFoundError,
    BreakthroughNotReadyError,
    BreakthroughRequirementError,
    CurrencyInsufficientError,
    MaterialInsufficientError,
    OperationConflictError,
    PlayerNotFoundError,
    PlayerStageConflictError,
    PlayerSuspendedError,
    ProtectionItemInsufficientError,
    RepositoryBusyError,
    WeaknessActiveError,
    WeaknessNotActiveError,
    SQLitePlayerRepository,
)
from .rules import breakthrough_definition, success_bp


ITEM_LABELS = {
    "item.pill.focus_low": "焦点丹",
    "item.herb.spirit_leaf": "灵叶",
    "item.pill.qi_guard": "聚气护脉丹",
    "item.pill.foundation_draft": "筑基丹",
    "item.mat.array_sand": "阵砂",
    "item.ore.ironstone": "铁石",
    "item.pill.foundation_guard": "筑基护脉丹",
    "item.pill.healing_low": "低阶疗伤丹",
}

REALM_LABELS = {
    "qi_gathering": "聚气",
    "foundation": "筑基",
}

PROTECTION_LABELS = {
    "item.pill.qi_guard": "聚气护脉丹",
    "item.pill.foundation_guard": "筑基护脉丹",
}


class BreakthroughApplication:
    """Keep Markdown and command parsing outside the SQLite repository."""

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
    def _parse_start_args(args: tuple[str, ...]) -> tuple[str, bool] | None:
        target = "qi_gathering"
        protection = False
        for arg in args:
            if arg in {"聚气", "聚气突破", "qi_gathering"}:
                target = "qi_gathering"
            elif arg in {"护脉", "保护", "聚气护脉丹", "qi_guard"}:
                protection = True
            elif arg in {"筑基", "foundation", "筑基突破"}:
                target = "foundation"
            else:
                return None
        return target, protection

    @staticmethod
    def _preparation_bp(player, definition) -> int:
        quality = 0
        if definition.quality_bonus_divisor:
            quality = min(
                definition.quality_bonus_cap_bp,
                player.foundation_quality // definition.quality_bonus_divisor,
            )
        technique = (
            definition.technique_bonus_bp
            if definition.technique_bonus_bp and player.inventory.get("item.manual.basic_qi", 0) > 0
            else 0
        )
        formation = (
            definition.formation_bonus_bp
            if definition.formation_bonus_bp and player.subprofession_key == "formation"
            else 0
        )
        return quality + technique + formation

    async def preview_breakthrough(self, context: CommandContext) -> CommandResult:
        parsed = self._parse_start_args(context.command_args)
        if parsed is None:
            return CommandResult(False, "INVALID_BREAKTHROUGH_COMMAND", "可用指令：`突破预览 聚气` 或 `突破预览 筑基`。", context.request_id)
        target, _ = parsed
        definition = breakthrough_definition(target)
        try:
            player = await self.repository.get_player(platform=context.adapter, platform_user_id=context.user_id)
        except Exception:
            player = None
        if player is None:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id)
        missing = [ITEM_LABELS.get(key, "突破材料") for key, amount in definition.materials.items() if player.inventory.get(key, 0) < amount]
        preparation_bp = self._preparation_bp(player, definition)
        current_success_bp = success_bp(definition, player.breakthrough_pity_bp, preparation_bp)
        ready = (
            player.realm_key == definition.source_realm
            and player.realm_layer == 10
            and player.total_cultivation >= definition.required_total_cultivation
            and not missing
            and player.spirit_stones >= definition.currency_cost
        )
        material_lines = "\n".join(
            f"- **{ITEM_LABELS.get(key, '突破材料')}** ×{amount}" for key, amount in definition.materials.items()
        )
        realm_label = REALM_LABELS[target]
        protection_label = PROTECTION_LABELS[definition.protection_key]
        retention = definition.retention_bp / 100
        message = (
            f"## {realm_label}突破预览\n\n"
            f"**{self._display_name(player)}**当前{('满足' if ready else '尚未满足')}突破条件。\n\n"
            f"- **境界要求**：{REALM_LABELS.get(definition.source_realm, definition.source_realm)} L10（混元）\n"
            f"- **总修为要求**：{definition.required_total_cultivation}\n"
            f"- **当前成功率**：{current_success_bp / 100:.0f}%（基础 {definition.base_success_bp / 100:.0f}%）\n"
            f"- **准备时长**：{definition.duration_seconds // 60} 分钟\n"
            f"- **消耗灵石**：{definition.currency_cost}\n\n"
            "### 必需材料\n\n"
            f"{material_lines}\n\n"
            f"> 失败会保留当前境内修为的 {retention:.0f}%，并进入 {definition.weakness_seconds // 3600} 小时虚弱。可选 **{protection_label}**，只在失败时消耗。"
        )
        if missing:
            message += f"\n> 当前缺少：{'、'.join(missing)}。"
        return CommandResult(True, "BREAKTHROUGH_PREVIEW", message, context.request_id, data={"target_realm": target, "ready": ready, "missing": missing, "success_bp": current_success_bp, "preparation_bp": preparation_bp, "pity_bp": player.breakthrough_pity_bp})

    async def start_breakthrough(self, context: CommandContext) -> CommandResult:
        parsed = self._parse_start_args(context.command_args)
        if parsed is None:
            return CommandResult(False, "INVALID_BREAKTHROUGH_COMMAND", "可用指令：`开始突破 聚气` 或 `开始突破 筑基`，可追加 `护脉`。", context.request_id)
        target, protection = parsed
        definition = breakthrough_definition(target)
        operation_id = self._operation_id(context, definition.key)
        try:
            record = await self.repository.start_breakthrough(
                platform=context.adapter,
                platform_user_id=context.user_id,
                target_realm=target,
                protection=protection,
                operation_id=operation_id,
            )
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色处于暂停状态，暂时不能突破。", context.request_id, operation_id)
        except PlayerStageConflictError:
            return CommandResult(False, "REALM_MISMATCH", "完成入道后才能进行跨境突破。", context.request_id, operation_id)
        except BreakthroughRequirementError:
            return CommandResult(False, "BREAKTHROUGH_REQUIREMENT_MISSING", f"只有{REALM_LABELS.get(definition.source_realm, definition.source_realm)} L10 混元且总修为达到 {definition.required_total_cultivation:,} 才能开始{REALM_LABELS[target]}突破。", context.request_id, operation_id)
        except BreakthroughBusyError:
            return CommandResult(False, "BREAKTHROUGH_BUSY", "当前已有修炼、生产或突破会话，请先完成后再试。", context.request_id, operation_id)
        except WeaknessActiveError:
            return CommandResult(False, "WEAKNESS_ACTIVE", "当前处于突破虚弱状态，请等待结束或发送 `恢复虚弱 提前`。", context.request_id, operation_id)
        except MaterialInsufficientError:
            return CommandResult(False, "MATERIAL_INSUFFICIENT", "突破材料不足，未扣除任何资源。", context.request_id, operation_id)
        except ProtectionItemInsufficientError:
            return CommandResult(False, "MATERIAL_INSUFFICIENT", f"缺少{PROTECTION_LABELS[definition.protection_key]}，未扣除任何资源。", context.request_id, operation_id)
        except CurrencyInsufficientError:
            return CommandResult(False, "RESOURCE_INSUFFICIENT", "灵石不足，未扣除任何资源。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于其他突破输入，请重新发起。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        return CommandResult(
            True,
            "BREAKTHROUGH_STARTED",
            (
                "## 突破已开始\n\n"
                f"**{self._display_name(record.player)}**开始冲击 **{REALM_LABELS[target]} L1**。\n\n"
                f"- **成功率**：{record.success_bp / 100:.0f}%\n"
                f"- **准备时长**：{definition.duration_seconds // 60} 分钟\n"
                f"- **灵石**：{record.player.spirit_stones}\n\n"
                "> 结束后发送 `结算突破`。准备期间不能修炼、生产或再次突破。"
            ),
            context.request_id,
            operation_id,
            data={"session_id": record.session_id, "target_realm": record.target_realm, "status": record.status, "success_bp": record.success_bp, "ends_at": record.ends_at, "protection_key": record.protection_key, "idempotent_replay": record.already_completed},
        )

    async def settle_breakthrough(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_BREAKTHROUGH_COMMAND", "结算突破无需附加参数。", context.request_id)
        operation_id = self._operation_id(context, "progression.settle_breakthrough")
        try:
            record = await self.repository.settle_breakthrough(platform=context.adapter, platform_user_id=context.user_id, operation_id=operation_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except BreakthroughNotFoundError:
            return CommandResult(False, "BREAKTHROUGH_NOT_FOUND", "当前没有等待结算的突破。", context.request_id, operation_id)
        except BreakthroughNotReadyError:
            return CommandResult(False, "BREAKTHROUGH_NOT_READY", "突破准备尚未结束，请稍后再来结算。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色处于暂停状态，暂时不能结算突破。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于其他突破结算，请重新发起。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        player = record.player
        target_label = REALM_LABELS.get(record.target_realm, record.target_realm)
        if record.success:
            reward_lines = []
            if record.reward_currency:
                reward_lines.append(f"灵石 ×{record.reward_currency}")
            if record.reward_stamina:
                reward_lines.append(f"体力 ×{record.reward_stamina}")
            if record.reward_world_merit:
                reward_lines.append(f"世界功勋 ×{record.reward_world_merit}")
            for item_key, quantity in (record.reward_items or {}).items():
                reward_lines.append(f"{ITEM_LABELS.get(item_key, '凭证')} ×{quantity}")
            message = (
                "## 突破成功\n\n"
                f"**{self._display_name(player)}**已踏入 **{target_label} L1（入门）**。\n\n"
                f"- **消耗灵石**：{record.currency_spent}\n"
                f"- **入境奖励**：{'、'.join(reward_lines) or '无'}\n"
                f"- **当前境内修为**：{player.cultivation}\n\n"
                f"> {target_label}阶段的新内容将按开发顺序逐步开放。"
            )
        else:
            weak_text = (
                f"保护丹生效，虚弱 {30 if record.target_realm == 'qi_gathering' else 120} 分钟"
                if record.protection_consumed
                else f"虚弱 {2 if record.target_realm == 'qi_gathering' else 6} 小时"
            )
            message = (
                "## 突破未成\n\n"
                f"**{self._display_name(player)}**暂未踏入{target_label}，保留境内修为 **{record.cultivation_after}**。\n\n"
                f"- **结果**：{weak_text}\n"
                f"- **本次成功率**：{record.success_bp / 100:.0f}%\n"
                f"- **保底**：下次增加 {record.pity_after_bp - record.pity_before_bp} bp\n\n"
                "> 虚弱期间不能再次突破；到期后发送 `恢复虚弱`，或使用 `恢复虚弱 提前`。"
            )
        return CommandResult(True, "BREAKTHROUGH_SUCCEEDED" if record.success else "BREAKTHROUGH_FAILED", message, context.request_id, operation_id, data={"session_id": record.session_id, "target_realm": record.target_realm, "success": record.success, "roll_bp": record.roll_bp, "success_bp": record.success_bp, "cultivation_before": record.cultivation_before, "cultivation_after": record.cultivation_after, "pity_before_bp": record.pity_before_bp, "pity_after_bp": record.pity_after_bp, "preparation_bp": record.preparation_bp, "reward_currency": record.reward_currency, "reward_stamina": record.reward_stamina, "reward_world_merit": record.reward_world_merit, "reward_items": record.reward_items or {}, "protection_consumed": record.protection_consumed, "weakness_until": record.weakness_until, "idempotent_replay": record.already_completed})

    async def recover_weakness(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) > 1 or (context.command_args and context.command_args[0] not in {"提前", "立即", "early"}):
            return CommandResult(False, "INVALID_RECOVERY_COMMAND", "可用指令：`恢复虚弱`，或 `恢复虚弱 提前`。", context.request_id)
        early = bool(context.command_args)
        operation_id = self._operation_id(context, "progression.recover_weakness")
        try:
            record = await self.repository.recover_weakness(platform=context.adapter, platform_user_id=context.user_id, early=early, operation_id=operation_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except WeaknessNotActiveError:
            return CommandResult(False, "WEAKNESS_NOT_ACTIVE", "当前没有需要恢复的突破虚弱。", context.request_id, operation_id)
        except WeaknessActiveError:
            return CommandResult(False, "WEAKNESS_ACTIVE", "虚弱尚未到期；提前恢复需要低阶疗伤丹 ×1 和 50 灵石。", context.request_id, operation_id)
        except MaterialInsufficientError:
            return CommandResult(False, "MATERIAL_INSUFFICIENT", "提前恢复需要低阶疗伤丹 ×1，未扣除资源。", context.request_id, operation_id)
        except CurrencyInsufficientError:
            return CommandResult(False, "RESOURCE_INSUFFICIENT", "提前恢复需要 50 灵石，未扣除资源。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色处于暂停状态，暂时不能恢复虚弱。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于其他恢复，请重新发起。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        return CommandResult(True, "WEAKNESS_RECOVERED", f"## 虚弱已恢复\n\n**{self._display_name(record.player)}**可以继续准备突破。\n\n- **提前恢复**：{'是' if record.early else '否'}\n- **消耗灵石**：{record.spirit_stones_spent}\n- **消耗疗伤丹**：{'是' if record.medicine_consumed else '否'}\n\n> 突破失败保底不会被清除。", context.request_id, operation_id, data={"early": record.early, "spirit_stones_spent": record.spirit_stones_spent, "medicine_consumed": record.medicine_consumed, "idempotent_replay": record.already_completed})


__all__ = ["BreakthroughApplication"]
