"""Application commands for the partner relationship lifecycle."""

from __future__ import annotations

from ...contracts import CommandContext, CommandResult
from ..content import ContentError
from ..persistence.errors import (
    OperationConflictError,
    PartnerBreakCooldownError,
    PartnerDissolutionExpiredError,
    PartnerDissolutionNotFoundError,
    PartnerInvitationExpiredError,
    PartnerInvitationNotFoundError,
    PartnerPermissionDeniedError,
    PartnerRelationConflictError,
    PartnerRequirementError,
    PartnerStateConflictError,
    PlayerNotFoundError,
    PlayerSuspendedError,
    RepositoryBusyError,
)
from ..repository import SQLitePlayerRepository
from .partner_models import PartnerRelationRecord


class PartnerApplication:
    """Translate relationship transitions into adapter-neutral results."""

    def __init__(self, repository: SQLitePlayerRepository):
        self.repository = repository

    @staticmethod
    def _operation_id(context: CommandContext, name: str) -> str:
        if context.operation_id:
            return context.operation_id
        request_key = context.message_id or context.request_id
        return f"{name}:{context.adapter}:{context.user_id}:{request_key}"

    @staticmethod
    def _data(record: PartnerRelationRecord) -> dict[str, object]:
        return {
            "relation_id": record.relation_id,
            "status": record.status,
            "initiator_dao_name": record.initiator_dao_name,
            "invitee_dao_name": record.invitee_dao_name,
            "player_a_dao_name": record.player_a_dao_name,
            "player_b_dao_name": record.player_b_dao_name,
            "invited_at": record.invited_at,
            "invitation_expires_at": record.invitation_expires_at,
            "accepted_at": record.accepted_at,
            "dissolution_requested_by_dao_name": record.dissolution_requested_by_dao_name,
            "dissolution_requested_at": record.dissolution_requested_at,
            "dissolution_expires_at": record.dissolution_expires_at,
            "dissolved_at": record.dissolved_at,
            "cooldown_until": record.cooldown_until,
            "idempotent_replay": record.already_completed,
        }

    @staticmethod
    def _status_text(status: str) -> str:
        return {
            "invited": "待应允",
            "active": "缘契已成",
            "dissolution_pending": "待共议解除",
            "dissolved": "缘契已解",
            "rejected": "已拒绝",
            "expired": "已过期",
        }.get(status, "缘契状态未知")

    @classmethod
    def _summary(cls, record: PartnerRelationRecord) -> str:
        return (
            f"- **关系号**：`{record.relation_id}`\n"
            f"- **道侣**：{record.player_a_dao_name}、{record.player_b_dao_name}\n"
            f"- **缘契**：{cls._status_text(record.status)}"
        )

    @staticmethod
    def _failure(context: CommandContext, code: str, message: str, operation_id: str | None = None, *, retryable: bool = False) -> CommandResult:
        return CommandResult(False, code, message, context.request_id, operation_id, retryable=retryable)

    async def invite_partner(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 1:
            return self._failure(context, "INVALID_PARTNER_COMMAND", "请使用 `邀请结为道侣 道号`。")
        operation_id = self._operation_id(context, "social.invite_partner")
        try:
            record = await self.repository.invite_partner(
                platform=context.adapter,
                platform_user_id=context.user_id,
                target_ref=context.command_args[0],
                operation_id=operation_id,
            )
        except PartnerRequirementError:
            return self._failure(context, "PARTNER_REQUIREMENT_MISSING", "你或对方的修为尚不足以结下道侣缘契。", operation_id)
        except PartnerRelationConflictError:
            return self._failure(context, "PARTNER_RELATION_CONFLICT", "你或对方已有未完的道侣缘契。", operation_id)
        except PartnerBreakCooldownError:
            return self._failure(context, "PARTNER_BREAK_COOLDOWN", "旧缘初解，尚需静候些时日，方可重结缘契。", operation_id)
        except PlayerNotFoundError:
            return self._failure(context, "PLAYER_NOT_FOUND", "没有找到这位道友的道号。", operation_id)
        except PlayerSuspendedError:
            return self._failure(context, "PLAYER_SUSPENDED", "对方当前无法结下道侣缘契。", operation_id)
        except OperationConflictError:
            return self._failure(context, "OPERATION_CONFLICT", "这道缘契请求已对应另一番心意。", operation_id)
        except ContentError:
            return self._failure(context, "CONTENT_ERROR", "此时尚无法缔结缘契，请稍后再试。", operation_id)
        except RepositoryBusyError:
            return self._failure(context, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", operation_id, retryable=True)
        except Exception:
            return self._failure(context, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", operation_id, retryable=True)
        return CommandResult(True, "PARTNER_INVITED", "## 结缘之请已送达\n\n" + self._summary(record), context.request_id, operation_id, data=self._data(record))

    async def accept_partner(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 1:
            return self._failure(context, "INVALID_PARTNER_COMMAND", "请使用 `接受道侣邀请 关系号`。")
        return await self._invitation_transition(context, accept=True)

    async def reject_partner(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 1:
            return self._failure(context, "INVALID_PARTNER_COMMAND", "请使用 `拒绝道侣邀请 关系号`。")
        return await self._invitation_transition(context, accept=False)

    async def _invitation_transition(self, context: CommandContext, *, accept: bool) -> CommandResult:
        operation_name = "social.accept_partner" if accept else "social.reject_partner"
        operation_id = self._operation_id(context, operation_name)
        method = self.repository.accept_partner if accept else self.repository.reject_partner
        try:
            record = await method(
                platform=context.adapter,
                platform_user_id=context.user_id,
                relation_id=context.command_args[0],
                operation_id=operation_id,
            )
        except PartnerInvitationExpiredError:
            return self._failure(context, "PARTNER_INVITATION_EXPIRED", "这份结缘之请已经过期。", operation_id)
        except PartnerInvitationNotFoundError:
            return self._failure(context, "PARTNER_INVITATION_NOT_FOUND", "没有找到这份结缘之请。", operation_id)
        except PartnerRequirementError:
            return self._failure(context, "PARTNER_REQUIREMENT_MISSING", "当前境界已不满足结缘条件。", operation_id)
        except (PlayerNotFoundError, PlayerSuspendedError):
            return self._failure(context, "PLAYER_NOT_FOUND", "当前角色暂时无法应允这份结缘之请。", operation_id)
        except OperationConflictError:
            return self._failure(context, "OPERATION_CONFLICT", "这道缘契请求已对应另一番心意。", operation_id)
        except ContentError:
            return self._failure(context, "CONTENT_ERROR", "仙缘簿暂时无法查阅，请稍后再试。", operation_id)
        except RepositoryBusyError:
            return self._failure(context, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", operation_id, retryable=True)
        except Exception:
            return self._failure(context, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", operation_id, retryable=True)
        code = "PARTNER_ACCEPTED" if accept else "PARTNER_REJECTED"
        title = "道侣缘契已成" if accept else "已拒绝这份结缘之请"
        return CommandResult(True, code, f"## {title}\n\n" + self._summary(record), context.request_id, operation_id, data=self._data(record))

    async def get_partner(self, context: CommandContext) -> CommandResult:
        try:
            record = await self.repository.get_partner(platform=context.adapter, platform_user_id=context.user_id)
        except PlayerNotFoundError:
            return self._failure(context, "PLAYER_NOT_FOUND", "尚未登记角色，请先发送 `开始修仙`。")
        except PlayerSuspendedError:
            return self._failure(context, "PLAYER_SUSPENDED", "当前角色暂时无法查看缘契。")
        except ContentError:
            return self._failure(context, "CONTENT_ERROR", "仙缘簿暂时无法查阅，请稍后再试。")
        except Exception:
            return self._failure(context, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", retryable=True)
        if record is None:
            return CommandResult(True, "PARTNER_NONE", "## 道侣缘契\n\n你尚未结下道侣缘契。", context.request_id, data={"status": "none"})
        return CommandResult(True, "PARTNER_RELATION", "## 道侣缘契\n\n" + self._summary(record), context.request_id, data=self._data(record))

    async def request_dissolution(self, context: CommandContext) -> CommandResult:
        return await self._dissolution_transition(context, "request", "申请解除道侣")

    async def confirm_dissolution(self, context: CommandContext) -> CommandResult:
        return await self._dissolution_transition(context, "confirm", "确认解除道侣")

    async def reject_dissolution(self, context: CommandContext) -> CommandResult:
        return await self._dissolution_transition(context, "reject", "拒绝解除道侣")

    async def _dissolution_transition(self, context: CommandContext, action: str, command_name: str) -> CommandResult:
        if len(context.command_args) != 1:
            return self._failure(context, "INVALID_PARTNER_COMMAND", f"请使用 `{command_name} 关系号`。")
        operation_name = f"social.{action}_partner_dissolution"
        operation_id = self._operation_id(context, operation_name)
        method = {
            "request": self.repository.request_partner_dissolution,
            "confirm": self.repository.confirm_partner_dissolution,
            "reject": self.repository.reject_partner_dissolution,
        }[action]
        try:
            record = await method(
                platform=context.adapter,
                platform_user_id=context.user_id,
                relation_id=context.command_args[0],
                operation_id=operation_id,
            )
        except PartnerDissolutionExpiredError:
            return self._failure(context, "PARTNER_DISSOLUTION_EXPIRED", "解除缘契之议已经过期。", operation_id)
        except PartnerDissolutionNotFoundError:
            return self._failure(context, "PARTNER_DISSOLUTION_NOT_FOUND", "没有找到待处理的解除缘契之议。", operation_id)
        except PartnerPermissionDeniedError:
            return self._failure(context, "PARTNER_PERMISSION_DENIED", "需由另一方应允，方可解除道侣缘契。", operation_id)
        except PartnerStateConflictError:
            return self._failure(context, "PARTNER_STATE_CONFLICT", "这段缘契当前不能办理此事。", operation_id)
        except (PlayerNotFoundError, PlayerSuspendedError):
            return self._failure(context, "PLAYER_NOT_FOUND", "当前角色暂时无法处理缘契。", operation_id)
        except OperationConflictError:
            return self._failure(context, "OPERATION_CONFLICT", "这道缘契请求已对应另一番心意。", operation_id)
        except ContentError:
            return self._failure(context, "CONTENT_ERROR", "仙缘簿暂时无法查阅，请稍后再试。", operation_id)
        except RepositoryBusyError:
            return self._failure(context, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", operation_id, retryable=True)
        except Exception:
            return self._failure(context, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", operation_id, retryable=True)
        titles = {"request": "已请对方共议解除缘契", "confirm": "道侣缘契已解", "reject": "对方拒绝了解除缘契"}
        codes = {"request": "PARTNER_DISSOLUTION_REQUESTED", "confirm": "PARTNER_DISSOLVED", "reject": "PARTNER_DISSOLUTION_REJECTED"}
        return CommandResult(True, codes[action], f"## {titles[action]}\n\n" + self._summary(record), context.request_id, operation_id, data=self._data(record))


__all__ = ["PartnerApplication"]
