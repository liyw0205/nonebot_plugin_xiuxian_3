"""SQLite transactions for residence rest sessions."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from ...contracts import serialize_datetime
from ..persistence.errors import (
    PlayerNotFoundError,
    ResidencePlotRequiredError,
    ResidenceRequiredError,
    RestBlockedError,
    RestDailyLimitError,
    RestNotNeededError,
    RestNotFoundError,
    RestNotReadyError,
)
from ..utils.json_cache import decode_json_strict
from ..utils.operations import operation_replay, record_operation
from ..utils.player import change_player_state, player_integer
from .models import RestRecord


_BLOCK_QUERIES = (
    ("travel", "SELECT 1 FROM travel_sessions WHERE player_id = ? AND status = 'running' LIMIT 1"),
    ("retreat", "SELECT 1 FROM retreat_sessions WHERE player_id = ? AND status = 'running' LIMIT 1"),
    ("cultivation", "SELECT 1 FROM cultivation_sessions WHERE player_id = ? AND status = 'running' LIMIT 1"),
    ("production", "SELECT 1 FROM production_orders WHERE player_id = ? AND status = 'processing' LIMIT 1"),
    (
        "exploration",
        "SELECT 1 FROM exploration_sessions WHERE player_id = ? "
        "AND status IN ('created', 'running', 'combat_pending') LIMIT 1",
    ),
    (
        "battle",
        "SELECT 1 FROM battle_sessions WHERE player_id = ? "
        "AND status IN ('created', 'running') LIMIT 1",
    ),
)


class RestRepositoryMixin:
    """Own the residence rest start and settlement transaction boundary."""

    async def start_rest(
        self,
        *,
        platform: str,
        platform_user_id: str,
        operation_id: str,
    ) -> RestRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._start_rest_once, platform, platform_user_id, operation_id
            )

    def _start_rest_once(
        self, platform: str, platform_user_id: str, operation_id: str
    ) -> RestRecord:
        operation_name = "livelihood.rest"
        request_hash = self._request_hash(
            operation_name, {"platform": platform, "platform_user_id": platform_user_id}
        )
        now = self._now()
        now_text = serialize_datetime(now)
        business_date = now.date().isoformat()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = operation_replay(connection, operation_id, operation_name, request_hash)
            if existing is not None:
                return self._rest_from_payload(existing, replay=True)
            row = self._require_player(connection, platform, platform_user_id)
            player_id = int(row["id"])
            if connection.execute(
                "SELECT 1 FROM rest_sessions WHERE player_id = ? AND status = 'running' LIMIT 1",
                (player_id,),
            ).fetchone() is not None:
                raise RestBlockedError("rest")
            for reason, query in _BLOCK_QUERIES:
                if connection.execute(query, (player_id,)).fetchone() is not None:
                    raise RestBlockedError(reason)
            residence = self._active_residence(connection, player_id, now, now_text)
            if residence is None:
                raise ResidenceRequiredError("resting requires an active residence")
            snapshot = self._residence_snapshot(residence)
            rest_slots = int(snapshot["rest_slots"])
            if rest_slots < 1:
                raise ResidencePlotRequiredError("the residence has no rest slot")
            stamina = player_integer(row, "stamina")
            stamina_max = player_integer(row, "stamina_max")
            energy = player_integer(row, "energy")
            energy_max = player_integer(row, "energy_max")
            if stamina >= stamina_max and energy >= energy_max:
                raise RestNotNeededError("stamina and energy are already full")
            daily_limit = int(snapshot["rest_daily_limit"])
            used_today = connection.execute(
                "SELECT COUNT(*) AS count FROM rest_sessions "
                "WHERE player_id = ? AND business_date = ?",
                (player_id, business_date),
            ).fetchone()["count"]
            if int(used_today) >= daily_limit:
                raise RestDailyLimitError("daily rest limit reached")
            duration_seconds = int(snapshot["rest_duration_seconds"])
            ends_at = serialize_datetime(now + timedelta(seconds=duration_seconds))
            restore_stamina = int(snapshot["rest_stamina"])
            restore_energy = int(snapshot["rest_energy"])
            rest_id = uuid4().hex
            rest_snapshot = {
                "residence_id": str(residence["residence_id"]),
                "residence_key": str(snapshot["key"]),
                "residence_label": str(snapshot["label"]),
                "duration_seconds": duration_seconds,
                "restore_stamina": restore_stamina,
                "restore_energy": restore_energy,
                "daily_limit": daily_limit,
                "rest_slots": rest_slots,
                "starts_at": now_text,
                "ends_at": ends_at,
            }
            connection.execute(
                """
                INSERT INTO rest_sessions(
                    rest_id, player_id, residence_id, operation_id, status,
                    starts_at, ends_at, business_date, snapshot_json, result_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'running', ?, ?, ?, ?, '{}', ?, ?)
                """,
                (
                    rest_id,
                    player_id,
                    residence["residence_id"],
                    operation_id,
                    now_text,
                    ends_at,
                    business_date,
                    json.dumps(rest_snapshot, ensure_ascii=False, sort_keys=True),
                    now_text,
                    now_text,
                ),
            )
            payload = {
                "player": self._player_payload(self._row_to_player(row)),
                "rest_id": rest_id,
                "residence_id": rest_snapshot["residence_id"],
                "residence_key": rest_snapshot["residence_key"],
                "residence_label": rest_snapshot["residence_label"],
                "status": "running",
                "starts_at": now_text,
                "ends_at": ends_at,
                "restore_stamina": restore_stamina,
                "restore_energy": restore_energy,
                "restored_stamina": 0,
                "restored_energy": 0,
                "daily_limit": daily_limit,
                "used_today": int(used_today) + 1,
            }
            record_operation(connection, operation_id, operation_name, player_id, request_hash, payload, now_text)
            return self._rest_from_payload(payload)

    async def settle_rest(
        self,
        *,
        platform: str,
        platform_user_id: str,
        operation_id: str,
    ) -> RestRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._settle_rest_once, platform, platform_user_id, operation_id
            )

    def _settle_rest_once(
        self, platform: str, platform_user_id: str, operation_id: str
    ) -> RestRecord:
        operation_name = "livelihood.rest_settle"
        request_hash = self._request_hash(
            operation_name, {"platform": platform, "platform_user_id": platform_user_id}
        )
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = operation_replay(connection, operation_id, operation_name, request_hash)
            if existing is not None:
                return self._rest_from_payload(existing, replay=True)
            row = self._require_player(connection, platform, platform_user_id)
            player_id = int(row["id"])
            session = connection.execute(
                "SELECT * FROM rest_sessions WHERE player_id = ? AND status = 'running' "
                "ORDER BY id DESC LIMIT 1",
                (player_id,),
            ).fetchone()
            if session is None:
                raise RestNotFoundError("no running rest session")
            snapshot = self._rest_snapshot(session)
            ends_at = datetime.fromisoformat(str(session["ends_at"]))
            if ends_at.tzinfo is None:
                raise ValueError("invalid rest session end time")
            if now < ends_at:
                raise RestNotReadyError("rest session has not ended")
            stamina = player_integer(row, "stamina")
            stamina_max = player_integer(row, "stamina_max")
            energy = player_integer(row, "energy")
            energy_max = player_integer(row, "energy_max")
            restored_stamina = min(int(snapshot["restore_stamina"]), max(0, stamina_max - stamina))
            restored_energy = min(int(snapshot["restore_energy"]), max(0, energy_max - energy))
            change_player_state(
                connection,
                row,
                updated_at=now_text,
                value_delta={"stamina": restored_stamina, "energy": restored_energy},
                maximums={"stamina": stamina_max, "energy": energy_max},
            )
            connection.execute(
                "UPDATE rest_sessions SET status = 'settled', result_json = ?, updated_at = ? "
                "WHERE id = ? AND status = 'running'",
                (
                    json.dumps(
                        {
                            "restored_stamina": restored_stamina,
                            "restored_energy": restored_energy,
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    now_text,
                    session["id"],
                ),
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (player_id,)).fetchone()
            if updated is None:
                raise RuntimeError("rest settlement returned no player")
            used_today = connection.execute(
                "SELECT COUNT(*) AS count FROM rest_sessions "
                "WHERE player_id = ? AND business_date = ?",
                (player_id, str(session["business_date"])),
            ).fetchone()["count"]
            payload = {
                "player": self._player_payload(self._row_to_player(updated)),
                "rest_id": str(session["rest_id"]),
                "residence_id": str(session["residence_id"]),
                "residence_key": str(snapshot["residence_key"]),
                "residence_label": str(snapshot["residence_label"]),
                "status": "settled",
                "starts_at": str(session["starts_at"]),
                "ends_at": str(session["ends_at"]),
                "restore_stamina": int(snapshot["restore_stamina"]),
                "restore_energy": int(snapshot["restore_energy"]),
                "restored_stamina": restored_stamina,
                "restored_energy": restored_energy,
                "daily_limit": int(snapshot["daily_limit"]),
                "used_today": int(used_today),
            }
            record_operation(connection, operation_id, operation_name, player_id, request_hash, payload, now_text)
            return self._rest_from_payload(payload)

    async def get_rest_summary(self, *, platform: str, platform_user_id: str) -> dict[str, Any]:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._get_rest_summary_sync, platform, platform_user_id)

    def _get_rest_summary_sync(self, platform: str, platform_user_id: str) -> dict[str, Any]:
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = self._require_player(connection, platform, platform_user_id, writable=False)
            player_id = int(row["id"])
            residence = self._active_residence(connection, player_id, now, now_text)
            snapshot = self._residence_snapshot(residence) if residence is not None else None
            business_date = now.date().isoformat()
            used_today = connection.execute(
                "SELECT COUNT(*) AS count FROM rest_sessions "
                "WHERE player_id = ? AND business_date = ?",
                (player_id, business_date),
            ).fetchone()["count"]
            running = connection.execute(
                "SELECT ends_at FROM rest_sessions WHERE player_id = ? AND status = 'running' "
                "ORDER BY id DESC LIMIT 1",
                (player_id,),
            ).fetchone()
            return {
                "rest_slots": int(snapshot["rest_slots"]) if snapshot is not None else 0,
                "daily_limit": int(snapshot["rest_daily_limit"]) if snapshot is not None else 0,
                "used_today": int(used_today),
                "duration_seconds": (
                    int(snapshot["rest_duration_seconds"]) if snapshot is not None else 0
                ),
                "restore_stamina": int(snapshot["rest_stamina"]) if snapshot is not None else 0,
                "restore_energy": int(snapshot["rest_energy"]) if snapshot is not None else 0,
                "residence_label": str(snapshot["label"]) if snapshot is not None else None,
                "running_until": str(running["ends_at"]) if running is not None else None,
            }

    def _rest_snapshot(self, session: Any) -> dict[str, Any]:
        snapshot = decode_json_strict(session["snapshot_json"])
        if not isinstance(snapshot, dict):
            raise TypeError("rest snapshot must be an object")
        required = (
            "residence_id",
            "residence_key",
            "residence_label",
            "duration_seconds",
            "restore_stamina",
            "restore_energy",
            "daily_limit",
            "rest_slots",
            "starts_at",
            "ends_at",
        )
        for field in required:
            snapshot[field]
        if (
            any(
                not isinstance(snapshot[field], str) or not snapshot[field].strip()
                for field in ("residence_id", "residence_key", "residence_label", "starts_at", "ends_at")
            )
            or any(
                isinstance(snapshot[field], bool)
                or not isinstance(snapshot[field], int)
                or snapshot[field] <= 0
                for field in (
                    "duration_seconds",
                    "restore_stamina",
                    "restore_energy",
                    "daily_limit",
                )
            )
            or isinstance(snapshot["rest_slots"], bool)
            or not isinstance(snapshot["rest_slots"], int)
            or snapshot["rest_slots"] < 1
            or snapshot["starts_at"] != str(session["starts_at"])
            or snapshot["ends_at"] != str(session["ends_at"])
        ):
            raise ValueError("invalid rest snapshot")
        return snapshot

    def _rest_from_payload(self, payload: dict[str, Any], *, replay: bool = False) -> RestRecord:
        if (
            payload["status"] not in {"running", "settled"}
            or not isinstance(payload["residence_label"], str)
            or not payload["residence_label"].strip()
            or any(
                isinstance(payload[field], bool)
                or not isinstance(payload[field], int)
                or payload[field] < 0
                for field in ("restored_stamina", "restored_energy", "used_today")
            )
            or any(
                isinstance(payload[field], bool)
                or not isinstance(payload[field], int)
                or payload[field] <= 0
                for field in ("restore_stamina", "restore_energy", "daily_limit")
            )
        ):
            raise ValueError("invalid rest result")
        player = self._row_to_player(payload["player"])
        return RestRecord(
            player=player,
            rest_id=str(payload["rest_id"]),
            residence_id=str(payload["residence_id"]),
            residence_key=str(payload["residence_key"]),
            residence_label=str(payload["residence_label"]),
            status=str(payload["status"]),
            starts_at=str(payload["starts_at"]),
            ends_at=str(payload["ends_at"]),
            restore_stamina=int(payload["restore_stamina"]),
            restore_energy=int(payload["restore_energy"]),
            restored_stamina=int(payload["restored_stamina"]),
            restored_energy=int(payload["restored_energy"]),
            daily_limit=int(payload["daily_limit"]),
            used_today=int(payload["used_today"]),
            already_completed=replay,
        )


__all__ = ["RestRepositoryMixin"]
