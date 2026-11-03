"""Application commands for the 留界据点 (``settlement.dao_hall``).

Presentation stays adapter-neutral: Markdown bodies plus one contextual
``CommandAction``.  QQ may render that action as a keyboard, OneBot degrades to
a readable "可发送" hint.
"""

from __future__ import annotations

from ...contracts import CommandAction, CommandContext, CommandResult
from ..content import ContentBundle, bundled_content
from ..repository import (
    DaoHallCapacityError,
    DaoHallMaterialError,
    DaoHallMemberStateError,
    DaoHallNotFoundError,
    DaoHallProjectLockedError,
    DaoHallRebuildingError,
    DaoHallRequirementError,
    OperationConflictError,
    PlayerNotFoundError,
    PlayerSuspendedError,
    RepositoryBusyError,
    SQLitePlayerRepository,
)
from ..utils.text import command_link
from .dao_hall_content import resolve_dao_hall_project
from .dao_hall_rules import dao_hall_project_list

STATUS_COMMAND = "据点"
FOUND_COMMAND = "建立据点"
JOIN_COMMAND = "加入据点"
LEAVE_COMMAND = "退出据点"
BUILD_COMMAND = "建设据点"
MAINTAIN_COMMAND = "维护据点"


class DaoHallApplication:
    """Translate dao hall commands into adapter-neutral results."""

    def __init__(self, repository: SQLitePlayerRepository):
        self.repository = repository

    def _content(self) -> ContentBundle:
        content = getattr(self.repository, "content", None)
        return content if content is not None else bundled_content()

    @staticmethod
    def _operation_id(context: CommandContext, suffix: str) -> str:
        if context.operation_id:
            return context.operation_id
        key = context.message_id or context.request_id
        return f"social.dao_hall.{suffix}:{context.adapter}:{context.user_id}:{key}"

    def _project_name(self, project_key: str) -> str:
        for project in dao_hall_project_list(self._content()):
            if project.key == project_key:
                return project.name
        return project_key

    def _status_lines(self, record) -> list[str]:
        lines = [f"## {record.name}", ""]
        if not record.is_member:
            lines.append(
                "> 唯有选择留界、且攒够世界功勋与灵石的修士，才能开辟据点。"
            )
            lines.append("")
            if record.qualified:
                lines.append("- **准入**：满足")
            else:
                lines.append(f"- **准入**：尚缺 {'、'.join(record.missing)}")
            lines.append(f"- **现有世界功勋**：{record.world_merit}")
            lines.append(f"- **现有灵石**：{record.spirit_stones}")
            lines.append(
                f"- **开辟所需**：世界功勋 {record.founding_cost_world_merit}、"
                f"灵石 {record.founding_cost_spirit_stones}（存入据点库房）"
            )
            return lines

        state = {"active": "运行中", "rebuilding": "重建中"}.get(record.status, record.status)
        lines.append(f"- **状态**：{state}")
        lines.append(f"- **核心成员**：{record.core_members}/{record.core_capacity}")
        lines.append(f"- **库房灵石**：{record.treasury_spirit_stones}")
        lines.append(f"- **已投入世界功勋**：{record.contributed_world_merit}")
        lines.append(f"- **你的身份**：{_role_label(record.role)}")
        lines.append(f"- **下次维护**：{record.next_maintenance_at}（{record.maintenance_due} 灵石）")
        if record.rebuild_ends_at:
            lines.append(f"- **重建完成**：{record.rebuild_ends_at}")
        projects = dao_hall_project_list(self._content())
        if projects:
            lines.append("")
            lines.append("**建设**")
            for project in projects:
                if project.key in record.built_project_keys:
                    status = "已建成"
                elif any(
                    key not in record.built_project_keys
                    for key in project.required_project_keys
                ):
                    status = "前置未成"
                else:
                    status = f"可建设（世界功勋 {project.world_merit}）"
                lines.append(f"- **{project.name}**：{status}")
        return lines

    async def status(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(
                False, "INVALID_DAO_HALL_COMMAND", "据点指令不带参数。", context.request_id
            )
        try:
            record = await self.repository.dao_hall_status(
                platform=context.adapter, platform_user_id=context.user_id
            )
        except PlayerNotFoundError:
            return CommandResult(
                False, "PLAYER_NOT_FOUND", "尚未登记，先发送“开始修仙”。", context.request_id
            )
        except RepositoryBusyError:
            return CommandResult(
                False, "REPOSITORY_BUSY", "仓储繁忙，请稍后再试。", context.request_id, retryable=True
            )
        lines = self._status_lines(record)
        actions: tuple[CommandAction, ...] = ()
        if not record.is_member:
            if record.qualified:
                lines.append("")
                lines.append(
                    f"> 点{command_link(FOUND_COMMAND, FOUND_COMMAND)}即可开辟据点。"
                )
            else:
                lines.append("")
                lines.append("> 先去完成留界结局，并攒够世界功勋与灵石。")
        else:
            lines.append("")
            if record.status == "rebuilding":
                actions = (CommandAction("查看据点", STATUS_COMMAND),)
                lines.append("> 重建期内停止新建设，成员与库房保留，维护不收费。")
            elif _maintenance_due(record):
                actions = (CommandAction(MAINTAIN_COMMAND, MAINTAIN_COMMAND),)
                lines.append(
                    f"> 维护已到期，点“{MAINTAIN_COMMAND}”缴纳 {record.maintenance_due} 灵石。"
                )
            else:
                buildable = [
                    project
                    for project in dao_hall_project_list(self._content())
                    if project.key not in record.built_project_keys
                    and all(
                        key in record.built_project_keys
                        for key in project.required_project_keys
                    )
                ]
                if buildable:
                    lines.append(
                        f"> 可用{command_link('建设据点', f'{BUILD_COMMAND} {buildable[0].name}')}"
                        f"投入世界功勋建设 {buildable[0].name}。"
                    )
        return CommandResult(
            True,
            "DAO_HALL_STATUS",
            "\n".join(lines),
            context.request_id,
            data=_data(record),
            actions=actions,
        )

    async def found(self, context: CommandContext) -> CommandResult:
        return await self._run(
            context,
            "found",
            FOUND_COMMAND,
            lambda: self.repository.found_dao_hall(
                platform=context.adapter,
                platform_user_id=context.user_id,
                operation_id=self._operation_id(context, "found"),
            ),
        )

    async def join(self, context: CommandContext) -> CommandResult:
        return await self._run(
            context,
            "join",
            JOIN_COMMAND,
            lambda: self.repository.join_dao_hall(
                platform=context.adapter,
                platform_user_id=context.user_id,
                operation_id=self._operation_id(context, "join"),
            ),
        )

    async def leave(self, context: CommandContext) -> CommandResult:
        return await self._run(
            context,
            "leave",
            LEAVE_COMMAND,
            lambda: self.repository.leave_dao_hall(
                platform=context.adapter,
                platform_user_id=context.user_id,
                operation_id=self._operation_id(context, "leave"),
            ),
        )

    async def build(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 1:
            return CommandResult(
                False,
                "INVALID_DAO_HALL_COMMAND",
                "用法：建设据点 <项目名>，例如“建设据点 太清殿”。",
                context.request_id,
            )
        project_key = resolve_dao_hall_project(context.command_args[0], self._content())
        if project_key is None:
            return CommandResult(
                False, "DAO_HALL_PROJECT_NOT_FOUND", "没有这项建设。", context.request_id
            )
        return await self._run(
            context,
            "build",
            BUILD_COMMAND,
            lambda: self.repository.build_dao_hall_project(
                platform=context.adapter,
                platform_user_id=context.user_id,
                project_key=project_key,
                operation_id=self._operation_id(context, "build"),
            ),
            project_key=project_key,
        )

    async def maintain(self, context: CommandContext) -> CommandResult:
        return await self._run(
            context,
            "maintain",
            MAINTAIN_COMMAND,
            lambda: self.repository.maintain_dao_hall(
                platform=context.adapter,
                platform_user_id=context.user_id,
                operation_id=self._operation_id(context, "maintain"),
            ),
        )

    async def _run(
        self,
        context: CommandContext,
        action: str,
        label: str,
        call,
        *,
        project_key: str | None = None,
    ) -> CommandResult:
        if context.command_args and action != "build":
            return CommandResult(
                False, "INVALID_DAO_HALL_COMMAND", f"{label}不带参数。", context.request_id
            )
        try:
            record = await call()
        except PlayerNotFoundError:
            return CommandResult(
                False, "PLAYER_NOT_FOUND", "尚未登记，先发送“开始修仙”。", context.request_id
            )
        except PlayerSuspendedError:
            return CommandResult(
                False, "PLAYER_SUSPENDED", "当前状态不允许操作据点。", context.request_id
            )
        except DaoHallRequirementError:
            return CommandResult(
                False,
                "DAO_HALL_REQUIREMENT",
                "开辟据点需要留界结局、2000 世界功勋与 5000 灵石。",
                context.request_id,
            )
        except DaoHallNotFoundError:
            return CommandResult(
                False, "DAO_HALL_NOT_FOUND", "你尚未加入任何据点。", context.request_id
            )
        except DaoHallCapacityError:
            return CommandResult(
                False, "DAO_HALL_CAPACITY", "核心席位已满，先扩建太清殿。", context.request_id
            )
        except DaoHallRebuildingError:
            return CommandResult(
                False, "DAO_HALL_REBUILDING", "据点正在重建，暂不能建设或加入。", context.request_id
            )
        except DaoHallProjectLockedError:
            return CommandResult(
                False, "DAO_HALL_PROJECT_LOCKED", "前置建设尚未完成。", context.request_id
            )
        except DaoHallMaterialError:
            return CommandResult(
                False, "DAO_HALL_MATERIAL_MISSING", "世界功勋或灵石不足。", context.request_id
            )
        except DaoHallMemberStateError as exc:
            return CommandResult(
                False, exc.code, _message(exc), context.request_id
            )
        except OperationConflictError:
            return CommandResult(
                False, "LEDGER_CONFLICT", "同一条指令的输入不一致，已拒绝。", context.request_id
            )
        except RepositoryBusyError:
            return CommandResult(
                False, "REPOSITORY_BUSY", "仓储繁忙，请稍后再试。", context.request_id, retryable=True
            )

        lines = [f"## {record.name if hasattr(record, 'name') else _HALL_NAME}", ""]
        if action == "found":
            lines.append(
                f"据点已开辟：投入世界功勋 {record.world_merit_spent}、"
                f"灵石 {record.spirit_stones_spent}（计入库房）。"
            )
            lines.append(f"- **库房灵石**：{record.treasury_spirit_stones}")
            lines.append(f"- **剩余世界功勋**：{record.world_merit_after}")
            lines.append(f"- **剩余灵石**：{record.spirit_stones_after}")
            lines.append("")
            lines.append(
                f"> 点{command_link('据点', STATUS_COMMAND)}查看成员与建设进度。"
            )
            actions = (CommandAction("查看据点", STATUS_COMMAND),)
        elif action == "join":
            role = record.action.split(":", 1)[1] if ":" in record.action else "guest"
            lines.append(
                "已加入据点，身份为核心成员。"
                if role == "core"
                else "已作为访客加入据点；达成渡劫或留界后可转为核心成员。"
            )
            lines.append(f"- **核心成员**：{record.core_members}/{record.core_capacity}")
            actions = (CommandAction("查看据点", STATUS_COMMAND),)
        elif action == "leave":
            lines.append("已退出据点。")
            actions = (CommandAction("查看据点", STATUS_COMMAND),)
        elif action == "build":
            name = self._project_name(project_key or "")
            lines.append(f"{name} 已建成：投入世界功勋 {record.world_merit_spent}。")
            lines.append(f"- **剩余世界功勋**：{record.world_merit_after}")
            lines.append(f"- **核心席位上限**：{record.core_capacity}")
            actions = (CommandAction("查看据点", STATUS_COMMAND),)
        else:
            if record.spirit_stones_spent:
                lines.append(f"维护已缴纳 {record.spirit_stones_spent} 灵石。")
            else:
                lines.append("重建期内无需维护，已登记本次维护。")
            lines.append(f"- **库房灵石**：{record.treasury_spirit_stones}")
            actions = (CommandAction("查看据点", STATUS_COMMAND),)
        return CommandResult(
            True,
            f"DAO_HALL_{action.upper()}",
            "\n".join(lines),
            context.request_id,
            data={
                "hall_id": record.hall_id,
                "action": record.action,
                "status": record.status,
                "core_members": record.core_members,
                "core_capacity": record.core_capacity,
                "treasury_spirit_stones": record.treasury_spirit_stones,
                "world_merit_spent": record.world_merit_spent,
                "world_merit_after": record.world_merit_after,
                "spirit_stones_spent": record.spirit_stones_spent,
                "spirit_stones_after": record.spirit_stones_after,
                "project_key": record.project_key,
                "already_completed": record.already_completed,
            },
            actions=actions,
        )


_HALL_NAME = "留界据点"


def _role_label(role: str | None) -> str:
    return {"founder": "创始者", "core": "核心成员", "guest": "访客", None: "非成员"}.get(
        role, str(role)
    )


def _message(exc: Exception) -> str:
    text = str(exc).strip()
    return text or "据点指令未能完成。"


def _maintenance_due(record) -> bool:
    return bool(record.next_maintenance_at) and record.status != "rebuilding"


def _data(record) -> dict[str, object]:
    return {
        "hall_id": record.hall_id,
        "name": record.name,
        "status": record.status,
        "core_members": record.core_members,
        "core_capacity": record.core_capacity,
        "treasury_spirit_stones": record.treasury_spirit_stones,
        "contributed_world_merit": record.contributed_world_merit,
        "built_project_keys": list(record.built_project_keys),
        "rebuild_ends_at": record.rebuild_ends_at,
        "next_maintenance_at": record.next_maintenance_at,
        "maintenance_due": record.maintenance_due,
        "world_merit": record.world_merit,
        "spirit_stones": record.spirit_stones,
        "is_member": record.is_member,
        "role": record.role,
        "qualified": record.qualified,
        "missing": list(record.missing),
        "ending_key": record.ending_key,
    }