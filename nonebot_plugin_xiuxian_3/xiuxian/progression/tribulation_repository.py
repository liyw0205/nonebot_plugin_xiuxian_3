"""Atomic trial sessions linked to the shared automatic battle journal."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from uuid import uuid4

from ...contracts import serialize_datetime
from ..utils.assets import inventory_amount, spend_player_items
from ..utils.player import grant_player_state, player_integer, player_inventory, player_object
from ..advancement.constitution_effects import constitution_effect_snapshot
from ..combat.rules import apply_constitution_combat_effect, MAX_TURNS, TURN_TIMEOUT_SECONDS
from ..combat.tribulation_rules import (
    ENEMY_AGILITY,
    ENEMY_ATTACK,
    ENEMY_INITIATIVE,
    ENEMY_KEY,
    ENEMY_MAX_HP,
    PHASES,
    PROFILE_KEY,
    debt_shield_bp,
    stat_snapshot as tribulation_stat_snapshot,
)
from .endgame_models import TrialSessionRecord, TrialSettlementRecord
from .endgame_rules import (
    fruit_for_path,
    trial_definition_from_snapshot,
    trial_definition,
    trial_roll_bp,
    tribulation_definition,
)


class TribulationTrialRepositoryMixin:
    async def start_tribulation_trial(
        self,
        *,
        platform: str,
        platform_user_id: str,
        trial_key: str,
        choice_key: str | None,
        operation_id: str,
    ) -> TrialSessionRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._retry_sync,
                self._start_tribulation_trial_once,
                platform,
                platform_user_id,
                trial_key,
                choice_key,
                operation_id,
            )

    def _start_tribulation_trial_once(
        self, platform: str, platform_user_id: str, trial_key: str, choice_key: str | None, operation_id: str
    ) -> TrialSessionRecord:
        from ..repository import (
            DaoFruitChoiceError,
            LocationRequirementError,
            OperationConflictError,
            PlayerSuspendedError,
            TribulationCooldownError,
            TribulationDebtBlockedError,
            TribulationTokenInsufficientError,
            TribulationTrialBusyError,
            TrialSequenceError,
        )

        event_definition = tribulation_definition(self.content)
        if trial_key not in event_definition.trial_order:
            raise TrialSequenceError("unknown tribulation trial")
        definition = trial_definition(trial_key, self.content)
        operation_name = "tribulation.start_trial"
        request_hash = self._request_hash(
            operation_name,
            {
                "platform": platform,
                "platform_user_id": platform_user_id,
                "trial_key": trial_key,
                "choice_key": choice_key,
            },
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
                return self._trial_session_from_payload(json.loads(existing["result_json"]), replay=True)

            row = self._require_player(connection, platform, platform_user_id)
            if str(row["status"]) != "active":
                raise PlayerSuspendedError("player is not active")
            if self._has_active_long_action(connection, int(row["id"])):
                raise TribulationTrialBusyError("another long action is active")
            if (
                str(row["realm_key"]) != event_definition.required_realm_key
                or player_integer(row, "realm_layer") < max(event_definition.required_layer, definition.required_layer)
            ):
                raise TrialSequenceError("tribulation layer is insufficient")
            if int(row["tribulation_debt"]) >= 100:
                raise TribulationDebtBlockedError("tribulation debt is too high")
            if connection.execute(
                "SELECT 1 FROM tribulation_trial_sessions WHERE player_id=? AND status='preparing' LIMIT 1",
                (row["id"],),
            ).fetchone() is not None:
                raise TribulationTrialBusyError("tribulation trial is already preparing")
            if connection.execute(
                "SELECT 1 FROM endgame_sessions WHERE player_id=? AND status='preparing' LIMIT 1", (row["id"],)
            ).fetchone() is not None:
                raise TribulationTrialBusyError("an endgame recipe is already preparing")
            if connection.execute(
                "SELECT 1 FROM final_battle_members WHERE player_id=? AND asset_lock_status='locked' LIMIT 1", (row["id"],)
            ).fetchone() is not None:
                raise TribulationTrialBusyError("final battle assets are locked")
            if connection.execute(
                "SELECT 1 FROM travel_sessions WHERE player_id=? AND status='running' LIMIT 1", (row["id"],)
            ).fetchone() is not None:
                raise TribulationTrialBusyError("travel is already running")
            if connection.execute(
                "SELECT 1 FROM battle_sessions WHERE player_id=? AND status IN ('created','running') LIMIT 1",
                (row["id"],),
            ).fetchone() is not None:
                raise TribulationTrialBusyError("another battle is already active")
            if str(row["location_key"]) != "tribulation.sky_terrace":
                raise LocationRequirementError("tribulation trial requires the sky terrace")

            previous = connection.execute(
                "SELECT trial_key, status, result_json FROM tribulation_trial_sessions WHERE player_id=? ORDER BY id",
                (row["id"],),
            ).fetchall()
            successful = {str(item["trial_key"]) for item in previous if str(item["status"]) == "succeeded"}
            index = event_definition.trial_order.index(trial_key)
            if trial_key in successful or any(required not in successful for required in event_definition.trial_order[:index]):
                raise TrialSequenceError("tribulation trials must be completed in order")
            last_failed = next(
                (item for item in reversed(previous) if str(item["trial_key"]) == trial_key and str(item["status"]) == "failed"),
                None,
            )
            if last_failed is not None:
                cooldown_until = self._json_object(last_failed["result_json"], {}).get("cooldown_until")
                if cooldown_until:
                    try:
                        if now < datetime.fromisoformat(str(cooldown_until)):
                            raise TribulationCooldownError("tribulation trial cooldown is active")
                    except ValueError:
                        pass

            if definition.choice_minimum_progress is not None:
                if int(row["dao_fruit_progress"]) < definition.choice_minimum_progress:
                    raise TrialSequenceError("dao fruit progress is insufficient")
                expected_fruit = fruit_for_path(row["path_key"], self.content)
                if not choice_key or (definition.choice_match_path_fruit and choice_key != expected_fruit):
                    raise DaoFruitChoiceError("dao fruit does not match the primary path")
                if row["dao_fruit_key"] and definition.choice_match_path_fruit:
                    raise DaoFruitChoiceError("dao fruit is already locked")
            inventory = player_inventory(row)
            guard_used = inventory_amount(inventory, "item.tribulation_guard") > 0
            costs = {"item.tribulation_token": definition.token_cost}
            if guard_used:
                costs["item.tribulation_guard"] = 1
            try:
                spend_player_items(connection, row, costs, now_text)
            except ValueError as exc:
                raise TribulationTokenInsufficientError("tribulation token is insufficient") from exc

            equipment = self._battle_equipment_snapshot(connection, int(row["id"]))
            qualification = player_object(row, "qualification_json")
            constitution_effect = constitution_effect_snapshot(connection, int(row["id"]))
            stats = apply_constitution_combat_effect(
                tribulation_stat_snapshot(
                    qualification,
                    realm_layer=player_integer(row, "realm_layer"),
                    equipment=equipment,
                ),
                constitution_effect,
            )
            # Keep the published random pool in the immutable battle snapshot. It
            # changes the encounter's pressure, while the persisted battle result
            # remains the only source used by settlement.
            fate_bp = trial_roll_bp(operation_id)
            if fate_bp >= 7_000:
                stats["max_hp"] = max(40_000, stats["max_hp"] // 2)
                stats["attack"] = max(5_000, stats["attack"] * 3 // 5)
            session_id = uuid4().hex
            battle_id = uuid4().hex
            shield_bp = debt_shield_bp(int(row["tribulation_debt"]))
            snapshot = {
                "profile_key": PROFILE_KEY,
                "battle_type": "pve.tribulation_trial",
                "location_key": str(row["location_key"]),
                "player": {
                    "player_id": str(row["player_id"]),
                    "path_key": row["path_key"],
                    "qualification": qualification,
                    "stats": stats,
                    "equipment": list(equipment),
                    "constitution_effect": constitution_effect,
                    "realm_key": str(row["realm_key"]),
                    "realm_layer": player_integer(row, "realm_layer"),
                    "dao_fruit_key": row["dao_fruit_key"],
                    "dao_fruit_progress": int(row["dao_fruit_progress"]),
                    "domain_key": row["domain_key"],
                    "domain_power": int(row["domain_power"]),
                    "domain_charge": int(row["domain_charge"]),
                    "realm_resistance_bp": int(row["realm_resistance_bp"]),
                },
                "enemy": {
                    "key": ENEMY_KEY,
                    "label": "三劫天尊",
                    "max_hp": ENEMY_MAX_HP,
                    "attack": ENEMY_ATTACK,
                    "initiative": ENEMY_INITIATIVE,
                    "agility": ENEMY_AGILITY,
                    "skill_key": PHASES[0].skill_key,
                    "phases": [
                        {
                            "key": phase.key,
                            "min_hp_bp": phase.min_hp_bp,
                            "attack": phase.attack,
                            "skill_key": phase.skill_key,
                            "enemy_hit_bonus_bp": phase.enemy_hit_bonus_bp,
                            "player_damage_bp": phase.player_damage_bp,
                        }
                        for phase in PHASES
                    ],
                },
                "trial": definition.snapshot(),
                "tribulation": {
                    "trial_key": trial_key,
                    "choice_key": choice_key,
                    "debt_before": int(row["tribulation_debt"]),
                    "difficulty_bp": shield_bp,
                    "debt_shield_bp": shield_bp,
                    "guard_used": guard_used,
                    "fate_roll_bp": fate_bp,
                    "fate_rule": "battle_pressure",
                },
                "random_pool": definition.random_pool,
                "random_seed": operation_id,
                "reward": {},
            }
            state = {
                "round_no": 0,
                "player_hp": stats["max_hp"],
                "enemy_hp": ENEMY_MAX_HP,
                "timeout_count": 0,
                "tribulation_phase": PHASES[0].key,
                "debt_shield_bp": shield_bp,
            }
            ends_at = serialize_datetime(now + timedelta(seconds=definition.duration_seconds))
            connection.execute(
                "INSERT INTO tribulation_trial_sessions(session_id, player_id, operation_id, trial_key, choice_key, status, starts_at, ends_at, snapshot_json, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, 'preparing', ?, ?, ?, ?, ?)",
                (
                    session_id,
                    row["id"],
                    operation_id,
                    trial_key,
                    choice_key,
                    now_text,
                    ends_at,
                    json.dumps({**snapshot, "battle_id": battle_id}, ensure_ascii=False, sort_keys=True),
                    now_text,
                    now_text,
                ),
            )
            connection.execute(
                "INSERT INTO battle_sessions(battle_id, player_id, start_operation_id, battle_type, enemy_key, location_key, status, reward_status, round_no, action_sequence, starts_at, turn_deadline, snapshot_json, state_json, result_json, created_at, updated_at) "
                "VALUES (?, ?, ?, 'pve.tribulation_trial', ?, ?, 'created', 'none', 0, 0, ?, ?, ?, ?, '{}', ?, ?)",
                (
                    battle_id,
                    row["id"],
                    operation_id,
                    ENEMY_KEY,
                    row["location_key"],
                    now_text,
                    serialize_datetime(now + timedelta(seconds=TURN_TIMEOUT_SECONDS)),
                    json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
                    json.dumps(state, ensure_ascii=False, sort_keys=True),
                    now_text,
                    now_text,
                ),
            )
            updated = connection.execute("SELECT * FROM players WHERE id=?", (row["id"],)).fetchone()
            player = self._row_to_player(updated)
            payload = {
                "player": self._player_payload(player),
                "session_id": session_id,
                "battle_id": battle_id,
                "trial_key": trial_key,
                "trial_name": definition.name,
                "choice_key": choice_key,
                "status": "preparing",
                "starts_at": now_text,
                "ends_at": ends_at,
                "debt_before": int(row["tribulation_debt"]),
            }
            connection.execute(
                "INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (operation_id, operation_name, row["id"], request_hash, json.dumps(payload, ensure_ascii=False, sort_keys=True), now_text),
            )
            return self._trial_session_from_payload(payload, replay=False)

    async def active_tribulation_trial_battle(self, *, platform: str, platform_user_id: str) -> str | None:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._active_tribulation_trial_battle_once, platform, platform_user_id)

    def _active_tribulation_trial_battle_once(self, platform: str, platform_user_id: str) -> str | None:
        with self._connect() as connection:
            row = self._require_player(connection, platform, platform_user_id, writable=False)
            session = connection.execute(
                "SELECT snapshot_json FROM tribulation_trial_sessions WHERE player_id=? AND status='preparing' ORDER BY id DESC LIMIT 1",
                (row["id"],),
            ).fetchone()
            if session is None:
                return None
            battle_id = self._json_object(session["snapshot_json"], {}).get("battle_id")
            return str(battle_id) if battle_id else None

    async def settle_tribulation_trial(
        self, *, platform: str, platform_user_id: str, operation_id: str
    ) -> TrialSettlementRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._retry_sync,
                self._settle_tribulation_trial_once,
                platform,
                platform_user_id,
                operation_id,
            )

    def _settle_tribulation_trial_once(
        self, platform: str, platform_user_id: str, operation_id: str
    ) -> TrialSettlementRecord:
        from ..repository import OperationConflictError, TribulationTrialNotFoundError, TribulationTrialNotReadyError

        operation_name = "tribulation.settle_trial"
        request_hash = self._request_hash(operation_name, {"platform": platform, "platform_user_id": platform_user_id})
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id=?", (operation_id,)
            ).fetchone()
            if existing is not None:
                if existing["operation_name"] != operation_name or existing["request_hash"] != request_hash:
                    raise OperationConflictError("operation input differs from its original request")
                return self._trial_settlement_from_payload(json.loads(existing["result_json"]), replay=True)

            row = self._require_player(connection, platform, platform_user_id)
            session = connection.execute(
                "SELECT * FROM tribulation_trial_sessions WHERE player_id=? AND status='preparing' ORDER BY id DESC LIMIT 1",
                (row["id"],),
            ).fetchone()
            if session is None:
                raise TribulationTrialNotFoundError("no preparing tribulation trial")
            if now < datetime.fromisoformat(str(session["ends_at"])):
                raise TribulationTrialNotReadyError("tribulation trial is not ready")
            snapshot = self._json_object(session["snapshot_json"], {})
            battle_id = snapshot["battle_id"]
            roll_bp: int | None = None
            battle_outcome: str | None = None
            battle = connection.execute(
                "SELECT status, result_json FROM battle_sessions WHERE battle_id=? AND player_id=?",
                (battle_id, row["id"]),
            ).fetchone()
            if battle is None:
                raise TribulationTrialNotFoundError("linked tribulation battle does not exist")
            if str(battle["status"]) != "settled":
                raise TribulationTrialNotReadyError("linked tribulation battle is not settled")
            battle_result = self._json_object(battle["result_json"], {})
            battle_outcome = str(battle_result.get("outcome", ""))
            if battle_outcome not in {"won", "lost", "expired"}:
                raise TribulationTrialNotReadyError("linked tribulation battle has no final outcome")
            success = battle_outcome == "won"

            trial_definition_snapshot = snapshot["trial"]
            definition = trial_definition_from_snapshot(trial_definition_snapshot, self.content)
            trial_key = definition.key
            tribulation_snapshot = snapshot["tribulation"]
            guard_used = bool(tribulation_snapshot["guard_used"])
            debt_delta = 0 if success else max(0, definition.debt_delta - (5 if guard_used else 0))
            progress = definition.progress_reward if success else 0
            merit = definition.merit_reward if success else 0
            world_merit = definition.world_merit_reward if success else 0
            reward_items = dict(definition.reward_items) if success else {}
            guard_refund = bool(
                success
                and guard_used
            )
            fruit_key = (
                str(tribulation_snapshot["choice_key"])
                if success and definition.choice_match_path_fruit
                else None
            )
            new_progress = min(1300, int(row["dao_fruit_progress"]) + progress)
            new_debt = int(row["tribulation_debt"]) + debt_delta
            cooldown_until = serialize_datetime(now + timedelta(seconds=definition.cooldown_seconds)) if not success else None
            reward_assets = dict(reward_items)
            if guard_refund:
                reward_assets["item.tribulation_guard"] = 1
            grant_player_state(
                connection,
                row,
                rewards=reward_assets,
                updated_at=now_text,
                value_delta={
                    "dao_fruit_progress": progress,
                    "ascension_merit": merit,
                    "world_merit": world_merit,
                    "tribulation_debt": debt_delta,
                },
                maximums={"dao_fruit_progress": 1300},
                player_values={"dao_fruit_key": fruit_key} if fruit_key else None,
            )
            result = {
                "success": success,
                "battle_id": battle_id,
                "battle_outcome": battle_outcome,
                "debt_delta": debt_delta,
                "reward_progress": progress,
                "reward_merit": merit,
                "reward_world_merit": world_merit,
                "reward_items": reward_items,
                "dao_fruit_key": fruit_key,
                "cooldown_until": cooldown_until,
                "status": "succeeded" if success else "failed",
                "trial_name": definition.name,
            }
            if roll_bp is not None:
                result["roll_bp"] = roll_bp
            connection.execute(
                "UPDATE tribulation_trial_sessions SET status=?, result_json=?, updated_at=? WHERE id=?",
                (result["status"], json.dumps(result, ensure_ascii=False, sort_keys=True), now_text, session["id"]),
            )
            updated = connection.execute("SELECT * FROM players WHERE id=?", (row["id"],)).fetchone()
            payload = {"player": self._player_payload(self._row_to_player(updated)), "session_id": session["session_id"], "trial_key": trial_key, **result}
            connection.execute(
                "INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (operation_id, operation_name, row["id"], request_hash, json.dumps(payload, ensure_ascii=False, sort_keys=True), now_text),
            )
            return self._trial_settlement_from_payload(payload, replay=False)

    @staticmethod
    def _trial_session_from_payload(payload: dict, *, replay: bool) -> TrialSessionRecord:
        from ..repository import SQLitePlayerRepository

        return TrialSessionRecord(
            player=SQLitePlayerRepository._row_to_player(payload["player"]),
            session_id=str(payload["session_id"]),
            battle_id=str(payload.get("battle_id", "")),
            trial_key=str(payload["trial_key"]),
            trial_name=str(payload["trial_name"]),
            choice_key=payload.get("choice_key"),
            status=str(payload["status"]),
            starts_at=str(payload["starts_at"]),
            ends_at=str(payload["ends_at"]),
            debt_before=int(payload.get("debt_before", 0)),
            already_completed=replay,
        )

    @staticmethod
    def _trial_settlement_from_payload(payload: dict, *, replay: bool) -> TrialSettlementRecord:
        from ..repository import SQLitePlayerRepository

        return TrialSettlementRecord(
            player=SQLitePlayerRepository._row_to_player(payload["player"]),
            session_id=str(payload["session_id"]),
            trial_key=str(payload["trial_key"]),
            trial_name=str(payload["trial_name"]),
            status=str(payload.get("status", "failed")),
            success=bool(payload.get("success", False)),
            roll_bp=int(payload["roll_bp"]) if payload.get("roll_bp") is not None else None,
            battle_id=str(payload["battle_id"]) if payload.get("battle_id") else None,
            battle_outcome=str(payload["battle_outcome"]) if payload.get("battle_outcome") else None,
            debt_delta=int(payload.get("debt_delta", 0)),
            reward_progress=int(payload.get("reward_progress", 0)),
            reward_merit=int(payload.get("reward_merit", 0)),
            reward_world_merit=int(payload.get("reward_world_merit", 0)),
            reward_items={str(key): int(value) for key, value in dict(payload.get("reward_items", {})).items()},
            dao_fruit_key=payload.get("dao_fruit_key"),
            already_completed=replay,
        )


__all__ = ["TribulationTrialRepositoryMixin"]
