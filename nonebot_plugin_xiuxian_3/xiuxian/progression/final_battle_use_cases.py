"""Adapter-neutral use cases for the cooperative ascension battle."""

from __future__ import annotations

from ...contracts import CommandContext, CommandResult
from ..persistence.errors import (
    AscensionRequirementError,
    EndingAlreadyChosenError,
    FinalBattleBusyError,
    FinalBattleCooldownError,
    FinalBattleMemberLimitError,
    FinalBattleNotFoundError,
    FinalBattleNotReadyError,
    FinalBattlePermissionError,
    FinalBattleRequirementError,
    OperationConflictError,
    PlayerNotFoundError,
    PlayerSuspendedError,
    RepositoryBusyError,
)


class FinalBattleApplication:
    def __init__(self, repository):
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
            FinalBattleRequirementError: ("FINAL_BATTLE_REQUIREMENT_MISSING", "发起者须在天劫台满足渡劫 L10、三次试炼、道果/功勋、债务和飞升凭证条件；协助者须在天劫台达到渡劫 L3。"),
            FinalBattleBusyError: ("FINAL_BATTLE_BUSY", "你已有进行中的长行动或已加入其他终局战。"),
            FinalBattleCooldownError: ("FINAL_BATTLE_COOLDOWN", "终局战失败后的七日冷却尚未结束。"),
            FinalBattleMemberLimitError: ("FINAL_BATTLE_MEMBER_LIMIT", "终局战最多容纳一名发起者和四名协助者。"),
            FinalBattleNotFoundError: ("FINAL_BATTLE_NOT_FOUND", "没有找到你可访问的终局战。"),
            FinalBattleNotReadyError: ("FINAL_BATTLE_NOT_READY", "终局战当前状态不能执行此操作。"),
            FinalBattlePermissionError: ("FINAL_BATTLE_PERMISSION_DENIED", "只有发起者能开始、取消或结算终局战。"),
            AscensionRequirementError: ("ASCENSION_REQUIREMENT_MISSING", "留界结局需要先锁定道果；选择失败不会消耗凭证或结束战斗。"),
            EndingAlreadyChosenError: ("ENDING_ALREADY_CHOSEN", "角色结局已经确定，不能更改。"),
            OperationConflictError: ("OPERATION_CONFLICT", "这次操作编号已用于不同的终局战请求。"),
            PlayerNotFoundError: ("PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。"),
            PlayerSuspendedError: ("PLAYER_SUSPENDED", "当前角色暂时不能参加终局战。"),
            RepositoryBusyError: ("PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。"),
        }
        for error_type, (code, message) in errors.items():
            if isinstance(exc, error_type):
                return CommandResult(False, code, message, context.request_id, operation_id, retryable=error_type is RepositoryBusyError)
        return CommandResult(False, "PERSISTENCE_ERROR", "终局战会话暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)

    async def create(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_FINAL_BATTLE_COMMAND", "创建终局战不接收参数。", context.request_id)
        operation_id = self._operation_id(context, "ascension.final_battle.create")
        try:
            record = await self.repository.create_final_battle(platform=context.adapter, platform_user_id=context.user_id, operation_id=operation_id)
        except Exception as exc:
            return self._error(context, operation_id, exc)
        return CommandResult(True, "FINAL_BATTLE_CREATED", f"## 终局战队伍已建立\n\n- **战斗编号**：`{record.battle_id}`\n- **人数**：{len(record.member_player_ids)}/5\n- **凭证**：已托管；失败或取消时返还。\n- **有效期**：至 {record.expires_at}\n\n协助者可发送 `加入终局战 {record.battle_id}`。", context.request_id, operation_id, data={"battle_id": record.battle_id, "status": record.status, "member_count": len(record.member_player_ids), "member_player_ids": record.member_player_ids, "expires_at": record.expires_at, "idempotent_replay": record.already_completed})

    async def join(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 1:
            return CommandResult(False, "INVALID_FINAL_BATTLE_COMMAND", "请使用 `加入终局战 战斗编号`。", context.request_id)
        operation_id = self._operation_id(context, "ascension.final_battle.join")
        try:
            record = await self.repository.join_final_battle(platform=context.adapter, platform_user_id=context.user_id, battle_id=context.command_args[0], operation_id=operation_id)
        except Exception as exc:
            return self._error(context, operation_id, exc)
        return CommandResult(True, "FINAL_BATTLE_JOINED", f"## 已加入终局战\n\n- **战斗编号**：`{record.battle_id}`\n- **队伍人数**：{len(record.member_player_ids)}/5\n- **资产状态**：已锁定至结算。", context.request_id, operation_id, data={"battle_id": record.battle_id, "status": record.status, "member_count": len(record.member_player_ids), "member_player_ids": record.member_player_ids, "idempotent_replay": record.already_completed})

    async def start(self, context: CommandContext, *, recover: bool = False) -> CommandResult:
        if len(context.command_args) > 1:
            return CommandResult(False, "INVALID_FINAL_BATTLE_COMMAND", "终局战操作最多接收一个战斗编号。", context.request_id)
        action = "recover" if recover else "start"
        operation_id = self._operation_id(context, f"ascension.final_battle.{action}")
        try:
            access = await self.repository.final_battle_access(platform=context.adapter, platform_user_id=context.user_id, battle_id=context.command_args[0] if context.command_args else None)
            if not bool(access.get("actor_is_initiator")):
                raise FinalBattlePermissionError("only the initiator can advance the final battle")
            battle_id = str(access["battle_id"])
            status = str(access["status"])
            result = access.get("result", {})
            if status == "expired" and (result.get("reason") == "lobby_timeout" or result.get("outcome") == "cancelled"):
                raise FinalBattleNotReadyError("final battle lobby expired")
            if status == "lobby":
                await self.repository.start_final_battle(platform=context.adapter, platform_user_id=context.user_id, battle_id=battle_id, operation_id=f"{operation_id}:begin")
                status = "running"
            return await self._advance_and_resolve(context, operation_id, battle_id, status, int(access["round_no"]))
        except Exception as exc:
            return self._error(context, operation_id, exc)

    async def _advance_and_resolve(
        self,
        context: CommandContext,
        operation_id: str,
        battle_id: str,
        status: str,
        round_no: int,
    ) -> CommandResult:
        for expected_round in range(round_no + 1, 31):
            if status != "running":
                break
            turn = await self.repository.run_final_battle_turn(battle_id=battle_id, expected_round=expected_round)
            status = str(turn["status"])
            if turn.get("choice_required"):
                return CommandResult(
                    True,
                    "FINAL_BATTLE_CHOICE_REQUIRED",
                    f"## 守界人的诱惑\n\n守界人气血已低于一半。请发起者发送 `选择终局战 继续` 或 `选择终局战 留界`；选择不可更改。\n\n- **战斗编号**：`{battle_id}`\n- **回合**：{turn['round_no']}",
                    context.request_id,
                    operation_id,
                    data={"battle_id": battle_id, "round_no": int(turn["round_no"]), "phase": "temptation"},
                )
        resolved = await self.repository.resolve_final_battle(
            platform=context.adapter,
            platform_user_id=context.user_id,
            battle_id=battle_id,
            operation_id=f"{operation_id}:resolve",
        )
        return self._resolution_result(context, operation_id, resolved)

    @staticmethod
    def _resolution_result(context: CommandContext, operation_id: str, resolved) -> CommandResult:
        victory = resolved.outcome == "won"
        remained = resolved.outcome == "remained"
        title = "守界成功" if victory else ("留界结局" if remained else "终局战失败")
        reward_lines = [f"{player_id}：世界功勋 +{reward.get('world_merit', 0)}" for player_id, reward in resolved.rewards.items() if reward]
        reward_text = "\n".join(reward_lines) if reward_lines else "无协助奖励"
        message = f"## {title}\n\n- **战斗编号**：`{resolved.battle_id}`\n- **回合**：{resolved.round_no}\n- **天劫债**：+{resolved.debt_delta}\n- **协助奖励**：\n{reward_text}"
        message += "\n\n飞升凭证已消耗，可选择结局。" if victory else ("\n\n你已通过 `ascension.choose_ending` 选择留界；飞升凭证已消耗。" if remained else f"\n\n飞升凭证已返还；七日冷却至 {resolved.cooldown_until}。")
        return CommandResult(True, "FINAL_BATTLE_SETTLED", message, context.request_id, operation_id, data={"battle_id": resolved.battle_id, "outcome": resolved.outcome, "round_no": resolved.round_no, "debt_delta": resolved.debt_delta, "cooldown_until": resolved.cooldown_until, "rewards": resolved.rewards, "idempotent_replay": resolved.already_completed})

    @staticmethod
    def _choice(value: str) -> str | None:
        return {"继续": "continue", "continue": "continue", "留界": "remain", "remain": "remain"}.get(value.strip().lower())

    async def choose(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) not in {1, 2}:
            return CommandResult(False, "INVALID_FINAL_BATTLE_COMMAND", "请使用 `选择终局战 <继续|留界> [战斗编号]`。", context.request_id)
        choice = self._choice(context.command_args[0])
        if choice is None:
            return CommandResult(False, "INVALID_FINAL_BATTLE_COMMAND", "选择只能是继续或留界。", context.request_id)
        operation_id = self._operation_id(context, "ascension.final_battle.choice")
        battle_id = context.command_args[1] if len(context.command_args) == 2 else None
        try:
            record = await self.repository.choose_final_battle(
                platform=context.adapter,
                platform_user_id=context.user_id,
                battle_id=battle_id,
                choice=choice,
                operation_id=operation_id,
            )
            if choice == "remain":
                resolved = await self.repository.resolve_final_battle(
                    platform=context.adapter,
                    platform_user_id=context.user_id,
                    battle_id=str(record["battle_id"]),
                    operation_id=f"{operation_id}:resolve",
                )
                return self._resolution_result(context, operation_id, resolved)
            return await self._advance_and_resolve(
                context,
                operation_id,
                str(record["battle_id"]),
                str(record["status"]),
                int(record["round_no"]),
            )
        except Exception as exc:
            return self._error(context, operation_id, exc)

    async def cancel(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) > 1:
            return CommandResult(False, "INVALID_FINAL_BATTLE_COMMAND", "取消终局战最多接收一个战斗编号。", context.request_id)
        operation_id = self._operation_id(context, "ascension.final_battle.cancel")
        try:
            record = await self.repository.cancel_final_battle(platform=context.adapter, platform_user_id=context.user_id, battle_id=context.command_args[0] if context.command_args else None, operation_id=operation_id)
        except Exception as exc:
            return self._error(context, operation_id, exc)
        return CommandResult(True, "FINAL_BATTLE_CANCELLED", f"终局战队伍已取消，托管的飞升凭证已返还。`{record.battle_id}`", context.request_id, operation_id, data={"battle_id": record.battle_id, "status": record.status})

    async def replay(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) > 1:
            return CommandResult(False, "INVALID_FINAL_BATTLE_COMMAND", "终局战回放最多接收一个战斗编号。", context.request_id)
        try:
            record = await self.repository.replay_final_battle(platform=context.adapter, platform_user_id=context.user_id, battle_id=context.command_args[0] if context.command_args else None)
        except Exception as exc:
            return self._error(context, "", exc)
        return CommandResult(True, "FINAL_BATTLE_REPLAY", f"## 终局战回放\n\n- **战斗编号**：`{record.battle_id}`\n- **状态**：{record.status}\n- **结果**：{record.result.get('outcome', '进行中')}\n- **行动数**：{len(record.actions)}", context.request_id, data={"battle_id": record.battle_id, "status": record.status, "snapshot": record.snapshot, "state": record.state, "result": record.result, "actions": list(record.actions)})


__all__ = ["FinalBattleApplication"]
