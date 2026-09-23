"""Application services for weekly public projects."""

from __future__ import annotations

from ...contracts import CommandContext, CommandResult
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
    RepositoryBusyError,
    ResourceInsufficientError,
)
from ..repository import SQLitePlayerRepository
from .rules import project_definition


class ProjectApplication:
    """Translate public-project commands into adapter-neutral DTOs."""

    def __init__(self, repository: SQLitePlayerRepository):
        self.repository = repository

    @staticmethod
    def _operation_id(context: CommandContext, operation_name: str) -> str:
        if context.operation_id:
            return context.operation_id
        return f"{operation_name}:{context.adapter}:{context.user_id}:{context.message_id or context.request_id}"

    @staticmethod
    def _project_key(value: str | None) -> str | None:
        if value is None:
            return None
        try:
            return project_definition(value).key
        except ValueError:
            return None

    @staticmethod
    def _resource_key(value: str | None) -> str | None:
        return {
            "木材": "item.mat.wood",
            "云铁": "item.material.cloud_iron",
            "灵石": "currency.spirit_stone",
            "灵叶": "item.herb.spirit_leaf",
        }.get((value or "").strip(), value)

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
        lines = ["## 本周地方公共项目", ""]
        for project in projects:
            requirements = "、".join(f"{key} ×{value}" for key, value in project.requirements.items())
            lines.extend(
                [
                    f"### {project.label}",
                    f"- **项目键**：`{project.project_key}`",
                    f"- **需求**：{requirements}",
                    f"- **进度**：{project.contribution_points}/{project.target_points} 点",
                    f"- **状态**：{project.status}",
                    f"- **效果**：{project.effect_key}（至 {project.effect_ends_at or '达成后 7 天'}）",
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
            return CommandResult(False, "INVALID_PROJECT_CONTRIBUTION", "可用 `贡献公共项目 <点数>` 或 `贡献公共项目 <项目键> <资源> <点数>`。", context.request_id)
        project_key: str | None = None
        resource_key: str | None = None
        amount_text: str | None = None
        if self._project_key(args[0]) is not None:
            project_key = self._project_key(args[0])
            if len(args) == 2:
                amount_text = args[1]
            elif len(args) == 3:
                resource_key, amount_text = args[1], args[2]
            else:
                return CommandResult(False, "INVALID_PROJECT_CONTRIBUTION", "贡献参数数量不正确。", context.request_id)
        elif len(args) == 1:
            amount_text = args[0]
        elif len(args) == 2:
            resource_key, amount_text = args
        else:
            return CommandResult(False, "INVALID_PROJECT_CONTRIBUTION", "贡献参数数量不正确。", context.request_id)
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
                resource_key=self._resource_key(resource_key),
                amount=amount,
                operation_id=operation_id,
            )
        except ProjectContentClosedError:
            return CommandResult(False, "LIVELIHOOD_CONTENT_CLOSED", "该公共项目暂未开放。", context.request_id, operation_id)
        except ProjectContributionLimitError:
            return CommandResult(False, "PROJECT_CONTRIBUTION_LIMIT", "单次公共项目贡献最多 30 点。", context.request_id, operation_id)
        except ProjectContributionRequirementError:
            return CommandResult(False, "PROJECT_RESOURCE_INVALID", "该资源不能用于当前公共项目。", context.request_id, operation_id)
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
        return CommandResult(
            True,
            "PROJECT_CONTRIBUTED",
            f"## 公共项目贡献完成\n\n已向**{project.label}**贡献 **{record.contribution_points} 点**。\n\n- **资源**：{record.resource_key} ×{record.resource_amount}\n- **项目进度**：{project.contribution_points}/{project.target_points}\n- **状态**：{project.status}",
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
                "progress": project.progress,
                "idempotent_replay": record.already_completed,
            },
        )

    async def settle(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) > 1:
            return CommandResult(False, "INVALID_PROJECT_COMMAND", "结算公共项目最多附加项目 ID。", context.request_id)
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
                f"公共项目已完成，但你的贡献不足 10 点，暂不满足个人奖励条件。\n\n- **项目**：{record.project.label}",
                context.request_id,
                operation_id,
                data={"project_id": record.project.project_id, "eligible": False, "rewarded": False, "idempotent_replay": record.already_completed},
            )
        reward = ", ".join(f"{key} ×{value}" for key, value in record.reward.items()) or "已登记"
        return CommandResult(
            True,
            "PROJECT_SETTLED" if not record.already_completed else "PROJECT_SETTLED",
            f"## 公共项目奖励已结算\n\n- **项目**：{record.project.label}\n- **奖励**：{reward}",
            context.request_id,
            operation_id,
            data={"project_id": record.project.project_id, "eligible": True, "rewarded": record.rewarded, "reward": record.reward, "idempotent_replay": record.already_completed},
        )


__all__ = ["ProjectApplication"]
