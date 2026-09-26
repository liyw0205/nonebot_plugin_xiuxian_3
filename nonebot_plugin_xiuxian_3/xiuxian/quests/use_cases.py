"""Adapter-neutral commands for producing high-realm breakthrough permits."""

from __future__ import annotations

from ...contracts import CommandContext, CommandResult
from ..persistence.errors import (
    BattleBusyError,
    BattleNotReadyError,
    BattleRequirementError,
    OperationConflictError,
    DaoOriginTaskRequirementError,
    PlayerNotFoundError,
    PlayerSuspendedError,
    QuestAlreadyCompletedError,
    QuestNotCompletedError,
    QuestRequirementError,
    QuestResourceInsufficientError,
    RepositoryBusyError,
)
from .repository import QuestRepositoryMixin
from .rules import ANCIENT_DOMAIN_LINE, DOMAIN_COMMISSION, SOUL_QUEST, VOID_QUEST, VOID_WALL_TRIAL


class QuestApplication:
    """Expose only server-selected quest actions; clients cannot set progress."""

    def __init__(self, repository: QuestRepositoryMixin):
        self.repository = repository

    @staticmethod
    def _operation_id(context: CommandContext, name: str) -> str:
        if context.operation_id:
            return context.operation_id
        key = context.message_id or context.request_id
        return f"{name}:{context.adapter}:{context.user_id}:{key}"

    @staticmethod
    def _error(context: CommandContext, operation_id: str, exc: Exception) -> CommandResult:
        errors = {
            PlayerNotFoundError: ("PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。"),
            PlayerSuspendedError: ("PLAYER_SUSPENDED", "当前角色暂时不能推进任务。"),
            QuestRequirementError: ("QUEST_REQUIREMENT_MISSING", "当前境界或任务前置不满足，未修改进度。"),
            QuestResourceInsufficientError: ("QUEST_RESOURCE_INSUFFICIENT", "任务材料不足，未修改进度。"),
            DaoOriginTaskRequirementError: ("ENDGAME_EVENT_REQUIREMENT_MISSING", "需要先进入合道且满足道源任务前置。"),
            QuestNotCompletedError: ("QUEST_REQUIREMENT_MISSING", "任务前置尚未完成，未发放许可。"),
            QuestAlreadyCompletedError: ("QUEST_ALREADY_COMPLETED", "这个任务环节已经完成。"),
            BattleRequirementError: ("BATTLE_REQUIREMENT_MISSING", "当前境界或位置不满足战斗前置。"),
            BattleBusyError: ("BATTLE_BUSY", "已有行动或战斗会话，请先完成后再试。"),
            BattleNotReadyError: ("BATTLE_NOT_READY", "服务器自动战斗尚未完成。"),
            OperationConflictError: ("OPERATION_CONFLICT", "这次请求编号已用于不同的任务输入。"),
            RepositoryBusyError: ("PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。"),
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
        return CommandResult(False, "PERSISTENCE_ERROR", "任务簿暂时不可用，请稍后再试。", context.request_id, operation_id or None, retryable=True)

    @staticmethod
    def _data(record) -> dict[str, object]:
        return {
            "quest_key": record.quest_key,
            "component_key": record.component_key,
            "status": record.status,
            "progress": record.progress,
            "reward": record.reward,
            "idempotent_replay": record.already_completed,
        }

    async def get_advanced_quests(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_QUEST_COMMAND", "查看高阶任务无需附加参数。", context.request_id)
        try:
            record = await self.repository.get_advanced_quests(
                platform=context.adapter, platform_user_id=context.user_id
            )
        except Exception as exc:
            return self._error(context, "", exc)
        return CommandResult(
            True,
            "QUEST_STATUS",
            "## 高阶任务\n\n任务进度已按来源 operation 汇总。",
            context.request_id,
            data={"quests": record.quests},
        )

    async def complete_domain_material_commission(self, context: CommandContext) -> CommandResult:
        return await self._simple_action(
            context,
            "quest.domain_material_commission",
            self.repository.complete_domain_material_commission,
            "领域材料委托",
        )

    async def complete_ancient_domain_line(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 1:
            return CommandResult(
                False,
                "INVALID_QUEST_COMMAND",
                "请提供已结算的界隙秘境战斗编号：`完成远古洞天任务 战斗编号`。",
                context.request_id,
            )
        operation_id = self._operation_id(context, "quest.ancient_domain_line")
        try:
            record = await self.repository.complete_ancient_domain_line(
                platform=context.adapter,
                platform_user_id=context.user_id,
                operation_id=operation_id,
                battle_id=context.command_args[0],
            )
        except Exception as exc:
            return self._error(context, operation_id, exc)
        return CommandResult(
            True,
            "QUEST_ACTION_RECORDED",
            f"## 远古洞天任务已核验\n\n- **进度**：{record.progress}\n- **奖励**：已登记界隙秘境胜利证据",
            context.request_id,
            operation_id,
            data=self._data(record),
        )

    async def acquire_void_archive(self, context: CommandContext) -> CommandResult:
        return await self._simple_action(
            context,
            "explore.archive_ruins",
            self.repository.acquire_void_archive,
            "档案遗迹探索",
        )

    async def deliver_void_archive(self, context: CommandContext) -> CommandResult:
        return await self._simple_action(
            context,
            "quest.break_void.deliver_archive",
            self.repository.deliver_void_archive,
            "虚空档案交付",
        )

    async def claim_soul_transformation(self, context: CommandContext) -> CommandResult:
        return await self._claim(
            context,
            "quest.soul_transformation.claim",
            self.repository.claim_soul_transformation_quest,
            "化神许可",
        )

    async def claim_void_refining(self, context: CommandContext) -> CommandResult:
        return await self._claim(
            context,
            "quest.break_void.claim",
            self.repository.claim_void_refining_quest,
            "炼虚许可",
        )

    async def claim_demon_mainline(self, context: CommandContext) -> CommandResult:
        return await self._claim(
            context,
            "quest.demon_main_1.claim",
            self.repository.claim_demon_mainline,
            "魔界主线",
        )

    async def record_dao_union_mainline(self, context: CommandContext) -> CommandResult:
        return await self._simple_action(
            context,
            "quest.dao_union.three_realm_mainline",
            self.repository.record_dao_union_mainline,
            "三界主线资格",
        )

    async def deliver_dao_union_work(self, context: CommandContext) -> CommandResult:
        return await self._simple_action(
            context,
            "quest.dao_union.endgame_work",
            self.repository.deliver_dao_union_work,
            "道途终局作品交付",
        )

    async def start_dao_union_challenge(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_QUEST_COMMAND", "合道挑战不接受技能、目标或伤害参数。", context.request_id)
        operation_id = self._operation_id(context, "quest.dao_union.personal_challenge")
        try:
            started = await self.repository.start_quest_battle(
                platform=context.adapter,
                platform_user_id=context.user_id,
                enemy_key="enemy.cross_realm_sentinel",
                battle_type="pve.dao_union_challenge",
                operation_id=operation_id,
            )
            resolved = await self._run_battle(started.battle_id, started.round_no)
            evidence = None
            if resolved.outcome == "won":
                try:
                    evidence = await self.repository.record_dao_union_challenge(
                        platform=context.adapter,
                        platform_user_id=context.user_id,
                        operation_id=f"{operation_id}:evidence",
                        battle_id=resolved.battle_id,
                    )
                except QuestAlreadyCompletedError:
                    pass
        except Exception as exc:
            return self._error(context, operation_id, exc)
        challenge_progress = evidence.progress if evidence else (
            {"cross_server_challenge": 1} if resolved.outcome == "won" else {}
        )
        return CommandResult(
            True,
            "DAO_UNION_CHALLENGE_SETTLED",
            f"## 合道个人挑战已结算\n\n- **结果**：{'胜利' if resolved.outcome == 'won' else '失败'}\n- **回合**：{resolved.round_no}/20\n- **资格进度**：{challenge_progress.get('cross_server_challenge', 0)}/1",
            context.request_id,
            operation_id,
            data={"battle_id": resolved.battle_id, "outcome": resolved.outcome, "progress": challenge_progress},
        )

    async def claim_dao_union_quest(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_QUEST_COMMAND", "领取合道许可无需附加参数。", context.request_id)
        operation_id = self._operation_id(context, "quest.dao_union.claim")
        try:
            record = await self.repository.claim_dao_union_quest(
                platform=context.adapter, platform_user_id=context.user_id, operation_id=operation_id
            )
        except Exception as exc:
            return self._error(context, operation_id, exc)
        return CommandResult(
            True,
            "QUEST_PERMIT_GRANTED",
            "## 合道许可已获得\n\n资格快照已冻结，可查看合道突破预览。",
            context.request_id,
            operation_id,
            data={
                "quest_key": record.quest_key,
                "status": record.status,
                "progress": record.progress,
                "snapshot": record.snapshot,
                "idempotent_replay": record.already_completed,
            },
        )

    async def complete_dao_origin_task(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 1:
            return CommandResult(False, "INVALID_QUEST_COMMAND", "请指定道源任务：守界、建设或传承。", context.request_id)
        task_key = {
            "守界": "task.dao_origin.guard",
            "task.dao_origin.guard": "task.dao_origin.guard",
            "建设": "task.dao_origin.build",
            "task.dao_origin.build": "task.dao_origin.build",
            "传承": "task.dao_origin.teach",
            "task.dao_origin.teach": "task.dao_origin.teach",
        }.get(context.command_args[0])
        if task_key is None:
            return CommandResult(False, "INVALID_QUEST_COMMAND", "道源任务只能选择守界、建设或传承。", context.request_id)
        operation_id = self._operation_id(context, task_key)
        try:
            record = await self.repository.complete_dao_origin_task(
                platform=context.adapter,
                platform_user_id=context.user_id,
                task_key=task_key,
                operation_id=operation_id,
            )
        except QuestNotCompletedError:
            requirements = {
                "task.dao_origin.guard": "守界需要一场本赛季的合道挑战胜利。",
                "task.dao_origin.build": "建设需要一项本赛季达标并已结算的公共项目。",
                "task.dao_origin.teach": "传承需要一段本赛季已毕业的师徒关系。",
            }
            return CommandResult(
                False,
                "ENDGAME_EVENT_REQUIREMENT_MISSING",
                requirements[task_key],
                context.request_id,
                operation_id,
            )
        except Exception as exc:
            return self._error(context, operation_id, exc)
        return CommandResult(
            True,
            "DAO_ORIGIN_TASK_RECORDED",
            f"## 道源任务已核验\n\n- **任务**：{task_key}\n- **进度**：{record.progress.get('completed', 0)}/3\n- **本次奖励**：{record.reward}",
            context.request_id,
            operation_id,
            data=self._data(record),
        )

    async def start_cross_realm_battle(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_QUEST_COMMAND", "跨界战不接受技能、目标或伤害参数。", context.request_id)
        operation_id = self._operation_id(context, "quest.cross_realm_battle")
        try:
            started = await self.repository.start_quest_battle(
                platform=context.adapter,
                platform_user_id=context.user_id,
                enemy_key="enemy.cross_realm_sentinel",
                battle_type="pve.cross_realm",
                operation_id=operation_id,
            )
            resolved = await self._run_battle(started.battle_id, started.round_no)
            if resolved.outcome == "won":
                await self.repository.record_cross_realm_victory(
                    platform=context.adapter,
                    platform_user_id=context.user_id,
                    operation_id=f"{operation_id}:evidence",
                    battle_id=resolved.battle_id,
                )
        except Exception as exc:
            return self._error(context, operation_id, exc)
        outcome = "胜利" if resolved.outcome == "won" else "失败"
        return CommandResult(
            True,
            "CROSS_REALM_BATTLE_SETTLED",
            f"## 跨界战已结算\n\n- **结果**：{outcome}\n- **回合**：{resolved.round_no}/20\n\n> 只有服务器记录的胜利才会计入化神许可。",
            context.request_id,
            operation_id,
            data={"battle_id": resolved.battle_id, "outcome": resolved.outcome, "reason": resolved.reason},
        )

    async def start_void_wall_trial(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_QUEST_COMMAND", "界壁试炼不接受技能、目标或伤害参数。", context.request_id)
        operation_id = self._operation_id(context, "quest.break_void.trial")
        try:
            started = await self.repository.start_quest_battle(
                platform=context.adapter,
                platform_user_id=context.user_id,
                enemy_key="enemy.boundary_trial_guardian",
                battle_type="pve.void_wall_trial",
                operation_id=operation_id,
            )
            resolved = await self._run_battle(started.battle_id, started.round_no)
            evidence = await self.repository.record_void_wall_trial(
                platform=context.adapter,
                platform_user_id=context.user_id,
                operation_id=f"{operation_id}:evidence",
                battle_id=resolved.battle_id,
                outcome=resolved.outcome,
            )
        except Exception as exc:
            return self._error(context, operation_id, exc)
        outcome = "胜利" if resolved.outcome == "won" else "失败"
        return CommandResult(
            True,
            "VOID_WALL_TRIAL_RECORDED",
            f"## 界壁试炼已记录\n\n- **结果**：{outcome}\n- **参与次数**：{evidence.progress.get(VOID_WALL_TRIAL, 0)}/3\n\n> 失败仍计一次参与，但不会产出虚空档案。",
            context.request_id,
            operation_id,
            data={"battle_id": resolved.battle_id, "outcome": resolved.outcome, "progress": evidence.progress},
        )

    async def _simple_action(self, context, operation_name, handler, label):
        if context.command_args:
            return CommandResult(False, "INVALID_QUEST_COMMAND", f"{label}无需附加参数。", context.request_id)
        operation_id = self._operation_id(context, operation_name)
        try:
            record = await handler(platform=context.adapter, platform_user_id=context.user_id, operation_id=operation_id)
        except Exception as exc:
            return self._error(context, operation_id, exc)
        reward = "、".join(f"{key} ×{value}" for key, value in record.reward.items()) or "无即时奖励"
        return CommandResult(
            True,
            "QUEST_ACTION_RECORDED",
            f"## {label}已记录\n\n- **进度**：{record.progress}\n- **奖励**：{reward}",
            context.request_id,
            operation_id,
            data=self._data(record),
        )

    async def _claim(self, context, operation_name, handler, label):
        if context.command_args:
            return CommandResult(False, "INVALID_QUEST_COMMAND", f"领取{label}无需附加参数。", context.request_id)
        operation_id = self._operation_id(context, operation_name)
        try:
            record = await handler(platform=context.adapter, platform_user_id=context.user_id, operation_id=operation_id)
        except Exception as exc:
            return self._error(context, operation_id, exc)
        return CommandResult(
            True,
            "QUEST_PERMIT_GRANTED",
            f"## {label}已获得\n\n已写入可审计的突破许可；现在可以查看对应突破预览。",
            context.request_id,
            operation_id,
            data={
                "quest_key": record.quest_key,
                "status": record.status,
                "progress": record.progress,
                "snapshot": record.snapshot,
                "idempotent_replay": record.already_completed,
            },
        )

    async def _run_battle(self, battle_id: str, completed_round: int):
        turn = None
        for expected_round in range(completed_round + 1, 21):
            turn = await self.repository.run_battle_turn(battle_id=battle_id, expected_round=expected_round)
            if turn.status not in {"created", "running"}:
                break
        if turn is None or turn.status in {"created", "running"}:
            raise BattleNotReadyError("automatic quest battle did not reach a terminal state")
        return await self.repository.resolve_battle(battle_id=battle_id)


__all__ = ["QuestApplication"]
