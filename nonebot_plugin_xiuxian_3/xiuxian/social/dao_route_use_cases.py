"""Application commands for 道统路线议事 (``dao.choose_route`` / ``dao.council_vote``)."""

from __future__ import annotations

from ...contracts import CommandAction, CommandContext, CommandResult
from ..content import ContentBundle, bundled_content
from ..repository import (
    DaoCouncilQuorumError,
    DaoRouteNotDueError,
    DaoRouteLockedError,
    DaoRouteRequirementError,
    DaoVoteAlreadyCastError,
    OperationConflictError,
    PlayerNotFoundError,
    PlayerSuspendedError,
    RepositoryBusyError,
    SQLitePlayerRepository,
)
from ..utils.text import command_link
from .dao_route_content import resolve_dao_route
from .dao_route_rules import dao_route_option_list

STATUS_COMMAND = "道统"
VOTE_COMMAND = "道统投票"
SETTLE_COMMAND = "道统结算"


class DaoRouteApplication:
    """Translate dao-route council commands into adapter-neutral results."""

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
        return f"social.dao_route.{suffix}:{context.adapter}:{context.user_id}:{key}"

    def _status_lines(self, record) -> list[str]:
        lines = ["## 道统议事", ""]
        if not record.sect_id:
            lines.append("> 需先加入一个活跃宗门，宗门等级达到 6 后方可议事。")
            lines.append("")
            lines.append(f"- **本周周期**：{record.cycle_id}")
            return lines

        lines.append(f"- **宗门**：{record.sect_name}（{record.sect_level} 级，公共功勋 {record.sect_merit}）")
        if record.route_label:
            lock = "锁定至 " + record.locked_until if record.locked else "可再议"
            lines.append(f"- **现行道统**：{record.route_label}（{lock}）")
        else:
            lines.append("- **现行道统**：尚未定线")
        lines.append(
            f"- **本周投票**：{record.voter_count}/{record.quorum}"
            f"（周期 {record.cycle_id}）"
        )
        if record.my_vote_label:
            lines.append(f"- **你的选择**：{record.my_vote_label}")
        elif record.eligible:
            lines.append("- **你的选择**：尚未投票")
        else:
            lines.append(f"- **议事资格**：尚缺 {'、'.join(record.missing)}")
        if record.tie_carryover:
            lines.append("- **上轮**：同票，沿用前一道统")
        lines.append("")
        lines.append("**可选道统**")
        for option in record.options:
            lines.append(
                f"- **{option.name}**：{option.description}"
                f"（{option.bonus_key} +{option.bonus_bp} bp）"
            )
        return lines

    async def status(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(
                False, "INVALID_DAO_ROUTE_COMMAND", "道统指令不带参数。", context.request_id
            )
        try:
            record = await self.repository.dao_route_status(
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
        if record.sect_id and record.eligible and record.my_vote_key is None:
            first = record.options[0] if record.options else None
            if first is not None:
                lines.append("")
                lines.append(
                    f"> 点{command_link(VOTE_COMMAND, f'{VOTE_COMMAND} {first.name}')}"
                    f"投下本周的第一票；同一周只能投一次。"
                )
                actions = (CommandAction("投票 守界", f"{VOTE_COMMAND} 守界"),)
        return CommandResult(
            True,
            "DAO_ROUTE_STATUS",
            "\n".join(lines),
            context.request_id,
            data=_data(record),
            actions=actions,
        )

    async def vote(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 1:
            names = "、".join(option.name for option in dao_route_option_list(self._content()))
            return CommandResult(
                False,
                "INVALID_DAO_ROUTE_COMMAND",
                f"用法：道统投票 <{names}>。",
                context.request_id,
            )
        route_key = resolve_dao_route(context.command_args[0], self._content())
        if route_key is None:
            return CommandResult(
                False, "DAO_ROUTE_NOT_FOUND", "没有这条道统路线。", context.request_id
            )
        try:
            record = await self.repository.cast_dao_route_vote(
                platform=context.adapter,
                platform_user_id=context.user_id,
                route_key=route_key,
                operation_id=self._operation_id(context, "vote"),
            )
        except PlayerNotFoundError:
            return CommandResult(
                False, "PLAYER_NOT_FOUND", "尚未登记，先发送“开始修仙”。", context.request_id
            )
        except PlayerSuspendedError:
            return CommandResult(
                False, "PLAYER_SUSPENDED", "当前状态不允许议事。", context.request_id
            )
        except DaoRouteRequirementError:
            return CommandResult(
                False,
                "DAO_ROUTE_REQUIREMENT",
                "议事需合道境界、活跃宗门且宗门等级达到 6。",
                context.request_id,
            )
        except DaoVoteAlreadyCastError:
            return CommandResult(
                False, "DAO_VOTE_ALREADY_CAST", "本周已投过票，下周再议。", context.request_id
            )
        except DaoCouncilQuorumError:
            return CommandResult(
                False,
                "DAO_COUNCIL_QUORUM_MISSING",
                "上周议事不足三票，无法结算。",
                context.request_id,
            )
        except DaoRouteLockedError:
            return CommandResult(
                False, "DAO_ROUTE_LOCKED", "现行道统仍在锁定期内。", context.request_id
            )
        except OperationConflictError:
            return CommandResult(
                False, "LEDGER_CONFLICT", "同一条指令的输入不一致，已拒绝。", context.request_id
            )
        except RepositoryBusyError:
            return CommandResult(
                False, "REPOSITORY_BUSY", "仓储繁忙，请稍后再试。", context.request_id, retryable=True
            )
        lines = [
            "## 道统议事",
            "",
            f"已投下 **{record.route_label}**；本周共 {record.voter_count} 票。",
            "",
            f"> 周日结算后按多数定线，可点{command_link(STATUS_COMMAND, STATUS_COMMAND)}查看进度。",
        ]
        return CommandResult(
            True,
            "DAO_ROUTE_VOTE",
            "\n".join(lines),
            context.request_id,
            data={
                "sect_id": record.sect_id,
                "cycle_id": record.cycle_id,
                "route_key": record.route_key,
                "route_label": record.route_label,
                "voter_count": record.voter_count,
                "already_completed": record.already_completed,
            },
            actions=(CommandAction("查看道统", STATUS_COMMAND),),
        )

    async def settle(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(
                False, "INVALID_DAO_ROUTE_COMMAND", "道统结算不带参数。", context.request_id
            )
        try:
            record = await self.repository.settle_dao_route(
                platform=context.adapter,
                platform_user_id=context.user_id,
                operation_id=self._operation_id(context, "settle"),
            )
        except PlayerNotFoundError:
            return CommandResult(
                False, "PLAYER_NOT_FOUND", "尚未登记，先发送“开始修仙”。", context.request_id
            )
        except DaoRouteRequirementError:
            return CommandResult(
                False, "DAO_ROUTE_REQUIREMENT", "你不在活跃宗门内，无法结算议事。", context.request_id
            )
        except DaoRouteNotDueError:
            return CommandResult(
                False,
                "DAO_ROUTE_NOT_DUE",
                "本周尚未结束，周日之后才能结算议事。",
                context.request_id,
            )
        except DaoCouncilQuorumError:
            return CommandResult(
                False,
                "DAO_COUNCIL_QUORUM_MISSING",
                "本期票数不足。",
                context.request_id,
            )
        except DaoRouteLockedError:
            return CommandResult(
                False, "DAO_ROUTE_LOCKED", "现行道统仍在锁定期内。", context.request_id
            )
        except OperationConflictError:
            return CommandResult(
                False, "LEDGER_CONFLICT", "同一条指令的输入不一致，已拒绝。", context.request_id
            )
        except RepositoryBusyError:
            return CommandResult(
                False, "REPOSITORY_BUSY", "仓储繁忙，请稍后再试。", context.request_id, retryable=True
            )
        if record.quorum_missing:
            return CommandResult(
                False,
                "DAO_COUNCIL_QUORUM_MISSING",
                f"周期 {record.cycle_id} 仅 {record.voter_count} 票，不足三票，本期未定线。",
                context.request_id,
                data={
                    "sect_id": record.sect_id,
                    "cycle_id": record.cycle_id,
                    "voter_count": record.voter_count,
                    "quorum_missing": True,
                },
            )
        if record.route_label is None:
            body = (
                f"周期 {record.cycle_id} 同票且无可沿用的道统，本期未定线；"
                f"共 {record.voter_count} 票。"
            )
        else:
            body = (
                f"周期 {record.cycle_id} 议定 **{record.route_label}**"
                f"（{record.voter_count} 票"
                + ("，同票沿用上周" if record.tie_carryover else "")
                + f"），耗宗门功勋 {record.sect_merit_spent}，道统锁定至 {record.locked_until}。"
            )
        return CommandResult(
            True,
            "DAO_ROUTE_SETTLE",
            "\n".join(["## 道统议事", "", body]),
            context.request_id,
            data={
                "sect_id": record.sect_id,
                "cycle_id": record.cycle_id,
                "route_key": record.route_key,
                "route_label": record.route_label,
                "tie_carryover": record.tie_carryover,
                "voter_count": record.voter_count,
                "sect_merit_spent": record.sect_merit_spent,
                "sect_merit_after": record.sect_merit_after,
                "locked_until": record.locked_until,
                "already_completed": record.already_completed,
            },
            actions=(CommandAction("查看道统", STATUS_COMMAND),),
        )


def _data(record) -> dict[str, object]:
    return {
        "sect_id": record.sect_id,
        "sect_name": record.sect_name,
        "sect_level": record.sect_level,
        "sect_merit": record.sect_merit,
        "route_key": record.route_key,
        "route_label": record.route_label,
        "locked_until": record.locked_until,
        "locked": record.locked,
        "cycle_id": record.cycle_id,
        "cycle_starts_at": record.cycle_starts_at,
        "cycle_ends_at": record.cycle_ends_at,
        "quorum": record.quorum,
        "voter_count": record.voter_count,
        "my_vote_key": record.my_vote_key,
        "eligible": record.eligible,
        "missing": list(record.missing),
        "tie_carryover": record.tie_carryover,
        "options": [option.key for option in record.options],
    }