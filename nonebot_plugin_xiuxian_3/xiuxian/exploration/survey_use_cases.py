"""Shared QQ/OneBot commands for player-owned field discoveries."""

from __future__ import annotations

import logging
import sqlite3

from ...contracts import CommandAction, CommandResult
from ..content import bundled_content
from ..persistence.errors import (
    OperationConflictError, PlayerNotFoundError, PlayerSuspendedError, RepositoryBusyError,
)
from ..utils.text import command_link
from .survey_repository import SurveyRequirementError

logger = logging.getLogger(__name__)


class SurveyApplication:
    def __init__(self, repository):
        self.repository = repository

    def _amounts(self, amounts):
        bundle = self.repository.content or bundled_content()
        return "、".join(f"{({'stamina': '体力', 'energy': '精力'}.get(k) or bundle.label('item', k))} {n}"
                         for k, n in amounts.items()) or "无"

    def _entry(self, site, state, detail):
        bundle = self.repository.content or bundled_content()
        status = {"unknown": "未勘察", "active": "查验中", "resting": "暂离", "completed": "已发现"}[state["status"]]
        lines = [f"**{site['name']} · {status} {state['step']}/{len(site['nodes'])}**"]
        if not detail:
            lines.append(command_link("查看现场与进度", "山野手札 " + site["key"]))
            return lines
        lines.extend([site["desc"],
                      f"所在地：{command_link(bundle.label('location', site['location_key']), '前往 ' + site['location_key'])}；"
                      f"门槛：{bundle.label('realm', site['required_realm'])}{site['required_layer']}层。"])
        if site["prerequisite"]:
            lines.append("需先完成 " + command_link("前一处地貌", "山野手札 " + site["prerequisite"]) + "。")
        if state["status"] == "completed":
            lines.append(site["completion_text"])
            lines.append("首勘奖励已经入袋，不会重复领取。用途：" + "、".join(
                command_link(u["name"], u["command"]) for u in site["uses"]))
            lines.append(command_link("查看下一处山野路线", "山野手札"))
            lines.append(command_link("回访取材与留养", "资源脉预览"))
        elif state["status"] in {"unknown", "resting"}:
            lines.append(command_link("开始查验" if state["status"] == "unknown" else "继续查验", "勘察地貌 " + site["key"]))
        else:
            node = site["nodes"][state["step"]]
            lines.extend([f"**{node['name']}**", node["body"]])
            for choice in node["choices"]:
                lines.append(f"- {command_link(choice['name'], '勘察抉择 ' + site['key'] + ' ' + choice['key'])}："
                             f"{choice['desc']}；耗{self._amounts(choice['costs'])}，"
                             f"查明概率 {choice['success_bp'] // 100}%，下次查验间隔 {choice['seconds']} 秒。")
            lines.append("下次可查验：" + state["ready_at"] + "。" + command_link("收起手札", "暂离勘察 " + site["key"]))
        return lines

    async def execute(self, context, action):
        args = context.command_args
        if (action == "journal" and len(args) > 1 or action in {"start", "rest"} and len(args) != 1
                or action == "choose" and len(args) != 2):
            return CommandResult(False, "INVALID_SURVEY_COMMAND", "请用 `山野手札 [地点]`、`勘察地貌 地点`、"
                                 "`勘察抉择 地点 做法` 或 `暂离勘察 地点`。", context.request_id)
        operation = context.operation_id or f"survey.{action}:{context.adapter}:{context.user_id}:{context.message_id or context.request_id}"
        try:
            payload = await self.repository.survey_command(
                platform=context.adapter, platform_user_id=context.user_id, action=action,
                selector=args[0] if args else "", choice=args[1] if len(args) > 1 else "", operation_id=operation,
            )
        except SurveyRequirementError as exc:
            return CommandResult(False, "SURVEY_REQUIREMENT_MISSING", str(exc) + "\n" + command_link("查看手札", "山野手札")
                                 + " · " + command_link("恢复状态", "恢复状态"), context.request_id, operation)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "本次请求与原来的安排不同，请重新发送。", context.request_id, operation)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "请先开始修仙。", context.request_id, operation)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色不能查验手札。", context.request_id, operation)
        except (ValueError, TypeError, KeyError, sqlite3.Error, RepositoryBusyError):
            logger.exception("survey command failed action=%s operation=%s", action, operation)
            return CommandResult(False, "PERSISTENCE_ERROR", "手札暂未记下本次查验，请稍后以原请求重试；"
                                 "可用山野手札查看已保存进度。", context.request_id, operation, retryable=True)
        actions = ()
        if action == "journal":
            lines = ["**山野手札**", ""]
            for entry in payload["entries"]:
                lines.extend(self._entry(entry["site"], entry["state"], bool(args)))
                lines.append("")
        else:
            site, state = payload["site"], payload["state"]
            lines = [payload["text"], ""]
            if payload["costs"]:
                lines.append("本次消耗：" + self._amounts(payload["costs"]) + "。")
            if payload["reward"]:
                lines.append("首勘所得：" + self._amounts(payload["reward"]) + "。")
            lines.extend(self._entry(site, state, True))
            if state["status"] == "completed":
                actions = (CommandAction("查看制作", site["uses"][0]["command"]),)
            elif state["status"] == "resting":
                actions = (CommandAction("继续勘察", "勘察地貌 " + site["key"]),)
        return CommandResult(True, "SURVEY_JOURNAL" if action == "journal" else "SURVEY_" + action.upper(),
                             "\n".join(lines), context.request_id, operation if action != "journal" else None,
                             data=payload, actions=actions)
