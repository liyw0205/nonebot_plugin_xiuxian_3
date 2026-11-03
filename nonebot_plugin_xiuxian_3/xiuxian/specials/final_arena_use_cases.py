"""Application commands for the endgame final arena."""

from __future__ import annotations

from ...contracts import CommandAction, CommandContext, CommandResult
from ..content import ContentBundle, bundled_content
from ..persistence.errors import (
    BattleBusyError,
    BattleCooldownError,
    FinalArenaAttemptCapError,
    FinalArenaChallengeNotFoundError,
    FinalArenaLocationRequiredError,
    FinalArenaNotOpenError,
    FinalArenaTierLockedError,
    OperationConflictError,
    PlayerNotFoundError,
    PlayerSuspendedError,
    RepositoryBusyError,
    ResourceInsufficientError,
)
from ..utils.text import command_link
from .final_arena_rules import (
    FinalArenaDefinition,
    resolve_final_arena_tier,
)

EVENT_KEY = "event.final_arena"


class FinalArenaApplication:
    """Translate final arena previews and challenges into adapter-neutral results."""

    def __init__(self, repository) -> None:
        self.repository = repository

    def _content(self) -> ContentBundle:
        content = getattr(self.repository, "content", None)
        return content if content is not None else bundled_content()

    def _definition(self) -> FinalArenaDefinition:
        from .final_arena_rules import final_arena_definition

        return final_arena_definition(self._content())

    @staticmethod
    def _operation_id(context: CommandContext, name: str) -> str:
        if context.operation_id:
            return context.operation_id
        key = context.message_id or context.request_id
        return f"{name}:{context.adapter}:{context.user_id}:{key}"

    def _preview_lines(self, record) -> list[str]:
        definition = self._definition()
        state = "开放中" if record.open else "已结束"
        lines = [
            "## 终局天榜",
            "",
            "> 天榜只在活动轮次内开放，每个 UTC 四小时轮次最多挑战三次；"
            "榜上名次只作展示与见闻，不影响飞升资格。",
            "",
            f"- **本轮**：{record.round_id}",
            f"- **轮次窗口**：{record.starts_at} 至 {record.ends_at}（当前{state}）",
            f"- **本轮次数**：已用 {record.attempts_used}/{record.attempt_limit}",
            f"- **你的进度**：最高层级 {record.best_tier}/{len(definition.tiers)}"
            f"{'，上阶已首通' if record.summit_cleared else ''}",
        ]
        if record.qualified:
            lines.append(
                f"- **准入**：满足（{definition.required_realm} L{definition.required_layer}）"
            )
        else:
            lines.append(f"- **准入**：尚缺 {'、'.join(record.missing)}")
        if not record.at_location:
            lines.append("- **位置**：需先抵达终局天榜")
        lines.append("")
        for tier in record.tiers:
            if tier.cleared:
                status = "已首通"
            elif not tier.unlocked:
                status = "需先首通上一层"
            elif not record.at_location:
                status = "需抵达终局天榜"
            elif not record.qualified:
                status = "准入不足"
            elif not record.open:
                status = "轮次未开放"
            elif record.attempts_used >= record.attempt_limit:
                status = "本轮次数已用尽"
            else:
                status = "可挑战"
            link = (
                " · " + command_link("挑战", f"挑战天榜 {tier.label}")
                if status == "可挑战"
                else ""
            )
            lines.append(
                f"- **{tier.label}**：第 {tier.tier_no} 重守榜人 · 体力 {definition.stamina_cost} · "
                f"{status}{link}"
            )
        if not record.at_location:
            lines.extend(
                [
                    "",
                    f"> 先{command_link('前往终局天榜', '前往 终局天榜')}"
                    "（需渡劫 L6，从天劫台出发）再挑战。",
                ]
            )
        elif record.qualified and record.open:
            lines.extend(["", "> 点选层级后的“挑战”可预填指令；每次挑战会冻结本轮层级与守榜人。"])
        return lines

    async def preview(self, context: CommandContext) -> CommandResult:
        definition = self._definition()
        if len(context.command_args) > 1:
            return CommandResult(
                False,
                "INVALID_FINAL_ARENA_COMMAND",
                "终局天榜最多接收一个层级名。",
                context.request_id,
            )
        selected = None
        if context.command_args:
            tier_key = resolve_final_arena_tier(context.command_args[0], self._content())
            if tier_key is None:
                return CommandResult(
                    False,
                    "INVALID_FINAL_ARENA_COMMAND",
                    "没有这一层天榜。",
                    context.request_id,
                )
            selected = definition.tier(tier_key)
        try:
            record = await self.repository.preview_final_arena(
                platform=context.adapter, platform_user_id=context.user_id
            )
        except PlayerNotFoundError:
            return CommandResult(
                False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id
            )
        except PlayerSuspendedError:
            return CommandResult(
                False, "PLAYER_SUSPENDED", "当前角色暂时不能登临天榜。", context.request_id
            )
        except RepositoryBusyError:
            return CommandResult(
                False,
                "PERSISTENCE_BUSY",
                "仙缘簿暂时繁忙，请稍后再试。",
                context.request_id,
                retryable=True,
            )
        except Exception:
            return CommandResult(
                False,
                "PERSISTENCE_ERROR",
                "仙缘簿暂时不可用，请稍后再试。",
                context.request_id,
                retryable=True,
            )
        data = {
            "location_key": record.location_key,
            "round_id": record.round_id,
            "starts_at": record.starts_at,
            "ends_at": record.ends_at,
            "claim_expires_at": record.claim_expires_at,
            "open": record.open,
            "at_location": record.at_location,
            "qualified": record.qualified,
            "missing": list(record.missing),
            "attempt_limit": record.attempt_limit,
            "attempts_used": record.attempts_used,
            "best_tier": record.best_tier,
            "summit_cleared": record.summit_cleared,
            "tiers": [
                {
                    "key": tier.key,
                    "label": tier.label,
                    "tier_no": tier.tier_no,
                    "enemy_key": tier.enemy_key,
                    "required_best_tier": tier.required_best_tier,
                    "unlocked": tier.unlocked,
                    "cleared": tier.cleared,
                    "title_key": tier.title_key,
                }
                for tier in record.tiers
            ],
        }
        if selected is not None:
            tier_state = next(tier for tier in record.tiers if tier.key == selected.key)
            lines = [
                f"## 终局天榜 · {tier_state.label}",
                "",
                f"- **位次**：第 {tier_state.tier_no} 重守榜人",
                f"- **本轮次数**：已用 {record.attempts_used}/{record.attempt_limit}",
                f"- **前置**："
                + (
                    "无需前置"
                    if tier_state.required_best_tier == 0
                    else f"需已首通第 {tier_state.required_best_tier} 重"
                ),
                f"- **本轮窗口**：{record.starts_at} 至 {record.ends_at}",
            ]
            if tier_state.cleared:
                lines.append("- **状态**：已首通（可再战练习）")
            elif not tier_state.unlocked:
                lines.append("- **状态**：需先首通上一层")
            elif not record.at_location:
                lines.append("- **状态**：需先抵达终局天榜")
            elif not record.qualified:
                lines.append(f"- **状态**：尚缺 {'、'.join(record.missing)}")
            elif not record.open:
                lines.append("- **状态**：当前轮次未开放")
            elif record.attempts_used >= record.attempt_limit:
                lines.append("- **状态**：本轮次数已用尽")
            else:
                lines.append("- **状态**：可挑战")
            actions: tuple[CommandAction, ...] = ()
            if (
                record.at_location
                and record.qualified
                and record.open
                and tier_state.unlocked
                and record.attempts_used < record.attempt_limit
            ):
                actions = (
                    CommandAction("挑战此层级", f"挑战天榜 {tier_state.label}", enter=True),
                )
            return CommandResult(
                True,
                "FINAL_ARENA_PREVIEW",
                "\n".join(lines),
                context.request_id,
                data={**data, "selected": tier_state.key},
                actions=actions,
            )
        return CommandResult(
            True,
            "FINAL_ARENA_PREVIEW",
            "\n".join(self._preview_lines(record)),
            context.request_id,
            data=data,
        )

    async def challenge(self, context: CommandContext) -> CommandResult:
        definition = self._definition()
        if len(context.command_args) != 1:
            return CommandResult(
                False,
                "INVALID_FINAL_ARENA_COMMAND",
                "请使用 `挑战天榜 <层级>`。",
                context.request_id,
            )
        tier_key = resolve_final_arena_tier(context.command_args[0], self._content())
        if tier_key is None:
            return CommandResult(
                False,
                "INVALID_FINAL_ARENA_COMMAND",
                "没有这一层天榜。",
                context.request_id,
            )
        tier = definition.tier(tier_key)
        operation_id = self._operation_id(context, "specials.final_arena.challenge")
        try:
            record = await self.repository.start_final_arena_challenge(
                platform=context.adapter,
                platform_user_id=context.user_id,
                tier_key=tier_key,
                operation_id=operation_id,
            )
        except FinalArenaNotOpenError:
            return CommandResult(
                False,
                "FINAL_ARENA_NOT_OPEN",
                "当前不在天榜活动轮次内，未扣除体力；请在开放轮次再来。",
                context.request_id,
                operation_id,
            )
        except FinalArenaLocationRequiredError:
            return CommandResult(
                False,
                "FINAL_ARENA_LOCATION_REQUIRED",
                f"需抵达终局天榜并满足渡劫 L{definition.required_layer}，未扣除任何资源。",
                context.request_id,
                operation_id,
            )
        except FinalArenaTierLockedError:
            return CommandResult(
                False,
                "FINAL_ARENA_TIER_LOCKED",
                f"需先首通上一层天榜，才能挑战{tier.label}，未扣除任何资源。",
                context.request_id,
                operation_id,
            )
        except FinalArenaAttemptCapError:
            return CommandResult(
                False,
                "FINAL_ARENA_ATTEMPT_CAP",
                f"本轮已挑战 {definition.attempt_limit_per_round} 次，未扣除体力；"
                "下个轮次再来。",
                context.request_id,
                operation_id,
            )
        except ResourceInsufficientError:
            return CommandResult(
                False,
                "STAMINA_INSUFFICIENT",
                f"体力不足，需要 {definition.stamina_cost} 点体力，未进入天榜。",
                context.request_id,
                operation_id,
            )
        except BattleCooldownError:
            return CommandResult(
                False,
                "BATTLE_COOLDOWN",
                "战败余悸未消，暂时不能登临天榜。",
                context.request_id,
                operation_id,
            )
        except BattleBusyError:
            return CommandResult(
                False,
                "BATTLE_BUSY",
                "当前还有未结束的战斗、天榜挑战或长时行动，未进入天榜。",
                context.request_id,
                operation_id,
            )
        except PlayerNotFoundError:
            return CommandResult(
                False,
                "PLAYER_NOT_FOUND",
                "还没有角色，请先发送 `开始修仙`。",
                context.request_id,
                operation_id,
            )
        except PlayerSuspendedError:
            return CommandResult(
                False,
                "PLAYER_SUSPENDED",
                "当前角色暂时不能登临天榜。",
                context.request_id,
                operation_id,
            )
        except OperationConflictError:
            return CommandResult(
                False,
                "LEDGER_CONFLICT",
                "此事已有安排，请重新起意。",
                context.request_id,
                operation_id,
            )
        except RepositoryBusyError:
            return CommandResult(
                False,
                "PERSISTENCE_BUSY",
                "仙缘簿暂时繁忙，请稍后再试。",
                context.request_id,
                operation_id,
                retryable=True,
            )
        except Exception:
            return CommandResult(
                False,
                "PERSISTENCE_ERROR",
                "仙缘簿暂时不可用，请稍后再试。",
                context.request_id,
                operation_id,
                retryable=True,
            )
        return CommandResult(
            True,
            "FINAL_ARENA_SETTLED",
            self._settlement_message(record),
            context.request_id,
            operation_id,
            data=self._settlement_data(record),
            actions=(CommandAction("再看终局天榜", "终局天榜", enter=True),),
        )

    async def settle(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(
                False,
                "INVALID_FINAL_ARENA_COMMAND",
                "结算天榜无需附加参数。",
                context.request_id,
            )
        operation_id = self._operation_id(context, "specials.final_arena.settle")
        try:
            record = await self.repository.settle_final_arena_challenge(
                platform=context.adapter,
                platform_user_id=context.user_id,
                operation_id=operation_id,
            )
        except FinalArenaChallengeNotFoundError:
            return CommandResult(
                False,
                "FINAL_ARENA_CHALLENGE_NOT_FOUND",
                "当前没有未结算的天榜挑战。",
                context.request_id,
                operation_id,
            )
        except PlayerNotFoundError:
            return CommandResult(
                False,
                "PLAYER_NOT_FOUND",
                "还没有角色，请先发送 `开始修仙`。",
                context.request_id,
                operation_id,
            )
        except PlayerSuspendedError:
            return CommandResult(
                False,
                "PLAYER_SUSPENDED",
                "当前角色暂时不能结算天榜。",
                context.request_id,
                operation_id,
            )
        except OperationConflictError:
            return CommandResult(
                False,
                "LEDGER_CONFLICT",
                "此事已有安排，请重新起意。",
                context.request_id,
                operation_id,
            )
        except RepositoryBusyError:
            return CommandResult(
                False,
                "PERSISTENCE_BUSY",
                "仙缘簿暂时繁忙，请稍后再试。",
                context.request_id,
                operation_id,
                retryable=True,
            )
        except Exception:
            return CommandResult(
                False,
                "PERSISTENCE_ERROR",
                "仙缘簿暂时不可用，请稍后再试。",
                context.request_id,
                operation_id,
                retryable=True,
            )
        return CommandResult(
            True,
            "FINAL_ARENA_SETTLED",
            self._settlement_message(record),
            context.request_id,
            operation_id,
            data=self._settlement_data(record),
            actions=(CommandAction("再看终局天榜", "终局天榜", enter=True),),
        )

    def _settlement_message(self, record) -> str:
        outcome = {
            "won": "破关",
            "lost": "落败",
            "expired": "已取消",
        }.get(record.outcome, "未分胜负")
        lines = [
            f"## 终局天榜 · {record.label}",
            "",
            f"- **结果**：{outcome}",
            f"- **轮次**：{record.round_id}",
            f"- **本轮次数**：已用 {record.attempts_used}/{record.attempt_limit}",
            f"- **你的最高层级**：{record.best_tier}",
        ]
        if record.outcome == "won":
            lines.append("- **榜上记录**：本层已记入你的天榜进度")
        else:
            lines.append("- **榜上记录**：本层未记入，未扣除任何资产")
        if record.title_granted:
            lines.append("- **首通称号**：终局天榜上阶首通，已获展示称号「终榜留名」")
        lines.extend(["", "> 天榜只记录展示与见闻，不影响飞升资格。"])
        return "\n".join(lines)

    @staticmethod
    def _settlement_data(record) -> dict[str, object]:
        return {
            "challenge_id": record.challenge_id,
            "tier_key": record.tier_key,
            "tier_no": record.tier_no,
            "enemy_key": record.enemy_key,
            "round_id": record.round_id,
            "starts_at": record.starts_at,
            "ends_at": record.ends_at,
            "attempts_used": record.attempts_used,
            "attempt_limit": record.attempt_limit,
            "best_tier": record.best_tier,
            "status": record.status,
            "outcome": record.outcome,
            "reason": record.reason,
            "summit_cleared": record.summit_cleared,
            "title_granted": record.title_granted,
            "idempotent_replay": record.already_completed,
        }


__all__ = ["EVENT_KEY", "FinalArenaApplication"]
