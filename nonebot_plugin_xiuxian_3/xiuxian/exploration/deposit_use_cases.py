"""Shared field extraction and upkeep commands with actionable stock previews."""

from __future__ import annotations

import logging
import sqlite3

from ...contracts import CommandAction, CommandResult
from ..content import bundled_content
from ..persistence.errors import OperationConflictError, PlayerNotFoundError, PlayerSuspendedError, RepositoryBusyError
from ..utils.text import command_link
from .survey_repository import SurveyRequirementError

logger = logging.getLogger(__name__)


class DepositApplication:
    def __init__(self, repository):
        self.repository = repository

    def _amounts(self, amounts):
        bundle = self.repository.content or bundled_content()
        return "、".join(f"{({'stamina': '体力', 'energy': '精力'}.get(k) or bundle.label('item', k))} {n}"
                         for k, n in amounts.items()) or "无"

    def _entry(self, entry, detail):
        frozen, state = entry["snapshot"], entry["state"]
        definition = frozen["definition"]
        unlocked, opened = entry.get("unlocked", True), entry.get("opened", True)
        lines = [f"**{definition['name']} · " + (f"储量 {state['stock']}/{definition['capacity']}" if unlocked else "尚未查明") + "**"]
        if not detail:
            lines.append(command_link("查看取材与恢复", "资源脉预览 " + definition["key"]))
            return lines
        site = frozen["site"] or (self.repository.content or bundled_content()).require("survey", definition["survey_key"])
        lines.extend([definition["desc"], command_link("查看地貌勘察", "山野手札 " + definition["survey_key"]) + " · "
                      + command_link("前往现场", "前往 " + site["location_key"]),
                      f"每 {definition['regen_seconds'] // 60} 分钟自然恢复 {definition['regen_units']} 格，最多 {definition['capacity']} 格；"
                      f"下次恢复 {state['regenerates_at']}。下次可操作 {state['ready_at']}。"])
        if not unlocked:
            lines.append("先完成此处地貌勘察，才能确认并取用资源脉。")
            return lines
        if not opened:
            lines.append("此处暂不开放新取材，旧回执保留。")
            return lines
        for plan in definition["plans"]:
            lines.append(f"- {command_link(plan['name'], '取用资源脉 ' + definition['key'] + ' ' + plan['key'])}：{plan['desc']}；"
                         f"耗储量 {plan['stock_cost']} 格、{self._amounts(plan['costs'])}，得{self._amounts(plan['rewards'])}；"
                         f"间隔 {plan['cooldown_seconds'] // 60} 分钟，恢复至少推迟到取材后 {plan['recovery_delay'] // 60} 分钟。")
        maintenance = definition["maintenance"]
        lines.append(command_link("养护资源脉", "养护资源脉 " + definition["key"]) + "：耗" + self._amounts(maintenance["costs"])
                     + f"，补回至多 {maintenance['restore_units']} 格；每日 {maintenance['daily_limit']} 次，"
                     + f"今日已用 {state['maintenance_used']} 次，养护后间隔 {maintenance['cooldown_seconds'] // 60} 分钟。")
        bundle = self.repository.content or bundled_content()
        recipe_name = bundle.label("recipe", maintenance["recipe_key"])
        lines.append("维护物资：" + command_link(recipe_name, "生产预览 " + recipe_name) + "。取材用途："
                     + "、".join(command_link(u["name"], u["command"]) for u in definition["uses"]))
        return lines

    async def execute(self, context, action):
        args = context.command_args
        if (action == "preview" and len(args) > 1 or action == "extract" and len(args) != 2
                or action == "maintain" and len(args) != 1):
            return CommandResult(False, "INVALID_DEPOSIT_COMMAND", "请用 `资源脉预览 [地点]`、`取用资源脉 地点 做法` "
                                 "或 `养护资源脉 地点`。", context.request_id)
        operation = context.operation_id or f"deposit.{action}:{context.adapter}:{context.user_id}:{context.message_id or context.request_id}"
        try:
            payload = await self.repository.deposit_command(platform=context.adapter, platform_user_id=context.user_id,
                action=action, selector=args[0] if args else "", plan=args[1] if len(args) > 1 else "", operation_id=operation)
        except SurveyRequirementError as exc:
            return CommandResult(False, "DEPOSIT_REQUIREMENT_MISSING", str(exc) + "\n" + command_link("查看资源脉", "资源脉预览")
                                 + " · " + command_link("查看勘察", "山野手札"), context.request_id, operation)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "本次请求与原来的取材安排不同，请重新发送。", context.request_id, operation)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "请先开始修仙。", context.request_id, operation)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色不能取用资源脉。", context.request_id, operation)
        except (ValueError, TypeError, KeyError, sqlite3.Error, RepositoryBusyError):
            logger.exception("deposit command failed action=%s operation=%s", action, operation)
            return CommandResult(False, "PERSISTENCE_ERROR", "这次取材未能入账，请稍后以原请求重试；资源脉预览可查已保存储量。",
                                 context.request_id, operation, retryable=True)
        actions = ()
        if action == "preview":
            lines = ["**山野资源脉**", ""]
            for entry in payload["entries"]:
                lines.extend(self._entry(entry, bool(args)))
                lines.append("")
        else:
            definition = payload["snapshot"]["definition"]
            lines = [payload["text"], "本次消耗：" + self._amounts(payload["costs"]) + "。"]
            if payload["reward"]:
                lines.append("带回材料：" + self._amounts(payload["reward"]) + "。")
            lines.append(command_link("查看储量与下一步", "资源脉预览 " + definition["key"]))
            actions = (CommandAction("查看资源脉", "资源脉预览 " + definition["key"]),)
        return CommandResult(True, "DEPOSIT_" + action.upper(), "\n".join(lines), context.request_id,
                             operation if action != "preview" else None, data=payload, actions=actions)
