"""SQLite persistence for previews and immutable attribute snapshots."""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import replace
from typing import Any

from ...contracts import serialize_datetime
from ..advancement.constitution_effects import constitution_effect_snapshot
from ..content import bundled_content
from ..items.manual_rules import manual_effect_totals
from ..utils.equipment import equipment_instance_rows
from ..utils.json_cache import decode_json_strict
from ..utils.operations import operation_replay, record_operation
from ..utils.player import player_inventory
from .models import StatSnapshot
from .rules import StatError, build_stat_preview, explain_stat


class StatsRepositoryMixin:
    async def preview_stats(self, *, platform: str, platform_user_id: str) -> dict[str, Any]:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._preview_stats_once, platform, platform_user_id)

    def _preview_stats_once(self, platform: str, platform_user_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            connection.execute("BEGIN")
            player = self._require_player(connection, platform, platform_user_id, writable=False)
            return self._build_player_stat_snapshot(connection, player)

    def _build_player_stat_snapshot(self, connection: Any, player: Any) -> dict[str, Any]:
        """Read one consistent build without creating a snapshot or changing assets."""
        player = dict(player)
        for field in ("qualification_json", "inventory_json"):
            player[field] = decode_json_strict(player[field])
            if not isinstance(player[field], dict):
                raise ValueError(f"player {field} must be an object")
        if any(type(value) is not int or value < 0 for value in player["inventory_json"].values()):
            raise ValueError("stat build inventory amounts must be non-negative integers")
        player_id = int(player["id"])
        equipment = self._battle_equipment_snapshot(connection, player_id)
        constitution = constitution_effect_snapshot(connection, player_id)
        manuals = manual_effect_totals(player_inventory(player), self.content)
        preview = build_stat_preview(
            player,
            self.content,
            equipment=equipment,
            constitution_effect=constitution,
            manual_effects=manuals,
        )
        for gear in self.companion_carry_snapshot(connection, player_id):
            value = int(gear["carry_capacity"])
            preview["derived_stats"]["carry_capacity"] += value
            preview["source_refs"].append({
                "key": "companion_gear", "value": gear, "multiplier_zone": "build",
                "effect": {"carry_capacity": value},
            })
        return {
            "player_id": player_id,
            **preview,
            "equipment": list(equipment),
            "constitution_effect": constitution,
            "manual_effects": manuals,
        }

    def _battle_equipment_snapshot(self, connection: Any, player_id: int) -> tuple[dict[str, Any], ...]:
        rows = equipment_instance_rows(
            connection, player_id, equipped_only=True, durable_only=True, active_only=True
        )
        content = self.content or bundled_content()
        player = connection.execute("SELECT path_key FROM players WHERE id = ?", (player_id,)).fetchone()
        if player is None:
            raise ValueError("equipment owner does not exist")
        path_key = str(player["path_key"] or "")
        equipment = []
        for row in rows:
            item_key = str(row["item_key"])
            definition = content.require("item", item_key, include_locked=False)
            if definition.get("path_key") not in {None, path_key}:
                continue
            affixes = decode_json_strict(row["affixes_json"])
            if not isinstance(affixes, dict) or any(
                isinstance(value, bool) or not isinstance(value, int) or value < 0
                for value in affixes.values()
            ):
                raise ValueError("equipment affixes must be non-negative integers")
            equipment.append({
                "instance_id": str(row["instance_id"]),
                "item_key": item_key,
                "slot": str(row["slot"]),
                "effects": list(definition["effects"]),
                "durability_bp": row["durability_bp"],
                "temper_level": row["temper_level"],
                "affixes": affixes,
            })
        return tuple(equipment)

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
            preview = self._build_player_stat_snapshot(connection, player)
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
            connection.execute("BEGIN")
            player = self._require_player(connection, platform, platform_user_id, writable=False)
            preview = self._build_player_stat_snapshot(connection, player)
            return explain_stat(preview, stat_key)


__all__ = ["StatsRepositoryMixin"]
