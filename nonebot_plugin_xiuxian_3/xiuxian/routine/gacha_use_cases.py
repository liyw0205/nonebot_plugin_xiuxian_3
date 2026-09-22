"""Application commands for the v0.1 fate treasure pool."""

from __future__ import annotations

from ...contracts import CommandContext, CommandResult
from ..repository import (
    FateDrawInsufficientError,
    FatePoolInvalidError,
    FatePoolNotOpenError,
    OperationConflictError,
    PlayerNotFoundError,
    PlayerSuspendedError,
    RepositoryBusyError,
    FateRollRecord,
    SQLitePlayerRepository,
)
from .gacha import FATE_PITY_LIMIT, FATE_POOL_KEY


class GachaApplication:
    """Coordinates deterministic treasure rolls and Markdown responses."""

    def __init__(self, repository: SQLitePlayerRepository):
        self.repository = repository

    @staticmethod
    def _operation_id(context: CommandContext, draw_count: int) -> str:
        if context.operation_id:
            return context.operation_id
        request_key = context.message_id or context.request_id
        return f"routine.roll_fate_pool:{FATE_POOL_KEY}:{draw_count}:{context.adapter}:{context.user_id}:{request_key}"

    @staticmethod
    def _display_name(player) -> str:
        value = player.dao_name or "未命名"
        return (
            value.replace("\\", "\\\\")
            .replace("`", "\\`")
            .replace("*", "\\*")
            .replace("_", "\\_")
            .replace("~", "\\~")
        )

    @staticmethod
    def _draw_count(args: tuple[str, ...]) -> int | None:
        if not args:
            return 1
        if len(args) != 1:
            return None
        return {
            "单抽": 1,
            "一抽": 1,
            "1": 1,
            "十连": 10,
            "十连抽": 10,
            "10": 10,
        }.get(args[0].strip().casefold())

    @staticmethod
    def _cost_text(record: FateRollRecord) -> str:
        label = "机缘签" if record.cost_kind == "ticket" else "灵石"
        return f"{label} ×{record.cost_quantity}"

    @staticmethod
    def _reward_text(record: FateRollRecord) -> str:
        labels = {
            "spirit_stones": "灵石返还",
            "item.herb.blood_grass": "止血草",
            "item.herb.spirit_leaf": "灵叶",
            "item.ore.ironstone": "铁石",
            "item.mat.wood": "木材",
            "item.mat.array_sand": "阵砂",
            "item.fragment.dao_name": "道号碎片",
            "item.clue.recipe_basic": "配方线索",
            "item.clue.manual_basic": "功法线索",
        }
        return "、".join(
            f"**{labels.get(key, '奖励')} ×{quantity}**"
            for key, quantity in record.reward.items()
            if quantity
        ) or "无"

    @staticmethod
    def _draw_lines(record: FateRollRecord) -> str:
        if record.draw_count == 1:
            draw = record.draws[0]
            marker = "（保底）" if draw.guaranteed else ""
            return f"- **结果**：{draw.label} ×{draw.quantity}{marker}"
        rare_count = sum(1 for draw in record.draws if draw.rarity == "rare")
        return f"- **结果**：{len(record.draws)} 项奖励，其中灵品/功法线索 **{rare_count}** 项"

    async def roll_fate_pool(self, context: CommandContext) -> CommandResult:
        draw_count = self._draw_count(context.command_args)
        if draw_count is None:
            return CommandResult(
                False,
                "INVALID_FATE_COMMAND",
                "请使用 `机缘寻宝`、`机缘寻宝 单抽` 或 `机缘寻宝 十连`。",
                context.request_id,
            )
        operation_id = self._operation_id(context, draw_count)
        try:
            record = await self.repository.roll_fate_pool(
                platform=context.adapter,
                platform_user_id=context.user_id,
                draw_count=draw_count,
                operation_id=operation_id,
            )
        except FatePoolInvalidError:
            return CommandResult(False, "INVALID_FATE_COMMAND", "这类机缘池尚未开放。", context.request_id, operation_id)
        except FatePoolNotOpenError:
            return CommandResult(False, "FATE_POOL_NOT_OPEN", "当前机缘池暂不可用，请稍后再试。", context.request_id, operation_id)
        except FateDrawInsufficientError:
            cost = "50 灵石或 1 张机缘签" if draw_count == 1 else "450 灵石"
            return CommandResult(False, "FATE_DRAW_INSUFFICIENT", f"机缘寻宝需要 {cost}，未扣除任何资源。", context.request_id, operation_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能进行机缘寻宝。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于其他机缘操作，请重新发起。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)

        lines = [
            "## 机缘寻宝",
            "",
            f"**{self._display_name(record.player)}**踏入基础机缘池。",
            "",
            f"- **抽取**：{'单抽' if record.draw_count == 1 else '十连'}",
            f"- **消耗**：{self._cost_text(record)}",
            self._draw_lines(record),
            f"- **获得**：{self._reward_text(record)}",
            f"- **保底进度**：{record.pity_after}/{FATE_PITY_LIMIT}",
            "",
            "> 单抽会优先消耗机缘签；十连固定消耗 450 灵石。结果已记档，重复请求不会重复扣费。",
        ]
        return CommandResult(
            True,
            "FATE_POOL_ROLLED",
            "\n".join(lines),
            context.request_id,
            operation_id,
            data={
                "pool_key": record.pool_key,
                "draw_count": record.draw_count,
                "cost_kind": record.cost_kind,
                "cost_quantity": record.cost_quantity,
                "pity_before": record.pity_before,
                "pity_after": record.pity_after,
                "seed_hash": record.seed_hash,
                "reward": record.reward,
                "draws": [
                    {
                        "key": draw.key,
                        "label": draw.label,
                        "rarity": draw.rarity,
                        "quantity": draw.quantity,
                        "guaranteed": draw.guaranteed,
                    }
                    for draw in record.draws
                ],
                "idempotent_replay": record.already_completed,
            },
        )


__all__ = ["GachaApplication"]
