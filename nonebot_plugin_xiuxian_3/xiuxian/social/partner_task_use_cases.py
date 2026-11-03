"""Application commands for 道侣终局协作 (``partner.endgame_task``)."""

from __future__ import annotations

from ...contracts import CommandAction, CommandContext, CommandResult
from ..content import ContentBundle, bundled_content
from ..repository import (
    EndgamePartnerStateConflictError,
    OperationConflictError,
    PartnerTaskActiveError,
    PartnerTaskClaimedError,
    PartnerTaskNoPartnerError,
    PartnerTaskNotCompleteError,
    PlayerNotFoundError,
    PlayerSuspendedError,
    RepositoryBusyError,
    SQLitePlayerRepository,
)
from ..utils.text import command_link

STATUS_COMMAND = "道侣协作"
START_COMMAND = "开始道侣协作"
CLAIM_COMMAND = "领取道侣协作"


class PartnerTaskApplication:
    """Translate partner-task commands into adapter-neutral results."""

    def __init__(self, repository: SQLitePlayerRepository):
        self.repository = repository

    def _content(self) -> ContentBundle:
        content = getattr(self.repository, "content", None)
        return content if content is not None else bundled_content()

    def _item_label(self, item_key: str) -> str:
        try:
            return str(self._content().label("item", item_key))
        except KeyError:
            return item_key

    @staticmethod
    def _operation_id(context: CommandContext, suffix: str) -> str:
        if context.operation_id:
            return context.operation_id
        key = context.message_id or context.request_id
        return f"social.partner_task.{suffix}:{context.adapter}:{context.user_id}:{key}"

    def _reward_text(self, record: dict) -> str:
        parts = [f"世界功勋 {record['reward_world_merit']}"]
        parts.extend(
            f"{self._item_label(item_key)} ×{quantity}"
            for item_key, quantity in record["reward_items"].items()
        )
        return "、".join(parts)

    def _lines(self, record: dict) -> list[str]:
        lines = [f"## {record['name']}", "", f"> {record['description']}", ""]
        if not record["has_partner"]:
            lines.append("> 需先结为道侣，且双方都尚未落下终局结局。")
            return lines
        if record["partner_locked"]:
            lines.append("- **状态**：一方已落结局，协作已终止")
            return lines
        lines.append(
            f"- **进度**：{record['progress']}/{record['target_amount']}"
            f"（协作助战胜利 {record['target_amount']} 场）"
        )
        lines.append(f"- **时限**：{record['window_days']} 天")
        lines.append(f"- **各得**：{self._reward_text(record)}")
        if not record["task_id"]:
            lines.append("- **任务**：尚未开始")
        elif record["claimed"]:
            lines.append("- **任务**：已领取")
        elif record["complete"]:
            lines.append("- **任务**：可领取")
        else:
            lines.append("- **任务**：进行中")
        return lines

    async def status(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(
                False, "INVALID_PARTNER_TASK_COMMAND", "道侣协作不带参数。", context.request_id
            )
        try:
            record = await self.repository.partner_task_status(
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
        lines = self._lines(record)
        actions: tuple[CommandAction, ...] = ()
        if record["has_partner"] and not record["partner_locked"]:
            if not record["task_id"]:
                lines.append("")
                lines.append(
                    f"> 点{command_link(START_COMMAND, START_COMMAND)}与道侣共赴终局。"
                )
                actions = (CommandAction(START_COMMAND, START_COMMAND),)
            elif record["complete"] and not record["claimed"]:
                actions = (CommandAction(CLAIM_COMMAND, CLAIM_COMMAND),)
                lines.append("")
                lines.append(f"> 条件已达成，点“{CLAIM_COMMAND}”领取各自所得。")
        return CommandResult(
            True,
            "PARTNER_TASK_STATUS",
            "\n".join(lines),
            context.request_id,
            data=dict(record),
            actions=actions,
        )

    async def start(self, context: CommandContext) -> CommandResult:
        return await self._run(context, "start", START_COMMAND)

    async def claim(self, context: CommandContext) -> CommandResult:
        return await self._run(context, "claim", CLAIM_COMMAND)

    async def _run(self, context: CommandContext, action: str, label: str) -> CommandResult:
        if context.command_args:
            return CommandResult(
                False, "INVALID_PARTNER_TASK_COMMAND", f"{label}不带参数。", context.request_id
            )
        callbacks = {
            "start": self.repository.start_partner_task,
            "claim": self.repository.claim_partner_task,
        }
        callback = callbacks[action]
        try:
            record = await callback(
                platform=context.adapter,
                platform_user_id=context.user_id,
                operation_id=self._operation_id(context, action),
            )
        except PlayerNotFoundError:
            return CommandResult(
                False, "PLAYER_NOT_FOUND", "尚未登记，先发送“开始修仙”。", context.request_id
            )
        except PlayerSuspendedError:
            return CommandResult(
                False, "PLAYER_SUSPENDED", "当前状态不允许道侣协作。", context.request_id
            )
        except PartnerTaskNoPartnerError:
            return CommandResult(
                False, "PARTNER_TASK_NO_PARTNER", "你当前没有有效的道侣关系。", context.request_id
            )
        except EndgamePartnerStateConflictError:
            return CommandResult(
                False,
                "ENDGAME_PARTNER_STATE_CONFLICT",
                "一方已落下终局结局，不能再开启协作。",
                context.request_id,
            )
        except PartnerTaskActiveError:
            return CommandResult(
                False, "PARTNER_TASK_ACTIVE", "已有进行中的道侣协作。", context.request_id
            )
        except PartnerTaskNotCompleteError:
            return CommandResult(
                False, "PARTNER_TASK_NOT_COMPLETE", "协作目标尚未达成。", context.request_id
            )
        except PartnerTaskClaimedError:
            return CommandResult(
                False, "PARTNER_TASK_CLAIMED", "这份协作奖励已领取。", context.request_id
            )
        except OperationConflictError:
            return CommandResult(
                False, "LEDGER_CONFLICT", "同一条指令的输入不一致，已拒绝。", context.request_id
            )
        except RepositoryBusyError:
            return CommandResult(
                False, "REPOSITORY_BUSY", "仓储繁忙，请稍后再试。", context.request_id, retryable=True
            )

        if action == "start":
            body = (
                "已开启道侣协作，"
                f"{record['target_amount']} 场协作助战胜利后双方各领一次。"
            )
            actions = (CommandAction("查看道侣协作", STATUS_COMMAND),)
        else:
            reward = record.get("reward", {})
            parts = [f"世界功勋 {reward.get('world_merit', 0)}"]
            parts.extend(
                f"{self._item_label(key)} ×{value}"
                for key, value in reward.items()
                if key != "world_merit"
            )
            body = f"已领取协作所得：{'、'.join(parts)}。"
            actions = (CommandAction("查看道侣协作", STATUS_COMMAND),)
        return CommandResult(
            True,
            f"PARTNER_TASK_{action.upper()}",
            "\n".join(["## 道侣协作", "", body]),
            context.request_id,
            data={
                "task_id": record.get("task_id"),
                "relation_id": record.get("relation_id"),
                "action": action,
                "progress": record.get("progress"),
                "target_amount": record.get("target_amount"),
                "reward": record.get("reward", {}),
                "already_completed": bool(record.get("already_completed")),
            },
            actions=actions,
        )