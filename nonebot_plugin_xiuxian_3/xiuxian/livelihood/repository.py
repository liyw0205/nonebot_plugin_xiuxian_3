"""SQLite transactions for residences and the evergreen field-plot loop."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from ...contracts import serialize_datetime
from ..utils.assets import spend_player_currency, player_currency
from ..utils.player import player_local_reputation
from ..persistence.errors import (
    CurrencyInsufficientError,
    LocalReputationInsufficientError,
    OperationConflictError,
    PlayerStageConflictError,
    ResidenceAlreadyActiveError,
    ResidenceContentClosedError,
    ResidenceNotFoundError,
)
from .commission_repository import CommissionRepositoryMixin
from .field_repository import FieldPlotRepositoryMixin
from .route_repository import RouteRepositoryMixin
from .service_repository import ServiceRepositoryMixin
from .project_repository import ProjectRepositoryMixin
from .trade_permit_repository import TradePermitRepositoryMixin
from .models import ResidenceRecord
from .rules import residence_definition


class LivelihoodRepositoryMixin(
    RouteRepositoryMixin,
    ServiceRepositoryMixin,
    CommissionRepositoryMixin,
    FieldPlotRepositoryMixin,
    ProjectRepositoryMixin,
    TradePermitRepositoryMixin,
):
    """Own every persistence transaction that belongs to ``livelihood``."""

    async def lease_residence(
        self,
        *,
        platform: str,
        platform_user_id: str,
        residence_key: str,
        operation_id: str,
    ) -> ResidenceRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._lease_residence_once,
                platform,
                platform_user_id,
                residence_key,
                operation_id,
            )

    def _lease_residence_once(
        self,
        platform: str,
        platform_user_id: str,
        residence_key: str,
        operation_id: str,
    ) -> ResidenceRecord:
        operation_name = "livelihood.lease_residence"
        request_value = (residence_key or "").strip() or "<default>"
        request_hash = self._request_hash(
            operation_name,
            {"platform": platform, "platform_user_id": platform_user_id, "residence_key": request_value},
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
                return self._residence_from_payload(json.loads(existing["result_json"]), replay=True)

            try:
                definition = residence_definition(residence_key, self.content)
            except ValueError as exc:
                raise ResidenceContentClosedError("unsupported residence") from exc

            row = self._require_player(connection, platform, platform_user_id)
            stage_order = {"mortal": 0, "seeker": 1, "cultivator": 2}
            if stage_order.get(str(row["stage"]), -1) < stage_order.get(definition.required_stage, 0):
                raise PlayerStageConflictError("residence requires a mortal-stage player")
            active = connection.execute(
                "SELECT * FROM residences WHERE player_id = ? AND status = 'active' ORDER BY id DESC LIMIT 1",
                (row["id"],),
            ).fetchone()
            if active is not None:
                self._residence_snapshot(active)
                if now < datetime.fromisoformat(str(active["ends_at"])):
                    raise ResidenceAlreadyActiveError("residence is already active")
                connection.execute(
                    "UPDATE residences SET status = 'expired', updated_at = ? WHERE id = ?",
                    (now_text, active["id"]),
                )
            if player_currency(row) < definition.rent_cost:
                raise CurrencyInsufficientError("rent is insufficient")
            if definition.required_local_reputation:
                if not definition.local_reputation_key:
                    raise ResidenceContentClosedError("residence reputation requirement is missing")
                reputation = player_local_reputation(connection, int(row["id"]), definition.local_reputation_key)
                if reputation < definition.required_local_reputation:
                    raise LocalReputationInsufficientError("local reputation is insufficient")
            residence_id = uuid4().hex
            ends_at = serialize_datetime(now + timedelta(days=definition.lease_days))
            spend_player_currency(connection, row, definition.rent_cost, now_text)
            connection.execute(
                """
                INSERT INTO residences(
                    residence_id, player_id, operation_id, residence_key, status,
                    starts_at, ends_at, rent_cost, snapshot_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?)
                """,
                (
                    residence_id,
                    row["id"],
                    operation_id,
                    definition.key,
                    now_text,
                    ends_at,
                    definition.rent_cost,
                    json.dumps(
                        {
                            "key": definition.key,
                            "label": definition.label,
                            "rent_cost": definition.rent_cost,
                            "lease_days": definition.lease_days,
                            "required_stage": definition.required_stage,
                            "required_local_reputation": definition.required_local_reputation,
                            "local_reputation_key": definition.local_reputation_key,
                            "plot_count": definition.plot_count,
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    now_text,
                    now_text,
                ),
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (row["id"],)).fetchone()
            if updated is None:
                raise RuntimeError("residence lease returned no player")
            payload = {
                "player": self._player_payload(self._row_to_player(updated)),
                "residence_id": residence_id,
                "residence_key": definition.key,
                "status": "active",
                "starts_at": now_text,
                "ends_at": ends_at,
                "rent_cost": definition.rent_cost,
                "label": definition.label,
            }
            connection.execute(
                "INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    operation_id,
                    operation_name,
                    row["id"],
                    request_hash,
                    json.dumps(payload, ensure_ascii=False, sort_keys=True),
                    now_text,
                ),
            )
            return self._residence_from_payload(payload)

    async def get_residence(self, *, platform: str, platform_user_id: str) -> ResidenceRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._get_residence_sync, platform, platform_user_id)

    def _get_residence_sync(self, platform: str, platform_user_id: str) -> ResidenceRecord:
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            row = self._require_player(connection, platform, platform_user_id, writable=False)
            residence = self._active_residence(connection, int(row["id"]), now, now_text)
            if residence is None:
                raise ResidenceNotFoundError("no residence")
            return self._residence_from_row(row, residence)

    def _residence_from_payload(self, payload: dict[str, Any], *, replay: bool = False) -> ResidenceRecord:
        return ResidenceRecord(
            player=self._row_to_player(payload["player"]),
            residence_id=str(payload["residence_id"]),
            residence_key=str(payload["residence_key"]),
            status=str(payload["status"]),
            starts_at=str(payload["starts_at"]),
            ends_at=str(payload["ends_at"]),
            rent_cost=int(payload["rent_cost"]),
            label=str(payload["label"]),
            already_completed=replay,
        )

    def _residence_from_row(self, player_row: Any, residence_row: Any) -> ResidenceRecord:
        snapshot = self._residence_snapshot(residence_row)
        return ResidenceRecord(
            player=self._row_to_player(player_row),
            residence_id=str(residence_row["residence_id"]),
            residence_key=str(residence_row["residence_key"]),
            status=str(residence_row["status"]),
            starts_at=str(residence_row["starts_at"]),
            ends_at=str(residence_row["ends_at"]),
            rent_cost=int(residence_row["rent_cost"]),
            label=str(snapshot["label"]),
        )

    def _residence_snapshot(self, residence_row: Any) -> dict[str, Any]:
        snapshot = self._json_object(residence_row["snapshot_json"], {})
        key = snapshot["key"]
        label = snapshot["label"]
        rent_cost = snapshot["rent_cost"]
        lease_days = snapshot["lease_days"]
        required_stage = snapshot["required_stage"]
        reputation_minimum = snapshot["required_local_reputation"]
        reputation_key = snapshot["local_reputation_key"]
        plot_count = snapshot["plot_count"]
        if (
            not isinstance(key, str)
            or not key
            or not isinstance(label, str)
            or not label.strip()
            or isinstance(rent_cost, bool)
            or not isinstance(rent_cost, int)
            or rent_cost <= 0
            or isinstance(lease_days, bool)
            or not isinstance(lease_days, int)
            or lease_days <= 0
            or not isinstance(required_stage, str)
            or not required_stage
            or isinstance(reputation_minimum, bool)
            or not isinstance(reputation_minimum, int)
            or reputation_minimum < 0
            or (reputation_key is not None and (not isinstance(reputation_key, str) or not reputation_key))
            or isinstance(plot_count, bool)
            or not isinstance(plot_count, int)
            or plot_count < 0
        ):
            raise ValueError("invalid residence snapshot")
        return snapshot

    def _active_residence(self, connection: Any, player_id: int, now: datetime, now_text: str) -> Any:
        residence = connection.execute(
            "SELECT * FROM residences WHERE player_id = ? AND status = 'active' ORDER BY id DESC LIMIT 1",
            (player_id,),
        ).fetchone()
        if residence is not None:
            self._residence_snapshot(residence)
        if residence is not None and now >= datetime.fromisoformat(str(residence["ends_at"])):
            connection.execute(
                "UPDATE residences SET status = 'expired', updated_at = ? WHERE id = ? AND status = 'active'",
                (now_text, residence["id"]),
            )
            return None
        return residence
