"""Personal heart-demon event projection and expiry handling."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from ...contracts import serialize_datetime
from ..persistence.errors import EventNotActiveError, HeartDemonPendingError
from .heart_demon_models import HeartDemonEventRecord


HEART_DEMON_EVENT_KEY = "event.heart_demon_trial"


class HeartDemonEventRepositoryMixin:
    """Keep the event-domain read model independent from breakthrough rules."""

    async def get_heart_demon_event(
        self,
        *,
        platform: str,
        platform_user_id: str,
        event_id: str | None = None,
    ) -> HeartDemonEventRecord:
        await self.initialize()
        async with self._inflight:
            await asyncio.to_thread(
                self._expire_heart_demon_for_player,
                platform,
                platform_user_id,
            )
            return await asyncio.to_thread(
                self._get_heart_demon_event_once,
                platform,
                platform_user_id,
                event_id,
            )

    async def expire_heart_demon_events(self) -> int:
        """Resolve every due personal event using the documented face branch."""

        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._expire_heart_demon_events_sync)

    def _get_heart_demon_event_once(
        self,
        platform: str,
        platform_user_id: str,
        event_id: str | None,
    ) -> HeartDemonEventRecord:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            player = self._require_player(connection, platform, platform_user_id, writable=False)
            if event_id:
                row = connection.execute(
                    "SELECT * FROM heart_demon_event_projections WHERE player_id = ? AND event_id = ?",
                    (player["id"], event_id),
                ).fetchone()
            else:
                row = connection.execute(
                    "SELECT * FROM heart_demon_event_projections WHERE player_id = ? ORDER BY id DESC LIMIT 1",
                    (player["id"],),
                ).fetchone()
            if row is None:
                raise EventNotActiveError("no heart demon event is available")
            return self._heart_demon_event_record(connection, player, row)

    def _expire_heart_demon_for_player(self, platform: str, platform_user_id: str) -> int:
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT session_id
                FROM heart_demon_sessions
                WHERE player_id = (
                    SELECT id FROM players WHERE platform = ? AND platform_user_id = ?
                ) AND status = 'pending' AND expires_at <= ?
                ORDER BY id
                """,
                (platform, platform_user_id, now_text),
            ).fetchall()
        resolved = 0
        for row in rows:
            operation_id = f"event.heart_demon_trial.timeout:{row['session_id']}"
            try:
                self._resolve_heart_demon_sync(
                    platform,
                    platform_user_id,
                    "heart_demon.face",
                    operation_id,
                )
            except HeartDemonPendingError:
                continue
            resolved += 1
        return resolved

    def _expire_heart_demon_events_sync(self) -> int:
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT p.platform, p.platform_user_id, h.session_id
                FROM heart_demon_sessions h
                JOIN players p ON p.id = h.player_id
                WHERE h.status = 'pending' AND h.expires_at <= ?
                ORDER BY h.id
                """,
                (now_text,),
            ).fetchall()
        resolved = 0
        for row in rows:
            operation_id = f"event.heart_demon_trial.timeout:{row['session_id']}"
            try:
                self._resolve_heart_demon_sync(
                    str(row["platform"]),
                    str(row["platform_user_id"]),
                    "heart_demon.face",
                    operation_id,
                )
            except HeartDemonPendingError:
                continue
            resolved += 1
        return resolved

    def _project_heart_demon_created(
        self,
        connection: Any,
        *,
        event_id: str,
        player_id: int,
        breakthrough_session_id: str,
        breakthrough_operation_id: str,
        starts_at: str,
        expires_at: str,
        snapshot: dict[str, object],
        created_at: str,
    ) -> None:
        connection.execute(
            """
            INSERT OR IGNORE INTO heart_demon_event_projections(
                event_id, event_key, player_id, breakthrough_session_id,
                breakthrough_operation_id, status, starts_at, expires_at,
                snapshot_json, result_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?, '{}', ?, ?)
            """,
            (
                event_id,
                HEART_DEMON_EVENT_KEY,
                player_id,
                breakthrough_session_id,
                breakthrough_operation_id,
                starts_at,
                expires_at,
                json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
                created_at,
                created_at,
            ),
        )
        connection.execute(
            """
            INSERT OR IGNORE INTO activity_events(
                player_id, event_key, source_operation_id, occurred_at, payload_json
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                player_id,
                HEART_DEMON_EVENT_KEY,
                breakthrough_operation_id,
                created_at,
                json.dumps(
                    {
                        "event_id": event_id,
                        "breakthrough_session_id": breakthrough_session_id,
                        "expires_at": expires_at,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            ),
        )

    def _project_heart_demon_resolved(
        self,
        connection: Any,
        *,
        event_id: str,
        choice_key: str,
        result: dict[str, object],
        resolved_at: str,
    ) -> None:
        connection.execute(
            """
            UPDATE heart_demon_event_projections
            SET status = 'resolved', choice_key = ?, resolved_at = ?,
                result_json = ?, updated_at = ?
            WHERE event_id = ? AND status = 'pending'
            """,
            (
                choice_key,
                resolved_at,
                json.dumps(result, ensure_ascii=False, sort_keys=True),
                resolved_at,
                event_id,
            ),
        )

    def _heart_demon_event_record(self, connection: Any, player: Any, row: Any) -> HeartDemonEventRecord:
        return HeartDemonEventRecord(
            player=self._row_to_player(player),
            event_id=str(row["event_id"]),
            event_key=str(row["event_key"]),
            status=str(row["status"]),
            breakthrough_session_id=str(row["breakthrough_session_id"]),
            breakthrough_operation_id=str(row["breakthrough_operation_id"]),
            starts_at=str(row["starts_at"]),
            expires_at=str(row["expires_at"]),
            choice_key=str(row["choice_key"]) if row["choice_key"] is not None else None,
            resolved_at=str(row["resolved_at"]) if row["resolved_at"] is not None else None,
            snapshot=self._json_object(row["snapshot_json"], {}),
            result=self._json_object(row["result_json"], {}),
        )


__all__ = ["HEART_DEMON_EVENT_KEY", "HeartDemonEventRepositoryMixin"]
