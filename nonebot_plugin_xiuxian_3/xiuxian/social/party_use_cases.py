"""Application services for the two-player exploration party slice."""

from __future__ import annotations

from ...contracts import CommandContext, CommandResult
from ..repository import (
    OperationConflictError,
    PartyAlreadyMemberError,
    PartyInvitationExpiredError,
    PartyInvitationNotFoundError,
    PartyLocationMismatchError,
    PartyNotFoundError,
    PartyPermissionDeniedError,
    PartyStateConflictError,
    PartyBattleBusyError,
    PartyBattleNotFoundError,
    PartyBattleNotReadyError,
    PartyBattlePermissionError,
    PartyBattleRequirementError,
    BoundaryRealmRequirementError,
    BoundaryRealmResourceError,
    CrossRealmPartyRequirementError,
    FactionReputationInsufficientError,
    PollutionTooHighError,
    SoulExhaustionActiveError,
    SoulPowerInsufficientError,
    PlayerNotFoundError,
    PlayerSuspendedError,
    RepositoryBusyError,
    SQLitePlayerRepository,
)
from .party_rules import (
    PARTY_TYPE_ARENA_TRIO,
    PARTY_TYPE_BEAST_REALM,
    PARTY_TYPE_DEMON_REALM,
    PARTY_TYPE_BOUNDARY_REALM,
    PARTY_TYPE_STANDARD_PVE,
)


class PartyApplication:
    """Translate party state transitions into adapter-neutral commands."""

    def __init__(self, repository: SQLitePlayerRepository):
        self.repository = repository

    @staticmethod
    def _operation_id(context: CommandContext, name: str) -> str:
        if context.operation_id:
            return context.operation_id
        request_key = context.message_id or context.request_id
        return f"{name}:{context.adapter}:{context.user_id}:{request_key}"

    @staticmethod
    def _members_data(record) -> list[dict[str, str | None]]:
        return [
            {
                "player_id": member.player_id,
                "platform_user_id": member.platform_user_id,
                "dao_name": member.dao_name,
                "role": member.role,
                "status": member.status,
                "confirmed_at": member.confirmed_at,
            }
            for member in record.members
        ]

    @classmethod
    def _data(cls, record) -> dict[str, object]:
        return {
            "party_id": record.party_id,
            "party_type": record.party_type,
            "status": record.status,
            "ready": record.ready,
            "leader_player_id": record.leader_player_id,
            "location_key": record.location_key,
            "confirmation_deadline": record.confirmation_deadline,
            "distribution_key": record.distribution_key,
            "members": cls._members_data(record),
            "idempotent_replay": record.already_completed,
        }

    @staticmethod
    def _summary(record) -> str:
        members = "、".join(member.dao_name for member in record.members if member.status in {"active", "invited"}) or "暂无成员"
        state = "已就绪" if record.ready else ("已解散" if record.status == "disbanded" else "等待确认")
        return f"- **队伍号**：`{record.party_id}`\n- **状态**：{state}\n- **地点**：`{record.location_key}`\n- **成员**：{members}\n- **确认截止**：{record.confirmation_deadline}"

    async def create_party(self, context: CommandContext) -> CommandResult:
        return await self._create_party(context, party_type="exploration_pair", title="双人探索队伍", invite_hint="一名同地点道友")

    async def create_arena_party(self, context: CommandContext) -> CommandResult:
        return await self._create_party(context, party_type=PARTY_TYPE_ARENA_TRIO, title="三人竞技队伍", invite_hint="两名同地点道友")

    async def create_boundary_party(self, context: CommandContext) -> CommandResult:
        return await self._create_party(context, party_type=PARTY_TYPE_BOUNDARY_REALM, title="界隙队伍", invite_hint="一至四名同地点、已完成三界主线的元婴道友")

    async def create_demon_party(self, context: CommandContext) -> CommandResult:
        return await self._create_party(context, party_type=PARTY_TYPE_DEMON_REALM, title="魔渊队伍", invite_hint="一至四名同在堕落遗迹的元婴道友")

    async def create_beast_party(self, context: CommandContext) -> CommandResult:
        return await self._create_party(context, party_type=PARTY_TYPE_BEAST_REALM, title="万兽队伍", invite_hint="一至四名同在万兽山的元婴道友")

    async def create_standard_pve_party(self, context: CommandContext) -> CommandResult:
        return await self._create_party(
            context,
            party_type=PARTY_TYPE_STANDARD_PVE,
            title="多人副本队伍",
            invite_hint="三至四名同地点道友",
        )

    async def _create_party(self, context: CommandContext, *, party_type: str, title: str, invite_hint: str) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_PARTY_COMMAND", f"创建{title}无需附加参数。", context.request_id)
        operation_id = self._operation_id(context, "social.create_party")
        try:
            record = await self.repository.create_party(
                platform=context.adapter,
                platform_user_id=context.user_id,
                operation_id=operation_id,
                party_type=party_type,
            )
        except PartyAlreadyMemberError:
            return CommandResult(False, "PARTY_ALREADY_MEMBER", "你已经在队伍或待处理邀请中。", context.request_id, operation_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能创建队伍。", context.request_id, operation_id)
        except PartyLocationMismatchError:
            return CommandResult(False, "PARTY_LOCATION_MISMATCH", "队伍必须在对应副本地点创建。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于其他队伍操作。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        return CommandResult(
            True,
            "PARTY_CREATED",
            f"## {title}已创建\n\n" + self._summary(record) + f"\n\n请邀请{invite_hint}。",
            context.request_id,
            operation_id,
            data=self._data(record),
        )

    async def invite_party(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 1:
            return CommandResult(False, "INVALID_PARTY_COMMAND", "请使用 `邀请入队 用户ID`，也可写成 `适配器:用户ID`。", context.request_id)
        operation_id = self._operation_id(context, "social.invite_party")
        try:
            record = await self.repository.invite_party(
                platform=context.adapter,
                platform_user_id=context.user_id,
                target_ref=context.command_args[0],
                operation_id=operation_id,
            )
        except PartyPermissionDeniedError:
            return CommandResult(False, "PARTY_PERMISSION_DENIED", "只有队长可以邀请成员。", context.request_id, operation_id)
        except PartyLocationMismatchError:
            return CommandResult(False, "PARTY_LOCATION_MISMATCH", "双方必须位于同一地点。", context.request_id, operation_id)
        except PartyAlreadyMemberError:
            return CommandResult(False, "PARTY_ALREADY_MEMBER", "目标已在队伍或其他待处理邀请中。", context.request_id, operation_id)
        except PartyStateConflictError:
            return CommandResult(False, "PARTY_MEMBER_CAP", "队伍已满或不再接受邀请。", context.request_id, operation_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "没有找到目标角色。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "目标角色暂时不可加入队伍。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于其他队伍操作。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        return CommandResult(True, "PARTY_INVITED", "## 已发出入队邀请\n\n" + self._summary(record), context.request_id, operation_id, data=self._data(record))

    async def accept_party(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 1:
            return CommandResult(False, "INVALID_PARTY_COMMAND", "请使用 `接受入队 队伍号`。", context.request_id)
        operation_id = self._operation_id(context, "social.accept_party")
        try:
            record = await self.repository.accept_party(
                platform=context.adapter,
                platform_user_id=context.user_id,
                party_id=context.command_args[0],
                operation_id=operation_id,
            )
        except PartyInvitationExpiredError:
            return CommandResult(False, "PARTY_CONFIRMATION_EXPIRED", "这份入队邀请已经过期。", context.request_id, operation_id)
        except PartyInvitationNotFoundError:
            return CommandResult(False, "PARTY_INVITATION_NOT_FOUND", "没有找到这份入队邀请。", context.request_id, operation_id)
        except PartyLocationMismatchError:
            return CommandResult(False, "PARTY_LOCATION_MISMATCH", "你已不在队伍创建时的地点。", context.request_id, operation_id)
        except PartyAlreadyMemberError:
            return CommandResult(False, "PARTY_ALREADY_MEMBER", "你已经在队伍或其他待处理邀请中。", context.request_id, operation_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能接受邀请。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于其他队伍操作。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        return CommandResult(True, "PARTY_JOINED", "## 已接受入队邀请\n\n" + self._summary(record) + "\n\n请发送 `确认入队 队伍号` 完成双方确认。", context.request_id, operation_id, data=self._data(record))

    async def reject_party(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 1:
            return CommandResult(False, "INVALID_PARTY_COMMAND", "请使用 `拒绝入队 队伍号`。", context.request_id)
        operation_id = self._operation_id(context, "social.reject_party")
        try:
            record = await self.repository.reject_party(
                platform=context.adapter,
                platform_user_id=context.user_id,
                party_id=context.command_args[0],
                operation_id=operation_id,
            )
        except PartyInvitationNotFoundError:
            return CommandResult(False, "PARTY_INVITATION_NOT_FOUND", "没有找到这份入队邀请。", context.request_id, operation_id)
        except PartyInvitationExpiredError:
            return CommandResult(False, "PARTY_CONFIRMATION_EXPIRED", "这份入队邀请已经过期。", context.request_id, operation_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能处理队伍邀请。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于其他队伍操作。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        return CommandResult(True, "PARTY_INVITATION_REJECTED", "## 已拒绝入队邀请\n\n" + self._summary(record), context.request_id, operation_id, data=self._data(record))

    async def confirm_party(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 1:
            return CommandResult(False, "INVALID_PARTY_COMMAND", "请使用 `确认入队 队伍号`。", context.request_id)
        operation_id = self._operation_id(context, "social.confirm_party")
        try:
            record = await self.repository.confirm_party(
                platform=context.adapter,
                platform_user_id=context.user_id,
                party_id=context.command_args[0],
                operation_id=operation_id,
            )
        except PartyNotFoundError:
            return CommandResult(False, "PARTY_NOT_FOUND", "你不在这支队伍中。", context.request_id, operation_id)
        except PartyLocationMismatchError:
            return CommandResult(False, "PARTY_LOCATION_MISMATCH", "所有成员必须位于队伍创建时的地点。", context.request_id, operation_id)
        except PartyStateConflictError:
            return CommandResult(False, "PARTY_STATE_CONFLICT", "当前队伍不能确认。", context.request_id, operation_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能确认队伍。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于其他队伍操作。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        message = "## 队伍已就绪\n\n" if record.ready else "## 队伍确认已记录\n\n"
        if record.ready:
            message += "全体成员已确认；队长可以发起队伍战斗。"
        else:
            message += "等待其他成员确认。"
        return CommandResult(True, "PARTY_READY" if record.ready else "PARTY_CONFIRMED", message + "\n\n" + self._summary(record), context.request_id, operation_id, data=self._data(record))

    @staticmethod
    def _party_battle_error(context: CommandContext, operation_id: str, exc: Exception) -> CommandResult:
        errors = {
            BoundaryRealmRequirementError: ("BATTLE_CROSS_REALM_REQUIREMENT_MISSING", "队伍成员必须满足元婴、三界主线和界隙地点要求。"),
            BoundaryRealmResourceError: ("SOUL_CRYSTAL_INSUFFICIENT", "队伍需要全员 30 体力，并由队长支付 1 枚神魂晶。"),
            CrossRealmPartyRequirementError: ("BATTLE_CROSS_REALM_REQUIREMENT_MISSING", "队伍成员未满足该跨界副本的地点、资格或体力要求。"),
            FactionReputationInsufficientError: ("BATTLE_CROSS_REALM_REQUIREMENT_MISSING", "队伍成员的对应阵营声望不足。"),
            PollutionTooHighError: ("POLLUTION_TOO_HIGH", "队伍成员污染过高，不能进入魔渊副本。"),
            SoulExhaustionActiveError: ("SOUL_EXHAUSTION_ACTIVE", "队伍成员的神魂疲劳尚未结束，暂时不能进入跨界副本。"),
            SoulPowerInsufficientError: ("BATTLE_SOUL_POWER_INSUFFICIENT", "队伍成员神魂不足，暂时不能进入跨界副本。"),
            PartyBattlePermissionError: ("PARTY_BATTLE_PERMISSION_DENIED", "只有队长可以发起队伍战斗，已确认成员可以结算。"),
            PartyBattleRequirementError: ("PARTY_BATTLE_REQUIREMENT_MISSING", "队伍必须在支持的地点完成双方确认。"),
            PartyBattleBusyError: ("PARTY_BATTLE_BUSY", "队伍或成员已有锁定中的战斗资产。"),
            PartyBattleNotFoundError: ("PARTY_BATTLE_NOT_FOUND", "当前没有可查看的队伍战斗。"),
            PartyBattleNotReadyError: ("PARTY_BATTLE_NOT_READY", "队伍战斗仍在由服务器自动推进。"),
            PartyNotFoundError: ("PARTY_NOT_FOUND", "当前没有可用的队伍。"),
            OperationConflictError: ("OPERATION_CONFLICT", "这次请求编号已用于不同的队伍战斗操作。"),
            PlayerNotFoundError: ("PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。"),
            PlayerSuspendedError: ("PLAYER_SUSPENDED", "当前角色暂时不能进行队伍战斗。"),
            RepositoryBusyError: ("PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。"),
        }
        for error_type, (code, message) in errors.items():
            if isinstance(exc, error_type):
                return CommandResult(False, code, message, context.request_id, operation_id, retryable=error_type is RepositoryBusyError)
        return CommandResult(False, "PERSISTENCE_ERROR", "队伍战斗会话暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)

    async def start_party_battle(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) > 1:
            return CommandResult(False, "INVALID_PARTY_BATTLE_COMMAND", "开始队伍战斗最多接收一个队伍号。", context.request_id)
        operation_id = self._operation_id(context, "battle.party.start")
        party_id = context.command_args[0] if context.command_args else None
        try:
            started = await self.repository.start_party_battle(
                platform=context.adapter,
                platform_user_id=context.user_id,
                party_id=party_id,
                operation_id=operation_id,
            )
            resolved = await self.repository.settle_party_battle(
                platform=context.adapter,
                platform_user_id=context.user_id,
                battle_id=started.battle_id,
                operation_id=f"{operation_id}:settle",
            )
        except Exception as exc:
            return self._party_battle_error(context, operation_id, exc)
        return self._party_battle_result(context, operation_id, resolved)

    async def settle_party_battle(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) > 1:
            return CommandResult(False, "INVALID_PARTY_BATTLE_COMMAND", "结算队伍战斗最多接收一个战斗编号。", context.request_id)
        operation_id = self._operation_id(context, "battle.party.settle")
        try:
            resolved = await self.repository.settle_party_battle(
                platform=context.adapter,
                platform_user_id=context.user_id,
                battle_id=context.command_args[0] if context.command_args else None,
                operation_id=operation_id,
            )
        except Exception as exc:
            return self._party_battle_error(context, operation_id, exc)
        return self._party_battle_result(context, operation_id, resolved)

    @staticmethod
    def _party_battle_result(context: CommandContext, operation_id: str, record) -> CommandResult:
        outcome = "胜利" if record.outcome == "won" else ("失败" if record.outcome == "lost" else "超时")
        rewards = next(iter(record.rewards.values()), {})
        reward_text = "、".join(
            (
                f"修为 +{value}"
                if key == "cultivation"
                else f"灵石 ×{value}"
                if key == "spirit_stones"
                else f"{key} ×{value}"
            )
            for key, value in rewards.items()
        ) or "无"
        return CommandResult(
            True,
            "PARTY_BATTLE_SETTLED",
            f"## 队伍战斗结束\n\n- **结果**：{outcome}\n- **回合**：{record.round_no}\n- **每名成员奖励**：{reward_text}\n\n> 服务端已保存全体成员快照与行动回放。",
            context.request_id,
            operation_id,
            data={
                "battle_id": record.battle_id,
                "party_id": record.party_id,
                "enemy_key": record.enemy_key,
                "outcome": record.outcome,
                "round_no": record.round_no,
                "rewards": record.rewards,
                "contributions": record.contributions,
                "reward_order": list(record.reward_order),
                "reward_rolls": record.reward_rolls,
                "idempotent_replay": record.already_completed,
            },
        )

    async def replay_party_battle(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) > 1:
            return CommandResult(False, "INVALID_PARTY_BATTLE_COMMAND", "队伍战斗回放最多接收一个战斗编号。", context.request_id)
        try:
            record = await self.repository.replay_party_battle(
                platform=context.adapter,
                platform_user_id=context.user_id,
                battle_id=context.command_args[0] if context.command_args else None,
            )
        except Exception as exc:
            return self._party_battle_error(context, "", exc)
        enemy = record.snapshot.get("enemy", {})
        return CommandResult(
            True,
            "PARTY_BATTLE_REPLAY",
            f"## 队伍战斗回放\n\n- **战斗**：`{record.battle_id}`\n- **敌人**：{enemy.get('label', record.enemy_key)}\n- **结果**：{record.result.get('outcome', '进行中')}\n- **行动数**：{len(record.actions)}",
            context.request_id,
            data={"battle_id": record.battle_id, "party_id": record.party_id, "enemy_key": record.enemy_key, "result": record.result, "actions": list(record.actions)},
        )

    async def leave_party(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_PARTY_COMMAND", "退出队伍无需附加参数。", context.request_id)
        operation_id = self._operation_id(context, "social.leave_party")
        try:
            record = await self.repository.leave_party(
                platform=context.adapter,
                platform_user_id=context.user_id,
                operation_id=operation_id,
            )
        except PartyNotFoundError:
            return CommandResult(False, "PARTY_NOT_FOUND", "你当前不在可退出的队伍中。", context.request_id, operation_id)
        except PartyStateConflictError:
            return CommandResult(False, "PARTY_STATE_CONFLICT", "队伍战斗进行中，结算前不能退出队伍。", context.request_id, operation_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能退出队伍。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于其他队伍操作。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        return CommandResult(True, "PARTY_LEFT", "## 已退出队伍\n\n" + self._summary(record), context.request_id, operation_id, data=self._data(record))

    async def get_party(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_PARTY_COMMAND", "我的队伍无需附加参数。", context.request_id)
        try:
            record = await self.repository.get_party(platform=context.adapter, platform_user_id=context.user_id)
        except PartyNotFoundError:
            return CommandResult(False, "PARTY_NOT_FOUND", "你当前没有队伍或待处理邀请。", context.request_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能查看队伍。", context.request_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, retryable=True)
        return CommandResult(True, "PARTY_PROFILE", "## 我的队伍\n\n" + self._summary(record), context.request_id, data=self._data(record))


__all__ = ["PartyApplication"]
