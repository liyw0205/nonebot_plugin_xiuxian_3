"""Application commands for the v0.1 bounty board."""

from __future__ import annotations

from datetime import datetime

from ...contracts import CommandContext, CommandResult
from ..repository import (
    BountyAlreadyClaimedError,
    BountyContentClosedError,
    BountyDailyLimitError,
    BountyExpiredError,
    BountyIncompleteError,
    BountyNotFoundError,
    BountyRequirementError,
    OperationConflictError,
    PlayerNotFoundError,
    PlayerSuspendedError,
    RepositoryBusyError,
    SQLitePlayerRepository,
)
from .rules import bounty_definition, default_content_bundle, resolve_bounty

STATUS_LABELS = {
    "available": "可接取",
    "accepted": "进行中",
    "completed": "待领取",
    "claimed": "已领取",
    "expired": "已过期",
    "daily_limit": "今日已接取其他悬赏",
    "requirement": "前置不足",
    "locked": "战斗功能未开放",
}


class AdventuresApplication:
    """Coordinates bounty reads and writes without duplicating domain rules."""

    def __init__(self, repository: SQLitePlayerRepository):
        self.repository = repository

    @staticmethod
    def _operation_id(context: CommandContext, operation_name: str) -> str:
        if context.operation_id:
            return context.operation_id
        request_key = context.message_id or context.request_id
        return f"{operation_name}:{context.adapter}:{context.user_id}:{request_key}"

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

    def _reward_text(self, rewards: dict[str, int], bounty_key: str | None = None) -> str:
        labels = {
            "spirit_stones": "灵石",
            "cultivation": "修为",
            "energy": "精力",
            "local_reputation": "城镇名望",
            "service_reputation": "服务信誉",
        }
        content = self.repository.content or default_content_bundle()
        configured_labels = {}
        if bounty_key is not None:
            configured_labels = bounty_definition(bounty_key, content).reward_labels
        parts: list[str] = []
        for key, quantity in rewards.items():
            if not quantity:
                continue
            label = configured_labels.get(key) or labels.get(key)
            if label is None and key.startswith("item."):
                label = content.label("item", key, fallback=key)
            if label is None and key.startswith("faction_reputation."):
                label = f"{key.removeprefix('faction_reputation.')}声望"
            label = label or "悬赏奖励"
            parts.append(f"{label} +{quantity}")
        return "、".join(parts) or "无"

    def _deadline_text(self, expires_at: str | None) -> str:
        if not expires_at:
            return ""
        try:
            seconds = max(0, int((datetime.fromisoformat(expires_at) - self.repository._now()).total_seconds()))
        except ValueError:
            return ""
        if seconds >= 3600:
            return f"约 {seconds // 3600} 小时后"
        return f"约 {max(1, seconds // 60)} 分钟后"

    def _bounty_args(self, args: tuple[str, ...]) -> tuple[bool, str | None]:
        if not args:
            return True, None
        if len(args) != 1:
            return False, None
        return True, resolve_bounty(args[0], self.repository.content)

    async def list_bounties(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_BOUNTY_COMMAND", "悬赏榜无需附加参数。", context.request_id)
        try:
            record = await self.repository.get_bounty_board(
                platform=context.adapter,
                platform_user_id=context.user_id,
            )
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能查看悬赏榜。", context.request_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, retryable=True)

        lines = [f"## 悬赏榜 · {record.business_date}", "", f"**{self._display_name(record.player)}**，今日悬赏如下：", ""]
        offer_data = []
        for offer in record.offers:
            status = STATUS_LABELS.get(offer.status, "暂不可用")
            progress = f"{offer.progress}/{offer.target}" if offer.target else "无需进度"
            deadline = self._deadline_text(offer.expires_at)
            expires = f"\n  - **截止**：{deadline}" if deadline else ""
            lines.extend(
                [
                    f"### {offer.label} · {status}",
                    f"- **目标**：{offer.description}（{progress}）",
                    f"- **奖励**：{self._reward_text(offer.reward, offer.key)}{expires}",
                    "",
                ]
            )
            offer_data.append(
                {
                    "bounty_key": offer.key,
                    "label": offer.label,
                    "status": offer.status,
                    "progress": offer.progress,
                    "target": offer.target,
                    "reward": offer.reward,
                    "expires_at": offer.expires_at,
                }
            )
        lines.append("> 每日最多接取一条悬赏；使用对应的 `接取悬赏 <名称>` 开始。")
        return CommandResult(
            True,
            "BOUNTY_BOARD",
            "\n".join(lines),
            context.request_id,
            data={"business_date": record.business_date, "offers": offer_data},
        )

    async def accept_bounty(self, context: CommandContext) -> CommandResult:
        valid, bounty_key = self._bounty_args(context.command_args)
        if not valid:
            return CommandResult(False, "INVALID_BOUNTY_COMMAND", "请发送 `接取悬赏` 随机领取，或指定悬赏名称。", context.request_id)
        operation_id = self._operation_id(context, "bounty.accept")
        try:
            record = await self.repository.accept_bounty(
                platform=context.adapter,
                platform_user_id=context.user_id,
                bounty_key=bounty_key,
                operation_id=operation_id,
            )
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色处于暂停状态，暂时不能接取悬赏。", context.request_id, operation_id)
        except BountyContentClosedError:
            return CommandResult(False, "CONTENT_CLOSED", "这条悬赏依赖的战斗功能尚未开放。", context.request_id, operation_id)
        except BountyRequirementError:
            return CommandResult(False, "BOUNTY_REQUIREMENT_MISSING", "当前阶段、境界或地区许可不满足这条悬赏。", context.request_id, operation_id)
        except BountyDailyLimitError:
            return CommandResult(False, "BOUNTY_DAILY_LIMIT", "今日已经接取过悬赏，请明日再来。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于其他悬赏操作，请重新发起。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        return CommandResult(
            True,
            "BOUNTY_ACCEPTED",
            (
                f"## 悬赏已接取\n\n**{self._display_name(record.player)}**已接取 **{record.label}**。\n\n"
                f"- **进度**：{record.progress}/{record.target}\n"
                f"- **有效期**：{self._deadline_text(record.expires_at)}\n\n"
                "> 完成目标后发送 `领取悬赏`；同一悬赏不会重复发奖。"
            ),
            context.request_id,
            operation_id,
            data={
                "bounty_key": record.bounty_key,
                "status": record.status,
                "progress": record.progress,
                "target": record.target,
                "expires_at": record.expires_at,
                "idempotent_replay": record.already_completed,
            },
        )

    async def claim_bounty(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_BOUNTY_COMMAND", "领取悬赏无需附加参数。", context.request_id)
        operation_id = self._operation_id(context, "bounty.claim")
        try:
            record = await self.repository.claim_bounty(
                platform=context.adapter,
                platform_user_id=context.user_id,
                operation_id=operation_id,
            )
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能领取悬赏。", context.request_id, operation_id)
        except BountyNotFoundError:
            return CommandResult(False, "BOUNTY_NOT_FOUND", "当前没有等待领取的悬赏。", context.request_id, operation_id)
        except BountyAlreadyClaimedError:
            return CommandResult(False, "BOUNTY_REWARD_ALREADY_CLAIMED", "这条悬赏的奖励已经领取过了。", context.request_id, operation_id)
        except BountyIncompleteError:
            return CommandResult(False, "BOUNTY_NOT_COMPLETE", "悬赏目标尚未完成，暂时不能领取奖励。", context.request_id, operation_id)
        except BountyExpiredError:
            return CommandResult(False, "BOUNTY_EXPIRED", "悬赏已过期，本次不发放奖励。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于其他悬赏领取，请重新发起。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        return CommandResult(
            True,
            "BOUNTY_CLAIMED",
            (
                f"## 悬赏奖励已领取\n\n**{self._display_name(record.player)}**完成了 **{record.label}**。\n\n"
                f"- **进度**：{record.progress}/{record.target}\n"
                f"- **奖励**：{self._reward_text(record.rewards, record.bounty_key)}\n\n"
                "> 奖励已写入角色资产，重复领取不会再次发放。"
            ),
            context.request_id,
            operation_id,
            data={
                "bounty_key": record.bounty_key,
                "status": record.status,
                "progress": record.progress,
                "target": record.target,
                "rewards": record.rewards,
                "idempotent_replay": record.already_completed,
            },
        )


__all__ = ["AdventuresApplication"]
