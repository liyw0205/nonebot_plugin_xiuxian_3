"""Application commands for v0.1 exploration sessions."""

from __future__ import annotations

from ...contracts import CommandContext, CommandResult
from ..repository import (
    CurrencyInsufficientError,
    ExplorationBusyError,
    ExplorationCombatPendingError,
    ExplorationNotFoundError,
    ExplorationNotReadyError,
    ExplorationQuotaExhaustedError,
    ExplorationStormChoiceError,
    ExplorationStormNotPendingError,
    EnergyInsufficientError,
    LocationRequirementError,
    OperationConflictError,
    PlayerNotFoundError,
    PlayerStageConflictError,
    PlayerSuspendedError,
    RepositoryBusyError,
    ResourceInsufficientError,
    PollutionTooHighError,
    SoulExhaustionActiveError,
    SQLitePlayerRepository,
)
from ..player.rules import LOCATION_LABELS
from .rules import exploration_definition, resolve_exploration_mode


ITEM_LABELS = {
    "item.herb.blood_grass": "止血草",
    "item.ore.ironstone": "铁石",
    "item.herb.spirit_leaf": "灵叶",
    "item.mat.array_sand": "阵砂",
    "item.material.cloud_iron": "云铁",
    "item.ticket.cloud_boat_fragment": "云舟票碎片",
    "item.demon_core": "魔核",
    "item.clue.demon_contract": "魔界契约线索",
    "item.clue.beast_bloodline": "妖界血脉线索",
    "item.ancestral_blood": "祖灵血",
    "item.spirit_water": "灵泉水",
}


class ExplorationApplication:
    """Coordinates exploration session writes and Markdown responses."""

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
    def _mode(args: tuple[str, ...]) -> str | None:
        if len(args) != 1:
            return None
        return resolve_exploration_mode(args[0])

    @staticmethod
    def _location_text(location_key: str) -> str:
        return LOCATION_LABELS.get(location_key, "未知地点")

    async def start_exploration(self, context: CommandContext) -> CommandResult:
        mode_key = self._mode(context.command_args)
        if mode_key is None:
            return CommandResult(
                False,
                "INVALID_EXPLORATION_MODE",
                "请使用 `开始探索 近郊采集`、`开始探索 短历练`、`开始探索 灵泉采集`、`开始探索 雾隐洞天探索`、`开始探索 云铁矿区采集`、`开始探索 洞天二层探索`、`开始探索 云舟试炼`、`开始探索 魔界堕落遗迹探索`、`开始探索 万兽山狩猎` 或 `开始探索 祖灵湖探索`。",
                context.request_id,
            )
        operation_id = self._operation_id(context, "exploration.start")
        try:
            record = await self.repository.start_exploration(
                platform=context.adapter,
                platform_user_id=context.user_id,
                mode_key=mode_key,
                operation_id=operation_id,
            )
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色处于暂停状态，暂时不能探索。", context.request_id, operation_id)
        except PlayerStageConflictError:
            return CommandResult(False, "EXPLORATION_REQUIREMENT_MISSING", "完成入道后才能开始探索。", context.request_id, operation_id)
        except LocationRequirementError:
            return CommandResult(False, "EXPLORATION_LOCATION_FORBIDDEN", "当前地点或境界不满足这项探索。", context.request_id, operation_id)
        except ExplorationBusyError:
            return CommandResult(False, "EXPLORATION_BUSY", "当前已有移动、修炼、生产、突破或探索会话。", context.request_id, operation_id)
        except ExplorationQuotaExhaustedError:
            return CommandResult(False, "EXPLORATION_QUOTA_EXHAUSTED", "这项探索今日次数已用尽。", context.request_id, operation_id)
        except ResourceInsufficientError:
            return CommandResult(False, "RESOURCE_INSUFFICIENT", "体力不足，未扣除任何资源。", context.request_id, operation_id)
        except EnergyInsufficientError:
            return CommandResult(False, "ENERGY_INSUFFICIENT", "精力不足，未扣除任何资源。", context.request_id, operation_id)
        except PollutionTooHighError:
            return CommandResult(False, "POLLUTION_TOO_HIGH", "污染已达到 80，暂时不能进入魔界堕落遗迹。", context.request_id, operation_id)
        except SoulExhaustionActiveError:
            return CommandResult(False, "SOUL_EXHAUSTION_ACTIVE", "神魂疲劳尚未结束，暂时不能进行跨界探索。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于其他探索输入，请重新发起。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        definition = exploration_definition(record.mode_key)
        return CommandResult(
            True,
            "EXPLORATION_STARTED",
            (
                f"## {definition.label}已开始\n\n"
                f"**{self._display_name(record.player)}**已锁定探索会话。\n\n"
                f"- **地点**：{self._location_text(definition.location_key)}\n"
                f"- **预计耗时**：{definition.duration_seconds // 60 if definition.duration_seconds >= 60 else definition.duration_seconds} {'分钟' if definition.duration_seconds >= 60 else '秒'}\n"
                f"- **体力**：{record.player.stamina}/{record.player.stamina_max}\n"
                f"- **精力**：{record.player.energy}/{record.player.energy_max}（消耗 {record.energy_cost}）\n"
                f"- **今日上限**：{definition.daily_limit} 次\n\n"
                + (f"- **迷雾屏障**：风险 -{record.risk_reduction_bp} bp\n\n" if record.risk_reduction_bp else "")
                + "> 完成后发送 `结算探索`；准备期间不能移动、修炼、生产、突破或再次探索。"
            ),
            context.request_id,
            operation_id,
            data={
                "exploration_id": record.exploration_id,
                "mode_key": record.mode_key,
                "status": record.status,
                "ends_at": record.ends_at,
                "stamina_cost": record.stamina_cost,
                "energy_cost": record.energy_cost,
                "content_version": definition.content_version,
                "risk_reduction_bp": record.risk_reduction_bp,
                "pollution_before": record.pollution_before,
                "pollution_after": record.pollution_after,
                "cross_realm_penalty_bp": record.cross_realm_penalty_bp,
                "bloodline_stability_before": record.bloodline_stability_before,
                "bloodline_stability_after": record.bloodline_stability_after,
                "idempotent_replay": record.already_completed,
            },
        )

    async def settle_exploration(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_EXPLORATION_COMMAND", "结算探索无需附加参数。", context.request_id)
        operation_id = self._operation_id(context, "exploration.settle")
        try:
            record = await self.repository.settle_exploration(
                platform=context.adapter,
                platform_user_id=context.user_id,
                operation_id=operation_id,
            )
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except ExplorationNotFoundError:
            return CommandResult(False, "EXPLORATION_NOT_FOUND", "当前没有等待结算的探索。", context.request_id, operation_id)
        except ExplorationNotReadyError:
            return CommandResult(False, "EXPLORATION_NOT_READY", "探索尚未完成，请稍后再来结算。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色处于暂停状态，暂时不能结算探索。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于其他探索结算，请重新发起。", context.request_id, operation_id)
        except ExplorationCombatPendingError:
            return CommandResult(
                False,
                "EXPLORATION_COMBAT_PENDING",
                "探索遭遇战仍在自动回合中，奖励已冻结，请稍后重试结算。",
                context.request_id,
                operation_id,
                retryable=True,
            )
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        definition = exploration_definition(record.mode_key)
        if record.status == "combat_pending":
            return CommandResult(
                False,
                "EXPLORATION_COMBAT_PENDING",
                (
                    f"## {definition.label}遭遇战斗\n\n"
                    f"**{self._display_name(record.player)}**在探索中触发了战斗遭遇。\n\n"
                    "> 自动回合战斗正在恢复，探索奖励已冻结；请稍后重试结算。"
                ),
                context.request_id,
                operation_id,
                data={"exploration_id": record.exploration_id, "status": record.status, "battle_id": record.battle_id, "idempotent_replay": record.already_completed},
            )
        if record.status == "storm_pending":
            return CommandResult(
                False,
                "EXPLORATION_STORM_PENDING",
                (
                    f"## {definition.label}遭遇风暴\n\n"
                    f"**{self._display_name(record.player)}**需要选择航行方案。\n\n"
                    "- `选择云舟风暴 等待`：延长 2 分钟，无额外损失\n"
                    "- `选择云舟风暴 支付`：支付 100 灵石，额外获得修为 +200\n"
                    "- `选择云舟风暴 返航`：返还本次一半体力，不发放探索奖励\n\n"
                    f"> 选择窗口截止：{record.storm_deadline or '未知'}。超时默认等待。"
                ),
                context.request_id,
                operation_id,
                data={
                    "exploration_id": record.exploration_id,
                    "status": record.status,
                    "storm_options": record.storm_options,
                    "storm_deadline": record.storm_deadline,
                    "storm_preview": {},
                    "idempotent_replay": record.already_completed,
                },
            )
        if record.status == "running" and record.storm_choice == "wait":
            return CommandResult(
                False,
                "EXPLORATION_STORM_WAITING",
                f"风暴已按等待方案处理，新的结算时间为 {record.storm_deadline or '稍后'}。",
                context.request_id,
                operation_id,
                data={
                    "exploration_id": record.exploration_id,
                    "status": record.status,
                    "storm_choice": record.storm_choice,
                    "ends_at": record.storm_deadline,
                    "idempotent_replay": record.already_completed,
                },
            )
        if record.status == "expired":
            return CommandResult(
                False,
                "EXPLORATION_EXPIRED",
                f"## 探索已过期\n\n**{self._display_name(record.player)}**的 **{definition.label}** 超过了结算窗口，本次不发放奖励。",
                context.request_id,
                operation_id,
                data={"exploration_id": record.exploration_id, "status": record.status, "idempotent_replay": record.already_completed},
            )
        reward_lines = []
        for key, quantity in record.result.items():
            if key == "cultivation":
                reward_lines.append(f"境内修为 +{quantity}")
            elif key == "spirit_stones":
                reward_lines.append(f"灵石 ×{quantity}")
            elif key.startswith("faction_reputation."):
                reward_lines.append(f"{key.removeprefix('faction_reputation.')}界声望 +{quantity}")
            else:
                reward_lines.append(f"{ITEM_LABELS.get(key, '探索材料')} ×{quantity}")
        battle_text = f"- **遭遇战**：{'胜利' if record.battle_outcome == 'won' else '失败'}\n" if record.battle_outcome else ""
        return CommandResult(
            True,
            "EXPLORATION_SETTLED",
            (
                f"## {definition.label}完成\n\n"
                + f"**{self._display_name(record.player)}**已完成探索。\n\n"
                + f"{battle_text}"
                + f"- **探索收获**：{'、'.join(reward_lines) or '无'}\n"
                + f"- **体力**：{record.player.stamina}/{record.player.stamina_max}\n"
                + f"- **精力**：{record.player.energy}/{record.player.energy_max}\n"
                + f"- **灵石**：{record.player.spirit_stones}\n"
                + f"- **污染**：{record.pollution_after}\n"
                + (f"- **血脉稳定**：{record.bloodline_stability_after}\n" if record.mode_key in {"explore.beast_hunt", "explore.ancestral_lake"} else "")
                + (f"- **神魂损失**：{record.soul_power_loss}\n" if record.soul_power_loss else "")
                + "\n> 结果按开始时的规则快照结算，重复结算不会重复发放。"
            ),
            context.request_id,
            operation_id,
            data={
                "exploration_id": record.exploration_id,
                "mode_key": record.mode_key,
                "status": record.status,
                "result": record.result,
                "battle_id": record.battle_id,
                "battle_outcome": record.battle_outcome,
                "energy_cost": record.energy_cost,
                "content_version": record.content_version,
                "pollution_before": record.pollution_before,
                "pollution_after": record.pollution_after,
                "soul_power_loss": record.soul_power_loss,
                "soul_fatigue_until": record.soul_fatigue_until,
                "bloodline_stability_before": record.bloodline_stability_before,
                "bloodline_stability_after": record.bloodline_stability_after,
                "idempotent_replay": record.already_completed,
            },
        )

    async def choose_cloud_boat_storm(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 1:
            return CommandResult(False, "INVALID_EXPLORATION_COMMAND", "请使用 `选择云舟风暴 等待`、`支付` 或 `返航`。", context.request_id)
        operation_id = self._operation_id(context, "exploration.storm")
        try:
            record = await self.repository.choose_exploration_storm(
                platform=context.adapter,
                platform_user_id=context.user_id,
                choice=context.command_args[0],
                operation_id=operation_id,
            )
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except ExplorationStormChoiceError:
            return CommandResult(False, "INVALID_EXPLORATION_COMMAND", "风暴方案只能选择 `等待`、`支付` 或 `返航`。", context.request_id, operation_id)
        except ExplorationStormNotPendingError:
            return CommandResult(False, "EXPLORATION_STORM_NOT_PENDING", "当前没有等待处理的云舟风暴。", context.request_id, operation_id)
        except CurrencyInsufficientError:
            return CommandResult(False, "SPIRIT_STONES_INSUFFICIENT", "灵石不足，无法支付风暴通行费。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于其他风暴选择，请重新发起。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        if record.status == "running":
            return CommandResult(
                False,
                "EXPLORATION_STORM_WAITING",
                f"风暴已按等待方案处理，新的结算时间为 {record.storm_deadline or '稍后'}。",
                context.request_id,
                operation_id,
                data={"exploration_id": record.exploration_id, "status": record.status, "storm_choice": record.storm_choice, "ends_at": record.storm_deadline, "idempotent_replay": record.already_completed},
            )
        if record.storm_choice == "turn_back":
            message = f"## 云舟已返航\n\n返还体力 +{record.result.get('stamina_refund', 0)}，本次不发放试炼奖励。"
        else:
            message = f"## 云舟试炼已结算\n\n奖励：{'、'.join(f'{key} +{value}' for key, value in record.result.items()) or '无'}。"
        return CommandResult(
            True,
            "EXPLORATION_STORM_SETTLED",
            message,
            context.request_id,
            operation_id,
            data={"exploration_id": record.exploration_id, "status": record.status, "result": record.result, "storm_choice": record.storm_choice, "idempotent_replay": record.already_completed},
        )

    async def cancel_exploration(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_EXPLORATION_COMMAND", "取消探索无需附加参数。", context.request_id)
        operation_id = self._operation_id(context, "exploration.cancel")
        try:
            record = await self.repository.cancel_exploration(
                platform=context.adapter,
                platform_user_id=context.user_id,
                operation_id=operation_id,
            )
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except ExplorationNotFoundError:
            return CommandResult(False, "EXPLORATION_NOT_SETTLEABLE", "当前探索已经进入运行阶段，不能取消。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色处于暂停状态，暂时不能取消探索。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于其他探索取消，请重新发起。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        return CommandResult(
            True,
            "EXPLORATION_CANCELLED",
            (
                "## 探索已取消\n\n"
                f"**{self._display_name(record.player)}**取消了尚未运行的探索。\n\n"
                f"- **返还体力**：{record.result.get('stamina_refund', 0)}\n"
                f"- **返还精力**：{record.result.get('energy_refund', 0)}\n"
                f"- **体力**：{record.player.stamina}/{record.player.stamina_max}"
            ),
            context.request_id,
            operation_id,
            data={"exploration_id": record.exploration_id, "status": record.status, "stamina_refund": record.result.get("stamina_refund", 0), "energy_refund": record.result.get("energy_refund", 0), "idempotent_replay": record.already_completed},
        )


__all__ = ["ExplorationApplication"]
