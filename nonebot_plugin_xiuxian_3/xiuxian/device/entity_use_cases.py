"""Application commands for 器修机关 (``device.scout_doll``).

Presentation stays adapter-neutral: the messages are Markdown, the actions are
``CommandAction`` tuples, and the only QQ-specific difference is that the
adapter may render the same tuple as a keyboard instead of a "可发送" hint.
"""

from __future__ import annotations

from ...contracts import CommandAction, CommandContext, CommandResult
from ..content import ContentBundle, bundled_content
from ..repository import (
    DeviceBrokenError,
    DeviceLimitReachedError,
    DeviceMaterialError,
    DeviceNotFoundError,
    DeviceRequirementError,
    DeviceStateError,
    OperationConflictError,
    PlayerNotFoundError,
    PlayerSuspendedError,
    RepositoryBusyError,
    ResourceInsufficientError,
    SQLitePlayerRepository,
)
from ..utils.text import command_link
from .entity_rules import DEFAULT_ENTITY_KEY, resolve_device_key

STATUS_COMMAND = "机关"
ASSEMBLE_COMMAND = "组装机关"
DEPLOY_COMMAND = "部署机关"
RECALL_COMMAND = "收回机关"
REPAIR_COMMAND = "维修机关"


class DeviceApplication:
    """Translate device commands into adapter-neutral results."""

    def __init__(self, repository: SQLitePlayerRepository):
        self.repository = repository

    def _content(self) -> ContentBundle:
        content = getattr(self.repository, "content", None)
        return content if content is not None else bundled_content()

    def _entity_key(self, value: str | None) -> str | None:
        return resolve_device_key(self._content(), value)

    @staticmethod
    def _operation_id(context: CommandContext, suffix: str) -> str:
        if context.operation_id:
            return context.operation_id
        key = context.message_id or context.request_id
        return f"device.{suffix}:{context.adapter}:{context.user_id}:{key}"

    def _item_label(self, item_key: str) -> str:
        try:
            return str(self._content().label("item", item_key))
        except KeyError:
            return item_key

    def _realm_label(self, realm_key: str) -> str:
        try:
            return str(self._content().label("realm", realm_key))
        except KeyError:
            return realm_key

    def _cost_text(self, stones: int, items: dict[str, int]) -> str:
        parts = [f"灵石 {stones}"]
        parts.extend(
            f"{self._item_label(item_key)} ×{quantity}" for item_key, quantity in items.items()
        )
        return "、".join(parts)

    def _status_body(self, record) -> list[str]:
        lines = [f"## {record.label}", "", f"> {record.description}", ""]
        if not record.qualified:
            lines.append(f"- **准入**：尚缺 {'、'.join(record.missing)}")
        else:
            lines.append(
                f"- **准入**：满足（{self._realm_label(record.required_realm)} 第 {record.min_layer} 层）"
            )
        if record.owned == 0:
            lines.append("- **状态**：尚未组装")
            lines.append(
                f"- **组装所需**：{self._cost_text(record.assembly_spirit_stones, record.assembly_items)}"
            )
            return lines
        state = "已部署" if record.deployed else "待命"
        if record.status == "broken":
            state = "已损坏"
        lines.append(
            f"- **状态**：{state} · 耐久 {record.durability_bp}/{record.max_durability_bp}"
        )
        lines.append(
            f"- **战法**：攻击为自身的 {record.attack_multiplier_bp / 100:.0f}%，"
            f"持续 {record.duration_rounds} 回合，每场至多 {record.max_actions_per_battle} 次"
        )
        if record.status == "broken":
            lines.append(
                f"- **维修所需**：{self._cost_text(record.maintenance_spirit_stones, record.maintenance_items)}/次"
            )
        return lines

    async def status(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) > 1:
            return CommandResult(
                False, "INVALID_DEVICE_COMMAND", "机关指令最多带一个机关名。", context.request_id
            )
        entity_key = (
            self._entity_key(context.command_args[0]) if context.command_args else DEFAULT_ENTITY_KEY
        )
        if entity_key is None:
            return CommandResult(
                False, "DEVICE_NOT_FOUND", "没有这个机关。", context.request_id
            )
        try:
            record = await self.repository.device_status(
                platform=context.adapter, platform_user_id=context.user_id, entity_key=entity_key
            )
        except PlayerNotFoundError:
            return CommandResult(
                False, "PLAYER_NOT_FOUND", "尚未登记，先发送“开始修仙”。", context.request_id
            )
        except DeviceNotFoundError as exc:
            return CommandResult(False, "DEVICE_NOT_FOUND", _message(exc), context.request_id)
        except RepositoryBusyError as exc:
            return CommandResult(False, "REPOSITORY_BUSY", _message(exc), context.request_id, retryable=True)

        lines = self._status_body(record)
        if record.owned == 0:
            if record.qualified:
                lines.append("")
                lines.append(
                    f"> 备妥材料后，点{command_link(ASSEMBLE_COMMAND, ASSEMBLE_COMMAND)}即可组装。"
                )
            return CommandResult(
                True, "DEVICE_STATUS", "\n".join(lines), context.request_id, data=_data(record)
            )
        if record.status == "broken":
            actions = (CommandAction(REPAIR_COMMAND, f"{REPAIR_COMMAND} {record.label}"),)
        elif record.deployed:
            actions = (CommandAction(RECALL_COMMAND, f"{RECALL_COMMAND} {record.label}"),)
        else:
            actions = (CommandAction(DEPLOY_COMMAND, f"{DEPLOY_COMMAND} {record.label}"),)
        lines.append("")
        lines.append(f"> 点下方“{actions[0].label}”可直接发送指令；部署后机关会随你出战。")
        return CommandResult(
            True,
            "DEVICE_STATUS",
            "\n".join(lines),
            context.request_id,
            data=_data(record),
            actions=actions,
        )

    async def assemble(self, context: CommandContext) -> CommandResult:
        entity_key = (
            self._entity_key(context.command_args[0]) if context.command_args else DEFAULT_ENTITY_KEY
        )
        if len(context.command_args) > 1:
            return CommandResult(
                False, "INVALID_DEVICE_COMMAND", "组装机关最多带一个机关名。", context.request_id
            )
        if entity_key is None:
            return CommandResult(False, "DEVICE_NOT_FOUND", "没有这个机关。", context.request_id)
        return await self._run(
            context,
            "assemble",
            lambda: self.repository.assemble_device(
                platform=context.adapter,
                platform_user_id=context.user_id,
                entity_key=entity_key,
                operation_id=self._operation_id(context, "assemble"),
            ),
        )

    async def deploy(self, context: CommandContext) -> CommandResult:
        return await self._transition(context, "deploy", DEPLOY_COMMAND)

    async def recall(self, context: CommandContext) -> CommandResult:
        return await self._transition(context, "recall", RECALL_COMMAND)

    async def repair(self, context: CommandContext) -> CommandResult:
        return await self._transition(context, "repair", REPAIR_COMMAND)

    async def _transition(self, context: CommandContext, action: str, label: str) -> CommandResult:
        entity_key = (
            self._entity_key(context.command_args[0]) if context.command_args else DEFAULT_ENTITY_KEY
        )
        if len(context.command_args) > 1:
            return CommandResult(
                False, "INVALID_DEVICE_COMMAND", f"{label}最多带一个机关名。", context.request_id
            )
        if entity_key is None:
            return CommandResult(False, "DEVICE_NOT_FOUND", "没有这个机关。", context.request_id)
        callbacks = {
            "deploy": self.repository.deploy_device,
            "recall": self.repository.recall_device,
            "repair": self.repository.repair_device,
        }
        callback = callbacks[action]
        return await self._run(
            context,
            action,
            lambda: callback(
                platform=context.adapter,
                platform_user_id=context.user_id,
                entity_key=entity_key,
                operation_id=self._operation_id(context, action),
            ),
        )

    async def _run(self, context: CommandContext, action: str, call) -> CommandResult:
        try:
            record = await call()
        except PlayerNotFoundError:
            return CommandResult(
                False, "PLAYER_NOT_FOUND", "尚未登记，先发送“开始修仙”。", context.request_id
            )
        except PlayerSuspendedError:
            return CommandResult(
                False, "PLAYER_SUSPENDED", "当前状态不允许操控机关。", context.request_id
            )
        except DeviceRequirementError:
            return CommandResult(
                False, "DEVICE_REQUIREMENT", "道途或境界不足，无法驱动这件机关。", context.request_id
            )
        except DeviceLimitReachedError:
            return CommandResult(
                False, "DEVICE_LIMIT_REACHED", "此机关已达数量上限。", context.request_id
            )
        except DeviceNotFoundError:
            return CommandResult(
                False, "DEVICE_NOT_FOUND", "你还没有这件机关。", context.request_id
            )
        except DeviceBrokenError:
            return CommandResult(
                False, "DEVICE_BROKEN", "机关已损坏，先维修再用。", context.request_id
            )
        except DeviceMaterialError:
            return CommandResult(
                False, "DEVICE_MATERIAL_MISSING", "灵石或材料不足。", context.request_id
            )
        except ResourceInsufficientError:
            return CommandResult(
                False, "DEVICE_MATERIAL_MISSING", "灵石或材料不足。", context.request_id
            )
        except DeviceStateError:
            return CommandResult(
                False,
                "DEVICE_STATE",
                {
                    "assemble": "此机关已组装。",
                    "deploy": "机关已在场上，或已损坏需先维修。",
                    "recall": "机关当前并未部署。",
                    "repair": "机关耐久已满，无需维修。",
                }[action],
                context.request_id,
            )
        except OperationConflictError:
            return CommandResult(
                False, "LEDGER_CONFLICT", "同一条指令的输入不一致，已拒绝。", context.request_id
            )
        except RepositoryBusyError:
            return CommandResult(
                False, "REPOSITORY_BUSY", "仓储繁忙，请稍后再试。", context.request_id, retryable=True
            )

        lines = [f"## {record.label}", ""]
        if action == "assemble":
            lines.append(
                f"已组装完成，耐久 {record.durability_bp}/{record.max_durability_bp}。"
            )
            lines.append(
                f"- **消耗**：灵石 {record.spirit_stones_before} → {record.spirit_stones_after}"
                + (
                    "、"
                    + "、".join(
                        f"{self._item_label(key)} ×{quantity}"
                        for key, quantity in record.items_spent.items()
                    )
                    if record.items_spent
                    else ""
                )
            )
            lines.append("")
            lines.append(
                f"> 点{command_link(DEPLOY_COMMAND, f'{DEPLOY_COMMAND} {record.label}')}让它随你出战。"
            )
            actions = (CommandAction(DEPLOY_COMMAND, f"{DEPLOY_COMMAND} {record.label}"),)
        elif action == "deploy":
            lines.append("已部署，下一场战斗它会替你出手。")
            lines.append("")
            lines.append(
                f"> 想让机关休整，点{command_link(RECALL_COMMAND, f'{RECALL_COMMAND} {record.label}')}。"
            )
            actions = (CommandAction(RECALL_COMMAND, f"{RECALL_COMMAND} {record.label}"),)
        elif action == "recall":
            lines.append("已收回机关。")
            actions = (CommandAction(DEPLOY_COMMAND, f"{DEPLOY_COMMAND} {record.label}"),)
        else:
            lines.append(
                f"维修完成，耐久 {record.durability_bp}/{record.max_durability_bp}。"
            )
            actions = (CommandAction(DEPLOY_COMMAND, f"{DEPLOY_COMMAND} {record.label}"),)
        return CommandResult(
            True,
            f"DEVICE_{action.upper()}",
            "\n".join(lines),
            context.request_id,
            operation_id=None,
            data={
                "entity_key": record.entity_key,
                "action": record.action,
                "instance_id": record.instance_id,
                "durability_bp": record.durability_bp,
                "max_durability_bp": record.max_durability_bp,
                "status": record.status,
                "deployed": record.deployed,
                "spirit_stones_after": record.spirit_stones_after,
                "items_spent": dict(record.items_spent),
                "already_completed": record.already_completed,
            },
            actions=actions,
        )


def _message(exc: Exception) -> str:
    text = str(exc).strip()
    return text or "机关指令未能完成。"


def _data(record) -> dict[str, object]:
    return {
        "entity_key": record.entity_key,
        "label": record.label,
        "owned": record.owned,
        "max_instances": record.max_instances,
        "qualified": record.qualified,
        "missing": list(record.missing),
        "durability_bp": record.durability_bp,
        "max_durability_bp": record.max_durability_bp,
        "status": record.status,
        "deployed": record.deployed,
        "instance_id": record.instance_id,
        "attack_multiplier_bp": record.attack_multiplier_bp,
        "duration_rounds": record.duration_rounds,
        "max_actions_per_battle": record.max_actions_per_battle,
        "assembly_spirit_stones": record.assembly_spirit_stones,
        "assembly_items": dict(record.assembly_items),
        "maintenance_spirit_stones": record.maintenance_spirit_stones,
        "maintenance_items": dict(record.maintenance_items),
    }