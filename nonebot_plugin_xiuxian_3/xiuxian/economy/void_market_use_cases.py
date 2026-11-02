"""Application commands for the weekly void market."""

from __future__ import annotations

from ...contracts import CommandAction, CommandContext, CommandResult
from ..content import ContentBundle, bundled_content
from ..repository import (
    OperationConflictError,
    PlayerNotFoundError,
    PlayerSuspendedError,
    RepositoryBusyError,
    ResourceInsufficientError,
    SQLitePlayerRepository,
    VoidMarketDailyCapError,
    VoidMarketRequirementError,
    VoidMarketStockError,
)
from ..utils.text import command_link
from .void_market_rules import (
    VoidMarketDefinition,
    resolve_void_market_offer,
    void_market_definition,
)


class VoidMarketApplication:
    """Translate void market previews and purchases into adapter-neutral results."""

    def __init__(self, repository: SQLitePlayerRepository):
        self.repository = repository

    def _content(self) -> ContentBundle:
        content = getattr(self.repository, "content", None)
        return content if content is not None else bundled_content()

    def _definition(self) -> VoidMarketDefinition:
        return void_market_definition(self._content())

    def _item_label(self, item_key: str) -> str:
        content = self._content()
        try:
            return str(content.label("item", item_key))
        except KeyError:
            return item_key

    @staticmethod
    def _operation_id(context: CommandContext, suffix: str) -> str:
        if context.operation_id:
            return context.operation_id
        key = context.message_id or context.request_id
        return f"economy.void_market.{suffix}:{context.adapter}:{context.user_id}:{key}"

    def _preview_lines(self, record) -> list[str]:
        definition = self._definition()
        lines = [
            "## 虚空集市",
            "",
            "> 每周一 00:00（UTC）换库，共二十个库存槽；每名修士每日限购三件，"
            "购得的虚空材料绑定二十四小时。",
            "",
            f"- **本周库期**：{record.week_id} 起，余量 {record.stock_remaining}/{record.stock_slots}，"
            f"下次换库 {record.refresh_at}",
            f"- **今日额度**：已购 {record.daily_used}/{record.daily_limit} 件",
        ]
        if record.qualified:
            lines.append(
                f"- **准入**：满足（炼虚 L1 或虚空功勋 {definition.required_merit}）"
            )
        else:
            lines.append(f"- **准入**：尚缺 {'、'.join(record.missing)}")
        lines.append("")
        for offer in record.offers:
            price = offer.price_spirit_stones
            if offer.remaining <= 0:
                state = "本周已售罄"
                link = ""
            elif not record.qualified:
                state = "准入不足"
                link = ""
            elif not record.at_market:
                state = "需抵达虚空集市"
                link = ""
            elif record.daily_used >= record.daily_limit:
                state = "今日额度已满"
                link = ""
            else:
                state = f"可购入 {offer.quantity} 件"
                link = " · " + command_link("购买", f"购买虚空物资 {offer.label}")
            lines.append(
                f"- **{offer.label}**：灵石 {price} / 件 · 本周余量 {offer.remaining}/{offer.stock} · "
                f"{state}{link}"
            )
        if not record.at_market:
            lines.extend(
                [
                    "",
                    f"> 你当前不在集市；先{command_link('进入虚空航道', '进入虚空航道 虚空集市')}"
                    " 填写“虚空集市”，抵达后才可购买。",
                ]
            )
        elif record.qualified and record.daily_used < record.daily_limit:
            lines.extend(["", "> 点选物资后的“购买”可预填指令；成交后余量与额度立即扣减。"])
        return lines

    async def preview(self, context: CommandContext) -> CommandResult:
        definition = self._definition()
        if len(context.command_args) > 1:
            return CommandResult(
                False,
                "INVALID_VOID_MARKET_COMMAND",
                "虚空集市最多接收一个物资名。",
                context.request_id,
            )
        selected = None
        if context.command_args:
            offer_key = resolve_void_market_offer(context.command_args[0], self._content())
            if offer_key is None:
                return CommandResult(
                    False,
                    "VOID_MARKET_OFFER_NOT_FOUND",
                    "虚空集市里没有这件物资。",
                    context.request_id,
                )
            selected = definition.offer(offer_key)
        try:
            record = await self.repository.preview_void_market(
                platform=context.adapter, platform_user_id=context.user_id
            )
        except PlayerNotFoundError:
            return CommandResult(
                False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id
            )
        except PlayerSuspendedError:
            return CommandResult(
                False, "PLAYER_SUSPENDED", "当前角色暂时不能前往虚空集市。", context.request_id
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
            "week_id": record.week_id,
            "refresh_at": record.refresh_at,
            "stock_slots": record.stock_slots,
            "stock_remaining": record.stock_remaining,
            "daily_limit": record.daily_limit,
            "daily_used": record.daily_used,
            "at_market": record.at_market,
            "qualified": record.qualified,
            "missing": list(record.missing),
            "offers": [
                {
                    "key": offer.key,
                    "label": offer.label,
                    "item_key": offer.item_key,
                    "quantity": offer.quantity,
                    "price_spirit_stones": offer.price_spirit_stones,
                    "stock": offer.stock,
                    "remaining": offer.remaining,
                }
                for offer in record.offers
            ],
        }
        if selected is not None:
            state = next(offer for offer in record.offers if offer.key == selected.key)
            lines = [
                f"## 虚空集市 · {state.label}",
                "",
                f"- **价格**：灵石 {state.price_spirit_stones} / 件（每件 {state.quantity} 个）",
                f"- **本周余量**：{state.remaining}/{state.stock}",
                f"- **今日额度**：已购 {record.daily_used}/{record.daily_limit} 件",
            ]
            if not record.at_market:
                lines.append("- **状态**：需先抵达虚空集市")
            elif not record.qualified:
                lines.append(f"- **状态**：尚缺 {'、'.join(record.missing)}")
            elif state.remaining <= 0:
                lines.append("- **状态**：本周已售罄")
            elif record.daily_used >= record.daily_limit:
                lines.append("- **状态**：今日额度已满")
            else:
                lines.append("- **状态**：可购买")
            actions: tuple[CommandAction, ...] = ()
            if (
                record.at_market
                and record.qualified
                and state.remaining > 0
                and record.daily_used < record.daily_limit
            ):
                actions = (
                    CommandAction("购买此物资", f"购买虚空物资 {state.label}", enter=True),
                )
            return CommandResult(
                True,
                "VOID_MARKET_PREVIEW",
                "\n".join(lines),
                context.request_id,
                data={**data, "selected": state.key},
                actions=actions,
            )
        return CommandResult(
            True,
            "VOID_MARKET_PREVIEW",
            "\n".join(self._preview_lines(record)),
            context.request_id,
            data=data,
        )

    async def purchase(self, context: CommandContext) -> CommandResult:
        definition = self._definition()
        if not context.command_args or len(context.command_args) > 2:
            return CommandResult(
                False,
                "INVALID_VOID_MARKET_COMMAND",
                "请使用 `购买虚空物资 <物资名> [数量]`。",
                context.request_id,
            )
        offer_key = resolve_void_market_offer(context.command_args[0], self._content())
        if offer_key is None:
            return CommandResult(
                False,
                "VOID_MARKET_OFFER_NOT_FOUND",
                "虚空集市里没有这件物资。",
                context.request_id,
            )
        offer = definition.offer(offer_key)
        quantity = 1
        if len(context.command_args) == 2:
            raw = context.command_args[1].strip()
            if not raw.isdigit():
                return CommandResult(
                    False,
                    "INVALID_VOID_MARKET_COMMAND",
                    "购买数量需为不小于 1 的整数。",
                    context.request_id,
                )
            quantity = int(raw)
            if quantity < 1 or quantity > definition.daily_purchase_limit:
                return CommandResult(
                    False,
                    "INVALID_VOID_MARKET_COMMAND",
                    f"单次购买数量需在 1 到 {definition.daily_purchase_limit} 之间。",
                    context.request_id,
                )
        operation_id = self._operation_id(context, offer_key)
        try:
            record = await self.repository.purchase_void_market_offer(
                platform=context.adapter,
                platform_user_id=context.user_id,
                offer_key=offer_key,
                quantity=quantity,
                operation_id=operation_id,
            )
        except VoidMarketRequirementError:
            return CommandResult(
                False,
                "VOID_MARKET_REQUIREMENT_MISSING",
                "需在虚空集市，并满足炼虚 L1 或虚空功勋 "
                f"{definition.required_merit} 才能购买，未扣除任何资源。",
                context.request_id,
                operation_id,
            )
        except VoidMarketDailyCapError:
            return CommandResult(
                False,
                "VOID_DAILY_PURCHASE_CAP",
                f"今日已在虚空集市购买 {definition.daily_purchase_limit} 件，"
                "未扣除任何资源；明日再来。",
                context.request_id,
                operation_id,
            )
        except VoidMarketStockError:
            return CommandResult(
                False,
                "VOID_STOCK_SOLD_OUT",
                f"{offer.label} 本周库存不足，未扣除任何资源；下周换库后再看。",
                context.request_id,
                operation_id,
            )
        except ResourceInsufficientError:
            return CommandResult(
                False,
                "BALANCE_INSUFFICIENT",
                f"灵石不足，需要 {offer.price_spirit_stones * quantity} 灵石，未扣除任何物资。",
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
                "当前角色暂时不能购买虚空物资。",
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
            "VOID_MARKET_PURCHASED",
            (
                f"## 已购入 {record.label}\n\n"
                f"- **花费**：灵石 ×{record.total_cost}\n"
                f"- **获得**：{self._item_label(record.item_key)} ×{record.quantity}"
                f"（绑定至 {record.binding_expires_at}）\n"
                f"- **今日额度**：{record.daily_used}/{record.daily_limit} 件\n"
                f"- **本周余量**：{record.remaining}\n\n"
                "> 重复请求不会重复扣费。"
            ),
            context.request_id,
            operation_id,
            data={
                "purchase_id": record.purchase_id,
                "offer_key": record.offer_key,
                "item_key": record.item_key,
                "quantity": record.quantity,
                "unit_price": record.unit_price,
                "total_cost": record.total_cost,
                "week_id": record.week_id,
                "business_date": record.business_date,
                "daily_used": record.daily_used,
                "daily_limit": record.daily_limit,
                "remaining": record.remaining,
                "binding_expires_at": record.binding_expires_at,
                "idempotent_replay": record.already_completed,
            },
            actions=(CommandAction("再看虚空集市", "虚空集市", enter=True),),
        )


__all__ = ["VoidMarketApplication"]
