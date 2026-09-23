"""SQLite transactions for personal, non-commissionable endgame recipes."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from uuid import uuid4

from ...contracts import serialize_datetime
from ..persistence.errors import (
    EndgameRecipeAlreadyCreatedError,
    EndgameRecipeBusyError,
    EndgameRecipeNotFoundError,
    EndgameRecipeNotReadyError,
    EndgameRecipeRequirementError,
    MaterialInsufficientError,
    OperationConflictError,
    QuestResourceInsufficientError,
)
from .endgame_models import EndgameRecipeRecord
from .endgame_rules import (
    CONTENT_VERSION,
    DAO_FRUIT_PROGRESS_CAP,
    ENDGAME_RECIPES,
    RULE_VERSION,
    SUCCESS_THRESHOLD_BP,
    endgame_recipe,
    recipe_roll_bp,
)


class EndgameProductionRepositoryMixin:
    """Keep terminal recipes outside ordinary personal and commission flows."""

    async def start_endgame_recipe(
        self, *, platform: str, platform_user_id: str, recipe_key: str, operation_id: str
    ) -> EndgameRecipeRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._start_endgame_recipe_sync, platform, platform_user_id, recipe_key, operation_id
            )

    async def settle_endgame_recipe(
        self, *, platform: str, platform_user_id: str, operation_id: str
    ) -> EndgameRecipeRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._settle_endgame_recipe_sync, platform, platform_user_id, operation_id
            )

    def _start_endgame_recipe_sync(
        self, platform: str, platform_user_id: str, recipe_key: str, operation_id: str
    ) -> EndgameRecipeRecord:
        if recipe_key not in ENDGAME_RECIPES:
            raise EndgameRecipeRequirementError("unknown endgame recipe")
        recipe = endgame_recipe(recipe_key)
        operation_name = "endgame.production.start"
        request_hash = self._request_hash(
            operation_name,
            {"platform": platform, "platform_user_id": platform_user_id, "recipe_key": recipe_key},
        )
        now = self._now()
        now_text = serialize_datetime(now)
        ends_at = serialize_datetime(now + timedelta(seconds=recipe.duration_seconds))
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            if existing is not None:
                if existing["operation_name"] != operation_name or existing["request_hash"] != request_hash:
                    raise OperationConflictError("operation input differs from its original request")
                return self._endgame_recipe_from_payload(json.loads(existing["result_json"]), replay=True)

            player = self._require_player(connection, platform, platform_user_id)
            active = connection.execute(
                "SELECT 1 FROM endgame_sessions WHERE player_id = ? AND status = 'preparing' LIMIT 1",
                (player["id"],),
            ).fetchone()
            if active is not None:
                raise EndgameRecipeBusyError("another endgame recipe is processing")
            realm_rank = {"mortal": 0, "qi_sensing": 1, "qi_gathering": 2, "foundation": 3, "golden_core": 4, "nascent_soul": 5, "soul_transformation": 6, "void_refining": 7, "dao_union": 8, "tribulation": 9}
            if realm_rank.get(str(player["realm_key"]), -1) < realm_rank[recipe.required_realm]:
                raise EndgameRecipeRequirementError("endgame recipe realm gate is not met")
            if recipe.key == "recipe.dao.fruit_fragment":
                if int(player["dao_fruit_progress"]) + recipe.output_progress > DAO_FRUIT_PROGRESS_CAP:
                    raise EndgameRecipeRequirementError("dao fruit progress cap would be exceeded")
                used = connection.execute(
                    "SELECT COUNT(*) AS count FROM endgame_sessions WHERE player_id = ? AND session_type = ?",
                    (player["id"], recipe.key),
                ).fetchone()
                if int(used["count"]) >= 3:
                    raise EndgameRecipeAlreadyCreatedError("fruit fragment recipe chain cap reached")
            elif recipe.key == "recipe.tribulation.guard":
                if not str(player["domain_key"] or ""):
                    raise EndgameRecipeRequirementError("a selected domain is required")
                used = connection.execute(
                    "SELECT COUNT(*) AS count FROM endgame_sessions WHERE player_id = ? AND session_type = ?",
                    (player["id"], recipe.key),
                ).fetchone()
                if int(used["count"]) >= 1:
                    raise EndgameRecipeAlreadyCreatedError("tribulation guard already prepared")
            else:
                trials = connection.execute(
                    "SELECT trial_key, status FROM tribulation_trial_sessions WHERE player_id = ?",
                    (player["id"],),
                ).fetchall()
                if {str(row["trial_key"]) for row in trials if str(row["status"]) == "succeeded"} != {
                    "trial.body_and_mind", "trial.three_realms", "trial.dao_choice"
                }:
                    raise EndgameRecipeRequirementError("all three trials must succeed")
                if int(player["dao_fruit_progress"]) < recipe.required_progress:
                    raise EndgameRecipeRequirementError("dao fruit progress is insufficient")
                if int(player["ascension_merit"]) < recipe.required_ascension_merit:
                    raise EndgameRecipeRequirementError("ascension merit is insufficient")
                if int(player["world_merit"]) < recipe.world_merit_cost:
                    raise QuestResourceInsufficientError("world merit is insufficient")
                issued = connection.execute(
                    "SELECT 1 FROM endgame_sessions WHERE player_id = ? AND session_type = ? AND status = 'succeeded' LIMIT 1",
                    (player["id"], recipe.key),
                ).fetchone()
                if issued is not None:
                    raise EndgameRecipeAlreadyCreatedError("ascension certificate was already created")

            inventory = self._json_object(player["inventory_json"], {})
            for item_key, quantity in recipe.inputs.items():
                if int(inventory.get(item_key, 0)) < quantity:
                    raise MaterialInsufficientError(f"missing {item_key}")
            for item_key, quantity in recipe.inputs.items():
                inventory[item_key] = int(inventory[item_key]) - quantity
                if inventory[item_key] == 0:
                    inventory.pop(item_key)
            session_id = uuid4().hex
            roll_bp = recipe_roll_bp(operation_id)
            snapshot = {
                "recipe_key": recipe.key,
                "inputs": recipe.inputs,
                "output_item": recipe.output_item,
                "output_progress": recipe.output_progress,
                "world_merit_cost": recipe.world_merit_cost,
                "progress_before": int(player["dao_fruit_progress"]),
                "roll_bp": roll_bp,
                "content_version": CONTENT_VERSION,
                "rule_version": RULE_VERSION,
            }
            connection.execute(
                "UPDATE players SET inventory_json = ?, world_merit = world_merit - ?, updated_at = ? WHERE id = ?",
                (json.dumps(inventory, ensure_ascii=False, sort_keys=True), recipe.world_merit_cost, now_text, player["id"]),
            )
            connection.execute(
                "INSERT INTO endgame_sessions(session_id, player_id, operation_id, session_type, status, starts_at, ends_at, snapshot_json, result_json, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, 'preparing', ?, ?, ?, '{}', ?, ?)",
                (session_id, player["id"], operation_id, recipe.key, now_text, ends_at, json.dumps(snapshot, ensure_ascii=False, sort_keys=True), now_text, now_text),
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (player["id"],)).fetchone()
            payload = {
                "player": self._player_payload(self._row_to_player(updated)),
                "session_id": session_id,
                "recipe_key": recipe.key,
                "status": "preparing",
                "starts_at": now_text,
                "ends_at": ends_at,
            }
            self._insert_operation(
                connection,
                operation_id=operation_id,
                operation_name=operation_name,
                player_id=int(player["id"]),
                request_hash=request_hash,
                payload=payload,
                now_text=now_text,
            )
            return self._endgame_recipe_from_payload(payload)

    def _settle_endgame_recipe_sync(
        self, platform: str, platform_user_id: str, operation_id: str
    ) -> EndgameRecipeRecord:
        operation_name = "endgame.production.settle"
        request_hash = self._request_hash(
            operation_name, {"platform": platform, "platform_user_id": platform_user_id}
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
                return self._endgame_recipe_from_payload(json.loads(existing["result_json"]), replay=True)
            player = self._require_player(connection, platform, platform_user_id)
            session = connection.execute(
                "SELECT * FROM endgame_sessions WHERE player_id = ? AND status = 'preparing' ORDER BY id DESC LIMIT 1",
                (player["id"],),
            ).fetchone()
            if session is None:
                raise EndgameRecipeNotFoundError("no endgame recipe is preparing")
            if now < datetime.fromisoformat(str(session["ends_at"])):
                raise EndgameRecipeNotReadyError("endgame recipe has not completed")

            recipe = endgame_recipe(str(session["session_type"]))
            snapshot = self._json_object(session["snapshot_json"], {})
            roll_bp = int(snapshot["roll_bp"])
            success = roll_bp < SUCCESS_THRESHOLD_BP
            inventory = self._json_object(player["inventory_json"], {})
            rewards: dict[str, int] = {}
            refunds: dict[str, int] = {}
            progress_reward = 0
            world_merit_refund = 0
            if success:
                if recipe.output_item:
                    inventory[recipe.output_item] = int(inventory.get(recipe.output_item, 0)) + 1
                    rewards[recipe.output_item] = 1
                if recipe.output_progress:
                    progress_reward = min(recipe.output_progress, DAO_FRUIT_PROGRESS_CAP - int(player["dao_fruit_progress"]))
                    rewards["dao_fruit_progress"] = progress_reward
                status = "succeeded"
            else:
                status = "failed"
                if recipe.key == "recipe.dao.fruit_fragment":
                    inventory["item.dao_fruit_fragment"] = int(inventory.get("item.dao_fruit_fragment", 0)) + 5
                    refunds["item.dao_fruit_fragment"] = 5
                elif recipe.key == "recipe.ascension.certificate":
                    world_merit_refund = recipe.world_merit_cost
                    refunds["world_merit"] = world_merit_refund

            connection.execute(
                "UPDATE players SET inventory_json = ?, dao_fruit_progress = dao_fruit_progress + ?, world_merit = world_merit + ?, updated_at = ? WHERE id = ?",
                (json.dumps(inventory, ensure_ascii=False, sort_keys=True), progress_reward, world_merit_refund, now_text, player["id"]),
            )
            result = {
                "success": success,
                "roll_bp": roll_bp,
                "rewards": rewards,
                "refunds": refunds,
                "settled_at": now_text,
            }
            connection.execute(
                "UPDATE endgame_sessions SET status = ?, result_json = ?, updated_at = ? WHERE id = ?",
                (status, json.dumps(result, ensure_ascii=False, sort_keys=True), now_text, session["id"]),
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (player["id"],)).fetchone()
            payload = {
                "player": self._player_payload(self._row_to_player(updated)),
                "session_id": str(session["session_id"]),
                "recipe_key": recipe.key,
                "status": status,
                "starts_at": str(session["starts_at"]),
                "ends_at": str(session["ends_at"]),
                **result,
            }
            self._insert_operation(
                connection,
                operation_id=operation_id,
                operation_name=operation_name,
                player_id=int(player["id"]),
                request_hash=request_hash,
                payload=payload,
                now_text=now_text,
            )
            return self._endgame_recipe_from_payload(payload)

    @staticmethod
    def _endgame_recipe_from_payload(payload: dict, *, replay: bool = False) -> EndgameRecipeRecord:
        from ..repository import SQLitePlayerRepository

        return EndgameRecipeRecord(
            player=SQLitePlayerRepository._row_to_player(payload["player"]),
            session_id=str(payload["session_id"]),
            recipe_key=str(payload["recipe_key"]),
            status=str(payload["status"]),
            starts_at=str(payload["starts_at"]),
            ends_at=str(payload["ends_at"]),
            success=bool(payload["success"]) if "success" in payload else None,
            roll_bp=int(payload["roll_bp"]) if payload.get("roll_bp") is not None else None,
            rewards={str(key): int(value) for key, value in dict(payload.get("rewards", {})).items()},
            refunds={str(key): int(value) for key, value in dict(payload.get("refunds", {})).items()},
            already_completed=replay,
        )


__all__ = ["EndgameProductionRepositoryMixin"]
