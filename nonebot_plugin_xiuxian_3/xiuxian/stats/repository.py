"""SQLite persistence for previews and immutable attribute snapshots."""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import replace
from typing import Any

from ...contracts import serialize_datetime
from ..persistence.errors import OperationConflictError, PlayerNotFoundError
from ..utils.operations import operation_replay, record_operation
from .models import StatSnapshot
from .rules import StatError, build_stat_preview, explain_stat


class StatsRepositoryMixin:
    async def preview_stats(self, *, platform: str, platform_user_id: str) -> dict[str, Any]:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._preview_stats_once, platform, platform_user_id)

    def _preview_stats_once(self, platform: str, platform_user_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            player = self._require_player(connection, platform, platform_user_id, writable=False)
            return {"player_id": int(player["id"]), **build_stat_preview(player, self.content)}

    async def freeze_stats(self, *, platform: str, platform_user_id: str, purpose: str, operation_id: str) -> StatSnapshot:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._freeze_stats_once, platform, platform_user_id, purpose, operation_id)

    def _freeze_stats_once(self, platform: str, platform_user_id: str, purpose: str, operation_id: str) -> StatSnapshot:
        if not isinstance(purpose, str) or not purpose.strip():
            raise StatError("STAT_SNAPSHOT_INVALID", "属性快照必须注明用途。")
        if not isinstance(operation_id, str) or not operation_id.strip():
            raise StatError("STAT_SNAPSHOT_INVALID", "属性快照缺少操作凭证。")
        operation_name = "stats.freeze"
        request_payload = {"platform": platform, "platform_user_id": platform_user_id, "purpose": purpose}
        request_hash = self._request_hash(operation_name, request_payload)
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            player = self._require_player(connection, platform, platform_user_id)
            replay = operation_replay(connection, operation_id, operation_name, request_hash, player_id=int(player["id"]))
            if replay is not None:
                return replace(StatSnapshot.from_payload(replay), already_completed=True)
            preview = {"player_id": int(player["id"]), **build_stat_preview(player, self.content)}
            digest = hashlib.sha256(f"{operation_id}:{preview['formula_fingerprint']}".encode("utf-8")).hexdigest()
            snapshot = StatSnapshot(
                snapshot_id=f"stats-{digest[:32]}",
                player_id=int(player["id"]),
                base_stats=dict(preview["base_stats"]),
                path_stats=dict(preview["path_stats"]),
                derived_stats=dict(preview["derived_stats"]),
                source_refs=tuple(dict(item) for item in preview["source_refs"]),
                formula_fingerprint=str(preview["formula_fingerprint"]),
                purpose=purpose,
                created_at=now_text,
            )
            payload = snapshot.payload()
            connection.execute(
                "INSERT INTO stat_snapshots(snapshot_id, player_id, purpose, base_stats_json, path_stats_json, derived_stats_json, source_refs_json, formula_fingerprint, operation_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (snapshot.snapshot_id, snapshot.player_id, purpose, json.dumps(snapshot.base_stats, ensure_ascii=False, sort_keys=True), json.dumps(snapshot.path_stats, ensure_ascii=False, sort_keys=True), json.dumps(snapshot.derived_stats, ensure_ascii=False, sort_keys=True), json.dumps(snapshot.source_refs, ensure_ascii=False, sort_keys=True), snapshot.formula_fingerprint, operation_id, now_text),
            )
            record_operation(connection, operation_id, operation_name, snapshot.player_id, request_hash, payload, now_text)
            return snapshot

    async def explain_stats(self, *, platform: str, platform_user_id: str, stat_key: str) -> dict[str, Any]:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._explain_stats_once, platform, platform_user_id, stat_key)

    def _explain_stats_once(self, platform: str, platform_user_id: str, stat_key: str) -> dict[str, Any]:
        with self._connect() as connection:
            player = self._require_player(connection, platform, platform_user_id, writable=False)
            preview = {"player_id": int(player["id"]), **build_stat_preview(player, self.content)}
            return explain_stat(preview, stat_key)


__all__ = ["StatsRepositoryMixin"]
