"""灵兽与灵骑的玩家端用例。"""

from __future__ import annotations

from ...contracts import CommandContext, CommandResult
from ..repository import (
    CompanionAlreadyBondedError,
    CompanionCapacityError,
    CompanionGearError,
    CompanionInjuredError,
    CompanionNotFoundError,
    CompanionRequirementError,
    OperationConflictError,
    PlayerNotFoundError,
    PlayerSuspendedError,
    RepositoryBusyError,
    ResourceInsufficientError,
    SQLitePlayerRepository,
)
from ..content import bundled_content
from .models import CompanionStatusRecord


class CompanionApplication:
    """只编排领域用例，规则和事务仍由 companions 模块负责。"""

    def __init__(self, repository: SQLitePlayerRepository):
        self.repository = repository

    @staticmethod
    def _operation_id(context: CommandContext, name: str) -> str:
        return context.operation_id or f"{name}:{context.adapter}:{context.user_id}:{context.message_id or context.request_id}"

    @staticmethod
    def _name(value: str) -> str:
        return (value or "未命名").replace("\\", "\\\\").replace("`", "\\`").replace("*", "\\*").replace("_", "\\_").replace("~", "\\~")

    def _label(self, key: str) -> str:
        content = self.repository.content or bundled_content()
        return content.label("companion", key, fallback=key)

    @staticmethod
    def _status(value: str) -> str:
        return {
            "active": "出战中",
            "available": "待命",
            "resting": "休养中",
            "injured": "受伤休养中",
            "bonded": "已结缘",
            "travelling": "随行中",
        }.get(value, "已结缘")

    async def status(self, context: CommandContext) -> CommandResult:
        try:
            record = await self.repository.list_companions(
                platform=context.adapter, platform_user_id=context.user_id
            )
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时无法查看灵兽。", context.request_id)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, retryable=True)
        lines = ["## 灵兽灵骑", "", f"**{self._name(record.player.dao_name)}**的随行灵兽："]
        if not record.companions:
            lines.append("暂无灵兽或灵骑。")
        for companion in record.companions:
            state = "出战" if companion.deployed else "待命"
            kind = "灵骑" if companion.kind == "mount" else "灵兽"
            lines.append(
                f"- **{companion.name}**（{kind}）\n"
                f"  - 等级 {companion.level}；经验 {companion.experience}\n"
                f"  - 状态：{self._status(companion.status)}；{state}；耐力 {companion.stamina}"
            )
            for gear in companion.gear:
                gear_key = str(gear.get("gear_key", ""))
                lines.append(f"  - 灵具：{self._label(gear_key)}，耐久 {gear.get('durability_bp', 0)} bp")
        return CommandResult(
            True,
            "COMPANION_STATUS",
            "\n".join(lines),
            context.request_id,
            data={
                "companions": [
                    {
                        "instance_id": item.instance_id,
                        "companion_key": item.companion_key,
                        "kind": item.kind,
                        "level": item.level,
                        "experience": item.experience,
                        "affinity": item.affinity,
                        "stamina": item.stamina,
                        "status": item.status,
                        "deployed": item.deployed,
                        "gear": [dict(gear) for gear in item.gear],
                    }
                    for item in record.companions
                ]
            },
        )

    async def bond(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 1:
            return CommandResult(False, "INVALID_COMPANION_COMMAND", "请指定要结缘的灵兽或灵骑。", context.request_id)
        operation_id = self._operation_id(context, "companion.bond")
        try:
            record = await self.repository.bond_companion(
                platform=context.adapter,
                platform_user_id=context.user_id,
                companion_key=context.command_args[0],
                operation_id=operation_id,
            )
        except ValueError:
            return CommandResult(False, "COMPANION_NOT_FOUND", "没有找到这只灵兽或灵骑。", context.request_id, operation_id)
        except CompanionRequirementError:
            return CommandResult(False, "COMPANION_REQUIREMENT", "当前地点或经历还不足以结缘此灵兽。", context.request_id, operation_id)
        except CompanionCapacityError:
            return CommandResult(False, "COMPANION_CAPACITY", "当前可结缘的同类灵兽已达上限。", context.request_id, operation_id)
        except (PlayerNotFoundError, PlayerSuspendedError):
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有可用的修仙角色。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次结缘请求已用于其他灵兽，请重新发起。", context.request_id, operation_id)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        return CommandResult(
            True,
            "COMPANION_BONDED",
            f"## 结缘有成\n\n**{record.companion.name}**已来到身边，当前为{self._status(record.companion.status)}。",
            context.request_id,
            operation_id,
            data={"instance_id": record.companion.instance_id, "companion_key": record.companion.companion_key, "idempotent_replay": record.already_completed},
        )

    async def feed(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 1:
            return CommandResult(False, "INVALID_COMPANION_COMMAND", "请指定要喂养的灵兽实体编号或稳定键。", context.request_id)
        operation_id = self._operation_id(context, "companion.feed")
        try:
            record = await self.repository.feed_companion(
                platform=context.adapter,
                platform_user_id=context.user_id,
                companion_ref=context.command_args[0],
                operation_id=operation_id,
            )
        except CompanionNotFoundError:
            return CommandResult(False, "COMPANION_NOT_FOUND", "没有找到这只灵兽。", context.request_id, operation_id)
        except CompanionInjuredError:
            return CommandResult(False, "COMPANION_RESTING", "灵兽正在休养，暂不能喂养。", context.request_id, operation_id)
        except CompanionRequirementError:
            return CommandResult(False, "COMPANION_NOT_FEEDABLE", "这只灵骑不适用灵粮喂养。", context.request_id, operation_id)
        except ResourceInsufficientError:
            return CommandResult(False, "COMPANION_FEED_INSUFFICIENT", "灵粮不足，未改变灵兽状态。", context.request_id, operation_id)
        except (PlayerNotFoundError, PlayerSuspendedError):
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有可用的修仙角色。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次喂养请求已用于其他操作，请重新发起。", context.request_id, operation_id)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        return CommandResult(
            True,
            "COMPANION_FED",
            f"## 灵粮入腹\n\n**{record.companion.name}**获得灵粮，经验来到 {record.companion.experience}，当前等级 {record.companion.level}。",
            context.request_id,
            operation_id,
            data={"instance_id": record.companion.instance_id, "level": record.companion.level, "experience": record.companion.experience, "spent": record.spent, "idempotent_replay": record.already_completed},
        )

    async def rest(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 1:
            return CommandResult(False, "INVALID_COMPANION_COMMAND", "请指定要休养的灵兽实体编号或稳定键。", context.request_id)
        operation_id = self._operation_id(context, "companion.rest")
        try:
            record = await self.repository.rest_companion(
                platform=context.adapter,
                platform_user_id=context.user_id,
                companion_ref=context.command_args[0],
                operation_id=operation_id,
            )
        except CompanionInjuredError:
            return CommandResult(False, "COMPANION_INJURED", "灵兽的伤势尚未恢复。", context.request_id, operation_id)
        except (CompanionRequirementError, CompanionNotFoundError):
            return CommandResult(False, "COMPANION_NOT_RESTING", "这只灵兽当前不需要休养。", context.request_id, operation_id)
        except (PlayerNotFoundError, PlayerSuspendedError):
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有可用的修仙角色。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次休养请求已用于其他操作，请重新发起。", context.request_id, operation_id)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        return CommandResult(True, "COMPANION_RESTED", f"## 休养完成\n\n**{record.companion.name}**已恢复为可行动状态。", context.request_id, operation_id, data={"instance_id": record.companion.instance_id, "status": record.companion.status, "idempotent_replay": record.already_completed})

    async def equip(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 2:
            return CommandResult(False, "INVALID_COMPANION_COMMAND", "请依次指定灵兽实体编号和灵具名称。", context.request_id)
        operation_id = self._operation_id(context, "companion.equip_gear")
        try:
            record = await self.repository.equip_companion_gear(
                platform=context.adapter,
                platform_user_id=context.user_id,
                companion_ref=context.command_args[0],
                gear_key=context.command_args[1],
                operation_id=operation_id,
            )
        except CompanionNotFoundError:
            return CommandResult(False, "COMPANION_NOT_FOUND", "没有找到这只灵兽。", context.request_id, operation_id)
        except CompanionGearError:
            return CommandResult(False, "COMPANION_GEAR_INVALID", "这件灵具不适合当前灵兽，或当前已有灵具。", context.request_id, operation_id)
        except ResourceInsufficientError:
            return CommandResult(False, "COMPANION_GEAR_INSUFFICIENT", "背包中没有这件灵具，未改变灵兽状态。", context.request_id, operation_id)
        except (PlayerNotFoundError, PlayerSuspendedError):
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有可用的修仙角色。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次装备请求已用于其他操作，请重新发起。", context.request_id, operation_id)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        return CommandResult(True, "COMPANION_GEAR_EQUIPPED", f"## 灵具相合\n\n**{record.companion.name}**已装备灵具。", context.request_id, operation_id, data={"instance_id": record.companion.instance_id, "gear": [dict(item) for item in record.companion.gear], "spent": record.spent, "idempotent_replay": record.already_completed})


__all__ = ["CompanionApplication"]
