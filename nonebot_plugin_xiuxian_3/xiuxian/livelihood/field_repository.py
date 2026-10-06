"""SQLite transactions for field plots and crop harvests."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from ...contracts import serialize_datetime
from ..content import bundled_content
from ..persistence.errors import (
    CropContentClosedError,
    CropDailyLimitError,
    FieldPlotAlreadyHarvestedError,
    FieldPlotBusyError,
    FieldPlotNotFoundError,
    FieldPlotNotReadyError,
    FieldPlotWitheredError,
    ResidencePlotRequiredError,
    ResidenceRequiredError,
    ResourceInsufficientError,
)
from ..specials.codex_projection import record_material_discoveries
from ..utils.assets import inventory_amount
from ..utils.json_cache import decode_json_strict
from ..utils.operations import operation_replay, record_operation
from ..utils.player import (
    change_player_state,
    grant_player_reward,
    player_integer,
    player_inventory,
    spend_player_state,
)
from .models import FieldPlotRecord
from .rules import crop_definition, crop_harvest_bonus


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
        operation_name = "livelihood.plant"
        request_value = (crop_key or "").strip() or "<default>"
        request_hash = self._request_hash(
            operation_name,
            {"platform": platform, "platform_user_id": platform_user_id, "crop_key": request_value},
        )
        now = self._now()
        now_text = serialize_datetime(now)
        business_date = now.date().isoformat()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = operation_replay(connection, operation_id, operation_name, request_hash)
            if existing is not None:
                return self._field_from_payload(existing, replay=True)
            try:
                crop = crop_definition(crop_key, self.content)
            except ValueError as exc:
                raise CropContentClosedError("unsupported crop") from exc
            row = self._require_player(connection, platform, platform_user_id)
            residence = self._active_residence(connection, int(row["id"]), now, now_text)
            if residence is None:
                raise ResidenceRequiredError("planting requires an active residence")
            residence_snapshot = self._residence_snapshot(residence)
            plot_count = int(residence_snapshot["plot_count"])
            if crop.residence_key and crop.residence_key != str(residence["residence_key"]):
                raise ResidencePlotRequiredError("the residence does not support this crop")
            if plot_count < 1:
                raise ResidencePlotRequiredError("the residence has no field plot")
            active = connection.execute(
                "SELECT * FROM field_plots WHERE player_id = ? AND residence_id = ? "
                "AND status IN ('growing', 'harvestable') ORDER BY id",
                (row["id"], residence["residence_id"]),
            ).fetchall()
            for plot in active:
                _, _, wither_at = self._field_window(plot)
                if now <= wither_at:
                    raise FieldPlotBusyError("field plot is occupied")
                connection.execute(
                    "UPDATE field_plots SET status = 'withered', updated_at = ? WHERE id = ?",
                    (now_text, plot["id"]),
                )
            used = connection.execute(
                "SELECT COUNT(*) AS count FROM field_plots WHERE player_id = ? AND crop_key = ? AND business_date = ?",
                (row["id"], crop.key, business_date),
            ).fetchone()
            if used is not None and int(used["count"]) >= crop.daily_limit:
                raise CropDailyLimitError("crop daily limit reached")
            inventory = player_inventory(row)
            if inventory_amount(inventory, crop.seed_key) < crop.seed_quantity:
                raise ResourceInsufficientError("seed is insufficient")
            if player_integer(row, "energy") < crop.maintenance_energy:
                raise ResourceInsufficientError("energy is insufficient")
            harvest_at = serialize_datetime(now + timedelta(seconds=crop.growth_seconds))
            random_harvest = crop_harvest_bonus(crop, operation_id)
            content = self.content or bundled_content()
            harvest_labels = {
                key: content.label("item", key)
                for key in sorted(
                    set(crop.maintained_harvest) | set(crop.unmaintained_harvest)
                    | set(crop.maintained_harvest_ranges or {})
                )
            }
            plot_id = uuid4().hex
            snapshot = {
                "crop_key": crop.key,
                "crop_label": crop.label,
                "seed_key": crop.seed_key,
                "seed_quantity": crop.seed_quantity,
                "growth_seconds": crop.growth_seconds,
                "required_maintenance": crop.required_maintenance,
                "maintenance_energy": crop.maintenance_energy,
                "maintained_harvest": crop.maintained_harvest,
                "maintained_harvest_ranges": crop.maintained_harvest_ranges or {},
                "unmaintained_harvest": crop.unmaintained_harvest,
                "random_pool": crop.random_pool,
                "random_harvest": random_harvest,
                "harvest_labels": harvest_labels,
                "reputation_key": crop.reputation_key,
                "reputation_delta": crop.reputation_delta,
                "reputation_maximum": crop.reputation_maximum,
                "wither_at": serialize_datetime(now + timedelta(seconds=crop.growth_seconds + 24 * 60 * 60)),
            }
            if crop.random_pool:
                snapshot["random_seed"] = operation_id
                snapshot["array_sand_roll"] = random_harvest.get("item.mat.array_sand", 0)
            spend_player_state(
                connection,
                row,
                updated_at=now_text,
                costs={crop.seed_key: crop.seed_quantity},
                value_delta={"energy": -crop.maintenance_energy},
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
                crop_label=crop.label,
                harvest_labels=harvest_labels,
            )
            record_operation(connection, operation_id, operation_name, row["id"], request_hash, payload, now_text)
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
            connection.execute("BEGIN IMMEDIATE")
            row = self._require_player(connection, platform, platform_user_id, writable=False)
            plot, snapshot, status = self._select_field_plot(connection, int(row["id"]), now, "profile")
            if status != str(plot["status"]):
                connection.execute(
                    "UPDATE field_plots SET status = ?, updated_at = ? WHERE id = ?",
                    (status, now_text, plot["id"]),
                )
            result = decode_json_strict(plot["result_json"])
            if not isinstance(result, dict):
                raise TypeError("field plot result must be an object")
            harvest = result["harvest"] if status == "harvested" else {}
            payload = self._field_payload(
                row,
                plot_id=str(plot["plot_id"]),
                residence_id=str(plot["residence_id"]),
                crop_key=str(plot["crop_key"]) if plot["crop_key"] else "",
                status=status,
                planted_at=str(plot["planted_at"]),
                harvest_at=str(plot["harvest_at"]),
                maintenance_count=int(plot["maintenance_count"]),
                required_maintenance=int(snapshot["required_maintenance"]),
                crop_label=str(snapshot["crop_label"]),
                harvest_labels=snapshot["harvest_labels"],
                harvest=harvest,
                local_reputation_delta=result["local_reputation_delta"] if status == "harvested" else 0,
            )
            return self._field_from_payload(payload)

    def _select_field_plot(
        self, connection: Any, player_id: int, now: datetime, action: str
    ) -> tuple[Any, dict[str, Any], str]:
        plots = connection.execute(
            "SELECT * FROM field_plots WHERE player_id = ? "
            "AND status IN ('growing', 'harvestable') ORDER BY id",
            (player_id,),
        ).fetchall()
        candidates = []
        for plot in plots:
            snapshot, harvest_at, wither_at = self._field_window(plot)
            candidates.append((plot, snapshot, harvest_at, wither_at))

        # A renewed lease may coexist with an older crop; select by action, not row age.
        ready = [entry for entry in candidates if entry[2] <= now <= entry[3]]
        growing = [entry for entry in candidates if now < entry[2]]
        if action == "maintain":
            available = [
                entry for entry in growing
                if int(entry[0]["maintenance_count"]) < entry[1]["required_maintenance"]
            ]
            deadline_index = 2
        elif ready:
            available = ready
            deadline_index = 3
        else:
            available = growing if action == "profile" else []
            deadline_index = 2
        if available:
            selected = min(available, key=lambda entry: (entry[deadline_index], int(entry[0]["id"])))
            plot, snapshot, harvest_at, _ = selected
            return plot, snapshot, "harvestable" if now >= harvest_at else "growing"
        if action != "profile" and (growing or ready):
            raise FieldPlotNotReadyError("no field plot is ready for this action")

        latest = connection.execute(
            "SELECT * FROM field_plots WHERE player_id = ? ORDER BY id DESC LIMIT 1", (player_id,)
        ).fetchone()
        if latest is None:
            raise FieldPlotNotFoundError("no field plot")
        snapshot = self._field_snapshot(latest)
        status = str(latest["status"])
        if status in {"growing", "harvestable"}:
            status = "withered"
        if action == "profile":
            return latest, snapshot, status
        if status == "withered":
            raise FieldPlotWitheredError("field plot withered")
        if action == "harvest" and status == "harvested":
            raise FieldPlotAlreadyHarvestedError("field plot already harvested")
        raise FieldPlotNotFoundError("no active field plot")

    def _field_window(self, plot: Any) -> tuple[dict[str, Any], datetime, datetime]:
        snapshot = self._field_snapshot(plot)
        harvest_at = datetime.fromisoformat(str(plot["harvest_at"]))
        wither_at = datetime.fromisoformat(snapshot["wither_at"])
        if harvest_at.tzinfo is None or wither_at.tzinfo is None or wither_at < harvest_at:
            raise ValueError("invalid field plot harvest window")
        return snapshot, harvest_at, wither_at

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
            existing = operation_replay(connection, operation_id, operation_name, request_hash)
            if existing is not None:
                return self._field_from_payload(existing, replay=True)
            row = self._require_player(connection, platform, platform_user_id)
            plot, snapshot, _ = self._select_field_plot(connection, int(row["id"]), now, action)
            if action == "maintain":
                required = int(snapshot["required_maintenance"])
                count = int(plot["maintenance_count"])
                if player_integer(row, "energy") < int(snapshot["maintenance_energy"]):
                    raise ResourceInsufficientError("energy is insufficient")
                count += 1
                change_player_state(
                    connection,
                    row,
                    updated_at=now_text,
                    value_delta={"energy": -int(snapshot["maintenance_energy"])},
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
                    crop_label=str(snapshot["crop_label"]),
                    harvest_labels=snapshot["harvest_labels"],
                )
            else:
                maintained = int(plot["maintenance_count"]) >= int(snapshot["required_maintenance"])
                harvest = dict(snapshot["maintained_harvest" if maintained else "unmaintained_harvest"])
                if maintained:
                    for item_key, quantity in dict(snapshot["random_harvest"]).items():
                        harvest[item_key] = int(harvest.get(item_key, 0)) + int(quantity)
                reputation_key = snapshot.get("reputation_key")
                reputation_delta = int(snapshot["reputation_delta"])
                reward = dict(harvest)
                if reputation_delta and isinstance(reputation_key, str) and reputation_key:
                    reward[reputation_key] = reputation_delta
                grant_player_reward(
                    connection,
                    row,
                    reward,
                    now_text,
                    local_reputation_maximums=(
                        {reputation_key: int(snapshot["reputation_maximum"])}
                        if reputation_delta and isinstance(reputation_key, str) and reputation_key
                        else None
                    ),
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
                    required_maintenance=int(snapshot["required_maintenance"]),
                    crop_label=str(snapshot["crop_label"]),
                    harvest_labels=snapshot["harvest_labels"],
                    harvest=harvest,
                    local_reputation_delta=reputation_delta,
                )
                record_material_discoveries(
                    connection,
                    player_id=int(row["id"]),
                    operation_id=operation_id,
                    occurred_at=now,
                    reward=harvest,
                    snapshot={
                        "source": "livelihood.harvest",
                        "crop_key": str(plot["crop_key"]),
                        "maintained": maintained,
                    },
                )
            record_operation(connection, operation_id, operation_name, row["id"], request_hash, payload, now_text)
            return self._field_from_payload(payload)

    def _field_snapshot(self, plot: Any) -> dict[str, Any]:
        snapshot = decode_json_strict(plot["snapshot_json"])
        if not isinstance(snapshot, dict):
            raise TypeError("field plot snapshot must be an object")
        required = (
            "crop_key",
            "crop_label",
            "seed_key",
            "seed_quantity",
            "growth_seconds",
            "required_maintenance",
            "maintenance_energy",
            "maintained_harvest",
            "maintained_harvest_ranges",
            "unmaintained_harvest",
            "random_pool",
            "random_harvest",
            "harvest_labels",
            "reputation_key",
            "reputation_delta",
            "reputation_maximum",
            "wither_at",
        )
        for field in required:
            snapshot[field]
        if (
            not isinstance(snapshot["crop_key"], str)
            or not isinstance(snapshot["crop_label"], str)
            or not snapshot["crop_label"].strip()
            or not isinstance(snapshot["seed_key"], str)
            or isinstance(snapshot["seed_quantity"], bool)
            or not isinstance(snapshot["seed_quantity"], int)
            or snapshot["seed_quantity"] <= 0
            or isinstance(snapshot["growth_seconds"], bool)
            or not isinstance(snapshot["growth_seconds"], int)
            or snapshot["growth_seconds"] <= 0
            or isinstance(snapshot["required_maintenance"], bool)
            or not isinstance(snapshot["required_maintenance"], int)
            or snapshot["required_maintenance"] < 0
            or isinstance(snapshot["maintenance_energy"], bool)
            or not isinstance(snapshot["maintenance_energy"], int)
            or snapshot["maintenance_energy"] < 0
            or any(not isinstance(snapshot[field], dict) for field in ("maintained_harvest", "maintained_harvest_ranges", "unmaintained_harvest", "random_harvest"))
            or (snapshot["random_pool"] is not None and not isinstance(snapshot["random_pool"], str))
            or (snapshot["reputation_key"] is not None and not isinstance(snapshot["reputation_key"], str))
            or isinstance(snapshot["reputation_delta"], bool)
            or not isinstance(snapshot["reputation_delta"], int)
            or snapshot["reputation_delta"] < 0
            or (snapshot["reputation_maximum"] is not None and (isinstance(snapshot["reputation_maximum"], bool) or not isinstance(snapshot["reputation_maximum"], int)))
            or not isinstance(snapshot["wither_at"], str)
        ):
            raise ValueError("invalid field plot snapshot")
        if snapshot["crop_key"] != plot["crop_key"] or not 0 <= int(plot["maintenance_count"]) <= snapshot["required_maintenance"]:
            raise ValueError("field plot does not match its snapshot")
        reputation_key = snapshot["reputation_key"]
        if reputation_key is None:
            if snapshot["reputation_delta"] != 0 or snapshot["reputation_maximum"] is not None:
                raise ValueError("field plot reputation requires a location")
        elif (
            not reputation_key.startswith("local.")
            or snapshot["reputation_maximum"] is None
            or snapshot["reputation_maximum"] <= 0
        ):
            raise ValueError("invalid field plot local reputation")
        labels = self._field_harvest_labels(snapshot, ("maintained_harvest", "unmaintained_harvest", "random_harvest"))
        for key, bounds in snapshot["maintained_harvest_ranges"].items():
            if (
                key not in labels or not isinstance(bounds, list) or len(bounds) != 2
                or any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in bounds)
                or bounds[0] > bounds[1]
            ):
                raise ValueError("invalid field plot harvest range")
        return snapshot

    @staticmethod
    def _field_harvest_labels(payload: dict[str, Any], fields: tuple[str, ...]) -> dict[str, str]:
        labels = payload["harvest_labels"]
        if not isinstance(labels, dict) or any(
            not key.startswith("item.") or not isinstance(label, str) or not label.strip()
            for key, label in labels.items()
        ):
            raise ValueError("invalid field plot harvest labels")
        for field in fields:
            harvest = payload[field]
            if not isinstance(harvest, dict) or any(
                key not in labels or isinstance(value, bool) or not isinstance(value, int) or value <= 0
                for key, value in harvest.items()
            ):
                raise ValueError("invalid field plot harvest")
        return labels

    def _field_payload(self, player: Any, *, plot_id: str, residence_id: str, crop_key: str, status: str, planted_at: str, harvest_at: str, maintenance_count: int, required_maintenance: int, crop_label: str, harvest_labels: dict[str, str], harvest: dict[str, int] | None = None, local_reputation_delta: int = 0) -> dict[str, Any]:
        return {
            "player": self._player_payload(self._row_to_player(player)),
            "plot_id": plot_id,
            "residence_id": residence_id,
            "crop_key": crop_key,
            "crop_label": crop_label,
            "harvest_labels": dict(harvest_labels),
            "status": status,
            "planted_at": planted_at,
            "harvest_at": harvest_at,
            "maintenance_count": maintenance_count,
            "required_maintenance": required_maintenance,
            "harvest": harvest or {},
            "local_reputation_delta": local_reputation_delta,
        }

    def _field_from_payload(self, payload: dict[str, Any], *, replay: bool = False) -> FieldPlotRecord:
        labels = self._field_harvest_labels(payload, ("harvest",))
        if (
            payload["status"] not in {"growing", "harvestable", "harvested", "withered"}
            or not isinstance(payload["crop_label"], str) or not payload["crop_label"].strip()
            or any(
                isinstance(payload[field], bool) or not isinstance(payload[field], int) or payload[field] < 0
                for field in ("maintenance_count", "required_maintenance", "local_reputation_delta")
            )
            or payload["maintenance_count"] > payload["required_maintenance"]
        ):
            raise ValueError("invalid field plot result")
        player_payload = payload["player"]
        player = self._row_to_player(player_payload)
        return FieldPlotRecord(
            player=player,
            plot_id=str(payload["plot_id"]),
            residence_id=str(payload["residence_id"]),
            crop_key=str(payload["crop_key"]),
            status=str(payload["status"]),
            planted_at=str(payload["planted_at"]),
            harvest_at=str(payload["harvest_at"]),
            crop_label=str(payload["crop_label"]),
            harvest_labels=dict(labels),
            maintenance_count=int(payload["maintenance_count"]),
            required_maintenance=int(payload["required_maintenance"]),
            harvest={str(key): int(value) for key, value in dict(payload["harvest"]).items()},
            local_reputation_delta=int(payload["local_reputation_delta"]),
            already_completed=replay,
        )


__all__ = ["FieldPlotRepositoryMixin"]
