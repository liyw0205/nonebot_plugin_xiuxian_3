"""Application services for weekly public projects."""

from __future__ import annotations

from datetime import datetime

from ...contracts import CommandContext, CommandResult
from ..content import bundled_content
from ..persistence.errors import (
    OperationConflictError,
    PlayerNotFoundError,
    PlayerSuspendedError,
    ProjectAlreadyCompleteError,
    ProjectContributionLimitError,
    ProjectContributionRequirementError,
    ProjectContentClosedError,
    ProjectNotFoundError,
    ProjectNotReadyError,
    ProjectSourceAlreadyUsedError,
    RepositoryBusyError,
    ResourceInsufficientError,
)
from ..repository import SQLitePlayerRepository
from .rules import project_definition, project_resource_key


class ProjectApplication:
    """Translate public-project commands into adapter-neutral DTOs."""

    def __init__(self, repository: SQLitePlayerRepository):
        self.repository = repository
        self.content = repository.content or bundled_content()

    @staticmethod
    def _operation_id(context: CommandContext, operation_name: str) -> str:
        if context.operation_id:
            return context.operation_id
        return f"{operation_name}:{context.adapter}:{context.user_id}:{context.message_id or context.request_id}"

    def _project_key(self, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            return project_definition(value, self.content).key
        except ValueError:
            return None

    @staticmethod
    def _service_marker(value: str | None) -> bool:
        return (value or "").strip() in {"服务", "来源", "运输", "净化", "驯养", "修复"}

    @staticmethod
    def _status_label(status: str) -> str:
        return {
            "proposed": "筹备中",
            "funded": "筹备中",
            "building": "修缮中",
            "active": "已建成",
            "maintenance_due": "效用期满",
            "inactive": "已停用",
        }[status]

    async def list_projects(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_PROJECT_COMMAND", "查看公共项目无需附加参数。", context.request_id)
        try:
            projects = await self.repository.list_projects(platform=context.adapter, platform_user_id=context.user_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能查看公共项目。", context.request_id)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, retryable=True)
        data = []
        lines = ["## 本周共建诸事", ""]
        for project in projects:
            requirements = "、".join(
                f"{project.resource_labels[key]} {project.progress.get(key, 0)}/{value}"
                for key, value in project.requirements.items()
            )
            effect_end = (
                f"（持续至 {datetime.fromisoformat(project.effect_ends_at).astimezone().strftime('%Y年%m月%d日 %H:%M')}）"
                if project.effect_ends_at
                else ""
            )
            lines.extend(
                [
                    f"### {project.label}",
                    project.description,
                    f"- **所需物资**：{requirements}",
                    f"- **众修合力**：{project.contribution_points}/{project.target_points}",
                    f"- **进境**：{self._status_label(project.status)}",
                    f"- **成效**：{project.effect_description}{effect_end}",
                    "",
                ]
            )
            data.append(
                {
                    "project_id": project.project_id,
                    "project_key": project.project_key,
                    "label": project.label,
                    "status": project.status,
                    "business_week": project.business_week,
                    "contribution_points": project.contribution_points,
                    "target_points": project.target_points,
                    "progress": project.progress,
                    "requirements": project.requirements,
                    "effect_key": project.effect_key,
                    "effect_ends_at": project.effect_ends_at,
                }
            )
        return CommandResult(True, "PROJECT_LIST", "\n".join(lines).rstrip(), context.request_id, data={"projects": data})

    async def contribute(self, context: CommandContext) -> CommandResult:
        args = context.command_args
        if not args:
            return CommandResult(False, "INVALID_PROJECT_CONTRIBUTION", "请说明贡献数量，或提供已完成事务的结算凭证。", context.request_id)
        project_key: str | None = None
        resource_key: str | None = None
        amount_text: str | None = None
        source_operation_id: str | None = None
        if self._project_key(args[0]) is not None:
            project_key = self._project_key(args[0])
            if len(args) == 2:
                amount_text = args[1]
            elif len(args) == 3:
                if self._service_marker(args[1]):
                    source_operation_id = args[2]
                else:
                    resource_key, amount_text = args[1], args[2]
            else:
                return CommandResult(False, "INVALID_PROJECT_CONTRIBUTION", "贡献参数数量不正确。", context.request_id)
        elif len(args) == 1:
            amount_text = args[0]
        elif len(args) == 2:
            if self._service_marker(args[0]):
                source_operation_id = args[1]
            else:
                resource_key, amount_text = args
        else:
            return CommandResult(False, "INVALID_PROJECT_CONTRIBUTION", "贡献参数数量不正确。", context.request_id)
        if source_operation_id:
            amount = 0
        else:
            try:
                amount = int(amount_text or "")
            except ValueError:
                return CommandResult(False, "INVALID_PROJECT_CONTRIBUTION", "贡献点数必须是正整数。", context.request_id)
        operation_id = self._operation_id(context, "livelihood.contribute_project")
        try:
            record = await self.repository.contribute_project(
                platform=context.adapter,
                platform_user_id=context.user_id,
                project_key=project_key,
                resource_key=project_resource_key(resource_key),
                amount=amount,
                operation_id=operation_id,
                source_operation_id=source_operation_id,
            )
        except ProjectContentClosedError:
            return CommandResult(False, "LIVELIHOOD_CONTENT_CLOSED", "该公共项目暂未开放。", context.request_id, operation_id)
        except ProjectContributionLimitError:
            return CommandResult(False, "PROJECT_CONTRIBUTION_LIMIT", "单次公共项目贡献最多 30 点。", context.request_id, operation_id)
        except ProjectContributionRequirementError:
            return CommandResult(False, "PROJECT_SOURCE_INVALID" if source_operation_id else "PROJECT_RESOURCE_INVALID", "这份结算凭证不符合当前公共项目要求。" if source_operation_id else "该资源不能用于当前公共项目。", context.request_id, operation_id)
        except ProjectSourceAlreadyUsedError:
            return CommandResult(False, "PROJECT_SOURCE_ALREADY_USED", "这份结算凭证已经贡献过公共项目。", context.request_id, operation_id)
        except ProjectAlreadyCompleteError:
            return CommandResult(False, "PROJECT_ALREADY_COMPLETE", "本周公共项目已经完成。", context.request_id, operation_id)
        except ResourceInsufficientError:
            return CommandResult(False, "RESOURCE_INSUFFICIENT", "资源不足，公共项目贡献未发生变化。", context.request_id, operation_id)
        except ProjectNotFoundError:
            return CommandResult(False, "PROJECT_NOT_FOUND", "没有找到本周公共项目。", context.request_id, operation_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能贡献公共项目。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于其他公共项目操作。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        project = record.project
        contribution = (
            "以一份善举"
            if record.service_key
            else f"将**{project.resource_labels[record.resource_key]} ×{record.quantity or record.resource_amount}**投入"
        )
        return CommandResult(
            True,
            "PROJECT_CONTRIBUTED",
            f"## 共建添力\n\n你{contribution}**{project.label}**，添力 **{record.contribution_points} 份**。\n\n- **众修合力**：{project.contribution_points}/{project.target_points}\n- **进境**：{self._status_label(project.status)}",
            context.request_id,
            operation_id,
            data={
                "project_id": project.project_id,
                "project_key": project.project_key,
                "status": project.status,
                "contribution_points": record.contribution_points,
                "project_contribution_points": project.contribution_points,
                "target_points": project.target_points,
                "resource_key": record.resource_key,
                "resource_amount": record.resource_amount,
                "quantity": record.quantity,
                "service_key": record.service_key,
                "source_operation_id": record.source_operation_id,
                "progress": project.progress,
                "idempotent_replay": record.already_completed,
            },
        )

    async def settle(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) > 1:
            return CommandResult(False, "INVALID_PROJECT_COMMAND", "一次只能结算一项公共项目。", context.request_id)
        project_id = context.command_args[0] if context.command_args else None
        operation_id = self._operation_id(context, "livelihood.settle_project")
        try:
            record = await self.repository.settle_project(
                platform=context.adapter,
                platform_user_id=context.user_id,
                project_id=project_id,
                operation_id=operation_id,
            )
        except ProjectNotFoundError:
            return CommandResult(False, "PROJECT_NOT_FOUND", "没有找到本周公共项目。", context.request_id, operation_id)
        except ProjectNotReadyError:
            return CommandResult(False, "PROJECT_NOT_READY", "公共项目尚未完成，暂不能结算奖励。", context.request_id, operation_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能结算公共项目。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于其他公共项目操作。", context.request_id, operation_id)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        if not record.eligible:
            return CommandResult(
                True,
                "PROJECT_SETTLEMENT_INELIGIBLE",
                f"**{record.project.label}**已告功成，你出力尚不足十份，未能领取个人嘉赏。",
                context.request_id,
                operation_id,
                data={"project_id": record.project.project_id, "eligible": False, "rewarded": False, "idempotent_replay": record.already_completed},
            )
        reward = "、".join(
            f"{record.project.reward_labels[key]} {'×' if key.startswith('item.') else '+'}{value}"
            for key, value in record.reward.items()
        ) or "未获得额外赏赐"
        return CommandResult(
            True,
            "PROJECT_SETTLED" if not record.already_completed else "PROJECT_SETTLED",
            f"## 嘉赏已入囊\n\n你为**{record.project.label}**出力有成，所得嘉赏：{reward}。",
            context.request_id,
            operation_id,
            data={
                "project_id": record.project.project_id,
                "eligible": True,
                "rewarded": record.rewarded,
                "reward": record.reward,
                "local_reputation_before": record.local_reputation_before,
                "local_reputation_after": record.local_reputation_after,
                "local_reputation_delta": record.local_reputation_delta,
                "idempotent_replay": record.already_completed,
            },
        )


__all__ = ["ProjectApplication"]
