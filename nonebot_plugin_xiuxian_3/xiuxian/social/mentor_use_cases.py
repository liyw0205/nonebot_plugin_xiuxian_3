"""Application services for the v0.1 mentor relationship slice."""

from __future__ import annotations

from ...contracts import CommandContext, CommandResult
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
            "service_reputation_delta": record.service_reputation_delta,
            "idempotent_replay": record.already_completed,
        }

    @staticmethod
    def _summary(record) -> str:
        return (
            f"- **关系号**：`{record.relation_id}`\n"
            f"- **师傅**：{record.master_dao_name}\n"
            f"- **徒弟**：{record.apprentice_dao_name}\n"
            f"- **状态**：{record.status}\n"
            f"- **邀请截止**：{record.expires_at}"
        )

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
            return CommandResult(False, "INVALID_MENTOR_COMMAND", "请使用 `邀请拜师 用户ID`，也可写成 `适配器:用户ID`。", context.request_id)
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
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于其他师徒操作。", context.request_id, operation_id)
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
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于其他师徒操作。", context.request_id, operation_id)
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
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于其他师徒操作。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return self._persistence_error(context, operation_id)
        return CommandResult(True, "MENTOR_REJECTED", "## 已拒绝拜师邀请\n\n" + self._summary(record), context.request_id, operation_id, data=self._data(record))

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
            return CommandResult(False, "MENTOR_PERMISSION_DENIED", "只有师傅可以为这段关系办理毕业。", context.request_id, operation_id)
        except MentorGraduationNotReadyError:
            return CommandResult(False, "MENTOR_GRADUATION_NOT_READY", "徒弟需完成入道、达到聚气 L3，并完成一次生产或常驻经营服务。", context.request_id, operation_id)
        except MentorStateConflictError:
            return CommandResult(False, "MENTOR_STATE_CONFLICT", "这段师徒关系当前不能毕业。", context.request_id, operation_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "没有找到师徒关系中的角色。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能办理师徒毕业。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于其他师徒操作。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return self._persistence_error(context, operation_id)
        return CommandResult(
            True,
            "MENTOR_GRADUATED",
            (
                "## 徒弟已毕业\n\n"
                + self._summary(record)
                + f"\n\n- **徒弟地方名望**：+{record.apprentice_local_reputation}"
                + f"\n- **师傅贡献**：+{record.master_contribution}"
                + f"\n- **双方服务信誉**：+{record.service_reputation_delta}"
            ),
            context.request_id,
            operation_id,
            data=self._data(record),
        )


__all__ = ["MentorApplication"]
