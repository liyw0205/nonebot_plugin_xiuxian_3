"""SQLite transactions for the limited weekly auction."""

from __future__ import annotations

import asyncio
import json
from dataclasses import fields
from datetime import date, datetime, timedelta
from typing import Any
from uuid import uuid4

from ...contracts import serialize_datetime
from ..persistence.errors import (
    AuctionBidTooLowError,
    AuctionItemLockedError,
    AuctionNotFoundError,
    AuctionSelfBidError,
    AuctionSlotFullError,
    AuctionStateConflictError,
    BalanceInsufficientError,
    PlayerNotFoundError,
)
from ..utils.assets import (
    apply_player_asset_transition,
    inventory_amount,
    player_currency,
    reserved_inventory_quantity,
)
from ..utils.json_cache import decode_json_strict
from ..utils.operations import operation_replay, record_operation
from ..utils.player import player_inventory
from .auction_models import AuctionRecord
from .bindings import active_binding_totals
from .auction_rules import (
    AuctionDefinition,
    auction_definition,
    auction_definition_from_snapshot,
    auction_week_start,
    minimum_next_bid,
    validate_auction_listing,
)


class AuctionRepositoryMixin:
    async def create_auction(
        self, *, platform: str, platform_user_id: str, item_key: str,
        quantity: int, starting_bid: int, operation_id: str
    ) -> AuctionRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._create_auction_once, platform, platform_user_id,
                item_key, quantity, starting_bid, operation_id
            )

    async def bid_auction(
        self, *, platform: str, platform_user_id: str, auction_id: str,
        bid_amount: int, operation_id: str
    ) -> AuctionRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._bid_auction_once, platform, platform_user_id,
                auction_id, bid_amount, operation_id
            )

    async def settle_auction(
        self, *, platform: str, platform_user_id: str,
        auction_id: str, operation_id: str
    ) -> AuctionRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._settle_auction_once, platform, platform_user_id,
                auction_id, operation_id
            )

    async def list_auctions(self, *, platform: str, platform_user_id: str) -> tuple[AuctionRecord, ...]:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._list_auctions_once, platform, platform_user_id)

    def _create_auction_once(
        self, platform: str, platform_user_id: str, item_key: str,
        quantity: int, starting_bid: int, operation_id: str
    ) -> AuctionRecord:
        item_selector = item_key.strip()
        operation_name = "economy.create_auction"
        request_hash = self._request_hash(operation_name, {
            "platform": platform, "platform_user_id": platform_user_id,
            "item_key": item_selector, "quantity": quantity,
            "starting_bid": starting_bid,
        })
        now = self._now()
        now_text = serialize_datetime(now)
        week_start = auction_week_start(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            seller = self._require_player(connection, platform, platform_user_id)
            existing = operation_replay(connection, operation_id, operation_name, request_hash, player_id=int(seller["id"]))
            if existing is not None:
                return self._auction_from_payload(
                    existing, replay=True, operation_name=operation_name,
                    expected_fields={"quantity": quantity, "starting_bid": starting_bid,
                                     "seller_platform_user_id": platform_user_id},
                )
            definition = auction_definition(self.content)
            try:
                item = validate_auction_listing(item_selector, quantity, starting_bid, definition, self.content)
            except ValueError as exc:
                from ..persistence.errors import MarketItemForbiddenError, MarketPriceInvalidError
                if "item" in str(exc):
                    raise MarketItemForbiddenError(str(exc)) from exc
                raise MarketPriceInvalidError(str(exc)) from exc
            active_count = connection.execute(
                "SELECT COUNT(*) FROM auction_lots WHERE week_start=? AND status IN ('open', 'settling')",
                (week_start,),
            ).fetchone()[0]
            if int(active_count) >= definition.slot_limit:
                raise AuctionSlotFullError("weekly auction slots are full")
            inventory = player_inventory(seller)
            reserved = reserved_inventory_quantity(connection, int(seller["id"]), item.key)
            bound, _ = active_binding_totals(connection, int(seller["id"]), item.key, now_text)
            available = inventory_amount(inventory, item.key) - reserved
            if available < int(quantity):
                raise AuctionItemLockedError("auction item is not available")
            if available - int(bound) < int(quantity):
                from ..persistence.errors import ItemBindingActiveError
                raise ItemBindingActiveError("auction item is still bound")
            auction_id = f"auction-{uuid4().hex}"
            ends_at = now + timedelta(seconds=definition.duration_seconds)
            settlement_deadline = ends_at + timedelta(seconds=definition.settlement_grace_seconds)
            snapshot = {
                "auction_id": auction_id, "week_start": week_start,
                "seller_player_id": int(seller["id"]),
                "item_key": item.key, "item_label": item.label, "quantity": quantity,
                "starting_bid": starting_bid, "created_at": now_text,
                "ends_at": serialize_datetime(ends_at),
                "settlement_deadline": serialize_datetime(settlement_deadline),
                "rules": definition.snapshot(),
            }
            connection.execute(
                """INSERT INTO auction_lots(
                    auction_id, seller_player_id, week_start, item_key, quantity,
                    starting_bid, current_bid, current_bidder_player_id, status,
                    ends_at, settlement_deadline, snapshot_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 0, NULL, 'open', ?, ?, ?, ?, ?)""",
                (auction_id, seller["id"], week_start, item.key, int(quantity), int(starting_bid),
                 serialize_datetime(ends_at), serialize_datetime(settlement_deadline),
                 json.dumps(snapshot, ensure_ascii=False, sort_keys=True), now_text, now_text),
            )
            connection.execute(
                "INSERT INTO auction_item_locks(auction_id, seller_player_id, item_key, quantity, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (auction_id, seller["id"], item.key, int(quantity), now_text, now_text),
            )
            self._auction_ledger(connection, operation_id, int(seller["id"]), "item", item.key,
                                 "auction.item_lock", "lock", int(quantity), available, available - int(quantity), auction_id, now_text)
            payload = self._auction_payload(connection, auction_id)
            record_operation(connection, operation_id, operation_name, int(seller["id"]), request_hash, payload, now_text)
            return self._auction_from_payload(payload, operation_name=operation_name)

    def _bid_auction_once(
        self, platform: str, platform_user_id: str,
        auction_id: str, bid_amount: int, operation_id: str
    ) -> AuctionRecord:
        operation_name = "economy.bid_auction"
        request_hash = self._request_hash(operation_name, {
            "platform": platform, "platform_user_id": platform_user_id,
            "auction_id": auction_id, "bid_amount": bid_amount,
        })
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            bidder = self._require_player(connection, platform, platform_user_id)
            existing = operation_replay(connection, operation_id, operation_name, request_hash, player_id=int(bidder["id"]))
            if existing is not None:
                return self._auction_from_payload(
                    existing, replay=True, operation_name=operation_name,
                    expected_fields={"auction_id": auction_id, "current_bid": bid_amount,
                                     "current_bidder_platform_user_id": platform_user_id},
                )
            if isinstance(bid_amount, bool) or not isinstance(bid_amount, int) or bid_amount <= 0:
                from ..persistence.errors import MarketPriceInvalidError
                raise MarketPriceInvalidError("bid amount must be a positive integer")
            lot = connection.execute("SELECT * FROM auction_lots WHERE auction_id=?", (auction_id,)).fetchone()
            if lot is None:
                raise AuctionNotFoundError("auction does not exist")
            if int(lot["seller_player_id"]) == int(bidder["id"]):
                raise AuctionSelfBidError("seller cannot bid on own auction")
            _, definition = self._auction_snapshot(lot)
            if str(lot["status"]) != "open" or datetime.fromisoformat(lot["ends_at"]) <= now:
                raise AuctionStateConflictError("auction is closed")
            previous = self._auction_open_state(connection, lot)
            required = minimum_next_bid(lot["current_bid"], lot["starting_bid"], definition.min_increment_bp)
            if int(bid_amount) < required:
                raise AuctionBidTooLowError(f"minimum bid is {required}")
            refund = int(previous["bid_amount"]) if previous is not None else 0
            available_balance = player_currency(bidder) + (refund if previous is not None and int(previous["bidder_player_id"]) == int(bidder["id"]) else 0)
            if available_balance < int(bid_amount):
                raise BalanceInsufficientError("auction bid balance is insufficient")
            if previous is not None:
                self._refund_bid(connection, previous, operation_id, now_text, outbid=True)
            bidder_before = player_currency(bidder) + (refund if previous is not None and int(previous["bidder_player_id"]) == int(bidder["id"]) else 0)
            bidder_transition = apply_player_asset_transition(
                connection,
                {
                    "id": bidder["id"],
                    "spirit_stones": bidder_before,
                    "inventory_json": bidder["inventory_json"],
                },
                {"spirit_stones": bid_amount},
                now_text,
                mode="spend",
            )
            bid_id = f"auction-bid-{uuid4().hex}"
            connection.execute(
                "INSERT INTO auction_bids(bid_id, auction_id, bidder_player_id, bid_amount, status, operation_id, created_at, updated_at) VALUES (?, ?, ?, ?, 'active', ?, ?, ?)",
                (bid_id, auction_id, bidder["id"], int(bid_amount), operation_id, now_text, now_text),
            )
            connection.execute("UPDATE auction_lots SET current_bid=?, current_bidder_player_id=?, updated_at=? WHERE auction_id=?", (int(bid_amount), bidder["id"], now_text, auction_id))
            self._auction_ledger(connection, operation_id, int(bidder["id"]), "currency", "currency.spirit_stone", "auction.bid_lock", "lock", int(bid_amount), bidder_transition.before.currency, bidder_transition.after.currency, auction_id, now_text)
            payload = self._auction_payload(connection, auction_id)
            record_operation(connection, operation_id, operation_name, int(bidder["id"]), request_hash, payload, now_text)
            return self._auction_from_payload(payload, operation_name=operation_name)

    def _settle_auction_once(
        self, platform: str, platform_user_id: str,
        auction_id: str, operation_id: str
    ) -> AuctionRecord:
        operation_name = "economy.settle_auction"
        request_hash = self._request_hash(operation_name, {"platform": platform, "platform_user_id": platform_user_id, "auction_id": auction_id})
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            actor = self._require_player(connection, platform, platform_user_id, writable=False)
            existing = operation_replay(connection, operation_id, operation_name, request_hash, player_id=int(actor["id"]))
            if existing is not None:
                return self._auction_from_payload(
                    existing, replay=True, operation_name=operation_name,
                    expected_fields={"auction_id": auction_id},
                )
            lot = connection.execute("SELECT * FROM auction_lots WHERE auction_id=?", (auction_id,)).fetchone()
            if lot is None:
                raise AuctionNotFoundError("auction does not exist")
            self._auction_snapshot(lot)
            if str(lot["status"]) not in {"open", "settling"}:
                raise AuctionStateConflictError("auction is already settled")
            if datetime.fromisoformat(lot["ends_at"]) > now:
                raise AuctionStateConflictError("auction has not ended")
            active = self._auction_open_state(connection, lot)
            if datetime.fromisoformat(lot["settlement_deadline"]) <= now:
                if active is not None:
                    self._refund_bid(connection, active, operation_id, now_text)
                self._release_auction_item(connection, lot, operation_id, now_text)
                connection.execute("UPDATE auction_lots SET status='expired', updated_at=? WHERE auction_id=?", (now_text, auction_id))
                payload = self._auction_payload(connection, auction_id)
                record_operation(connection, operation_id, operation_name, int(actor["id"]), request_hash, payload, now_text)
                return self._auction_from_payload(payload, operation_name=operation_name)
            if active is None:
                self._release_auction_item(connection, lot, operation_id, now_text)
                connection.execute("UPDATE auction_lots SET status='unsold', updated_at=? WHERE auction_id=?", (now_text, auction_id))
            else:
                seller = connection.execute("SELECT * FROM players WHERE id=?", (lot["seller_player_id"],)).fetchone()
                winner = connection.execute("SELECT * FROM players WHERE id=?", (active["bidder_player_id"],)).fetchone()
                lock = connection.execute("SELECT * FROM auction_item_locks WHERE auction_id=?", (auction_id,)).fetchone()
                if seller is None or winner is None or lock is None:
                    raise AuctionItemLockedError("auction settlement lock is missing")
                seller_inventory = player_inventory(seller)
                quantity = int(lock["quantity"])
                if inventory_amount(seller_inventory, lock["item_key"]) < quantity:
                    raise AuctionItemLockedError("seller inventory no longer contains auction item")
                seller_transition = apply_player_asset_transition(
                    connection,
                    seller,
                    {str(lock["item_key"]): -quantity, "spirit_stones": active["bid_amount"]},
                    now_text,
                )
                winner_transition = apply_player_asset_transition(
                    connection,
                    winner,
                    {str(lock["item_key"]): quantity},
                    now_text,
                )
                connection.execute("UPDATE auction_bids SET status='won', updated_at=? WHERE id=?", (now_text, active["id"]))
                connection.execute("DELETE FROM auction_item_locks WHERE auction_id=?", (auction_id,))
                connection.execute("UPDATE auction_lots SET status='settled', updated_at=? WHERE auction_id=?", (now_text, auction_id))
                self._auction_ledger(connection, operation_id, int(seller["id"]), "currency", "currency.spirit_stone", "auction.sale", "credit", int(active["bid_amount"]), seller_transition.before.currency, seller_transition.after.currency, auction_id, now_text)
                self._auction_ledger(connection, operation_id, int(seller["id"]), "item", str(lock["item_key"]), "auction.sale", "debit", quantity, inventory_amount(seller_transition.before.inventory, lock["item_key"]), inventory_amount(seller_transition.after.inventory, lock["item_key"]), auction_id, now_text)
                self._auction_ledger(connection, operation_id, int(winner["id"]), "item", str(lock["item_key"]), "auction.purchase", "credit", quantity, inventory_amount(winner_transition.before.inventory, lock["item_key"]), inventory_amount(winner_transition.after.inventory, lock["item_key"]), auction_id, now_text)
            payload = self._auction_payload(connection, auction_id)
            record_operation(connection, operation_id, operation_name, int(actor["id"]), request_hash, payload, now_text)
            return self._auction_from_payload(payload, operation_name=operation_name)

    def _list_auctions_once(self, platform: str, platform_user_id: str) -> tuple[AuctionRecord, ...]:
        with self._connect() as connection:
            connection.execute("BEGIN")
            self._require_player(connection, platform, platform_user_id, writable=False)
            rows = connection.execute("SELECT auction_id FROM auction_lots WHERE status='open' ORDER BY ends_at, created_at").fetchall()
            return tuple(self._auction_from_payload(self._auction_payload(connection, row["auction_id"])) for row in rows)

    def _refund_bid(
        self, connection: Any, bid: Any, operation_id: str, now_text: str, *, outbid: bool = False,
    ) -> None:
        player = connection.execute("SELECT * FROM players WHERE id=?", (bid["bidder_player_id"],)).fetchone()
        if player is None:
            raise PlayerNotFoundError("bidder does not exist")
        transition = apply_player_asset_transition(
            connection,
            player,
            {"spirit_stones": bid["bid_amount"]},
            now_text,
        )
        status = "outbid" if outbid else "refunded"
        reason = "auction.outbid_refund" if outbid else "auction.refund"
        connection.execute("UPDATE auction_bids SET status=?, updated_at=? WHERE id=?", (status, now_text, bid["id"]))
        self._auction_ledger(connection, operation_id, int(player["id"]), "currency", "currency.spirit_stone", reason, "credit", int(bid["bid_amount"]), transition.before.currency, transition.after.currency, str(bid["auction_id"]), now_text)

    def _release_auction_item(self, connection: Any, lot: Any, operation_id: str, now_text: str) -> None:
        lock = connection.execute("SELECT * FROM auction_item_locks WHERE auction_id=?", (lot["auction_id"],)).fetchone()
        if lock is not None:
            self._auction_ledger(connection, operation_id, int(lock["seller_player_id"]), "item", str(lock["item_key"]), "auction.item_unlock", "release", int(lock["quantity"]), int(lock["quantity"]), int(lock["quantity"]), str(lot["auction_id"]), now_text)
            connection.execute("DELETE FROM auction_item_locks WHERE auction_id=?", (lot["auction_id"],))

    @staticmethod
    def _auction_snapshot(lot: Any) -> tuple[dict[str, Any], AuctionDefinition]:
        snapshot = decode_json_strict(lot["snapshot_json"])
        text_fields = {
            "auction_id", "week_start", "item_key", "item_label", "created_at",
            "ends_at", "settlement_deadline",
        }
        number_fields = {"seller_player_id", "quantity", "starting_bid"}
        if not isinstance(snapshot, dict) or set(snapshot) != text_fields | number_fields | {"rules"}:
            raise ValueError("auction snapshot fields are invalid")
        for key in text_fields:
            if not isinstance(snapshot[key], str) or not snapshot[key].strip():
                raise ValueError(f"auction snapshot {key} is invalid")
        for key in number_fields:
            if type(snapshot[key]) is not int or snapshot[key] <= 0:
                raise ValueError(f"auction snapshot {key} is invalid")
        definition = auction_definition_from_snapshot(snapshot["rules"])
        if not definition.min_quantity <= snapshot["quantity"] <= definition.max_quantity:
            raise ValueError("auction snapshot quantity is outside its bounds")
        if snapshot["starting_bid"] < definition.min_starting_bid:
            raise ValueError("auction snapshot starting bid is below its minimum")
        for key in (text_fields | number_fields) - {"item_label"}:
            if snapshot[key] != lot[key]:
                raise ValueError(f"auction snapshot differs from lot: {key}")
        created = datetime.fromisoformat(snapshot["created_at"])
        ends = datetime.fromisoformat(snapshot["ends_at"])
        deadline = datetime.fromisoformat(snapshot["settlement_deadline"])
        if any(value.utcoffset() is None for value in (created, ends, deadline)):
            raise ValueError("auction snapshot timestamps must have timezones")
        if (
            auction_week_start(created) != snapshot["week_start"]
            or created + timedelta(seconds=definition.duration_seconds) != ends
            or ends + timedelta(seconds=definition.settlement_grace_seconds) != deadline
        ):
            raise ValueError("auction snapshot deadlines differ from its rules")
        return snapshot, definition

    @staticmethod
    def _auction_open_state(connection: Any, lot: Any) -> Any:
        lock = connection.execute(
            "SELECT * FROM auction_item_locks WHERE auction_id=?", (lot["auction_id"],)
        ).fetchone()
        if lock is None or any(lock[key] != lot[key] for key in ("seller_player_id", "item_key", "quantity")):
            raise AuctionItemLockedError("auction item lock differs from the lot")
        if type(lot["current_bid"]) is not int or lot["current_bid"] < 0:
            raise ValueError("auction current bid is invalid")
        bids = connection.execute(
            "SELECT * FROM auction_bids WHERE auction_id=? AND status='active'", (lot["auction_id"],)
        ).fetchall()
        if not bids:
            if lot["current_bid"] != 0 or lot["current_bidder_player_id"] is not None:
                raise ValueError("auction bid escrow is missing")
            return None
        if len(bids) != 1:
            raise ValueError("auction has multiple active bid escrows")
        bid = bids[0]
        if (
            type(bid["bid_amount"]) is not int
            or bid["bid_amount"] < lot["starting_bid"]
            or bid["bid_amount"] != lot["current_bid"]
            or bid["bidder_player_id"] != lot["current_bidder_player_id"]
            or bid["bidder_player_id"] == lot["seller_player_id"]
        ):
            raise ValueError("auction bid escrow differs from the lot")
        return bid

    @classmethod
    def _auction_payload(cls, connection: Any, auction_id: str) -> dict[str, Any]:
        row = connection.execute("SELECT a.*, p.platform_user_id AS seller_platform_user_id, p.dao_name AS seller_dao_name, b.platform_user_id AS bidder_platform_user_id FROM auction_lots a JOIN players p ON p.id=a.seller_player_id LEFT JOIN players b ON b.id=a.current_bidder_player_id WHERE a.auction_id=?", (auction_id,)).fetchone()
        if row is None:
            raise AuctionNotFoundError("auction does not exist")
        snapshot, _ = cls._auction_snapshot(row)
        return {
            "auction_id": str(row["auction_id"]), "status": str(row["status"]), "week_start": str(row["week_start"]),
            "seller_platform_user_id": str(row["seller_platform_user_id"]), "seller_dao_name": str(row["seller_dao_name"] or "无名"),
            "item_key": snapshot["item_key"], "item_label": snapshot["item_label"],
            "quantity": row["quantity"], "starting_bid": row["starting_bid"],
            "current_bid": row["current_bid"], "current_bidder_platform_user_id": str(row["bidder_platform_user_id"]) if row["bidder_platform_user_id"] is not None else None,
            "ends_at": str(row["ends_at"]), "settlement_deadline": str(row["settlement_deadline"]), "created_at": str(row["created_at"]),
        }

    @staticmethod
    def _auction_from_payload(
        payload: dict[str, Any], replay: bool = False, *, operation_name: str | None = None,
        expected_fields: dict[str, Any] | None = None,
    ) -> AuctionRecord:
        expected = {field.name for field in fields(AuctionRecord)} - {"already_completed"}
        if set(payload) != expected:
            raise ValueError("auction result fields are invalid")
        amounts = {"quantity", "starting_bid", "current_bid"}
        for key, value in payload.items():
            if key in amounts:
                minimum = 0 if key == "current_bid" else 1
                if type(value) is not int or value < minimum:
                    raise ValueError(f"auction result {key} is invalid")
            elif key == "current_bidder_platform_user_id" and value is None:
                continue
            elif not isinstance(value, str) or not value.strip():
                raise ValueError(f"auction result {key} is invalid")
        if payload["status"] not in {"open", "settling", "settled", "unsold", "expired"}:
            raise ValueError("auction result status is invalid")
        if (payload["current_bidder_platform_user_id"] is None) != (payload["current_bid"] == 0):
            raise ValueError("auction result bidder differs from its bid")
        if payload["current_bid"] and payload["current_bid"] < payload["starting_bid"]:
            raise ValueError("auction result bid is below its starting bid")
        if payload["status"] == "settled" and not payload["current_bid"]:
            raise ValueError("settled auction result has no bid")
        if payload["status"] == "unsold" and payload["current_bid"]:
            raise ValueError("unsold auction result has a bid")
        if operation_name == "economy.create_auction" and (payload["status"] != "open" or payload["current_bid"]):
            raise ValueError("auction creation result is not an unbid open lot")
        if operation_name == "economy.bid_auction" and (payload["status"] != "open" or not payload["current_bid"]):
            raise ValueError("auction bidding result is not a bid open lot")
        if operation_name == "economy.settle_auction" and payload["status"] not in {"settled", "unsold", "expired"}:
            raise ValueError("auction settlement result is not final")
        if expected_fields is not None and any(payload[key] != value for key, value in expected_fields.items()):
            raise ValueError("auction result differs from its request")
        created, ends, deadline = (
            datetime.fromisoformat(payload[key]) for key in ("created_at", "ends_at", "settlement_deadline")
        )
        if any(value.utcoffset() is None for value in (created, ends, deadline)) or not created < ends < deadline:
            raise ValueError("auction result timestamps are invalid")
        if date.fromisoformat(payload["week_start"]).isoformat() != auction_week_start(created):
            raise ValueError("auction result week differs from its creation time")
        return AuctionRecord(**payload, already_completed=replay)

    @staticmethod
    def _auction_ledger(connection: Any, operation_id: str, player_id: int, asset_kind: str, asset_key: str, reason: str, direction: str, amount: int, before_value: int, after_value: int, source_id: str, created_at: str) -> None:
        connection.execute("INSERT INTO economy_ledger_entries(operation_id, player_id, asset_kind, asset_key, reason, direction, amount, before_value, after_value, source_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (operation_id, player_id, asset_kind, asset_key, reason, direction, amount, before_value, after_value, source_id, created_at))


__all__ = ["AuctionRepositoryMixin"]
