"""SQLite transactions for the limited weekly auction."""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta
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
    OperationConflictError,
    PlayerNotFoundError,
)
from .auction_models import AuctionRecord
from .auction_rules import (
    AUCTION_DURATION,
    AUCTION_SETTLEMENT_GRACE,
    AUCTION_SLOT_LIMIT,
    CONTENT_VERSION,
    RULE_VERSION,
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
        try:
            item = validate_auction_listing(item_key, quantity, starting_bid)
        except ValueError as exc:
            from ..persistence.errors import MarketItemForbiddenError, MarketPriceInvalidError
            if "item" in str(exc):
                raise MarketItemForbiddenError(str(exc)) from exc
            raise MarketPriceInvalidError(str(exc)) from exc
        operation_name = "economy.create_auction"
        request_hash = self._request_hash(operation_name, {
            "platform": platform, "platform_user_id": platform_user_id,
            "item_key": item.key, "quantity": int(quantity),
            "starting_bid": int(starting_bid),
        })
        now = self._now()
        now_text = serialize_datetime(now)
        week_start = auction_week_start(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._auction_operation(connection, operation_id, operation_name, request_hash)
            if existing is not None:
                return self._auction_from_payload(existing, replay=True)
            seller = self._require_player(connection, platform, platform_user_id)
            active_count = connection.execute(
                "SELECT COUNT(*) FROM auction_lots WHERE week_start=? AND status IN ('open', 'settling')",
                (week_start,),
            ).fetchone()[0]
            if int(active_count) >= AUCTION_SLOT_LIMIT:
                raise AuctionSlotFullError("weekly auction slots are full")
            inventory = self._json_object(seller["inventory_json"], {})
            locked_market = connection.execute(
                "SELECT COALESCE(SUM(quantity), 0) FROM market_item_locks WHERE seller_player_id=? AND item_key=?",
                (seller["id"], item.key),
            ).fetchone()[0]
            locked_auction = connection.execute(
                "SELECT COALESCE(SUM(quantity), 0) FROM auction_item_locks WHERE seller_player_id=? AND item_key=?",
                (seller["id"], item.key),
            ).fetchone()[0]
            bound = connection.execute(
                "SELECT COALESCE(SUM(quantity), 0) FROM item_bindings WHERE player_id=? AND item_key=? AND bound_until > ?",
                (seller["id"], item.key, now_text),
            ).fetchone()[0]
            available = int(inventory.get(item.key, 0)) - int(locked_market) - int(locked_auction)
            if available < int(quantity):
                raise AuctionItemLockedError("auction item is not available")
            if available - int(bound) < int(quantity):
                from ..persistence.errors import ItemBindingActiveError
                raise ItemBindingActiveError("auction item is still bound")
            auction_id = f"auction-{uuid4().hex}"
            ends_at = now + AUCTION_DURATION
            settlement_deadline = ends_at + AUCTION_SETTLEMENT_GRACE
            snapshot = {
                "content_version": CONTENT_VERSION, "rule_version": RULE_VERSION,
                "auction_id": auction_id, "week_start": week_start,
                "item_key": item.key, "quantity": int(quantity),
                "starting_bid": int(starting_bid), "slot_limit": AUCTION_SLOT_LIMIT,
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
            self._record_auction_operation(connection, operation_id, operation_name, int(seller["id"]), request_hash, payload, now_text)
            return self._auction_from_payload(payload)

    def _bid_auction_once(
        self, platform: str, platform_user_id: str,
        auction_id: str, bid_amount: int, operation_id: str
    ) -> AuctionRecord:
        operation_name = "economy.bid_auction"
        request_hash = self._request_hash(operation_name, {
            "platform": platform, "platform_user_id": platform_user_id,
            "auction_id": auction_id, "bid_amount": int(bid_amount),
        })
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._auction_operation(connection, operation_id, operation_name, request_hash)
            if existing is not None:
                return self._auction_from_payload(existing, replay=True)
            bidder = self._require_player(connection, platform, platform_user_id)
            lot = connection.execute("SELECT * FROM auction_lots WHERE auction_id=?", (auction_id,)).fetchone()
            if lot is None:
                raise AuctionNotFoundError("auction does not exist")
            if int(lot["seller_player_id"]) == int(bidder["id"]):
                raise AuctionSelfBidError("seller cannot bid on own auction")
            if str(lot["status"]) != "open" or str(lot["ends_at"]) <= now_text:
                raise AuctionStateConflictError("auction is closed")
            required = minimum_next_bid(int(lot["current_bid"]), int(lot["starting_bid"]))
            if int(bid_amount) < required:
                raise AuctionBidTooLowError(f"minimum bid is {required}")
            previous = connection.execute(
                "SELECT * FROM auction_bids WHERE auction_id=? AND status='active'", (auction_id,)
            ).fetchone()
            refund = int(previous["bid_amount"]) if previous is not None else 0
            available_balance = int(bidder["spirit_stones"]) + (refund if previous is not None and int(previous["bidder_player_id"]) == int(bidder["id"]) else 0)
            if available_balance < int(bid_amount):
                raise BalanceInsufficientError("auction bid balance is insufficient")
            if previous is not None:
                connection.execute("UPDATE auction_bids SET status='outbid' WHERE id=?", (previous["id"],))
                previous_player = connection.execute("SELECT * FROM players WHERE id=?", (previous["bidder_player_id"],)).fetchone()
                if previous_player is not None:
                    connection.execute("UPDATE players SET spirit_stones=spirit_stones+?, updated_at=? WHERE id=?", (int(previous["bid_amount"]), now_text, previous_player["id"]))
                    self._auction_ledger(connection, operation_id, int(previous_player["id"]), "currency", "currency.spirit_stone", "auction.outbid_refund", "credit", int(previous["bid_amount"]), int(previous_player["spirit_stones"]), int(previous_player["spirit_stones"]) + int(previous["bid_amount"]), auction_id, now_text)
            bidder_before = int(bidder["spirit_stones"]) + (refund if previous is not None and int(previous["bidder_player_id"]) == int(bidder["id"]) else 0)
            connection.execute("UPDATE players SET spirit_stones=spirit_stones-?, updated_at=? WHERE id=?", (int(bid_amount), now_text, bidder["id"]))
            bid_id = f"auction-bid-{uuid4().hex}"
            connection.execute(
                "INSERT INTO auction_bids(bid_id, auction_id, bidder_player_id, bid_amount, status, operation_id, created_at, updated_at) VALUES (?, ?, ?, ?, 'active', ?, ?, ?)",
                (bid_id, auction_id, bidder["id"], int(bid_amount), operation_id, now_text, now_text),
            )
            connection.execute("UPDATE auction_lots SET current_bid=?, current_bidder_player_id=?, updated_at=? WHERE auction_id=?", (int(bid_amount), bidder["id"], now_text, auction_id))
            self._auction_ledger(connection, operation_id, int(bidder["id"]), "currency", "currency.spirit_stone", "auction.bid_lock", "lock", int(bid_amount), bidder_before, bidder_before - int(bid_amount), auction_id, now_text)
            payload = self._auction_payload(connection, auction_id)
            self._record_auction_operation(connection, operation_id, operation_name, int(bidder["id"]), request_hash, payload, now_text)
            return self._auction_from_payload(payload)

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
            existing = self._auction_operation(connection, operation_id, operation_name, request_hash)
            if existing is not None:
                return self._auction_from_payload(existing, replay=True)
            actor = self._require_player(connection, platform, platform_user_id, writable=False)
            lot = connection.execute("SELECT * FROM auction_lots WHERE auction_id=?", (auction_id,)).fetchone()
            if lot is None:
                raise AuctionNotFoundError("auction does not exist")
            if str(lot["status"]) not in {"open", "settling"}:
                raise AuctionStateConflictError("auction is already settled")
            if str(lot["ends_at"]) > now_text:
                raise AuctionStateConflictError("auction has not ended")
            active = connection.execute("SELECT * FROM auction_bids WHERE auction_id=? AND status='active'", (auction_id,)).fetchone()
            if str(lot["settlement_deadline"]) <= now_text:
                if active is not None:
                    self._refund_bid(connection, active, operation_id, now_text)
                self._release_auction_item(connection, lot, operation_id, now_text)
                connection.execute("UPDATE auction_lots SET status='expired', updated_at=? WHERE auction_id=?", (now_text, auction_id))
                payload = self._auction_payload(connection, auction_id)
                self._record_auction_operation(connection, operation_id, operation_name, int(actor["id"]), request_hash, payload, now_text)
                return self._auction_from_payload(payload)
            if active is None:
                self._release_auction_item(connection, lot, operation_id, now_text)
                connection.execute("UPDATE auction_lots SET status='unsold', updated_at=? WHERE auction_id=?", (now_text, auction_id))
            else:
                seller = connection.execute("SELECT * FROM players WHERE id=?", (lot["seller_player_id"],)).fetchone()
                winner = connection.execute("SELECT * FROM players WHERE id=?", (active["bidder_player_id"],)).fetchone()
                lock = connection.execute("SELECT * FROM auction_item_locks WHERE auction_id=?", (auction_id,)).fetchone()
                if seller is None or winner is None or lock is None:
                    raise AuctionItemLockedError("auction settlement lock is missing")
                seller_inventory = self._json_object(seller["inventory_json"], {})
                winner_inventory = self._json_object(winner["inventory_json"], {})
                quantity = int(lock["quantity"])
                if int(seller_inventory.get(lock["item_key"], 0)) < quantity:
                    raise AuctionItemLockedError("seller inventory no longer contains auction item")
                seller_inventory[lock["item_key"]] = int(seller_inventory.get(lock["item_key"], 0)) - quantity
                if seller_inventory[lock["item_key"]] <= 0:
                    seller_inventory.pop(lock["item_key"], None)
                winner_inventory[lock["item_key"]] = int(winner_inventory.get(lock["item_key"], 0)) + quantity
                connection.execute("UPDATE players SET inventory_json=?, spirit_stones=spirit_stones+?, updated_at=? WHERE id=?", (json.dumps(seller_inventory, ensure_ascii=False, sort_keys=True), int(active["bid_amount"]), now_text, seller["id"]))
                connection.execute("UPDATE players SET inventory_json=?, updated_at=? WHERE id=?", (json.dumps(winner_inventory, ensure_ascii=False, sort_keys=True), now_text, winner["id"]))
                connection.execute("UPDATE auction_bids SET status='won', updated_at=? WHERE id=?", (now_text, active["id"]))
                connection.execute("DELETE FROM auction_item_locks WHERE auction_id=?", (auction_id,))
                connection.execute("UPDATE auction_lots SET status='settled', updated_at=? WHERE auction_id=?", (now_text, auction_id))
                self._auction_ledger(connection, operation_id, int(seller["id"]), "currency", "currency.spirit_stone", "auction.sale", "credit", int(active["bid_amount"]), int(seller["spirit_stones"]), int(seller["spirit_stones"]) + int(active["bid_amount"]), auction_id, now_text)
                self._auction_ledger(connection, operation_id, int(seller["id"]), "item", str(lock["item_key"]), "auction.sale", "debit", quantity, int(seller_inventory.get(lock["item_key"], 0)) + quantity, int(seller_inventory.get(lock["item_key"], 0)), auction_id, now_text)
                self._auction_ledger(connection, operation_id, int(winner["id"]), "item", str(lock["item_key"]), "auction.purchase", "credit", quantity, int(winner_inventory.get(lock["item_key"], 0)) - quantity, int(winner_inventory.get(lock["item_key"], 0)), auction_id, now_text)
            payload = self._auction_payload(connection, auction_id)
            self._record_auction_operation(connection, operation_id, operation_name, int(actor["id"]), request_hash, payload, now_text)
            return self._auction_from_payload(payload)

    def _list_auctions_once(self, platform: str, platform_user_id: str) -> tuple[AuctionRecord, ...]:
        with self._connect() as connection:
            self._require_player(connection, platform, platform_user_id, writable=False)
            rows = connection.execute("SELECT auction_id FROM auction_lots WHERE status='open' ORDER BY ends_at, created_at").fetchall()
            return tuple(self._auction_from_payload(self._auction_payload(connection, row["auction_id"])) for row in rows)

    def _refund_bid(self, connection: Any, bid: Any, operation_id: str, now_text: str) -> None:
        player = connection.execute("SELECT * FROM players WHERE id=?", (bid["bidder_player_id"],)).fetchone()
        if player is None:
            raise PlayerNotFoundError("bidder does not exist")
        connection.execute("UPDATE players SET spirit_stones=spirit_stones+?, updated_at=? WHERE id=?", (int(bid["bid_amount"]), now_text, player["id"]))
        connection.execute("UPDATE auction_bids SET status='refunded', updated_at=? WHERE id=?", (now_text, bid["id"]))
        self._auction_ledger(connection, operation_id, int(player["id"]), "currency", "currency.spirit_stone", "auction.refund", "credit", int(bid["bid_amount"]), int(player["spirit_stones"]), int(player["spirit_stones"]) + int(bid["bid_amount"]), str(bid["auction_id"]), now_text)

    def _release_auction_item(self, connection: Any, lot: Any, operation_id: str, now_text: str) -> None:
        lock = connection.execute("SELECT * FROM auction_item_locks WHERE auction_id=?", (lot["auction_id"],)).fetchone()
        if lock is not None:
            self._auction_ledger(connection, operation_id, int(lock["seller_player_id"]), "item", str(lock["item_key"]), "auction.item_unlock", "release", int(lock["quantity"]), int(lock["quantity"]), int(lock["quantity"]), str(lot["auction_id"]), now_text)
            connection.execute("DELETE FROM auction_item_locks WHERE auction_id=?", (lot["auction_id"],))

    @staticmethod
    def _auction_operation(connection: Any, operation_id: str, operation_name: str, request_hash: str) -> dict[str, Any] | None:
        row = connection.execute("SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id=?", (operation_id,)).fetchone()
        if row is None:
            return None
        if row["operation_name"] != operation_name or row["request_hash"] != request_hash:
            raise OperationConflictError("operation input differs from its original request")
        return json.loads(row["result_json"])

    @staticmethod
    def _record_auction_operation(connection: Any, operation_id: str, operation_name: str, player_id: int, request_hash: str, payload: dict[str, Any], now_text: str) -> None:
        connection.execute("INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)", (operation_id, operation_name, player_id, request_hash, json.dumps(payload, ensure_ascii=False, sort_keys=True), now_text))

    @staticmethod
    def _auction_payload(connection: Any, auction_id: str) -> dict[str, Any]:
        row = connection.execute("SELECT a.*, p.platform_user_id AS seller_platform_user_id, p.dao_name AS seller_dao_name, b.platform_user_id AS bidder_platform_user_id FROM auction_lots a JOIN players p ON p.id=a.seller_player_id LEFT JOIN players b ON b.id=a.current_bidder_player_id WHERE a.auction_id=?", (auction_id,)).fetchone()
        if row is None:
            raise AuctionNotFoundError("auction does not exist")
        return {
            "auction_id": str(row["auction_id"]), "status": str(row["status"]), "week_start": str(row["week_start"]),
            "seller_platform_user_id": str(row["seller_platform_user_id"]), "seller_dao_name": str(row["seller_dao_name"] or "无名"),
            "item_key": str(row["item_key"]), "quantity": int(row["quantity"]), "starting_bid": int(row["starting_bid"]),
            "current_bid": int(row["current_bid"]), "current_bidder_platform_user_id": str(row["bidder_platform_user_id"]) if row["bidder_platform_user_id"] is not None else None,
            "ends_at": str(row["ends_at"]), "settlement_deadline": str(row["settlement_deadline"]), "created_at": str(row["created_at"]),
        }

    @staticmethod
    def _auction_from_payload(payload: dict[str, Any], replay: bool = False) -> AuctionRecord:
        return AuctionRecord(
            auction_id=str(payload["auction_id"]), status=str(payload["status"]), week_start=str(payload["week_start"]),
            seller_platform_user_id=str(payload["seller_platform_user_id"]), seller_dao_name=str(payload["seller_dao_name"]),
            item_key=str(payload["item_key"]), quantity=int(payload["quantity"]), starting_bid=int(payload["starting_bid"]),
            current_bid=int(payload["current_bid"]), current_bidder_platform_user_id=payload.get("current_bidder_platform_user_id"),
            ends_at=str(payload["ends_at"]), settlement_deadline=str(payload["settlement_deadline"]), created_at=str(payload["created_at"]), already_completed=replay,
        )

    @staticmethod
    def _auction_ledger(connection: Any, operation_id: str, player_id: int, asset_kind: str, asset_key: str, reason: str, direction: str, amount: int, before_value: int, after_value: int, source_id: str, created_at: str) -> None:
        connection.execute("INSERT INTO economy_ledger_entries(operation_id, player_id, asset_kind, asset_key, reason, direction, amount, before_value, after_value, source_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (operation_id, player_id, asset_kind, asset_key, reason, direction, amount, before_value, after_value, source_id, created_at))


__all__ = ["AuctionRepositoryMixin"]
