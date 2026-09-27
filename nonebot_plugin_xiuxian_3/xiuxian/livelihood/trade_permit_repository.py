"""Atomic application of v0.3 trade permits."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from uuid import uuid4

from ...contracts import serialize_datetime
from ..persistence.errors import (
    CurrencyInsufficientError,
    OperationConflictError,
    TradePermitContentClosedError,
    TradePermitRequirementError,
)
from .models import TradePermitRecord
from .trade_permit_rules import resolve_trade_permit


class TradePermitRepositoryMixin:
    async def issue_trade_permit(
        self, *, platform: str, platform_user_id: str, permit_key: str, operation_id: str
    ) -> TradePermitRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._issue_trade_permit_once,
                platform,
                platform_user_id,
                permit_key,
                operation_id,
            )

    def _issue_trade_permit_once(
        self, platform: str, platform_user_id: str, permit_key: str, operation_id: str
    ) -> TradePermitRecord:
        try:
            definition = resolve_trade_permit(permit_key)
        except ValueError as exc:
            raise TradePermitContentClosedError("unsupported trade permit") from exc
        operation_name = "livelihood.issue_trade_permit"
        request_hash = self._request_hash(
            operation_name,
            {"platform": platform, "platform_user_id": platform_user_id, "permit_key": definition.key},
        )
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            if existing is not None:
                if existing["operation_name"] != operation_name or existing["request_hash"] != request_hash:
                    raise OperationConflictError("operation input differs from its original request")
                return self._trade_permit_from_payload(json.loads(existing["result_json"]), replay=True)

            player = self._require_player(connection, platform, platform_user_id)
            active = connection.execute(
                """
                SELECT * FROM trade_permits
                WHERE player_id = ? AND permit_key = ? AND expires_at > ?
                ORDER BY expires_at DESC, id DESC LIMIT 1
                """,
                (player["id"], definition.key, now_text),
            ).fetchone()
            if active is not None:
                payload = self._trade_permit_payload(player, active, already_active=True)
            else:
                intro = self._json_object(player["intro_json"], {})
                flags = {str(flag) for flag in intro.get("flags", [])}
                reputation = self._json_object(player["faction_reputation_json"], {})
                if definition.required_quest not in flags or int(reputation.get(definition.faction_key, 0)) < definition.reputation_required:
                    raise TradePermitRequirementError("trade permit requirements are not met")
                if int(player["spirit_stones"]) < definition.cost:
                    raise CurrencyInsufficientError("trade permit cost is insufficient")
                permit_id = f"trade-permit:{uuid4().hex}"
                expires_at = serialize_datetime(now + timedelta(seconds=definition.duration_seconds))
                snapshot = {
                    "required_quest": definition.required_quest,
                    "faction_key": definition.faction_key,
                    "faction_reputation": int(reputation.get(definition.faction_key, 0)),
                    "cost": definition.cost,
                    "content_version": definition.content_version,
                    "rule_version": definition.rule_version,
                }
                connection.execute(
                    """
                    INSERT INTO trade_permits(
                        permit_id, player_id, operation_id, permit_key, issued_at, expires_at,
                        cost, snapshot_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        permit_id,
                        player["id"],
                        operation_id,
                        definition.key,
                        now_text,
                        expires_at,
                        definition.cost,
                        json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
                        now_text,
                        now_text,
                    ),
                )
                connection.execute(
                    "UPDATE players SET spirit_stones = spirit_stones - ?, updated_at = ? WHERE id = ?",
                    (definition.cost, now_text, player["id"]),
                )
                updated = connection.execute("SELECT * FROM players WHERE id = ?", (player["id"],)).fetchone()
                active = connection.execute(
                    "SELECT * FROM trade_permits WHERE permit_id = ?", (permit_id,)
                ).fetchone()
                if updated is None or active is None:
                    raise RuntimeError("trade permit issuance returned no record")
                payload = self._trade_permit_payload(updated, active, already_active=False)

            connection.execute(
                "INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    operation_id,
                    operation_name,
                    player["id"],
                    request_hash,
                    json.dumps(payload, ensure_ascii=False, sort_keys=True),
                    now_text,
                ),
            )
            return self._trade_permit_from_payload(payload)

    def _trade_permit_payload(self, player, permit, *, already_active: bool) -> dict[str, object]:
        player_payload = self._player_payload(self._row_to_player(player))
        return {
            "player": player_payload,
            "permit_id": str(permit["permit_id"]),
            "permit_key": str(permit["permit_key"]),
            "issued_at": str(permit["issued_at"]),
            "expires_at": str(permit["expires_at"]),
            "cost": int(permit["cost"]),
            "already_active": already_active,
        }

    def _trade_permit_from_payload(self, payload: dict[str, object], replay: bool = False) -> TradePermitRecord:
        return TradePermitRecord(
            player=self._row_to_player(payload["player"]),
            permit_id=str(payload["permit_id"]),
            permit_key=str(payload["permit_key"]),
            issued_at=str(payload["issued_at"]),
            expires_at=str(payload["expires_at"]),
            cost=int(payload["cost"]),
            already_active=bool(payload.get("already_active", False)),
            already_completed=replay,
        )


__all__ = ["TradePermitRepositoryMixin"]
