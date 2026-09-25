"""Management application boundary for cross-server social recovery drills."""

from __future__ import annotations

from ...contracts import CommandContext, CommandResult
from .sect_social_recovery_models import SocialRecoveryArtifact, SocialRecoveryReport


class SectSocialRecoveryApplication:
    """Expose recovery only to explicitly authorized operations identities."""

    _CAPABILITIES = frozenset({"social.recovery", "ops.recovery"})

    def __init__(self, repository):
        self.repository = repository

    @classmethod
    def _authorized(cls, context: CommandContext) -> bool:
        return bool(cls._CAPABILITIES.intersection(context.capabilities))

    @staticmethod
    def _operation_id(context: CommandContext, name: str) -> str:
        return context.operation_id or f"{name}:{context.adapter}:{context.user_id}:{context.request_id}"

    @staticmethod
    def _error(context: CommandContext, operation_id: str, exc: Exception) -> CommandResult:
        if isinstance(exc, FileNotFoundError):
            code, message = "SOCIAL_RECOVERY_NOT_FOUND", "跨服社交备份工件不存在。"
        elif isinstance(exc, ValueError):
            code, message = "INVALID_SOCIAL_RECOVERY", str(exc)
        else:
            code, message = "SOCIAL_RECOVERY_FAILED", "跨服社交恢复操作失败，请查看审计记录。"
        return CommandResult(False, code, message, context.request_id, operation_id)

    @staticmethod
    def _artifact_data(artifact: SocialRecoveryArtifact) -> dict[str, object]:
        return artifact.as_dict()

    @staticmethod
    def _report_data(report: SocialRecoveryReport) -> dict[str, object]:
        return report.as_dict()

    async def create(self, context: CommandContext) -> CommandResult:
        operation_id = self._operation_id(context, "social-backup")
        if not self._authorized(context):
            return CommandResult(False, "SOCIAL_RECOVERY_PERMISSION_DENIED", "当前身份没有跨服社交恢复权限。", context.request_id, operation_id)
        if len(context.command_args) != 1:
            return CommandResult(False, "INVALID_SOCIAL_RECOVERY_COMMAND", "用法：创建跨服社交备份 <工件键>。", context.request_id, operation_id)
        try:
            artifact = await self.repository.create_social_recovery_backup(
                artifact_key=context.command_args[0],
                request_id=context.request_id,
                operation_id=operation_id,
            )
        except Exception as exc:
            return self._error(context, operation_id, exc)
        return CommandResult(True, "SOCIAL_RECOVERY_BACKUP_CREATED", "跨服社交备份已创建。", context.request_id, operation_id, data=self._artifact_data(artifact))

    async def verify(self, context: CommandContext) -> CommandResult:
        operation_id = self._operation_id(context, "social-verify")
        if not self._authorized(context):
            return CommandResult(False, "SOCIAL_RECOVERY_PERMISSION_DENIED", "当前身份没有跨服社交恢复权限。", context.request_id, operation_id)
        if len(context.command_args) != 1:
            return CommandResult(False, "INVALID_SOCIAL_RECOVERY_COMMAND", "用法：校验跨服社交备份 <工件键>。", context.request_id, operation_id)
        try:
            artifact = await self.repository.verify_social_recovery_backup(artifact_key=context.command_args[0])
        except Exception as exc:
            return self._error(context, operation_id, exc)
        return CommandResult(True, "SOCIAL_RECOVERY_BACKUP_VERIFIED", "跨服社交备份校验通过。", context.request_id, operation_id, data=self._artifact_data(artifact))

    async def restore(self, context: CommandContext) -> CommandResult:
        operation_id = self._operation_id(context, "social-restore")
        if not self._authorized(context):
            return CommandResult(False, "SOCIAL_RECOVERY_PERMISSION_DENIED", "当前身份没有跨服社交恢复权限。", context.request_id, operation_id)
        if len(context.command_args) != 1:
            return CommandResult(False, "INVALID_SOCIAL_RECOVERY_COMMAND", "用法：恢复跨服社交备份 <工件键>。", context.request_id, operation_id)
        try:
            report = await self.repository.restore_social_recovery_backup(
                artifact_key=context.command_args[0],
                request_id=context.request_id,
                operation_id=operation_id,
            )
        except Exception as exc:
            return self._error(context, operation_id, exc)
        code = "SOCIAL_RECOVERY_RESTORED" if report.status == "active" else "SOCIAL_RECOVERY_FAILED"
        return CommandResult(report.status == "active", code, "跨服社交备份已恢复。" if report.status == "active" else "跨服社交备份恢复失败。", context.request_id, operation_id, data=self._report_data(report))


__all__ = ["SectSocialRecoveryApplication"]
