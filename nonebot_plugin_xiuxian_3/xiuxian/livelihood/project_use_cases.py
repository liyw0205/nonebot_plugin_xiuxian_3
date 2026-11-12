"""Application services for weekly projects and persistent construction."""

from __future__ import annotations

from datetime import datetime
from dataclasses import asdict
import logging

from ...contracts import CommandAction, CommandContext, CommandResult
from ..utils.text import command_link
from ..content import bundled_content
from ..persistence.errors import (
    OperationConflictError,
    PlayerNotFoundError,
    PlayerSuspendedError,
    ProjectAlreadyCompleteError,
    ProjectContributionLimitError,
    ProjectDailyLimitError,
    ProjectContributionRequirementError,
    ProjectPhaseRequirementError,
    ProjectContentClosedError,
    ProjectNotFoundError,
    ProjectNotReadyError,
    ProjectSourceAlreadyUsedError,
    RepositoryBusyError,
    ResourceInsufficientError,
)
from ..repository import SQLitePlayerRepository
from .rules import project_resource_key, public_project_definitions


logger = logging.getLogger(__name__)


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

    async def _project_key(self, value: str | None) -> str | None:
        if value is None:
            return None
        existing = await self.repository.resolve_project_selector(value)
        if existing is not None:
            return existing
        for row in (self.repository.content or self.content).list("livelihood"):
            if row.get("record_type") == "public_project" and value in {row["key"], row["name"], *row.get("aliases", [])}:
                return row["key"]
        return None

    @staticmethod
    def _phase_lines(stages: list | tuple, progress: dict, service_points: int, labels: dict) -> list[str]:
        lines = []
        for index, stage in enumerate(stages, 1):
            complete = all(progress.get(key, 0) >= value for key, value in stage["requirements"].items()) and service_points >= stage["service_points"]
            lines.extend([f"### 第{index}期 · {stage['name']}（{'已完成' if complete else '待齐备'}）", stage["complete_text"] if complete else stage["scene"]])
            materials = "、".join(f"{labels[key]} {min(progress.get(key, 0), value)}/{value}" for key, value in stage["requirements"].items())
            lines.append(f"累计物资：{materials}；运输劳作：{min(service_points, stage['service_points'])}/{stage['service_points']} 点。")
        return lines

    async def preview_construction(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) > 1:
            return CommandResult(False, "INVALID_PROJECT_COMMAND", "一次查看一项工程，或不附参数查看全部。", context.request_id)
        try:
            definitions = public_project_definitions(self.repository.content or self.content)
            selected = context.command_args[0] if context.command_args else None
            projects = [definition for definition in definitions.values() if definition.cycle == "persistent" and (
                selected is None or selected in {definition.key, definition.label, *definition.aliases}
            )]
            if not projects:
                return CommandResult(False, "PROJECT_NOT_FOUND", "没有找到开放的长期工程。", context.request_id)
        except Exception:
            logger.exception("construction preview failed request=%s command=%s", context.request_id, context.command_args)
            raise
        lines = ["## 山野共建工程", ""]
        data = []
        for project in projects:
            lines.extend([f"## {project.label}", project.description])
            for index, stage in enumerate(project.stages, 1):
                materials = "、".join(f"{project.resource_labels[key]} {value}" for key, value in stage["requirements"].items())
                lines.extend([f"### 第{index}期 · {stage['name']}", stage["scene"], f"累计物资：{materials}；累计运输劳作：{stage['service_points']} 点。"])
            for source in project.sources:
                lines.append(f"{source['item_label']}来源：{source['location_label']} · {command_link(source['source_label'], '开始探索 ' + source['source_label'])}")
            lines.extend([f"成效：{project.effect_description}", "个人累计十点可领一次嘉赏；每日材料与劳作合计最多三十点。",
                command_link("投入物资", f"贡献公共项目 {project.label} 物资 数量") + " · " + command_link("贡献运输", f"贡献公共项目 {project.label} 运输"), ""])
            data.append({"project_key": project.key, "label": project.label, "stages": list(project.stages), "sources": list(project.sources), "effect_value": project.effect_value, "effect_duration_seconds": project.effect_duration_seconds})
        return CommandResult(True, "CONSTRUCTION_PREVIEW", "\n".join(lines), context.request_id, data={"projects": data}, actions=(CommandAction("我的工程", "我的工程", enter=True),))

    async def construction_status(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_PROJECT_COMMAND", "查看我的工程无需附加参数。", context.request_id)
        try:
            projects = await self.repository.construction_status(platform=context.adapter, platform_user_id=context.user_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能查看工程。", context.request_id)
        except Exception:
            logger.exception("construction status failed request=%s user=%s", context.request_id, context.user_id)
            raise
        lines = ["## 共建行程", ""]
        data = []
        for project in projects:
            remaining = "、".join(f"{project.resource_labels[key]} {max(0, value-project.progress.get(key, 0))}" for key, value in project.requirements.items())
            claimable = project.status in {"active", "maintenance_due"} and project.personal_points >= 10 and not project.rewarded
            lines.extend([f"## {project.label} · {self._status_label(project.status)}", project.description,
                f"本人出力：{project.personal_points} 点；今日剩余额度：{max(0, 30-project.daily_points)} 点。",
                f"待备总物资：{remaining}；运输劳作：{project.service_points}/{project.stages[-1]['service_points']} 点。",
                *self._phase_lines(project.stages, project.progress, project.service_points, project.resource_labels),
                f"成效：{project.effect_description}"])
            if project.effect_ends_at:
                lines.append(f"效用截止：{datetime.fromisoformat(project.effect_ends_at).astimezone().strftime('%Y年%m月%d日 %H:%M')}。")
            if claimable:
                lines.append(command_link("领取嘉赏", f"结算公共项目 {project.label}"))
            elif project.rewarded:
                lines.append("个人嘉赏已领取。")
            elif project.personal_points < 10:
                lines.append("个人出力未满十点，尚未取得领奖资格。")
            else:
                lines.append("完工后可领取个人嘉赏。")
            if project.status not in {"active", "maintenance_due", "inactive"}:
                lines.append(command_link("投入物资", f"贡献公共项目 {project.label} 物资 数量") + " · " + command_link("贡献运输", f"贡献公共项目 {project.label} 运输"))
            lines.append("")
            data.append({**asdict(project), "claimable": claimable})
        if not projects:
            lines.append("尚无开工的长期工程。" + command_link("查看工程", "工程预览"))
        return CommandResult(True, "CONSTRUCTION_STATUS", "\n".join(lines), context.request_id, data={"projects": data})

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
        lines.append("> 接收运输劳作的项目可用 `贡献公共项目 项目名 运输` 贡献本人已完成的运输；每份劳作只记一次。")
        return CommandResult(True, "PROJECT_LIST", "\n".join(lines).rstrip(), context.request_id, data={"projects": data})

    async def contribute(self, context: CommandContext) -> CommandResult:
        args = context.command_args
        if not args:
            return CommandResult(False, "INVALID_PROJECT_CONTRIBUTION", "请说明贡献数量，或提供已完成事务的结算凭证。", context.request_id)
        project_key: str | None = None
        resource_key: str | None = None
        amount_text: str | None = None
        source_operation_id: str | None = None
        operation_id = self._operation_id(context, "livelihood.contribute_project")
        try:
            selected = await self._project_key(args[0])
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            logger.exception("project selector failed request=%s operation=%s args=%s", context.request_id, operation_id, args)
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        if selected is not None:
            project_key = selected
            if len(args) == 2:
                if args[1] == "运输":
                    source_operation_id = "最近运输"
                else:
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
        except ProjectDailyLimitError:
            return CommandResult(False, "PROJECT_CONTRIBUTION_LIMIT", "本项目今日剩余贡献额度不足，请明日再来；本次没有扣除资源或使用运输劳作。", context.request_id, operation_id)
        except ProjectContributionLimitError:
            return CommandResult(False, "PROJECT_CONTRIBUTION_LIMIT", "单次公共项目贡献最多 30 点。", context.request_id, operation_id)
        except ProjectPhaseRequirementError as exc:
            message = "本期这项物资已齐备，请先补齐其余物资和运输劳作。" if exc.reason == "phase_material_complete" else "本期运输劳作已齐备，请先补齐物资。"
            if exc.reason == "transport_not_successful":
                message = "只有成功抵达的运输可以计入工程劳作，请完成另一趟运输。"
            return CommandResult(False, "PROJECT_PHASE_REQUIREMENT", f"{exc.subject}：{message}本次没有扣费或使用凭证。", context.request_id, operation_id, data={"reason": exc.reason, "subject": exc.subject})
        except ProjectContributionRequirementError:
            message = "这份结算凭证不符合当前公共项目要求。" if source_operation_id else "该资源不能用于当前公共项目。"
            if source_operation_id == "最近运输":
                message = "没有符合项目要求的已完成运输。请先备货、开始运输并结算运输，再来贡献。"
            return CommandResult(False, "PROJECT_SOURCE_INVALID" if source_operation_id else "PROJECT_RESOURCE_INVALID", message, context.request_id, operation_id)
        except ProjectSourceAlreadyUsedError:
            return CommandResult(False, "PROJECT_SOURCE_ALREADY_USED", "这份结算凭证已经贡献过公共项目。", context.request_id, operation_id)
        except ProjectAlreadyCompleteError:
            return CommandResult(False, "PROJECT_ALREADY_COMPLETE", "公共项目已经完成。", context.request_id, operation_id)
        except ResourceInsufficientError:
            return CommandResult(False, "RESOURCE_INSUFFICIENT", "资源不足，公共项目贡献未发生变化。", context.request_id, operation_id)
        except ProjectNotFoundError:
            return CommandResult(False, "PROJECT_NOT_FOUND", "没有找到本周公共项目。", context.request_id, operation_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能贡献公共项目。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "此事已有安排，请重新起意。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            logger.exception("project contribution failed request=%s operation=%s args=%s", context.request_id, operation_id, context.command_args)
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
            f"## 共建添力\n\n你{contribution}**{project.label}**，添力 **{record.contribution_points} 份**。\n\n- **众修合力**：{project.contribution_points}/{project.target_points}\n- **进境**：{self._status_label(project.status)}" + (
                "\n\n" + "\n".join(self._phase_lines(project.stages, project.progress, project.service_points, project.resource_labels)) if project.stages else ""
            ),
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
                "service_points": project.service_points,
                "stages": project.stages,
                "idempotent_replay": record.already_completed,
            },
        )

    async def settle(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) > 1:
            return CommandResult(False, "INVALID_PROJECT_COMMAND", "一次只能结算一项公共项目。", context.request_id)
        project_id = context.command_args[0] if context.command_args else None
        operation_id = self._operation_id(context, "livelihood.settle_project")
        try:
            if project_id:
                project_id = await self._project_key(project_id) or project_id
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
            return CommandResult(False, "OPERATION_CONFLICT", "此事已有安排，请重新起意。", context.request_id, operation_id)
        except Exception:
            logger.exception("project settlement failed request=%s operation=%s args=%s", context.request_id, operation_id, context.command_args)
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
            for key, value in sorted(record.reward.items())
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
