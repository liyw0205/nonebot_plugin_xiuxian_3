"""SQLite transactions for field plots and crop harvests."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from ...contracts import serialize_datetime
from ..persistence.errors import (
    CropContentClosedError,
    CropDailyLimitError,
    FieldPlotAlreadyHarvestedError,
    FieldPlotBusyError,
    FieldPlotNotFoundError,
    FieldPlotNotReadyError,
    FieldPlotWitheredError,
    OperationConflictError,
    ResidencePlotRequiredError,
    ResidenceRequiredError,
    ResourceInsufficientError,
)
from .models import FieldPlotRecord
from .rules import crop_definition, residence_definition, spirit_leaf_array_sand_roll


class FieldPlotRepositoryMixin:
    """Own the planting, maintenance and harvest transaction boundary."""

    async def plant_plot(
        self,
        *,
        platform: str,
        platform_user_id: str,
        crop_key: str,
        operation_id: str,
    ) -> FieldPlotRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._plant_plot_once, platform, platform_user_id, crop_key, operation_id
            )

    def _plant_plot_once(self, platform: str, platform_user_id: str, crop_key: str, operation_id: str) -> FieldPlotRecord:
        try:
            crop = crop_definition(crop_key)
        except ValueError as exc:
            raise CropContentClosedError("unsupported crop") from exc
        operation_name = "livelihood.plant"
        request_hash = self._request_hash(
            operation_name,
            {"platform": platform, "platform_user_id": platform_user_id, "crop_key": crop.key},
        )
        now = self._now()
        now_text = serialize_datetime(now)
        business_date = now.date().isoformat()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._operation(connection, operation_id, operation_name, request_hash)
            if existing is not None:
                return self._field_from_payload(existing, replay=True)
            row = self._require_player(connection, platform, platform_user_id)
            residence = self._active_residence(connection, int(row["id"]), now, now_text)
            if residence is None:
                raise ResidenceRequiredError("planting requires an active residence")
            residence_definition_value = residence_definition(str(residence["residence_key"]))
            if crop.residence_key and crop.residence_key != residence_definition_value.key:
                raise ResidencePlotRequiredError("the residence does not support this crop")
            if residence_definition_value.plot_count < 1:
                raise ResidencePlotRequiredError("the residence has no field plot")
            active = connection.execute(
                "SELECT * FROM field_plots WHERE residence_id = ? AND status IN ('growing', 'harvestable') LIMIT 1",
                (residence["residence_id"],),
            ).fetchone()
            if active is not None:
                raise FieldPlotBusyError("field plot is occupied")
            used = connection.execute(
                "SELECT COUNT(*) AS count FROM field_plots WHERE player_id = ? AND crop_key = ? AND business_date = ?",
                (row["id"], crop.key, business_date),
            ).fetchone()
            if used is not None and int(used["count"]) >= crop.daily_limit:
                raise CropDailyLimitError("crop daily limit reached")
            inventory = self._json_object(row["inventory_json"], {})
            if int(inventory.get(crop.seed_key, 0)) < 1:
                raise ResourceInsufficientError("seed is insufficient")
            if int(row["energy"]) < crop.maintenance_energy:
                raise ResourceInsufficientError("energy is insufficient")
            inventory[crop.seed_key] = int(inventory.get(crop.seed_key, 0)) - 1
            harvest_at = serialize_datetime(now + timedelta(seconds=crop.growth_seconds))
            plot_id = uuid4().hex
            snapshot = {
                "crop_key": crop.key,
                "seed_key": crop.seed_key,
                "required_maintenance": crop.required_maintenance,
                "maintenance_energy": crop.maintenance_energy,
                "maintained_harvest": crop.maintained_harvest,
                "unmaintained_harvest": crop.unmaintained_harvest,
                "content_version": crop.content_version,
                "rule_version": crop.rule_version,
                "wither_at": serialize_datetime(now + timedelta(seconds=crop.growth_seconds + 24 * 60 * 60)),
            }
            if crop.random_pool:
                snapshot.update(
                    {
                        "random_pool": crop.random_pool,
                        "random_seed": operation_id,
                        "array_sand_roll": spirit_leaf_array_sand_roll(operation_id),
                    }
                )
            connection.execute(
                "UPDATE players SET energy = energy - ?, inventory_json = ?, updated_at = ? WHERE id = ?",
                (crop.maintenance_energy, json.dumps(inventory, ensure_ascii=False, sort_keys=True), now_text, row["id"]),
            )
            connection.execute(
                """
                INSERT INTO field_plots(
                    plot_id, player_id, residence_id, operation_id, crop_key, status,
                    planted_at, harvest_at, business_date, maintenance_count,
                    snapshot_json, result_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'growing', ?, ?, ?, 0, ?, '{}', ?, ?)
                """,
                (
                    plot_id,
                    row["id"],
                    residence["residence_id"],
                    operation_id,
                    crop.key,
                    now_text,
                    harvest_at,
                    business_date,
                    json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
                    now_text,
                    now_text,
                ),
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (row["id"],)).fetchone()
            if updated is None:
                raise RuntimeError("plant returned no player")
            payload = self._field_payload(
                updated,
                plot_id=plot_id,
                residence_id=str(residence["residence_id"]),
                crop_key=crop.key,
                status="growing",
                planted_at=now_text,
                harvest_at=harvest_at,
                maintenance_count=0,
                required_maintenance=crop.required_maintenance,
            )
            self._record_operation(connection, operation_id, operation_name, row["id"], request_hash, payload, now_text)
            return self._field_from_payload(payload)

    async def maintain_plot(self, *, platform: str, platform_user_id: str, operation_id: str) -> FieldPlotRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._maintain_plot_once, platform, platform_user_id, operation_id)

    def _maintain_plot_once(self, platform: str, platform_user_id: str, operation_id: str) -> FieldPlotRecord:
        operation_name = "livelihood.maintain_plot"
        request_hash = self._request_hash(operation_name, {"platform": platform, "platform_user_id": platform_user_id})
        return self._mutate_plot(operation_name, request_hash, platform, platform_user_id, operation_id, "maintain")

    async def harvest_plot(self, *, platform: str, platform_user_id: str, operation_id: str) -> FieldPlotRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._harvest_plot_once, platform, platform_user_id, operation_id)

    async def get_field_plot(self, *, platform: str, platform_user_id: str) -> FieldPlotRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._get_field_plot_sync, platform, platform_user_id)

    def _get_field_plot_sync(self, platform: str, platform_user_id: str) -> FieldPlotRecord:
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            row = self._require_player(connection, platform, platform_user_id, writable=False)
            plot = connection.execute(
                "SELECT * FROM field_plots WHERE player_id = ? ORDER BY id DESC LIMIT 1", (row["id"],)
            ).fetchone()
            if plot is None:
                raise FieldPlotNotFoundError("no field plot")
            status = str(plot["status"])
            snapshot = self._json_object(plot["snapshot_json"], {})
            if status == "growing" and now >= datetime.fromisoformat(str(plot["harvest_at"])):
                status = "harvestable"
                connection.execute(
                    "UPDATE field_plots SET status = 'harvestable', updated_at = ? WHERE id = ? AND status = 'growing'",
                    (now_text, plot["id"]),
                )
            if status in {"growing", "harvestable"} and now > datetime.fromisoformat(str(snapshot.get("wither_at", plot["harvest_at"]))):
                status = "withered"
                connection.execute(
                    "UPDATE field_plots SET status = 'withered', updated_at = ? WHERE id = ? AND status IN ('growing', 'harvestable')",
                    (now_text, plot["id"]),
                )
            result = self._json_object(plot["result_json"], {})
            payload = self._field_payload(
                row,
                plot_id=str(plot["plot_id"]),
                residence_id=str(plot["residence_id"]),
                crop_key=str(plot["crop_key"]) if plot["crop_key"] else "",
                status=status,
                planted_at=str(plot["planted_at"]),
                harvest_at=str(plot["harvest_at"]),
                maintenance_count=int(plot["maintenance_count"]),
                required_maintenance=int(snapshot.get("required_maintenance", 1)),
                harvest={str(key): int(value) for key, value in dict(result.get("harvest", {})).items()},
                local_reputation_delta=int(result.get("local_reputation_delta", 0)),
            )
            return self._field_from_payload(payload)

    def _harvest_plot_once(self, platform: str, platform_user_id: str, operation_id: str) -> FieldPlotRecord:
        operation_name = "livelihood.harvest"
        request_hash = self._request_hash(operation_name, {"platform": platform, "platform_user_id": platform_user_id})
        return self._mutate_plot(operation_name, request_hash, platform, platform_user_id, operation_id, "harvest")

    def _mutate_plot(
        self,
        operation_name: str,
        request_hash: str,
        platform: str,
        platform_user_id: str,
        operation_id: str,
        action: str,
    ) -> FieldPlotRecord:
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._operation(connection, operation_id, operation_name, request_hash)
            if existing is not None:
                return self._field_from_payload(existing, replay=True)
            row = self._require_player(connection, platform, platform_user_id)
            plot = connection.execute(
                "SELECT * FROM field_plots WHERE player_id = ? AND status IN ('growing', 'harvestable') ORDER BY id DESC LIMIT 1",
                (row["id"],),
            ).fetchone()
            if plot is None:
                latest = connection.execute(
                    "SELECT status FROM field_plots WHERE player_id = ? ORDER BY id DESC LIMIT 1", (row["id"],)
                ).fetchone()
                if latest is not None and str(latest["status"]) == "harvested":
                    raise FieldPlotAlreadyHarvestedError("field plot already harvested")
                raise FieldPlotNotFoundError("no active field plot")
            snapshot = self._json_object(plot["snapshot_json"], {})
            wither_at = datetime.fromisoformat(str(snapshot.get("wither_at", plot["harvest_at"])))
            harvest_at = datetime.fromisoformat(str(plot["harvest_at"]))
            if now > wither_at:
                connection.execute(
                    "UPDATE field_plots SET status = 'withered', updated_at = ? WHERE id = ? AND status IN ('growing', 'harvestable')",
                    (now_text, plot["id"]),
                )
                raise FieldPlotWitheredError("field plot withered")
            if action == "maintain":
                if str(plot["status"]) != "growing":
                    raise FieldPlotNotReadyError("field plot is no longer growing")
                if now >= harvest_at:
                    connection.execute(
                        "UPDATE field_plots SET status = 'harvestable', updated_at = ? WHERE id = ? AND status = 'growing'",
                        (now_text, plot["id"]),
                    )
                    raise FieldPlotNotReadyError("maintenance window has ended")
                required = int(snapshot.get("required_maintenance", 1))
                count = int(plot["maintenance_count"])
                if count >= required:
                    raise FieldPlotNotReadyError("field plot maintenance is complete")
                if int(row["energy"]) < int(snapshot.get("maintenance_energy", 1)):
                    raise ResourceInsufficientError("energy is insufficient")
                count += 1
                connection.execute(
                    "UPDATE players SET energy = energy - ?, updated_at = ? WHERE id = ?",
                    (int(snapshot.get("maintenance_energy", 1)), now_text, row["id"]),
                )
                connection.execute(
                    "UPDATE field_plots SET maintenance_count = ?, updated_at = ? WHERE id = ? AND status = 'growing'",
                    (count, now_text, plot["id"]),
                )
                updated = connection.execute("SELECT * FROM players WHERE id = ?", (row["id"],)).fetchone()
                if updated is None:
                    raise RuntimeError("maintenance returned no player")
                payload = self._field_payload(
                    updated,
                    plot_id=str(plot["plot_id"]),
                    residence_id=str(plot["residence_id"]),
                    crop_key=str(plot["crop_key"]),
                    status="growing",
                    planted_at=str(plot["planted_at"]),
                    harvest_at=str(plot["harvest_at"]),
                    maintenance_count=count,
                    required_maintenance=required,
                )
            else:
                if now < harvest_at:
                    raise FieldPlotNotReadyError("field plot is not ready")
                status = "harvestable"
                if str(plot["status"]) == "growing":
                    connection.execute(
                        "UPDATE field_plots SET status = 'harvestable', updated_at = ? WHERE id = ? AND status = 'growing'",
                        (now_text, plot["id"]),
                    )
                maintained = int(plot["maintenance_count"]) >= int(snapshot.get("required_maintenance", 1))
                harvest = dict(snapshot.get("maintained_harvest" if maintained else "unmaintained_harvest", {}))
                if maintained and int(snapshot.get("array_sand_roll", 0)):
                    harvest["item.mat.array_sand"] = int(harvest.get("item.mat.array_sand", 0)) + 1
                inventory = self._json_object(row["inventory_json"], {})
                for item_key, quantity in harvest.items():
                    inventory[str(item_key)] = int(inventory.get(str(item_key), 0)) + int(quantity)
                connection.execute(
                    "UPDATE players SET inventory_json = ?, updated_at = ? WHERE id = ?",
                    (json.dumps(inventory, ensure_ascii=False, sort_keys=True), now_text, row["id"]),
                )
                reputation_delta = 1 if str(plot["crop_key"]) == "crop.blood_grass" else 0
                if reputation_delta:
                    reputation = connection.execute(
                        "SELECT local_json FROM player_reputations WHERE player_id = ?", (row["id"],)
                    ).fetchone()
                    local = self._json_object(reputation["local_json"], {}) if reputation is not None else {}
                    local_key = "local.xuantian.new_town"
                    local[local_key] = min(1000, int(local.get(local_key, 0)) + reputation_delta)
                    connection.execute(
                        """
                        INSERT INTO player_reputations(player_id, local_json, service_reputation, updated_at)
                        VALUES (?, ?, 0, ?)
                        ON CONFLICT(player_id) DO UPDATE SET local_json = excluded.local_json, updated_at = excluded.updated_at
                        """,
                        (row["id"], json.dumps(local, ensure_ascii=False, sort_keys=True), now_text),
                    )
                connection.execute(
                    "UPDATE field_plots SET status = 'harvested', result_json = ?, updated_at = ? WHERE id = ? AND status IN ('growing', 'harvestable')",
                    (json.dumps({"harvest": harvest, "maintained": maintained, "local_reputation_delta": reputation_delta}, ensure_ascii=False, sort_keys=True), now_text, plot["id"]),
                )
                updated = connection.execute("SELECT * FROM players WHERE id = ?", (row["id"],)).fetchone()
                if updated is None:
                    raise RuntimeError("harvest returned no player")
                payload = self._field_payload(
                    updated,
                    plot_id=str(plot["plot_id"]),
                    residence_id=str(plot["residence_id"]),
                    crop_key=str(plot["crop_key"]),
                    status="harvested",
                    planted_at=str(plot["planted_at"]),
                    harvest_at=str(plot["harvest_at"]),
                    maintenance_count=int(plot["maintenance_count"]),
                    required_maintenance=int(snapshot.get("required_maintenance", 1)),
                    harvest=harvest,
                    local_reputation_delta=reputation_delta,
                )
            self._record_operation(connection, operation_id, operation_name, row["id"], request_hash, payload, now_text)
            return self._field_from_payload(payload)

    @staticmethod
    def _operation(connection: Any, operation_id: str, operation_name: str, request_hash: str) -> dict[str, Any] | None:
        existing = connection.execute(
            "SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id = ?",
            (operation_id,),
        ).fetchone()
        if existing is None:
            return None
        if existing["operation_name"] != operation_name or existing["request_hash"] != request_hash:
            raise OperationConflictError("operation input differs from its original request")
        return json.loads(existing["result_json"])

    @staticmethod
    def _record_operation(connection: Any, operation_id: str, operation_name: str, player_id: int, request_hash: str, payload: dict[str, Any], now_text: str) -> None:
        connection.execute(
            "INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (operation_id, operation_name, player_id, request_hash, json.dumps(payload, ensure_ascii=False, sort_keys=True), now_text),
        )

    def _field_payload(self, player: Any, *, plot_id: str, residence_id: str, crop_key: str, status: str, planted_at: str, harvest_at: str, maintenance_count: int, required_maintenance: int, harvest: dict[str, int] | None = None, local_reputation_delta: int = 0) -> dict[str, Any]:
        return {
            "player": self._player_payload(self._row_to_player(player)),
            "plot_id": plot_id,
            "residence_id": residence_id,
            "crop_key": crop_key,
            "status": status,
            "planted_at": planted_at,
            "harvest_at": harvest_at,
            "maintenance_count": maintenance_count,
            "required_maintenance": required_maintenance,
            "harvest": harvest or {},
            "local_reputation_delta": local_reputation_delta,
        }

    def _field_from_payload(self, payload: dict[str, Any], *, replay: bool = False) -> FieldPlotRecord:
        player_payload = payload["player"]
        player = self._row_to_player(player_payload)
        return FieldPlotRecord(
            player=player,
            plot_id=str(payload["plot_id"]),
            residence_id=str(payload["residence_id"]),
            crop_key=payload.get("crop_key"),
            status=str(payload["status"]),
            planted_at=payload.get("planted_at"),
            harvest_at=payload.get("harvest_at"),
            maintenance_count=int(payload.get("maintenance_count", 0)),
            required_maintenance=int(payload.get("required_maintenance", 0)),
            harvest={str(key): int(value) for key, value in dict(payload.get("harvest", {})).items()},
            local_reputation_delta=int(payload.get("local_reputation_delta", 0)),
            already_completed=replay,
        )


__all__ = ["FieldPlotRepositoryMixin"]
