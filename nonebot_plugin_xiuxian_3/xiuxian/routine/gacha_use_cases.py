"""Application commands for the fate treasure pool."""

from __future__ import annotations

from ...contracts import CommandContext, CommandResult
from ..content import ContentError, bundled_content
from ..repository import (
    FateDrawInsufficientError,
    FatePoolInvalidError,
    FatePoolNotOpenError,
    FatePoolRequirementError,
    OperationConflictError,
    PlayerNotFoundError,
    PlayerSuspendedError,
    RepositoryBusyError,
    SQLitePlayerRepository,
)
from .gacha import FATE_POOL_KEY, fate_pool_definition, resolve_fate_pool_key
from .models import FateRollRecord


class GachaApplication:
    """Coordinates deterministic treasure rolls and Markdown responses."""

    def __init__(self, repository: SQLitePlayerRepository):
        self.repository = repository

    @staticmethod
    def _operation_id(context: CommandContext, pool_key: str, draw_count: int) -> str:
        if context.operation_id:
            return context.operation_id
        request_key = context.message_id or context.request_id
        return f"routine.roll_fate_pool:{pool_key}:{draw_count}:{context.adapter}:{context.user_id}:{request_key}"

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
    def _pool_and_draw_count(args: tuple[str, ...], content) -> tuple[str, int] | None:
        aliases = {
            "单抽": 1,
            "一抽": 1,
            "1": 1,
            "十连": 10,
            "十连抽": 10,
            "10": 10,
        }
        tokens = tuple(item.strip() for item in args if item.strip())
        if not tokens:
            return FATE_POOL_KEY, 1
        if len(tokens) == 1 and tokens[0].casefold() in aliases:
            return FATE_POOL_KEY, aliases[tokens[0].casefold()]
        if len(tokens) == 2 and tokens[1].casefold() in aliases:
            try:
                return resolve_fate_pool_key(tokens[0], content, include_locked=True), aliases[tokens[1].casefold()]
            except (ValueError, ContentError):
                return None
        return None

    @staticmethod
    def _draw_count(args: tuple[str, ...]) -> int | None:
        aliases = {
            "单抽": 1,
            "一抽": 1,
            "1": 1,
            "十连": 10,
            "十连抽": 10,
            "10": 10,
        }
        tokens = tuple(item.strip() for item in args if item.strip())
        if len(tokens) != 2:
            return None
        return aliases.get(tokens[1].casefold())

    @staticmethod
    def _cost_text(record: FateRollRecord) -> str:
        label = "机缘签" if record.cost_kind == "ticket" else "灵石"
        return f"{label} ×{record.cost_quantity}"

    @staticmethod
    def _reward_text(record: FateRollRecord) -> str:
        labels = {draw.key: draw.label for draw in record.draws}
        return "、".join(
            f"**{labels.get(key, key)} ×{quantity}**"
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
        content = self.repository.content or bundled_content()
        parsed = self._pool_and_draw_count(context.command_args, content)
        if parsed is None and context.operation_id:
            draw_count = self._draw_count(context.command_args)
            if draw_count is not None:
                try:
                    pool_key = await self.repository.fate_pool_key_for_operation(
                        platform=context.adapter,
                        platform_user_id=context.user_id,
                        operation_id=context.operation_id,
                    )
                except Exception:
                    return CommandResult(
                        False,
                        "PERSISTENCE_ERROR",
                        "仙缘簿暂时不可用，请稍后再试。",
                        context.request_id,
                        context.operation_id,
                        retryable=True,
                    )
                if pool_key:
                    parsed = pool_key, draw_count
        if parsed is None:
            return CommandResult(
                False,
                "INVALID_FATE_COMMAND",
                "请使用 `机缘寻宝`、`机缘寻宝 单抽` 或 `机缘寻宝 十连`。",
                context.request_id,
            )
        pool_key, draw_count = parsed
        try:
            pool = fate_pool_definition(pool_key, content, include_locked=True)
        except ContentError:
            return CommandResult(False, "FATE_POOL_NOT_OPEN", "当前机缘池暂不可用。", context.request_id)
        operation_id = self._operation_id(context, pool_key, draw_count)
        try:
            record = await self.repository.roll_fate_pool(
                platform=context.adapter,
                platform_user_id=context.user_id,
                pool_key=pool_key,
                draw_count=draw_count,
                operation_id=operation_id,
            )
        except FatePoolInvalidError:
            return CommandResult(False, "INVALID_FATE_COMMAND", "这类机缘池尚未开放。", context.request_id, operation_id)
        except FatePoolNotOpenError:
            return CommandResult(False, "FATE_POOL_NOT_OPEN", "当前机缘池暂不可用，请稍后再试。", context.request_id, operation_id)
        except FatePoolRequirementError:
            return CommandResult(False, "FATE_POOL_REQUIREMENT_MISSING", "当前境界尚未听见这道回响。", context.request_id, operation_id)
        except FateDrawInsufficientError:
            cost = (
                f"{pool.single_cost} 灵石" + (f"或 {pool.ticket_quantity} 张机缘签" if pool.ticket_key else "")
                if draw_count == 1
                else f"{pool.ten_cost} 灵石"
            )
            return CommandResult(False, "FATE_DRAW_INSUFFICIENT", f"机缘寻宝需要 {cost}，未扣除任何资源。", context.request_id, operation_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能进行机缘寻宝。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "此事已有安排，请重新起意。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)

        lines = [
            "## 机缘寻宝",
            "",
            f"**{self._display_name(record.player)}**踏入{record.pool_name}。",
            "",
            f"- **抽取**：{'单抽' if record.draw_count == 1 else '十连'}",
            f"- **消耗**：{self._cost_text(record)}",
            self._draw_lines(record),
            f"- **获得**：{self._reward_text(record)}",
            f"- **保底进度**：{record.pity_after}/{record.pity_limit}",
            "",
            "> 结果已记档，重复请求不会重复扣费。",
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
