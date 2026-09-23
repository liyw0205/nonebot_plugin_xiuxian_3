"""SQLite transactions for residences and the evergreen field-plot loop."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from ...contracts import serialize_datetime
from ..persistence.errors import (
    CurrencyInsufficientError,
    LocalReputationInsufficientError,
    OperationConflictError,
    PlayerStageConflictError,
    ResidenceAlreadyActiveError,
    ResidenceContentClosedError,
    ResidenceNotFoundError,
)
from ..player.rules import STAGE_MORTAL
from .commission_repository import CommissionRepositoryMixin
from .field_repository import FieldPlotRepositoryMixin
from .route_repository import RouteRepositoryMixin
from .service_repository import ServiceRepositoryMixin
from .project_repository import ProjectRepositoryMixin
from .models import ResidenceRecord
from .rules import residence_definition


class LivelihoodRepositoryMixin(
    RouteRepositoryMixin,
    ServiceRepositoryMixin,
    CommissionRepositoryMixin,
    FieldPlotRepositoryMixin,
    ProjectRepositoryMixin,
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
        try:
            definition = residence_definition(residence_key)
        except ValueError as exc:
            raise ResidenceContentClosedError("unsupported residence") from exc
        operation_name = "livelihood.lease_residence"
        request_hash = self._request_hash(
            operation_name,
            {"platform": platform, "platform_user_id": platform_user_id, "residence_key": definition.key},
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

            row = self._require_player(connection, platform, platform_user_id)
            if str(row["stage"]) not in {STAGE_MORTAL, "seeker", "cultivator"}:
                raise PlayerStageConflictError("residence requires a mortal-stage player")
            active = connection.execute(
                "SELECT * FROM residences WHERE player_id = ? AND status = 'active' ORDER BY id DESC LIMIT 1",
                (row["id"],),
            ).fetchone()
            if active is not None:
                if now < datetime.fromisoformat(str(active["ends_at"])):
                    raise ResidenceAlreadyActiveError("residence is already active")
                connection.execute(
                    "UPDATE residences SET status = 'expired', updated_at = ? WHERE id = ?",
                    (now_text, active["id"]),
                )
            if int(row["spirit_stones"]) < definition.rent_cost:
                raise CurrencyInsufficientError("rent is insufficient")
            if definition.required_local_reputation:
                reputation = connection.execute(
                    "SELECT local_json FROM player_reputations WHERE player_id = ?", (row["id"],)
                ).fetchone()
                local = self._json_object(reputation["local_json"], {}) if reputation is not None else {}
                if int(local.get("local.xuantian.new_town", 0)) < definition.required_local_reputation:
                    raise LocalReputationInsufficientError("local reputation is insufficient")
            residence_id = uuid4().hex
            ends_at = serialize_datetime(now + timedelta(days=definition.lease_days))
            connection.execute(
                "UPDATE players SET spirit_stones = spirit_stones - ?, updated_at = ? WHERE id = ?",
                (definition.rent_cost, now_text, row["id"]),
            )
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
                            "content_version": definition.content_version,
                            "rule_version": definition.rule_version,
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
            already_completed=replay,
        )

    def _residence_from_row(self, player_row: Any, residence_row: Any) -> ResidenceRecord:
        return ResidenceRecord(
            player=self._row_to_player(player_row),
            residence_id=str(residence_row["residence_id"]),
            residence_key=str(residence_row["residence_key"]),
            status=str(residence_row["status"]),
            starts_at=str(residence_row["starts_at"]),
            ends_at=str(residence_row["ends_at"]),
            rent_cost=int(residence_row["rent_cost"]),
        )

    def _active_residence(self, connection: Any, player_id: int, now: datetime, now_text: str) -> Any:
        residence = connection.execute(
            "SELECT * FROM residences WHERE player_id = ? AND status = 'active' ORDER BY id DESC LIMIT 1",
            (player_id,),
        ).fetchone()
        if residence is not None and now >= datetime.fromisoformat(str(residence["ends_at"])):
            connection.execute(
                "UPDATE residences SET status = 'expired', updated_at = ? WHERE id = ? AND status = 'active'",
                (now_text, residence["id"]),
            )
            return None
        return residence
