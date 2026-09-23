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
    PlayerNotFoundError,
    PlayerSuspendedError,
    RepositoryBusyError,
    SQLitePlayerRepository,
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
        if context.command_args:
            return CommandResult(False, "INVALID_PARTY_COMMAND", "创建双人队伍无需附加参数。", context.request_id)
        operation_id = self._operation_id(context, "social.create_party")
        try:
            record = await self.repository.create_party(
                platform=context.adapter,
                platform_user_id=context.user_id,
                operation_id=operation_id,
            )
        except PartyAlreadyMemberError:
            return CommandResult(False, "PARTY_ALREADY_MEMBER", "你已经在队伍或待处理邀请中。", context.request_id, operation_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能创建队伍。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于其他队伍操作。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        return CommandResult(
            True,
            "PARTY_CREATED",
            "## 双人探索队伍已创建\n\n" + self._summary(record) + "\n\n请邀请一名同地点道友。",
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
            message += "双方已确认；当前版本只开放队伍状态，探索与战斗运行时仍未开放。"
        else:
            message += "等待另一名成员确认。"
        return CommandResult(True, "PARTY_READY" if record.ready else "PARTY_CONFIRMED", message + "\n\n" + self._summary(record), context.request_id, operation_id, data=self._data(record))

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
