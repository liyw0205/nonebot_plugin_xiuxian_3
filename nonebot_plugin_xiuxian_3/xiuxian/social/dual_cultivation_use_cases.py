"""Adapter-neutral commands for the partner cultivation loop."""

from __future__ import annotations

from typing import Any

from ...contracts import CommandAction, CommandContext, CommandResult
from ..content import ContentError
from ..persistence.errors import OperationConflictError, PlayerNotFoundError, PlayerSuspendedError
from ..repository import SQLitePlayerRepository
from .dual_cultivation_repository import DualCultivationError


class DualCultivationApplication:
    def __init__(self, repository: SQLitePlayerRepository):
        self.repository = repository

    @staticmethod
    def _operation_id(context: CommandContext, action: str) -> str:
        if context.operation_id:
            return context.operation_id
        request_key = context.message_id or context.request_id
        return f"social.dual.{action}:{context.adapter}:{context.user_id}:{request_key}"

    async def run(self, context: CommandContext, action: str) -> CommandResult:
        needs_reference = action in {"invite", "accept", "reject", "cancel"}
        if (needs_reference and len(context.command_args) != 1) or (
            not needs_reference and context.command_args
        ):
            usage = {
                "preview": "双修预览", "status": "双修状态", "invite": "发起双修 道号",
                "accept": "接受双修 邀请号", "reject": "拒绝双修 邀请号", "cancel": "取消双修 邀请号",
            }[action]
            return CommandResult(False, "INVALID_DUAL_CULTIVATION_COMMAND", f"请使用 `{usage}`。", context.request_id)

        operation_id = self._operation_id(context, action) if needs_reference else ""
        try:
            data = await self.repository.dual_cultivation(
                platform=context.adapter,
                platform_user_id=context.user_id,
                action=action,
                reference=context.command_args[0] if needs_reference else "",
                operation_id=operation_id,
            )
        except DualCultivationError as exc:
            messages = {
                "CLOSED": "双修暂未开放新的共修邀请。", "RELATION": "需要仍然有效的道侣关系。",
                "LOCATION": "双方须在同一处开放的共修地点。", "BUSY": "你或道侣正处于不能中断的活动中。",
                "PROGRESSION": "双方都需达到共修境界，且仍有本层修为可修。",
                "COST": "你或道侣的灵石、精力不足；此次共修未扣除任何资源。",
                "QUOTA": "你或道侣今日的共修次数已用尽。", "TARGET": "没有找到这位道友。",
                "SELF": "不能向自己发出共修邀请。", "PENDING": "这段道侣关系已有待处理的共修邀请。",
                "NOT_FOUND": "没有找到你有权处理的共修邀请。", "PERMISSION": "只有指定的道侣可以执行此操作。",
                "STATE": "这份共修邀请已处理，不能再次更改。",
                "PLAYER": "你或道侣当前角色不可进行共修。",
            }
            return CommandResult(False, f"DUAL_CULTIVATION_{exc.code}", messages.get(exc.code, "当前无法进行共修。"),
                                 context.request_id, operation_id or None)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次共修请求号已用于不同请求。", context.request_id, operation_id)
        except (PlayerNotFoundError, PlayerSuspendedError):
            return CommandResult(False, "PLAYER_UNAVAILABLE", "当前角色暂时无法进行共修。", context.request_id, operation_id or None)
        except ContentError:
            return CommandResult(False, "CONTENT_ERROR", "共修规则或邀请记录无效；未进行扣费。", context.request_id, operation_id or None)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "共修账簿暂时不可用，请稍后重试。", context.request_id,
                                 operation_id or None, retryable=True)
        return self._result(context, action, data, operation_id)

    @staticmethod
    def _result(context: CommandContext, action: str, data: dict[str, Any], operation_id: str) -> CommandResult:
        status = data.get("status")
        actions: tuple[CommandAction, ...] = ()
        if action in {"preview", "status"}:
            lines = ["## 道侣共修", f"- 道侣：{data.get('partner') or '未结缘'}",
                     f"- 状态：{'可以共修' if data.get('eligible') else '暂不可共修'}",
                     f"- 地点：{'、'.join(data.get('locations', []))}",
                     f"- 各自成本：灵石 {data['cost_each']['spirit_stones']}、精力 {data['cost_each']['energy']}",
                     f"- 本人修为预计：{data.get('gain', 0)}，单次上限 {data.get('gain_max', 0)}",
                     f"- 今日次数（UTC）：{data.get('used_today', 0)}/{data.get('daily_limit', 0)}"]
            pending = [item for item in data.get("invitations", []) if item["status"] == "invited"]
            for item in pending:
                lines.append(f"- 待处理邀请：`{item['invitation_id']}`（{item['role']}，至 {item['expires_at']}）")
                if item["role"] == "invitee":
                    actions += (CommandAction("接受", f"接受双修 {item['invitation_id']}"),
                                CommandAction("拒绝", f"拒绝双修 {item['invitation_id']}"))
                else:
                    actions += (CommandAction("取消", f"取消双修 {item['invitation_id']}"),)
            code = "DUAL_CULTIVATION_PREVIEW" if action == "preview" else "DUAL_CULTIVATION_STATUS"
            return CommandResult(True, code, "\n".join(lines), context.request_id, data=data, actions=actions)
        if action == "invite":
            message = (f"共修邀请 `{data['invitation_id']}` 已送达 {data['invitee']}，待对方应允。"
                       f"\n各自成本：灵石 {data['cost_each']['spirit_stones']}、精力 {data['cost_each']['energy']}。")
            actions = (CommandAction("查看双修", "双修状态"), CommandAction("取消邀请", f"取消双修 {data['invitation_id']}"))
            code = "DUAL_CULTIVATION_INVITED"
        elif action == "accept" and status == "settled":
            gains = data["gains"]
            message = (f"共修已完成。{data['initiator']} 获得修为 {gains['initiator']}，"
                       f"{data['invitee']} 获得修为 {gains['invitee']}；双方分别支付各自成本。")
            code = "DUAL_CULTIVATION_SETTLED"
        else:
            labels = {"accept": "邀请已过期", "reject": "已拒绝共修邀请", "cancel": "已取消共修邀请"}
            message = f"{labels[action]}。"
            code = f"DUAL_CULTIVATION_{status.upper()}"
        if data.get("idempotent_replay"):
            message += "（此结果为原操作回放）"
        return CommandResult(True, code, message, context.request_id, operation_id, data=data, actions=actions)
