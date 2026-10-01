"""SQLite transactions for progression-wide resource recovery."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from datetime import datetime, timedelta

from ...contracts import serialize_datetime
from .models import ResourceRecoveryRecord
from ..utils.player import change_player_state, player_numeric_values


class ProgressionRepositoryMixin:
    """Persistence operations shared by cultivation/progression commands."""

    async def recover_resources(
        self,
        *,
        platform: str,
        platform_user_id: str,
        operation_id: str,
    ) -> ResourceRecoveryRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._recover_resources_sync, platform, platform_user_id, operation_id)

    def _recover_resources_sync(self, platform: str, platform_user_id: str, operation_id: str) -> ResourceRecoveryRecord:
        from ..repository import RepositoryBusyError

        last_error: Exception | None = None
        for attempt in range(5):
            try:
                return self._recover_resources_once(platform, platform_user_id, operation_id)
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc).lower():
                    raise
                if attempt == 4:
                    raise RepositoryBusyError("database remained locked") from exc
                last_error = exc
                time.sleep(0.01 * (2**attempt))
        raise RepositoryBusyError("database remained locked") from last_error

    def _recover_resources_once(self, platform: str, platform_user_id: str, operation_id: str) -> ResourceRecoveryRecord:
        from .rules import RECOVERY_PERIOD_SECONDS
        from ..repository import OperationConflictError

        operation_payload = {"platform": platform, "platform_user_id": platform_user_id}
        request_hash = self._request_hash("player.recover_resources", operation_payload)
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing_operation = connection.execute(
                "SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            if existing_operation is not None:
                if (
                    existing_operation["operation_name"] != "player.recover_resources"
                    or existing_operation["request_hash"] != request_hash
                ):
                    raise OperationConflictError("operation input differs from its original request")
                payload = json.loads(existing_operation["result_json"])
                return ResourceRecoveryRecord(
                    player=self._row_to_player(payload["player"]),
                    periods=int(payload["periods"]),
                    recovered_stamina=int(payload["recovered_stamina"]),
                    recovered_energy=int(payload["recovered_energy"]),
                    changed=bool(payload["changed"]),
                    recovered_void_power=int(payload.get("recovered_void_power", 0)),
                    already_completed=True,
                )
            row = self._require_player(connection, platform, platform_user_id)
            try:
                last_update = datetime.fromisoformat(str(row["updated_at"]))
            except ValueError:
                last_update = now
            elapsed = max(0, int((now - last_update).total_seconds()))
            periods = elapsed // RECOVERY_PERIOD_SECONDS
            resources = player_numeric_values(
                row,
                ("stamina", "stamina_max", "energy", "energy_max", "void_power", "void_power_max"),
            )
            stamina_before = resources["stamina"]
            energy_before = resources["energy"]
            stamina_after = min(resources["stamina_max"], stamina_before + periods)
            energy_after = min(resources["energy_max"], energy_before + periods)
            recovered_stamina = stamina_after - stamina_before
            recovered_energy = energy_after - energy_before
            void_before = resources["void_power"]
            void_after = void_before
            recovered_void_power = 0
            if resources["void_power_max"] > 0 and str(row["void_power_reset_date"] or "") != now.date().isoformat():
                void_after = resources["void_power_max"]
                recovered_void_power = max(0, void_after - void_before)
            changed = recovered_stamina > 0 or recovered_energy > 0 or recovered_void_power > 0
            if periods > 0:
                advanced_update = last_update + timedelta(seconds=periods * RECOVERY_PERIOD_SECONDS)
                change_player_state(
                    connection,
                    row,
                    updated_at=serialize_datetime(advanced_update),
                    value_delta={
                        "stamina": recovered_stamina,
                        "energy": recovered_energy,
                    },
                    maximums={"stamina": resources["stamina_max"], "energy": resources["energy_max"]},
                    player_values={
                        "void_power": void_after,
                        "void_power_reset_date": now.date().isoformat(),
                    },
                )
            elif recovered_void_power > 0:
                change_player_state(
                    connection,
                    row,
                    updated_at=now_text,
                    player_values={
                        "void_power": void_after,
                        "void_power_reset_date": now.date().isoformat(),
                    },
                )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (row["id"],)).fetchone()
            if updated is None:
                raise RuntimeError("resource recovery returned no player")
            player = self._row_to_player(updated)
            payload = {
                "player": self._player_payload(player),
                "periods": periods,
                "recovered_stamina": recovered_stamina,
                "recovered_energy": recovered_energy,
                "changed": changed,
                "recovered_void_power": recovered_void_power,
            }
            connection.execute(
                "INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    operation_id,
                    "player.recover_resources",
                    row["id"],
                    request_hash,
                    json.dumps(payload, ensure_ascii=False, sort_keys=True),
                    now_text,
                ),
            )
            return ResourceRecoveryRecord(
                player=player,
                periods=periods,
                recovered_stamina=recovered_stamina,
                recovered_energy=recovered_energy,
                changed=changed,
                recovered_void_power=recovered_void_power,
            )


__all__ = ["ProgressionRepositoryMixin"]
