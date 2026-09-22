"""Application commands for previewing and resolving breakthroughs."""

from __future__ import annotations

from datetime import datetime, timezone

from ....contracts import CommandContext, CommandResult
from ...repository import (
    BreakthroughBusyError,
    BreakthroughNotFoundError,
    BreakthroughNotReadyError,
    BreakthroughRequirementError,
    HeartDemonPendingError,
    QuestRequirementError,
    SoulFatigueActiveError,
    CurrencyInsufficientError,
    MaterialInsufficientError,
    OperationConflictError,
    PlayerNotFoundError,
    PlayerStageConflictError,
    PlayerSuspendedError,
    ProtectionItemInsufficientError,
    FoundationQualityInsufficientError,
    RepositoryBusyError,
    WeaknessActiveError,
    WeaknessNotActiveError,
    DomainCrackActiveError,
    DomainSelectionBusyError,
    DomainAlreadySelectedError,
    DomainNotEligibleError,
    SoulPowerInsufficientError,
    FactionReputationInsufficientError,
    CultivationInsufficientError,
    RealmMismatchError,
    SQLitePlayerRepository,
)
from .rules import breakthrough_definition, success_bp
from ...paths.rules import domain_definition, resolve_domain


ITEM_LABELS = {
    "item.pill.focus_low": "焦点丹",
    "item.herb.spirit_leaf": "灵叶",
    "item.pill.qi_guard": "聚气护脉丹",
    "item.pill.foundation_draft": "筑基丹",
    "item.mat.array_sand": "阵砂",
    "item.ore.ironstone": "铁石",
    "item.pill.foundation_guard": "筑基护脉丹",
    "item.pill.core_condense": "凝核丹",
    "item.pill.golden_core_guard": "金丹护脉丹",
    "item.pill.golden_core_restore": "金丹恢复丹",
    "item.material.cloud_iron": "云铁",
    "item.pill.healing_low": "低阶疗伤丹",
    "item.pill.soul_condense": "凝魂丹",
    "item.pill.soul_restore": "魂元丹",
    "item.soul_crystal": "神魂晶",
    "item.demon_core": "魔核",
    "item.beast_blood": "兽血",
    "item.soul_seed": "化神魂种",
    "item.domain_core": "领域核心",
    "item.ancient_fruit": "远古古果",
    "item.pill.domain_restore": "领域复原丹",
}

REALM_LABELS = {
    "qi_gathering": "聚气",
    "foundation": "筑基",
    "golden_core": "金丹",
    "nascent_soul": "元婴",
    "soul_transformation": "化神",
}

PROTECTION_LABELS = {
    "item.pill.qi_guard": "聚气护脉丹",
    "item.pill.foundation_guard": "筑基护脉丹",
    "item.pill.golden_core_guard": "金丹护脉丹",
    "item.pill.soul_restore": "魂元丹",
    "item.pill.domain_restore": "领域复原丹",
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
            elif arg in {"金丹", "golden_core", "金丹突破"}:
                target = "golden_core"
            elif arg in {"金丹护脉丹", "金丹保护", "golden_core_guard"}:
                protection = True
            elif arg in {"元婴", "nascent_soul", "元婴突破"}:
                target = "nascent_soul"
            elif arg in {"魂元丹", "心魔保护", "soul_restore"}:
                protection = True
            elif arg in {"化神", "soul_transformation", "化神突破"}:
                target = "soul_transformation"
            elif arg in {"领域复原丹", "领域保护", "domain_restore"}:
                protection = True
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
        location = (
            definition.location_bonus_bp
            if definition.location_bonus_bp and player.location_key == "xuantian.cloud_city"
            else 0
        )
        support = (
            definition.support_bonus_bp
            if definition.support_bonus_bp and definition.support_key and player.inventory.get(definition.support_key, 0) > 0
            else 0
        )
        if definition.target_realm == "nascent_soul":
            flags = set(player.intro_flags)
            preparation = 0
            if player.inventory.get("item.manual.basic_qi", 0) > 0 or "preparation.nascent_soul.technique" in flags:
                preparation += 300
            world = player.location_key.split(".", 1)[0]
            if f"alliance.{world}" in flags:
                preparation += 300
            if {"sect.nascent_soul_ritual", "quest.nascent_soul_ritual"} & flags:
                preparation += 300
            if player.location_key.startswith("xuantian."):
                preparation += 300
            return preparation
        return quality + technique + formation + location + support

    async def prepare_nascent_soul(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_PREPARATION_COMMAND", "准备元婴无需附加参数。", context.request_id)
        operation_id = self._operation_id(context, "progression.prepare_nascent_soul")
        try:
            record = await self.repository.prepare_nascent_soul(platform=context.adapter, platform_user_id=context.user_id, operation_id=operation_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except FoundationQualityInsufficientError:
            return CommandResult(False, "FOUNDATION_QUALITY_LOW", "道基质量至少需要 5,500，未修改任务状态。", context.request_id, operation_id)
        except BreakthroughRequirementError:
            return CommandResult(False, "REALM_MISMATCH", "需要金丹 L10、总修为达到 58,960 才能准备元婴。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于其他准备操作，请重新发起。", context.request_id, operation_id)
        return CommandResult(True, "NASCENT_SOUL_PREPARED", "## 元婴准备完成\n\n已记录 `quest.prepare_nascent_soul`，可以查看 `突破预览 元婴`。", context.request_id, operation_id, data={"quest_key": "quest.prepare_nascent_soul", "idempotent_replay": record.already_completed})

    async def preview_breakthrough(self, context: CommandContext) -> CommandResult:
        parsed = self._parse_start_args(context.command_args)
        if parsed is None:
            return CommandResult(False, "INVALID_BREAKTHROUGH_COMMAND", "可用指令：`突破预览 聚气`、`突破预览 筑基`、`突破预览 金丹`、`突破预览 元婴` 或 `突破预览 化神`。", context.request_id)
        target, _ = parsed
        definition = breakthrough_definition(target)
        try:
            player = await self.repository.get_player(platform=context.adapter, platform_user_id=context.user_id)
        except Exception:
            player = None
        if player is None:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id)
        missing = [ITEM_LABELS.get(key, "突破材料") for key, amount in definition.materials.items() if player.inventory.get(key, 0) < amount]
        if target == "nascent_soul" and max(player.inventory.get("item.demon_core", 0), player.inventory.get("item.beast_blood", 0)) < 2:
            missing.append("魔核或兽血 ×2")
        preparation_bp = self._preparation_bp(player, definition)
        soul_prepare_bp = reputation_prepare_bp = quest_prepare_bp = 0
        if target == "nascent_soul":
            quality_bp = min(1000, player.foundation_quality // 10)
            world = player.location_key.split(".", 1)[0]
            risk_bp = 400 if not player.location_key.startswith("xuantian.") and f"alliance.{world}" not in set(player.intro_flags) else 0
            current_success_bp = max(5500, min(9000, 5500 + quality_bp + preparation_bp + player.breakthrough_pity_bp + player.heart_demon_bonus_bp - risk_bp))
        elif target == "soul_transformation":
            faction = getattr(player, "faction_reputation", {}) if hasattr(player, "faction_reputation") else {}
            max_rep = max((int(value) for value in faction.values()), default=0)
            soul_prepare_bp = min(1000, max(0, player.soul_power - 200) * 4)
            reputation_prepare_bp = min(1000, max(0, max_rep - 2000) // 2)
            quest_prepare_bp = 600 if "quest.soul_transformation" in set(player.intro_flags) else 0
            preparation_bp = soul_prepare_bp + reputation_prepare_bp + quest_prepare_bp
            current_success_bp = max(6500, min(9000, 6500 + preparation_bp + player.breakthrough_pity_bp))
        else:
            current_success_bp = success_bp(definition, player.breakthrough_pity_bp, preparation_bp)
        ready = (
            player.realm_key == definition.source_realm
            and player.realm_layer == 10
            and player.total_cultivation >= definition.required_total_cultivation
            and player.foundation_quality >= definition.required_foundation_quality
            and not missing
            and player.spirit_stones >= definition.currency_cost
            and (target != "nascent_soul" or (player.world_merit >= 100 and "quest.prepare_nascent_soul" in player.intro_flags))
            and (target != "soul_transformation" or (player.soul_power >= 200 and player.world_merit >= 500 and "quest.soul_transformation" in player.intro_flags))
            and (target != "soul_transformation" or max((int(value) for value in player.faction_reputation.values()), default=0) >= 2000)
            and (target != "nascent_soul" or player.soul_fatigue_until is None)
            and (target != "soul_transformation" or player.domain_crack_until is None)
        )
        material_lines = "\n".join(
            f"- **{ITEM_LABELS.get(key, '突破材料')}** ×{amount}" for key, amount in definition.materials.items()
        )
        if target == "nascent_soul":
            material_lines += "\n- **魔核或兽血** ×2（任选其一）\n- **世界功勋** ×100"
        realm_label = REALM_LABELS[target]
        protection_label = PROTECTION_LABELS[definition.protection_key]
        retention = definition.retention_bp / 100
        quality_line = f"- **道基质量要求**：{definition.required_foundation_quality}\n" if definition.required_foundation_quality else ""
        message = (
            f"## {realm_label}突破预览\n\n"
            f"**{self._display_name(player)}**当前{('满足' if ready else '尚未满足')}突破条件。\n\n"
            f"- **境界要求**：{REALM_LABELS.get(definition.source_realm, definition.source_realm)} L10（混元）\n"
            f"- **总修为要求**：{definition.required_total_cultivation}\n"
            f"{quality_line}"
            f"- **当前成功率**：{current_success_bp / 100:.0f}%（基础 {definition.base_success_bp / 100:.0f}%）\n"
            f"- **准备时长**：{definition.duration_seconds // 60} 分钟\n"
            f"- **消耗灵石**：{definition.currency_cost}\n\n"
            "### 必需材料\n\n"
            f"{material_lines}\n\n"
            f"> 失败会保留当前境内修为的 {retention:.0f}%，并进入{'心魔试炼' if target == 'nascent_soul' else '24 小时领域裂痕' if target == 'soul_transformation' else f' {definition.weakness_seconds // 3600} 小时虚弱'}。可选 **{protection_label}**，只在失败时消耗。"
        )
        if missing:
            message += f"\n> 当前缺少：{'、'.join(missing)}。"
        return CommandResult(True, "BREAKTHROUGH_PREVIEW", message, context.request_id, data={"target_realm": target, "ready": ready, "missing": missing, "success_bp": current_success_bp, "preparation_bp": preparation_bp, "soul_prepare_bp": soul_prepare_bp, "reputation_prepare_bp": reputation_prepare_bp, "quest_prepare_bp": quest_prepare_bp, "pity_bp": player.breakthrough_pity_bp})

    async def start_breakthrough(self, context: CommandContext) -> CommandResult:
        parsed = self._parse_start_args(context.command_args)
        if parsed is None:
            return CommandResult(False, "INVALID_BREAKTHROUGH_COMMAND", "可用指令：`开始突破 聚气`、`开始突破 筑基`、`开始突破 金丹`、`开始突破 元婴` 或 `开始突破 化神`，可追加保护丹。", context.request_id)
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
        except RealmMismatchError:
            return CommandResult(False, "REALM_MISMATCH", f"需要{REALM_LABELS.get(definition.source_realm, definition.source_realm)} L10 才能开始{REALM_LABELS[target]}突破，未扣除任何资源。", context.request_id, operation_id)
        except CultivationInsufficientError:
            return CommandResult(False, "CULTIVATION_INSUFFICIENT", f"化神需要总修为达到 {definition.required_total_cultivation:,}，未扣除任何资源。", context.request_id, operation_id)
        except SoulPowerInsufficientError:
            return CommandResult(False, "SOUL_POWER_INSUFFICIENT", "化神需要神魂至少 200，未扣除任何资源。", context.request_id, operation_id)
        except FactionReputationInsufficientError:
            return CommandResult(False, "FACTION_REPUTATION_INSUFFICIENT", "任一三界声望达到 2,000 后才能化神，未扣除任何资源。", context.request_id, operation_id)
        except QuestRequirementError:
            return CommandResult(False, "QUEST_REQUIREMENT_MISSING", "尚未完成对应突破任务，未扣除任何资源。", context.request_id, operation_id)
        except DomainCrackActiveError:
            return CommandResult(False, "DOMAIN_CRACK_ACTIVE", "领域裂痕尚未恢复，暂时不能再次冲击化神。", context.request_id, operation_id)
        except HeartDemonPendingError:
            return CommandResult(False, "HEART_DEMON_PENDING", "心魔尚未化解，请先发送 `化解心魔 面对/净化/交易`。", context.request_id, operation_id)
        except SoulFatigueActiveError:
            return CommandResult(False, "SOUL_FATIGUE_ACTIVE", "神魂疲劳尚未恢复，请稍后再试或发送 `恢复神魂疲劳`。", context.request_id, operation_id)
        except FoundationQualityInsufficientError:
            return CommandResult(False, "FOUNDATION_QUALITY_LOW", f"道基质量至少需要 {definition.required_foundation_quality:,}，未扣除任何资源。", context.request_id, operation_id)
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
        except HeartDemonPendingError:
            return CommandResult(False, "HEART_DEMON_PENDING", "心魔尚未化解，请先处理心魔。", context.request_id, operation_id)
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
            if record.reward_local_reputation:
                reward_lines.append(f"地方名望 ×{record.reward_local_reputation}")
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
            if record.heart_demon_pending:
                message = "## 突破未成\n\n元婴突破失败，心魔已现。请在 24 小时内选择 `化解心魔 面对`、`净化` 或 `交易`。"
            else:
                if record.target_realm == "soul_transformation":
                    weak_text = "保护丹生效，领域裂痕 8 小时" if record.protection_consumed else "领域裂痕 24 小时"
                else:
                    weak_text = (
                        f"保护丹生效，虚弱 {30 if record.target_realm == 'qi_gathering' else 120 if record.target_realm == 'foundation' else 240} 分钟"
                        if record.protection_consumed
                        else f"虚弱 {2 if record.target_realm == 'qi_gathering' else 6 if record.target_realm == 'foundation' else 12} 小时"
                    )
                recovery_command = "恢复领域裂痕" if record.target_realm == "soul_transformation" else "恢复虚弱"
                message = (
                    "## 突破未成\n\n"
                    f"**{self._display_name(player)}**暂未踏入{target_label}，保留境内修为 **{record.cultivation_after}**。\n\n"
                    f"- **结果**：{weak_text}\n"
                    f"- **本次成功率**：{record.success_bp / 100:.0f}%\n"
                    f"- **保底**：下次增加 {record.pity_after_bp - record.pity_before_bp} bp\n\n"
                    f"> 限制期间不能再次突破；到期后发送 `{recovery_command}`，或使用 `{recovery_command} 提前`。"
                )
        return CommandResult(True, "BREAKTHROUGH_SUCCEEDED" if record.success else "BREAKTHROUGH_FAILED", message, context.request_id, operation_id, data={"session_id": record.session_id, "target_realm": record.target_realm, "success": record.success, "roll_bp": record.roll_bp, "success_bp": record.success_bp, "cultivation_before": record.cultivation_before, "cultivation_after": record.cultivation_after, "pity_before_bp": record.pity_before_bp, "pity_after_bp": record.pity_after_bp, "preparation_bp": record.preparation_bp, "soul_prepare_bp": record.soul_prepare_bp, "reputation_prepare_bp": record.reputation_prepare_bp, "quest_prepare_bp": record.quest_prepare_bp, "reward_currency": record.reward_currency, "reward_stamina": record.reward_stamina, "reward_world_merit": record.reward_world_merit, "reward_local_reputation": record.reward_local_reputation, "reward_items": record.reward_items or {}, "protection_consumed": record.protection_consumed, "heart_demon_pending": record.heart_demon_pending, "cross_realm_risk_bp": record.cross_realm_risk_bp, "heart_demon_bonus_bp": record.heart_demon_bonus_bp, "weakness_until": record.weakness_until, "domain_crack_until": record.weakness_until if record.target_realm == "soul_transformation" and not record.success else None, "idempotent_replay": record.already_completed})

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

    async def resolve_heart_demon(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 1:
            return CommandResult(False, "INVALID_HEART_DEMON_COMMAND", "可用指令：`化解心魔 面对`、`化解心魔 净化` 或 `化解心魔 交易`。", context.request_id)
        choice = {"面对": "heart_demon.face", "净化": "heart_demon.purify", "交易": "heart_demon.bargain", "face": "heart_demon.face", "purify": "heart_demon.purify", "bargain": "heart_demon.bargain"}.get(context.command_args[0])
        if choice is None:
            return CommandResult(False, "INVALID_HEART_DEMON_COMMAND", "可用指令：`化解心魔 面对`、`化解心魔 净化` 或 `化解心魔 交易`。", context.request_id)
        operation_id = self._operation_id(context, "event.resolve_heart_demon")
        try:
            record = await self.repository.resolve_heart_demon(platform=context.adapter, platform_user_id=context.user_id, choice_key=choice, operation_id=operation_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except HeartDemonPendingError:
            return CommandResult(False, "HEART_DEMON_NOT_FOUND", "当前没有待处理的心魔。", context.request_id, operation_id)
        except MaterialInsufficientError:
            return CommandResult(False, "MATERIAL_INSUFFICIENT", "净化心魔需要魂元丹 ×1，未扣除资源。", context.request_id, operation_id)
        except BreakthroughRequirementError:
            return CommandResult(False, "HEART_DEMON_CHOICE_INVALID", "当前状态不能选择该心魔处理方式。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于其他心魔选择，请重新发起。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色处于暂停状态，暂时不能处理心魔。", context.request_id, operation_id)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        return CommandResult(True, "HEART_DEMON_RESOLVED", f"## 心魔已化解\n\n处理方式：**{choice.split('.')[-1]}**\n\n- **神魂疲劳**：至 {record.fatigue_until or '无'}\n- **保底**：{record.pity_after_bp} bp\n\n> 疲劳结束后可再次准备元婴突破。", context.request_id, operation_id, data={"session_id": record.session_id, "choice_key": record.choice_key, "status": record.status, "pity_after_bp": record.pity_after_bp, "fatigue_until": record.fatigue_until, "pollution_before": record.pollution_before, "pollution_after": record.pollution_after, "world_merit_gained": record.world_merit_gained, "idempotent_replay": record.already_completed})

    async def recover_soul_fatigue(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_RECOVERY_COMMAND", "恢复神魂疲劳无需附加参数。", context.request_id)
        operation_id = self._operation_id(context, "progression.recover_soul_fatigue")
        try:
            record = await self.repository.recover_soul_fatigue(platform=context.adapter, platform_user_id=context.user_id, operation_id=operation_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except SoulFatigueActiveError:
            return CommandResult(False, "SOUL_FATIGUE_ACTIVE", "神魂疲劳尚未到期。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于其他恢复，请重新发起。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色处于暂停状态，暂时不能恢复神魂疲劳。", context.request_id, operation_id)
        return CommandResult(True, "SOUL_FATIGUE_RECOVERED", "## 神魂疲劳已恢复\n\n现在可以继续准备元婴突破。", context.request_id, operation_id, data={"recovered": record.recovered, "idempotent_replay": record.already_completed})

    async def recover_foundation_shock(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) > 1 or (context.command_args and context.command_args[0] not in {"提前", "立即", "early"}):
            return CommandResult(False, "INVALID_RECOVERY_COMMAND", "可用指令：`恢复道基震荡`，或 `恢复道基震荡 提前`。", context.request_id)
        early = bool(context.command_args)
        operation_id = self._operation_id(context, "progression.recover_foundation_shock")
        try:
            record = await self.repository.recover_foundation_shock(
                platform=context.adapter,
                platform_user_id=context.user_id,
                early=early,
                operation_id=operation_id,
            )
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except WeaknessNotActiveError:
            return CommandResult(False, "WEAKNESS_NOT_ACTIVE", "当前没有需要恢复的道基震荡。", context.request_id, operation_id)
        except WeaknessActiveError:
            return CommandResult(False, "WEAKNESS_ACTIVE", "道基震荡尚未到期；提前恢复需要金丹恢复丹 ×1 和 200 灵石。", context.request_id, operation_id)
        except MaterialInsufficientError:
            return CommandResult(False, "MATERIAL_INSUFFICIENT", "提前恢复需要金丹恢复丹 ×1，未扣除资源。", context.request_id, operation_id)
        except CurrencyInsufficientError:
            return CommandResult(False, "RESOURCE_INSUFFICIENT", "提前恢复需要 200 灵石，未扣除资源。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色处于暂停状态，暂时不能恢复道基震荡。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于其他恢复，请重新发起。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        return CommandResult(
            True,
            "FOUNDATION_SHOCK_RECOVERED",
            f"## 道基震荡已恢复\n\n**{self._display_name(record.player)}**可以继续准备金丹突破。\n\n- **提前恢复**：{'是' if record.early else '否'}\n- **消耗灵石**：{record.spirit_stones_spent}\n- **消耗金丹恢复丹**：{'是' if record.medicine_consumed else '否'}\n\n> 突破失败保底不会被清除。",
            context.request_id,
            operation_id,
            data={"early": record.early, "spirit_stones_spent": record.spirit_stones_spent, "medicine_consumed": record.medicine_consumed, "medicine_key": record.medicine_key, "idempotent_replay": record.already_completed},
        )

    async def choose_domain(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 1:
            return CommandResult(False, "INVALID_DOMAIN_COMMAND", "请使用 `选择领域 体修/法修/器修/魔修/妖修/辅修`。", context.request_id)
        path_key = resolve_domain(context.command_args[0])
        if path_key is None:
            return CommandResult(False, "INVALID_DOMAIN_COMMAND", "领域必须匹配首要道途：体修、法修、器修、魔修、妖修或辅修。", context.request_id)
        operation_id = self._operation_id(context, "paths.choose_domain")
        try:
            record = await self.repository.choose_domain(platform=context.adapter, platform_user_id=context.user_id, path_key=path_key, operation_id=operation_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except DomainCrackActiveError:
            return CommandResult(False, "DOMAIN_CRACK_ACTIVE", "领域裂痕尚未恢复，暂时不能选择领域。", context.request_id, operation_id)
        except DomainAlreadySelectedError:
            return CommandResult(False, "DOMAIN_ALREADY_SELECTED", "你已经选择过领域，当前版本不能普通重选。", context.request_id, operation_id)
        except DomainSelectionBusyError:
            return CommandResult(False, "DOMAIN_SELECTION_PENDING", "已有待确认的领域选择，请发送 `确认领域`。", context.request_id, operation_id)
        except DomainNotEligibleError:
            return CommandResult(False, "DOMAIN_NOT_ELIGIBLE", "需要化神 L3、首要道途等级 5，且领域必须匹配首要道途。", context.request_id, operation_id)
        except MaterialInsufficientError:
            return CommandResult(False, "MATERIAL_INSUFFICIENT", "选择领域需要领域核心 ×1，未扣除资源。", context.request_id, operation_id)
        except CurrencyInsufficientError:
            return CommandResult(False, "RESOURCE_INSUFFICIENT", "选择领域需要 10,000 灵石，未扣除资源。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于其他领域选择，请重新发起。", context.request_id, operation_id)
        definition = domain_definition(path_key)
        return CommandResult(True, "DOMAIN_SELECTION_PENDING", f"## 领域选择待确认\n\n将选择 **{definition.label}**。\n\n- **确认期限**：5 分钟\n- **确认消耗**：领域核心 ×1、灵石 ×10,000\n\n请发送 `确认领域` 完成选择。", context.request_id, operation_id, data={"session_id": record.session_id, "domain_key": record.domain_key, "status": record.status, "ends_at": record.ends_at, "energy_cost": record.energy_cost, "idempotent_replay": record.already_completed})

    async def confirm_domain(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_DOMAIN_COMMAND", "确认领域无需附加参数。", context.request_id)
        operation_id = self._operation_id(context, "paths.confirm_domain")
        try:
            record = await self.repository.confirm_domain(platform=context.adapter, platform_user_id=context.user_id, operation_id=operation_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except DomainCrackActiveError:
            return CommandResult(False, "DOMAIN_CRACK_ACTIVE", "领域裂痕尚未恢复，暂时不能确认领域。", context.request_id, operation_id)
        except DomainAlreadySelectedError:
            return CommandResult(False, "DOMAIN_ALREADY_SELECTED", "你已经选择过领域，当前版本不能普通重选。", context.request_id, operation_id)
        except DomainNotEligibleError:
            return CommandResult(False, "DOMAIN_NOT_ELIGIBLE", "没有有效的待确认领域选择，或确认已超时。", context.request_id, operation_id)
        except MaterialInsufficientError:
            return CommandResult(False, "MATERIAL_INSUFFICIENT", "领域核心不足，未扣除灵石。", context.request_id, operation_id)
        except CurrencyInsufficientError:
            return CommandResult(False, "RESOURCE_INSUFFICIENT", "灵石不足，未扣除领域核心。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于其他确认，请重新发起。", context.request_id, operation_id)
        return CommandResult(True, "DOMAIN_SELECTED", f"## 领域已觉醒\n\n已激活 **{record.domain_key}**。\n\n- **领域能量**：{record.player.domain_charge}/{record.player.domain_charge_max}\n- **领域力量**：{record.player.domain_power}\n- **灵石**：{record.player.spirit_stones}", context.request_id, operation_id, data={"session_id": record.session_id, "domain_key": record.domain_key, "status": record.status, "idempotent_replay": record.already_completed})

    async def cancel_domain(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_DOMAIN_COMMAND", "取消领域无需附加参数。", context.request_id)
        operation_id = self._operation_id(context, "paths.cancel_domain")
        try:
            record = await self.repository.cancel_domain(platform=context.adapter, platform_user_id=context.user_id, operation_id=operation_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except DomainNotEligibleError:
            return CommandResult(False, "DOMAIN_NOT_ELIGIBLE", "当前没有待确认的领域选择。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于其他领域操作，请重新发起。", context.request_id, operation_id)
        return CommandResult(True, "DOMAIN_SELECTION_CANCELLED", "## 领域选择已取消\n\n未扣除领域核心或灵石。", context.request_id, operation_id, data={"session_id": record.session_id, "domain_key": record.domain_key, "status": record.status, "idempotent_replay": record.already_completed})

    async def recover_domain_crack(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) > 1 or (context.command_args and context.command_args[0] not in {"提前", "立即", "early"}):
            return CommandResult(False, "INVALID_RECOVERY_COMMAND", "可用指令：`恢复领域裂痕`，或 `恢复领域裂痕 提前`。", context.request_id)
        early = bool(context.command_args)
        operation_id = self._operation_id(context, "progression.recover_domain_crack")
        try:
            record = await self.repository.recover_domain_crack(platform=context.adapter, platform_user_id=context.user_id, early=early, operation_id=operation_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except WeaknessNotActiveError:
            return CommandResult(False, "DOMAIN_CRACK_NOT_ACTIVE", "当前没有需要恢复的领域裂痕。", context.request_id, operation_id)
        except WeaknessActiveError:
            return CommandResult(False, "DOMAIN_CRACK_ACTIVE", "领域裂痕尚未到期；提前恢复需要在领域前线使用领域复原丹 ×1 和 2,000 灵石。", context.request_id, operation_id)
        except BreakthroughRequirementError:
            return CommandResult(False, "LOCATION_DOMAIN_FORBIDDEN", "提前恢复领域裂痕必须位于玄天·领域前线。", context.request_id, operation_id)
        except MaterialInsufficientError:
            return CommandResult(False, "MATERIAL_INSUFFICIENT", "提前恢复需要领域复原丹 ×1，未扣除资源。", context.request_id, operation_id)
        except CurrencyInsufficientError:
            return CommandResult(False, "RESOURCE_INSUFFICIENT", "提前恢复需要 2,000 灵石，未扣除资源。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于其他恢复，请重新发起。", context.request_id, operation_id)
        return CommandResult(True, "DOMAIN_CRACK_RECOVERED", "## 领域裂痕已恢复\n\n现在可以再次准备化神或选择领域。", context.request_id, operation_id, data={"early": record.early, "spirit_stones_spent": record.spirit_stones_spent, "medicine_consumed": record.medicine_consumed, "idempotent_replay": record.already_completed})


__all__ = ["BreakthroughApplication"]
