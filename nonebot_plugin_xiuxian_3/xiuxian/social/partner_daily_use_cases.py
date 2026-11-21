"""Application commands for shared daily partner fieldwork."""

from __future__ import annotations

import logging
import sqlite3

from ...contracts import CommandAction, CommandContext, CommandResult
from ..content import ContentError, bundled_content
from ..persistence.errors import (
    OperationConflictError,
    OperationResultMalformedError,
    PartnerTaskNoPartnerError,
    PlayerNotFoundError,
    PlayerSuspendedError,
    RepositoryBusyError,
)
from ..utils.text import command_link
from .partner_daily_repository import PartnerDailyTaskError

logger = logging.getLogger(__name__)

STATUS_COMMAND = "道侣日课"
START_COMMAND = "开始道侣日课"
CLAIM_COMMAND = "领取道侣日课"


class PartnerDailyApplication:
    def __init__(self, repository):
        self.repository = repository

    def _item_label(self, key: str) -> str:
        bundle = self.repository.content or bundled_content()
        try:
            return str(bundle.label("item", key))
        except KeyError:
            return key

    def _reward_text(self, merit: int, items: dict[str, int]) -> str:
        parts = [f"世界功勋 {merit}"]
        parts.extend(f"{self._item_label(key)} ×{amount}" for key, amount in items.items())
        return "、".join(parts)

    def _rule_text(self, rule: dict) -> str:
        return self._reward_text(rule["reward_world_merit"], rule["reward_items"])

    def _deposit_links(self, keys) -> str:
        bundle = self.repository.content or bundled_content()
        return "、".join(
            command_link(bundle.label("deposit", key, fallback=key), "资源脉预览 " + key)
            for key in keys
        )

    def _status_result(self, context: CommandContext, record: dict) -> CommandResult:
        task, rule = record["task"], record["rule"]
        actions: tuple[CommandAction, ...] = ()
        lines = ["## 道侣同行日课", ""]
        if not record["has_partner"] and task is None:
            lines.append("当前没有有效的道侣关系，无法开启同行日课。")
            return CommandResult(True, "PARTNER_DAILY_STATUS", "\n".join(lines),
                                 context.request_id, data=record)

        if task is None:
            if not record["rule_available"] or rule is None:
                lines.append("今日同行日课暂未开放。")
            else:
                lines.extend([
                    f"> {rule['description']}",
                    f"- UTC 日期：{record['quota_day']}",
                    f"- 今日已开：{record['used_today']}/{rule['daily_limit']}",
                    f"- 双方各完成：成功取材 {rule['target_each']} 次",
                    f"- 允许取材：{self._deposit_links(rule['deposit_keys'])}",
                    f"- 各自可领：{self._rule_text(rule)}",
                ])
                if record["eligible"] and record["used_today"] < rule["daily_limit"]:
                    actions = (CommandAction(START_COMMAND, START_COMMAND),)
                    lines.extend(["", f"> {command_link(START_COMMAND, START_COMMAND)}"])
            return CommandResult(True, "PARTNER_DAILY_STATUS", "\n".join(lines),
                                 context.request_id, data=record, actions=actions)

        progress = task["progress"]
        lines.extend([
            f"> {task['description']}",
            f"- UTC 日期：{task['quota_day']}；期限至 {task['expires_at']}",
            f"- 你的取材：{progress['self']}/{task['target_each']}",
            f"- 道侣取材：{progress['partner']}/{task['target_each']}",
            f"- 允许取材：{self._deposit_links(task['deposit_keys'])}",
            f"- 你的领取：{'已领取' if task['claimed'] else '未领取'}",
            f"- 道侣领取：{'已领取' if task['partner_claimed'] else '未领取'}",
            f"- 各自可领：{self._reward_text(task['reward_world_merit'], task['reward_items'])}",
        ])
        status = task["status"]
        can_participate = record["eligible"] and task["relation_active"]
        if not can_participate:
            lines.append("- 参与状态：当前关系或角色状态不允许继续取材计数或领奖")
        if status == "claimable":
            lines.append("- 日课状态：双方均已完成")
            if not task["claimed"] and can_participate:
                claim_input = f"{CLAIM_COMMAND} {task['task_id']}"
                actions = (CommandAction(CLAIM_COMMAND, claim_input),)
                lines.extend(["", f"> {command_link(CLAIM_COMMAND, claim_input)}"])
        elif status == "open":
            lines.append("- 日课状态：进行中")
        elif status == "expired":
            lines.append("- 日课状态：已过期，未达成的进度不再增加")
        else:
            lines.append("- 日课状态：双方已领取")

        can_start_today = (
            can_participate and record["rule_available"] and rule is not None
            and record["used_today"] < rule["daily_limit"]
            and task["quota_day"] != record["quota_day"]
            and status in {"expired", "completed"}
        )
        if can_start_today:
            actions = (CommandAction(START_COMMAND, START_COMMAND),)
            lines.extend(["", f"> {command_link(START_COMMAND, START_COMMAND)}"])
        return CommandResult(True, "PARTNER_DAILY_STATUS", "\n".join(lines),
                             context.request_id, data=record, actions=actions)

    async def status(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) > 1:
            return CommandResult(False, "INVALID_PARTNER_DAILY_COMMAND",
                                 "道侣日课最多接受一个任务号。", context.request_id)
        try:
            record = await self.repository.partner_daily_status(
                platform=context.adapter,
                platform_user_id=context.user_id,
                task_id=context.command_args[0] if context.command_args else "",
            )
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "尚未登记，先发送“开始修仙”。",
                                 context.request_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色不能查看同行日课。", context.request_id)
        except PartnerDailyTaskError:
            return CommandResult(False, "PARTNER_DAILY_NOT_FOUND", "没有找到属于你的同行日课。", context.request_id)
        except (OperationResultMalformedError, ContentError, ValueError, TypeError, KeyError, sqlite3.Error, RepositoryBusyError):
            logger.exception("partner daily status failed user=%s", context.user_id)
            return CommandResult(False, "PERSISTENCE_ERROR", "同行日课状态暂不可读取，请稍后重试。",
                                 context.request_id, retryable=True)
        return self._status_result(context, record)

    @staticmethod
    def _operation_id(context: CommandContext, suffix: str) -> str:
        if context.operation_id:
            return context.operation_id
        key = context.message_id or context.request_id
        return f"social.partner_daily.{suffix}:{context.adapter}:{context.user_id}:{key}"

    async def start(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_PARTNER_DAILY_COMMAND", "开始道侣日课不带参数。",
                                 context.request_id)
        operation_id = self._operation_id(context, "start")
        try:
            record = await self.repository.start_partner_daily_task(
                platform=context.adapter, platform_user_id=context.user_id,
                operation_id=operation_id,
            )
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "尚未登记，先发送“开始修仙”。",
                                 context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色不能开启同行日课。",
                                 context.request_id, operation_id)
        except PartnerTaskNoPartnerError:
            return CommandResult(False, "PARTNER_DAILY_NO_PARTNER", "你当前没有有效的道侣关系。",
                                 context.request_id, operation_id)
        except PartnerDailyTaskError as exc:
            codes = {
                "PLAYER": ("PARTNER_DAILY_PLAYER", "双方角色当前都须可参与修行。"),
                "ACTIVE": ("PARTNER_DAILY_ACTIVE", "上一份同行日课仍在进行或待双方领取。"),
                "QUOTA": ("PARTNER_DAILY_QUOTA", "今日同行日课已开启。"),
                "UNAVAILABLE": ("PARTNER_DAILY_UNAVAILABLE", "同行日课规则暂不可用，未创建任务。"),
            }
            code, message = codes.get(exc.code, ("PARTNER_DAILY_ERROR", "无法开启同行日课。"))
            return CommandResult(False, code, message, context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "同一操作编号对应了不同请求。",
                                 context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "REPOSITORY_BUSY", "仓储繁忙，请稍后用原操作重试。",
                                 context.request_id, operation_id, retryable=True)
        except (OperationResultMalformedError, ContentError, ValueError, TypeError, KeyError, sqlite3.Error):
            logger.exception("partner daily start failed operation=%s", operation_id)
            return CommandResult(False, "PERSISTENCE_ERROR", "同行日课未能入账，请稍后用原操作重试。",
                                 context.request_id, operation_id, retryable=True)
        state = "已恢复今日同行日课" if record.get("resumed") or record.get("idempotent_replay") else "已开启今日同行日课"
        message = (
            f"{state}：双方各完成 {record['target_each']} 次允许的资源脉取材后，可分别领取"
            f"{self._reward_text(record['reward_world_merit'], record['reward_items'])}。"
        )
        if record["status"] == "expired":
            message = "今日同行日课已过期，今日不再新开；可在下一 UTC 日期重新开启。"
        elif record["status"] == "completed":
            message = "今日同行日课已结清，双方均已领取；下一 UTC 日期可开启新任务。"
        elif record["status"] == "claimable":
            message = "双方已完成今日同行日课，请各自领取本人的奖励。"
        return CommandResult(True, "PARTNER_DAILY_START", message, context.request_id,
                             operation_id, data=record,
                             actions=(CommandAction(STATUS_COMMAND, STATUS_COMMAND),))

    async def claim(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) > 1:
            return CommandResult(False, "INVALID_PARTNER_DAILY_COMMAND", "领取道侣日课最多接受一个任务号。",
                                 context.request_id)
        operation_id = self._operation_id(context, "claim")
        try:
            record = await self.repository.claim_partner_daily_task(
                platform=context.adapter, platform_user_id=context.user_id,
                task_id=context.command_args[0] if context.command_args else "",
                operation_id=operation_id,
            )
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "尚未登记，先发送“开始修仙”。",
                                 context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色不能领取同行日课。",
                                 context.request_id, operation_id)
        except PartnerDailyTaskError as exc:
            codes = {
                "RELATION": ("PARTNER_DAILY_RELATION", "当前有效道侣关系与这份日课不匹配。"),
                "NOT_FOUND": ("PARTNER_DAILY_NOT_FOUND", "没有找到可领取的同行日课。"),
                "CLAIMED": ("PARTNER_DAILY_CLAIMED", "你已领取这份同行日课奖励。"),
                "NOT_COMPLETE": ("PARTNER_DAILY_NOT_COMPLETE", "双方尚未完成日课，暂不可领取。"),
                "PLAYER": ("PARTNER_DAILY_PLAYER", "双方角色当前都须可参与修行。"),
            }
            code, message = codes.get(exc.code, ("PARTNER_DAILY_ERROR", "无法领取同行日课。"))
            return CommandResult(False, code, message, context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "同一操作编号对应了不同请求。",
                                 context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "REPOSITORY_BUSY", "仓储繁忙，请稍后用原操作重试。",
                                 context.request_id, operation_id, retryable=True)
        except (OperationResultMalformedError, ContentError, ValueError, TypeError, KeyError, sqlite3.Error):
            logger.exception("partner daily claim failed operation=%s", operation_id)
            return CommandResult(False, "PERSISTENCE_ERROR", "奖励未能入账，请稍后用原操作重试。",
                                 context.request_id, operation_id, retryable=True)
        reward = record["reward"]
        reward_text = self._reward_text(reward["world_merit"], {
            key: value for key, value in reward.items() if key != "world_merit"
        })
        return CommandResult(True, "PARTNER_DAILY_CLAIM", f"已领取你的同行日课所得：{reward_text}。",
                             context.request_id, operation_id, data=record,
                             actions=(CommandAction(STATUS_COMMAND, STATUS_COMMAND),))
