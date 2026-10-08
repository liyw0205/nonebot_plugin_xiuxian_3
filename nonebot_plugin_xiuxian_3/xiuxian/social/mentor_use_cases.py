"""Application services for the mentor relationship slice."""

from __future__ import annotations

from ...contracts import CommandContext, CommandResult
from ..content import ContentError
from ..repository import (
    MentorGraduationNotReadyError,
    MentorInvitationExpiredError,
    MentorInvitationNotFoundError,
    MentorPermissionDeniedError,
    MentorRelationConflictError,
    MentorRequirementError,
    MentorStateConflictError,
    OperationConflictError,
    PlayerNotFoundError,
    PlayerSuspendedError,
    RepositoryBusyError,
    SQLitePlayerRepository,
)


class MentorApplication:
    """Translate mentor relationship transitions into adapter-neutral commands."""

    _STATUS_NAMES = {
        "invited": "待应允",
        "active": "传道授业",
        "graduated": "已出师",
        "rejected": "已谢绝",
        "expired": "邀约已过期",
    }
    _ROLE_NAMES = {"master": "师傅", "apprentice": "徒弟"}

    def __init__(self, repository: SQLitePlayerRepository):
        self.repository = repository

    @staticmethod
    def _operation_id(context: CommandContext, name: str) -> str:
        if context.operation_id:
            return context.operation_id
        request_key = context.message_id or context.request_id
        return f"{name}:{context.adapter}:{context.user_id}:{request_key}"

    @staticmethod
    def _data(record) -> dict[str, object]:
        return {
            "relation_id": record.relation_id,
            "status": record.status,
            "master_player_id": record.master_player_id,
            "master_platform_user_id": record.master_platform_user_id,
            "master_dao_name": record.master_dao_name,
            "apprentice_player_id": record.apprentice_player_id,
            "apprentice_platform_user_id": record.apprentice_platform_user_id,
            "apprentice_dao_name": record.apprentice_dao_name,
            "expires_at": record.expires_at,
            "accepted_at": record.accepted_at,
            "graduated_at": record.graduated_at,
            "master_contribution": record.master_contribution,
            "apprentice_local_reputation": record.apprentice_local_reputation,
            "apprentice_service_reputation_gain": record.apprentice_service_reputation_gain,
            "master_service_reputation_gain": record.master_service_reputation_gain,
            "idempotent_replay": record.already_completed,
        }

    @staticmethod
    def _summary(record) -> str:
        status = MentorApplication._STATUS_NAMES[record.status]
        return (
            f"- **关系号**：`{record.relation_id}`\n"
            f"- **师傅**：{record.master_dao_name}\n"
            f"- **徒弟**：{record.apprentice_dao_name}\n"
            f"- **师承**：{status}\n"
            f"- **邀请截止**：{record.expires_at}"
        )

    @staticmethod
    def _relation_view_data(record) -> dict[str, object]:
        return {
            "relation_id": record.relation_id,
            "role": record.role,
            "counterpart_dao_name": record.counterpart_dao_name,
            "master_dao_name": record.master_dao_name,
            "apprentice_dao_name": record.apprentice_dao_name,
            "status": record.status,
            "invited_at": record.invited_at,
            "expires_at": record.expires_at,
            "accepted_at": record.accepted_at,
            "rejected_at": record.rejected_at,
            "graduated_at": record.graduated_at,
            "master_contribution": record.master_contribution,
        }

    @staticmethod
    def _persistence_error(context: CommandContext, operation_id: str | None = None) -> CommandResult:
        return CommandResult(
            False,
            "PERSISTENCE_ERROR",
            "仙缘簿暂时不可用，请稍后再试。",
            context.request_id,
            operation_id,
            retryable=True,
        )

    async def invite_mentor(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 1:
            return CommandResult(False, "INVALID_MENTOR_COMMAND", "请使用 `邀请拜师 用户ID`。", context.request_id)
        operation_id = self._operation_id(context, "social.invite_mentor")
        try:
            record = await self.repository.invite_mentor(
                platform=context.adapter,
                platform_user_id=context.user_id,
                target_ref=context.command_args[0],
                operation_id=operation_id,
            )
        except MentorRequirementError:
            return CommandResult(False, "MASTER_REQUIREMENT_MISSING", "师傅需达到筑基 L4，徒弟需处于凡人至聚气 L6。", context.request_id, operation_id)
        except MentorRelationConflictError:
            return CommandResult(False, "APPRENTICE_RELATION_CONFLICT", "双方已有师徒关系，或徒弟已有现任师傅。", context.request_id, operation_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "没有找到目标角色。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "目标角色暂时不可建立师徒关系。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "此事已有安排，请重新起意。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return self._persistence_error(context, operation_id)
        return CommandResult(
            True,
            "MENTOR_INVITED",
            "## 拜师邀请已发出\n\n" + self._summary(record),
            context.request_id,
            operation_id,
            data=self._data(record),
        )

    async def accept_mentor(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 1:
            return CommandResult(False, "INVALID_MENTOR_COMMAND", "请使用 `接受拜师 关系号`。", context.request_id)
        operation_id = self._operation_id(context, "social.accept_mentor")
        try:
            record = await self.repository.accept_mentor(
                platform=context.adapter,
                platform_user_id=context.user_id,
                relation_id=context.command_args[0],
                operation_id=operation_id,
            )
        except MentorInvitationExpiredError:
            return CommandResult(False, "MENTOR_INVITATION_EXPIRED", "这份拜师邀请已经过期。", context.request_id, operation_id)
        except MentorInvitationNotFoundError:
            return CommandResult(False, "MENTOR_INVITATION_NOT_FOUND", "没有找到这份拜师邀请。", context.request_id, operation_id)
        except MentorRequirementError:
            return CommandResult(False, "MASTER_REQUIREMENT_MISSING", "当前境界已不满足师徒关系条件。", context.request_id, operation_id)
        except MentorRelationConflictError:
            return CommandResult(False, "APPRENTICE_RELATION_CONFLICT", "你已经有现任师傅。", context.request_id, operation_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能接受拜师。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "此事已有安排，请重新起意。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return self._persistence_error(context, operation_id)
        return CommandResult(True, "MENTOR_ACCEPTED", "## 已拜师\n\n" + self._summary(record), context.request_id, operation_id, data=self._data(record))

    async def reject_mentor(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 1:
            return CommandResult(False, "INVALID_MENTOR_COMMAND", "请使用 `拒绝拜师 关系号`。", context.request_id)
        operation_id = self._operation_id(context, "social.reject_mentor")
        try:
            record = await self.repository.reject_mentor(
                platform=context.adapter,
                platform_user_id=context.user_id,
                relation_id=context.command_args[0],
                operation_id=operation_id,
            )
        except MentorInvitationExpiredError:
            return CommandResult(False, "MENTOR_INVITATION_EXPIRED", "这份拜师邀请已经过期。", context.request_id, operation_id)
        except MentorInvitationNotFoundError:
            return CommandResult(False, "MENTOR_INVITATION_NOT_FOUND", "没有找到这份拜师邀请。", context.request_id, operation_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能处理拜师邀请。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "此事已有安排，请重新起意。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return self._persistence_error(context, operation_id)
        return CommandResult(True, "MENTOR_REJECTED", "## 已拒绝拜师邀请\n\n" + self._summary(record), context.request_id, operation_id, data=self._data(record))

    async def get_mentor_relations(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_MENTOR_COMMAND", "请直接发送 `师徒关系` 查看当前师承。", context.request_id)
        try:
            records = await self.repository.get_mentor_relations(
                platform=context.adapter,
                platform_user_id=context.user_id,
            )
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时无法查看师徒关系。", context.request_id)
        except RepositoryBusyError:
            return self._persistence_error(context)
        except Exception:
            return self._persistence_error(context)
        data = {
            "status": "none" if not records else "ok",
            "count": len(records),
            "relations": [self._relation_view_data(record) for record in records],
        }
        if not records:
            return CommandResult(True, "MENTOR_NONE", "## 师徒关系\n\n暂未结下师徒缘分。", context.request_id, data=data)
        lines = ["## 师徒关系"]
        for record in records:
            lines.extend(
                (
                    "",
                    f"- **关系号**：`{record.relation_id}`",
                    f"- **身份**：{MentorApplication._ROLE_NAMES[record.role]}",
                    f"- **对方**：{record.counterpart_dao_name}",
                    f"- **师承**：{MentorApplication._STATUS_NAMES[record.status]}",
                    f"- **邀请时间**：{record.invited_at}",
                    f"- **邀请截止**：{record.expires_at}",
                )
            )
            if record.accepted_at:
                lines.append(f"- **应允时间**：{record.accepted_at}")
            if record.rejected_at:
                lines.append(f"- **谢绝时间**：{record.rejected_at}")
            if record.graduated_at:
                lines.append(f"- **出师时间**：{record.graduated_at}")
            if record.master_contribution:
                lines.append(f"- **师傅贡献**：{record.master_contribution}")
        return CommandResult(True, "MENTOR_RELATIONS", "\n".join(lines), context.request_id, data=data)

    async def graduate_apprentice(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 1:
            return CommandResult(False, "INVALID_MENTOR_COMMAND", "请使用 `师徒毕业 关系号`。", context.request_id)
        operation_id = self._operation_id(context, "social.graduate_apprentice")
        try:
            record = await self.repository.graduate_apprentice(
                platform=context.adapter,
                platform_user_id=context.user_id,
                relation_id=context.command_args[0],
                operation_id=operation_id,
            )
        except MentorPermissionDeniedError:
            return CommandResult(False, "MENTOR_PERMISSION_DENIED", "须由师傅准许徒弟出师。", context.request_id, operation_id)
        except MentorGraduationNotReadyError:
            return CommandResult(False, "MENTOR_GRADUATION_NOT_READY", "徒弟的修行或历练尚未达到出师要求。", context.request_id, operation_id)
        except MentorStateConflictError:
            return CommandResult(False, "MENTOR_STATE_CONFLICT", "这段师承眼下不能办理出师。", context.request_id, operation_id)
        except ContentError:
            return CommandResult(False, "CONTENT_ERROR", "出师名册暂未备妥，请稍后再来。", context.request_id, operation_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "没有找到师徒关系中的角色。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能办理师徒毕业。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "此事已有安排，请重新起意。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return self._persistence_error(context, operation_id)
        reward_lines = [f"- **师傅贡献**：+{record.master_contribution}"]
        if record.apprentice_local_reputation:
            reward_lines.append(f"- **徒弟地方名望**：+{record.apprentice_local_reputation}")
        if record.apprentice_service_reputation_gain:
            reward_lines.append(f"- **徒弟服务信誉**：+{record.apprentice_service_reputation_gain}")
        if record.master_service_reputation_gain:
            reward_lines.append(f"- **师傅服务信誉**：+{record.master_service_reputation_gain}")
        return CommandResult(
            True,
            "MENTOR_GRADUATED",
            "## 徒弟已出师\n\n" + self._summary(record) + "\n\n" + "\n".join(reward_lines),
            context.request_id,
            operation_id,
            data=self._data(record),
        )


__all__ = ["MentorApplication"]
