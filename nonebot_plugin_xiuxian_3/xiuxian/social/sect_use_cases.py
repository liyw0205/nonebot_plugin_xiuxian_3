"""Application services for sect membership."""

from __future__ import annotations

from ...contracts import CommandContext, CommandResult
from ..repository import (
    OperationConflictError,
    PlayerNotFoundError,
    PlayerSuspendedError,
    RepositoryBusyError,
    ResourceInsufficientError,
    SectAlreadyJoinedError,
    SectApplicationExpiredError,
    SectApplicationExistsError,
    SectApplicationNotFoundError,
    SectAssetLockedError,
    SectFullError,
    SectJoinCooldownError,
    SectLeaderCannotLeaveError,
    SectNameInvalidError,
    SectNotFoundError,
    SectPermissionDeniedError,
    SectRequirementError,
    SQLitePlayerRepository,
)
from .sect_rules import role_label


class SectApplication:
    """Translate sect commands into one adapter-neutral application contract."""

    def __init__(self, repository: SQLitePlayerRepository):
        self.repository = repository

    @staticmethod
    def _operation_id(context: CommandContext, operation_name: str) -> str:
        if context.operation_id:
            return context.operation_id
        request_key = context.message_id or context.request_id
        return f"{operation_name}:{context.adapter}:{context.user_id}:{request_key}"

    @staticmethod
    def _parse_create_args(args: tuple[str, ...]) -> tuple[str, str] | None:
        if not args or len(args) > 13:
            return None
        return args[0], " ".join(args[1:])

    @staticmethod
    def _parse_ref_args(args: tuple[str, ...], *, allow_reason: bool = True) -> tuple[str, str] | None:
        if not args or (not allow_reason and len(args) != 1):
            return None
        return args[0], " ".join(args[1:])

    @staticmethod
    def _parse_review_args(args: tuple[str, ...]) -> tuple[str, bool, str] | None:
        if len(args) < 2:
            return None
        action = args[1].strip().lower()
        if action in {"同意", "批准", "通过", "accept", "approve"}:
            approve = True
        elif action in {"拒绝", "驳回", "reject", "deny"}:
            approve = False
        else:
            return None
        return args[0], approve, " ".join(args[2:])

    @staticmethod
    def _display_name(value: str) -> str:
        return value.replace("\\", "\\\\").replace("`", "\\`").replace("*", "\\*").replace("_", "\\_").replace("~", "\\~")

    async def create_sect(self, context: CommandContext) -> CommandResult:
        parsed = self._parse_create_args(context.command_args)
        if parsed is None:
            return CommandResult(False, "INVALID_SECT", "请使用 `创建宗门 宗门名 [宗旨]`。", context.request_id)
        name, motto = parsed
        operation_id = self._operation_id(context, "social.create_sect")
        try:
            record = await self.repository.create_sect(
                platform=context.adapter,
                platform_user_id=context.user_id,
                name=name,
                motto=motto,
                operation_id=operation_id,
            )
        except SectNameInvalidError:
            return CommandResult(False, "INVALID_SECT", "宗门名或宗旨不符合内容规则，或宗门名已被占用。", context.request_id, operation_id)
        except SectRequirementError:
            return CommandResult(False, "SECT_REQUIREMENT_MISSING", "达到筑基后才能创建宗门。", context.request_id, operation_id)
        except SectAlreadyJoinedError:
            return CommandResult(False, "SECT_ALREADY_JOINED", "你已经加入宗门，不能重复创建。", context.request_id, operation_id)
        except SectJoinCooldownError:
            return CommandResult(False, "SECT_JOIN_COOLDOWN", "离开宗门后的冷却尚未结束。", context.request_id, operation_id)
        except ResourceInsufficientError:
            return CommandResult(False, "CURRENCY_INSUFFICIENT", "创建宗门需要灵石 1000。", context.request_id, operation_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能创建宗门。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于其他宗门操作。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        return CommandResult(
            True,
            "SECT_CREATED",
            f"## 宗门创建成功\n\n**{self._display_name(record.name)}**已建立。\n\n- **宗门号**：`{record.sect_id}`\n- **职位**：宗主\n- **成员**：{record.member_count}/{record.max_members}\n- **建设**：{record.construction}\n\n> 创建费已扣除灵石 1000。",
            context.request_id,
            operation_id,
            data={"sect_id": record.sect_id, "name": record.name, "motto": record.motto, "role": record.role, "member_count": record.member_count, "max_members": record.max_members, "spirit_stones": record.spirit_stones, "idempotent_replay": record.already_completed},
        )

    async def apply_sect(self, context: CommandContext) -> CommandResult:
        parsed = self._parse_ref_args(context.command_args)
        if parsed is None:
            return CommandResult(False, "INVALID_SECT", "请使用 `申请入宗 宗门号或宗门名 [申请说明]`。", context.request_id)
        sect_ref, reason = parsed
        operation_id = self._operation_id(context, "social.apply_sect")
        try:
            record = await self.repository.apply_sect(
                platform=context.adapter,
                platform_user_id=context.user_id,
                sect_ref=sect_ref,
                reason=reason,
                operation_id=operation_id,
            )
        except SectNameInvalidError:
            return CommandResult(False, "INVALID_SECT", "申请说明过长。", context.request_id, operation_id)
        except SectNotFoundError:
            return CommandResult(False, "SECT_NOT_FOUND", "没有找到可申请的宗门。", context.request_id, operation_id)
        except SectAlreadyJoinedError:
            return CommandResult(False, "SECT_ALREADY_JOINED", "你已经加入宗门。", context.request_id, operation_id)
        except SectJoinCooldownError:
            return CommandResult(False, "SECT_JOIN_COOLDOWN", "离开宗门后的冷却尚未结束。", context.request_id, operation_id)
        except SectApplicationExistsError:
            return CommandResult(False, "APPLICATION_EXISTS", "你已经向这个宗门提交过申请。", context.request_id, operation_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能申请入宗。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于其他宗门操作。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        return CommandResult(
            True,
            "SECT_APPLICATION_SUBMITTED",
            f"## 入宗申请已提交\n\n你已向 **{self._display_name(record.sect_name)}** 提交申请。\n\n- **申请号**：`{record.application_id}`\n- **有效至**：{record.expires_at}",
            context.request_id,
            operation_id,
            data={"application_id": record.application_id, "sect_id": record.sect_id, "sect_name": record.sect_name, "status": record.status, "expires_at": record.expires_at, "idempotent_replay": record.already_completed},
        )

    async def list_applications(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_SECT", "宗门申请列表无需附加参数。", context.request_id)
        try:
            records = await self.repository.list_sect_applications(platform=context.adapter, platform_user_id=context.user_id)
        except SectPermissionDeniedError:
            return CommandResult(False, "SECT_PERMISSION_DENIED", "只有长老、副宗主或宗主可以审批入宗申请。", context.request_id)
        except SectNotFoundError:
            return CommandResult(False, "SECT_NOT_FOUND", "你当前不在宗门中。", context.request_id)
        except (PlayerNotFoundError, PlayerSuspendedError):
            return CommandResult(False, "PLAYER_NOT_FOUND", "当前角色不存在或暂时不可用。", context.request_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, retryable=True)
        if not records:
            return CommandResult(True, "SECT_APPLICATIONS_EMPTY", "## 入宗申请\n\n当前没有待审批申请。", context.request_id, data={"applications": []})
        lines = ["## 入宗申请", ""]
        data = []
        for record in records:
            lines.append(f"- `{record.application_id}`：{self._display_name(record.applicant_name)}，申请说明：{record.reason or '未填写'}，截止 {record.expires_at}")
            data.append({"application_id": record.application_id, "applicant_name": record.applicant_name, "reason": record.reason, "expires_at": record.expires_at, "status": record.status})
        return CommandResult(True, "SECT_APPLICATIONS", "\n".join(lines), context.request_id, data={"applications": data})

    async def review_application(self, context: CommandContext) -> CommandResult:
        parsed = self._parse_review_args(context.command_args)
        if parsed is None:
            return CommandResult(False, "INVALID_SECT", "请使用 `审批入宗 申请号 同意|拒绝 [原因]`。", context.request_id)
        application_id, approve, review_reason = parsed
        operation_id = self._operation_id(context, "social.review_sect_application")
        try:
            record = await self.repository.review_sect_application(
                platform=context.adapter,
                platform_user_id=context.user_id,
                application_id=application_id,
                approve=approve,
                review_reason=review_reason,
                operation_id=operation_id,
            )
        except SectPermissionDeniedError:
            return CommandResult(False, "SECT_PERMISSION_DENIED", "只有长老、副宗主或宗主可以审批入宗申请。", context.request_id, operation_id)
        except SectApplicationNotFoundError:
            return CommandResult(False, "APPLICATION_NOT_FOUND", "没有找到待审批的入宗申请。", context.request_id, operation_id)
        except SectApplicationExpiredError:
            return CommandResult(False, "APPLICATION_EXPIRED", "这份入宗申请已经过期。", context.request_id, operation_id)
        except SectFullError:
            return CommandResult(False, "SECT_FULL", "宗门成员已满，暂时不能批准申请。", context.request_id, operation_id)
        except SectAlreadyJoinedError:
            return CommandResult(False, "SECT_ALREADY_JOINED", "申请人已经加入其他宗门。", context.request_id, operation_id)
        except SectJoinCooldownError:
            return CommandResult(False, "SECT_JOIN_COOLDOWN", "申请人的离宗冷却尚未结束。", context.request_id, operation_id)
        except SectNotFoundError:
            return CommandResult(False, "SECT_NOT_FOUND", "宗门不存在或已经关闭。", context.request_id, operation_id)
        except SectNameInvalidError:
            return CommandResult(False, "INVALID_SECT", "审批原因过长。", context.request_id, operation_id)
        except (PlayerNotFoundError, PlayerSuspendedError):
            return CommandResult(False, "PLAYER_NOT_FOUND", "当前角色不存在或暂时不可用。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于其他审批输入。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        verb = "已批准" if record.status == "accepted" else "已拒绝"
        return CommandResult(
            True,
            "SECT_APPLICATION_REVIEWED",
            f"## 入宗申请{verb}\n\n- **申请号**：`{record.application_id}`\n- **申请人**：{self._display_name(record.applicant_name)}\n- **宗门**：{self._display_name(record.sect_name)}",
            context.request_id,
            operation_id,
            data={"application_id": record.application_id, "sect_id": record.sect_id, "status": record.status, "review_reason": record.review_reason, "idempotent_replay": record.already_completed},
        )

    async def leave_sect(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_SECT", "离开宗门无需附加参数。", context.request_id)
        operation_id = self._operation_id(context, "social.leave_sect")
        try:
            record = await self.repository.leave_sect(platform=context.adapter, platform_user_id=context.user_id, operation_id=operation_id)
        except SectNotFoundError:
            return CommandResult(False, "SECT_NOT_FOUND", "你当前不在宗门中。", context.request_id, operation_id)
        except SectLeaderCannotLeaveError:
            return CommandResult(False, "SECT_PERMISSION_DENIED", "宗主必须先完成宗主职位交接，不能直接离宗。", context.request_id, operation_id)
        except SectAssetLockedError:
            return CommandResult(False, "SECT_ASSET_LOCKED", "你有进行中的会话或订单，结算后才能离宗。", context.request_id, operation_id)
        except (PlayerNotFoundError, PlayerSuspendedError):
            return CommandResult(False, "PLAYER_NOT_FOUND", "当前角色不存在或暂时不可用。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于其他离宗输入。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        return CommandResult(
            True,
            "SECT_LEFT",
            f"## 已离开宗门\n\n你已离开 **{self._display_name(record.name)}**，24 小时内不能再次加入宗门。",
            context.request_id,
            operation_id,
            data={"sect_id": record.sect_id, "name": record.name, "status": "left", "idempotent_replay": record.already_completed},
        )

    async def get_profile(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) > 1:
            return CommandResult(False, "INVALID_SECT", "请使用 `我的宗门` 或 `宗门信息 宗门号`。", context.request_id)
        sect_ref = context.command_args[0] if context.command_args else None
        try:
            record = await self.repository.get_sect_profile(platform=context.adapter, platform_user_id=context.user_id, sect_ref=sect_ref)
        except SectNotFoundError:
            return CommandResult(False, "SECT_NOT_FOUND", "没有找到宗门，或你当前不在宗门中。", context.request_id)
        except (PlayerNotFoundError, PlayerSuspendedError):
            return CommandResult(False, "PLAYER_NOT_FOUND", "当前角色不存在或暂时不可用。", context.request_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, retryable=True)
        return CommandResult(
            True,
            "SECT_PROFILE",
            f"## {self._display_name(record.name)}\n\n{record.motto or '宗旨未填写'}\n\n- **宗门号**：`{record.sect_id}`\n- **职位**：{role_label(record.role)}\n- **成员**：{record.member_count}/{record.max_members}\n- **建设**：{record.construction}",
            context.request_id,
            data={"sect_id": record.sect_id, "name": record.name, "motto": record.motto, "role": record.role, "member_count": record.member_count, "max_members": record.max_members, "construction": record.construction},
        )


__all__ = ["SectApplication"]
