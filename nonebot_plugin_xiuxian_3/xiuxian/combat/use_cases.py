"""Adapter-neutral use cases for the automatic training battle."""

from __future__ import annotations

from ...contracts import CommandContext, CommandResult
from ..persistence.errors import (
    BattleAlreadySettledError,
    BattleBusyError,
    BattleCooldownError,
    BattleNotFoundError,
    BattleNotReadyError,
    BattleRequirementError,
    BattleRewardAlreadyClaimedError,
    BattleRewardNotAvailableError,
    EventNotActiveError,
    OperationConflictError,
    PlayerNotFoundError,
    PlayerSuspendedError,
    RepositoryBusyError,
)
from ..utils.text import escape_markdown
from .repository import CombatRepositoryMixin


class CombatApplication:
    """Start and present server-driven combat without accepting client actions."""

    def __init__(self, repository: CombatRepositoryMixin):
        self.repository = repository

    @staticmethod
    def _operation_id(context: CommandContext, operation_name: str) -> str:
        if context.operation_id:
            return context.operation_id
        request_key = context.message_id or context.request_id
        return f"{operation_name}:{context.adapter}:{context.user_id}:{request_key}"

    @staticmethod
    def _display_name(player) -> str:
        return escape_markdown(player.dao_name or "未命名")

    @staticmethod
    def _error(context: CommandContext, operation_id: str, exc: Exception) -> CommandResult:
        errors = {
            PlayerNotFoundError: ("PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。"),
            PlayerSuspendedError: ("PLAYER_SUSPENDED", "当前角色处于暂停状态，暂时不能斗法。"),
            BattleRequirementError: ("BATTLE_REQUIREMENT_MISSING", "训练战需要在新手城达到感气 L1。"),
            BattleBusyError: ("BATTLE_PLAYER_OCCUPIED", "当前已有进行中的会话，暂时不能开始训练战。"),
            BattleCooldownError: ("BATTLE_COOLDOWN_ACTIVE", "战败后的调息尚未结束，请稍后再试。"),
            BattleNotFoundError: ("BATTLE_NOT_FOUND", "当前没有可查看的战斗会话。"),
            BattleNotReadyError: ("BATTLE_NOT_READY", "战斗仍在由服务器自动推进。"),
            BattleAlreadySettledError: ("BATTLE_ALREADY_SETTLED", "这场战斗已经结算。"),
            BattleRewardNotAvailableError: ("BATTLE_REWARD_NOT_AVAILABLE", "当前没有待领取的战斗奖励。"),
            BattleRewardAlreadyClaimedError: ("BATTLE_REWARD_ALREADY_CLAIMED", "这场战斗奖励已经领取。"),
            OperationConflictError: ("OPERATION_CONFLICT", "此番请求与先前的斗法不同，请另行发起。"),
            RepositoryBusyError: ("PERSISTENCE_BUSY", "演武场中人影纷乱，稍后再来。"),
        }
        for error_type, (code, message) in errors.items():
            if isinstance(exc, error_type):
                return CommandResult(
                    False,
                    code,
                    message,
                    context.request_id,
                    operation_id or None,
                    retryable=error_type is RepositoryBusyError,
                )
        return CommandResult(
            False,
            "PERSISTENCE_ERROR",
            "战斗会话暂时不可用，请稍后再试。",
            context.request_id,
            operation_id or None,
            retryable=True,
        )

    async def start_training_battle(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(
                False,
                "INVALID_BATTLE_COMMAND",
                "傀儡演武自有章法，无需指定招式与胜负。",
                context.request_id,
            )
        try:
            preview = await self.repository.preview_training_dummy(
                platform=context.adapter,
                platform_user_id=context.user_id,
            )
        except Exception as exc:
            return self._error(context, "", exc)
        snapshots = preview.snapshots
        player_name = escape_markdown(str(snapshots.get("player", {}).get("display_name", "修士")))
        enemy_name = escape_markdown(str(snapshots.get("enemy", {}).get("display_name", "训练傀儡")))
        actions = [dict(action) for action in preview.actions]
        action_lines = []
        for action in actions:
            actor = player_name if action["actor_key"] == "player" else enemy_name
            target = enemy_name if action["target_key"] == "enemy" else player_name
            exchange = (
                f"{actor} 招势命中 {target}，气血损去 {action['damage']}"
                if action.get("hit")
                else f"{actor} 一招落空"
            )
            action_lines.append(f"- 第 {action['round_no']} 合：{exchange}")
        return CommandResult(
            True,
            "TRAINING_SPECTATOR",
            (
                "## 演武旁观\n\n"
                f"**{player_name}**与**{enemy_name}**交手一场，招式尽显。\n\n"
                f"- **结果**：{ {'challenger_won': '你技高一筹', 'defender_won': '训练傀儡略胜一筹', 'draw': '双方势均力敌'}.get(preview.outcome, '演武已毕') }\n"
                f"- **交手合数**：{preview.rounds}\n\n"
                "### 招式往来\n"
                + "\n".join(action_lines)
                + "\n\n> 此番只为观招，不入斗法功业；随身资粮与法器皆无损。"
            ),
            context.request_id,
            data={
                "status": "spectator",
                "outcome": preview.outcome,
                "rounds": preview.rounds,
                "snapshots": snapshots,
                "actions": actions,
            },
        )

    async def start_demon_war_front_battle(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(
                False,
                "INVALID_BATTLE_COMMAND",
                "开始魔界战不接受敌人、技能、目标、伤害或其他参数。",
                context.request_id,
            )
        operation_id = self._operation_id(context, "battle.start.pve.demon_war_front")
        try:
            started = await self.repository.start_demon_war_front_battle(
                platform=context.adapter,
                platform_user_id=context.user_id,
                operation_id=operation_id,
            )
            resolved = await self.run_to_resolution(started.battle_id, started.round_no)
        except EventNotActiveError:
            return CommandResult(False, "EVENT_NOT_ACTIVE", "魔界战只在活动窗口内开放。", context.request_id, operation_id)
        except BattleRequirementError:
            return CommandResult(False, "BATTLE_REQUIREMENT_MISSING", "需在魔界战场达到元婴 L1 后开始魔界战。", context.request_id, operation_id)
        except Exception as exc:
            return self._error(context, operation_id, exc)
        outcome_text = "胜利" if resolved.outcome == "won" else "落败"
        return CommandResult(
            True,
            "DEMON_WAR_FRONT_SETTLED",
            (
                "## 魔界战场战斗结束\n\n"
                f"**{self._display_name(resolved.player)}**完成了魔界战场自动战斗。\n\n"
                f"- **结果**：{outcome_text}\n"
                f"- **回合**：{resolved.round_no}/{20}\n"
                "- **奖励**：战场贡献将按已结算伤害核验，无额外战斗奖励\n\n"
                "> 服务器已记录完整行动回放；发送 `贡献魔界战场 战斗` 投影本场贡献。"
            ),
            context.request_id,
            operation_id,
            data={
                "battle_id": resolved.battle_id,
                "enemy_key": resolved.enemy_key,
                "status": resolved.status,
                "outcome": resolved.outcome,
                "reason": resolved.reason,
                "round_no": resolved.round_no,
                "reward": resolved.reward,
                "reward_status": resolved.reward_status,
                "idempotent_replay": started.already_completed or resolved.already_completed,
            },
        )

    async def claim_battle_reward(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_BATTLE_COMMAND", "领取战斗奖励无需附加参数。", context.request_id)
        operation_id = self._operation_id(context, "battle.claim_reward")
        try:
            record = await self.repository.claim_battle_reward(
                platform=context.adapter,
                platform_user_id=context.user_id,
                operation_id=operation_id,
            )
        except Exception as exc:
            return self._error(context, operation_id, exc)
        rewards = []
        if record.reward.get("cultivation"):
            rewards.append(f"修为 +{record.reward['cultivation']}")
        if record.reward.get("spirit_stones"):
            rewards.append(f"灵石 ×{record.reward['spirit_stones']}")
        rewards.extend(
            f"{key} ×{value}"
            for key, value in record.reward.items()
            if key not in {"cultivation", "spirit_stones"}
        )
        return CommandResult(
            True,
            "BATTLE_REWARD_CLAIMED",
            f"## 战斗奖励已领取\n\n**{self._display_name(record.player)}**获得：{'、'.join(rewards) or '无'}。",
            context.request_id,
            operation_id,
            data={
                "battle_id": record.battle_id,
                "reward": record.reward,
                "reward_status": record.reward_status,
                "idempotent_replay": record.already_completed,
            },
        )

    async def resolve_domain_front_battle(
        self,
        *,
        platform: str,
        platform_user_id: str,
        event_operation_id: str,
    ):
        started = await self.repository.start_domain_front_battle(
            platform=platform,
            platform_user_id=platform_user_id,
            operation_id=f"{event_operation_id}:combat",
            event_operation_id=event_operation_id,
        )
        return await self.run_to_resolution(started.battle_id, started.round_no)

    async def replay_battle(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) > 1:
            return CommandResult(False, "INVALID_BATTLE_COMMAND", "战斗回放最多接收一个战斗编号。", context.request_id)
        battle_id = context.command_args[0] if context.command_args else None
        try:
            record = await self.repository.replay_battle(
                platform=context.adapter,
                platform_user_id=context.user_id,
                battle_id=battle_id,
            )
        except Exception as exc:
            return self._error(context, "", exc)
        result = record.result
        outcome = result.get("outcome", "进行中")
        enemy_snapshot = record.snapshot.get("enemy", {})
        enemy_label = str(enemy_snapshot.get("label") or record.enemy_key)
        lines = ["## 战斗回放", "", f"- **战斗**：`{record.battle_id}`", f"- **敌人**：{enemy_label}", f"- **结果**：{outcome}", ""]
        for action in record.actions:
            actor = "你" if action["actor_key"] == "player" else enemy_label
            target = enemy_label if action["target_key"] == "enemy" else "你"
            phase = action.get("state", {}).get("tribulation_phase")
            phase_text = f"（{phase}阶段）" if phase else ""
            lines.append(
                f"- 回合 {action['round_no']}：{actor}{phase_text} 使用 `{action['skill_key']}` 攻击 {target}，伤害 {action['damage']}。"
            )
        return CommandResult(
            True,
            "BATTLE_REPLAY",
            "\n".join(lines),
            context.request_id,
            data={
                "battle_id": record.battle_id,
                "enemy_key": record.enemy_key,
                "status": record.status,
                "snapshot": record.snapshot,
                "result": record.result,
                "actions": list(record.actions),
            },
        )

    async def run_to_resolution(self, battle_id: str, completed_round: int):
        turn = None
        for expected_round in range(completed_round + 1, 21):
            turn = await self.repository.run_battle_turn(
                battle_id=battle_id,
                expected_round=expected_round,
            )
            if turn.status not in {"created", "running"}:
                break
        if turn is not None and turn.status in {"created", "running"}:
            raise BattleNotReadyError("automatic battle did not reach a terminal state")
        return await self.repository.resolve_battle(battle_id=battle_id)


__all__ = ["CombatApplication"]
