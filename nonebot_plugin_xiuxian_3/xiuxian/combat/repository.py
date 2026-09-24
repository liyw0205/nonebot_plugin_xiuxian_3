"""SQLite transactions for server-authoritative automatic battle sessions."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from ...contracts import serialize_datetime
from ..persistence.errors import (
    BattleAlreadySettledError,
    BattleBusyError,
    BattleCooldownError,
    BattleNotFoundError,
    BattleNotReadyError,
    BattleRequirementError,
    BattleRewardAlreadyClaimedError,
    BattleRewardNotAvailableError,
    OperationConflictError,
    PlayerNotFoundError,
    RepositoryBusyError,
)
from .models import (
    BattleReplayRecord,
    BattleResolutionRecord,
    BattleRewardClaimRecord,
    BattleStartRecord,
    BattleTurnRecord,
)
from .rules import (
    CONTENT_VERSION,
    DEFEAT_COOLDOWN_SECONDS,
    MAX_TURNS,
    RULE_VERSION,
    TURN_TIMEOUT_SECONDS,
    battle_roll_bp,
    enemy_definition,
    hit_chance_bp,
    player_goes_first,
    player_stat_snapshot,
)
from .tribulation_rules import PROFILE_KEY, phase_for_hp


class CombatRepositoryMixin:
    """Persist every automatic combat transition as an independently replayable write."""

    async def start_training_battle(
        self, *, platform: str, platform_user_id: str, operation_id: str
    ) -> BattleStartRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._retry_sync,
                self._start_training_battle_once,
                platform,
                platform_user_id,
                operation_id,
                "enemy.training_dummy",
                "pve.training",
            )

    async def start_quest_battle(
        self,
        *,
        platform: str,
        platform_user_id: str,
        enemy_key: str,
        battle_type: str,
        operation_id: str,
    ) -> BattleStartRecord:
        """Create a named quest encounter using the same replayable battle core."""

        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._retry_sync,
                self._start_training_battle_once,
                platform,
                platform_user_id,
                operation_id,
                enemy_key,
                battle_type,
            )

    async def start_exploration_battle(
        self,
        *,
        platform: str,
        platform_user_id: str,
        exploration_id: str,
        mode_key: str,
        operation_id: str,
    ) -> BattleStartRecord:
        """Create the encounter linked to an already frozen exploration result."""

        from ..exploration.rules import exploration_enemy_key

        enemy_key = exploration_enemy_key(mode_key)
        if enemy_key is None:
            raise BattleRequirementError("exploration mode has no battle encounter")
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._retry_sync,
                self._start_training_battle_once,
                platform,
                platform_user_id,
                operation_id,
                enemy_key,
                "pve.exploration",
                exploration_id,
            )

    async def run_battle_turn(self, *, battle_id: str, expected_round: int) -> BattleTurnRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._retry_sync,
                self._run_battle_turn_once,
                battle_id,
                expected_round,
            )

    async def resolve_battle(self, *, battle_id: str) -> BattleResolutionRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._retry_sync, self._resolve_battle_once, battle_id)

    async def claim_battle_reward(
        self, *, platform: str, platform_user_id: str, operation_id: str
    ) -> BattleRewardClaimRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._retry_sync,
                self._claim_battle_reward_once,
                platform,
                platform_user_id,
                operation_id,
            )

    async def replay_battle(
        self, *, platform: str, platform_user_id: str, battle_id: str | None = None
    ) -> BattleReplayRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._replay_battle_once, platform, platform_user_id, battle_id
            )

    @staticmethod
    def _retry_sync(callback: Any, *args: Any) -> Any:
        last_error: Exception | None = None
        for attempt in range(5):
            try:
                return callback(*args)
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc).lower():
                    raise
                if attempt == 4:
                    raise RepositoryBusyError("database remained locked") from exc
                last_error = exc
                time.sleep(0.01 * (2**attempt))
        raise RepositoryBusyError("database remained locked") from last_error

    def _start_training_battle_once(
        self,
        platform: str,
        platform_user_id: str,
        operation_id: str,
        enemy_key: str = "enemy.training_dummy",
        battle_type: str = "pve.training",
        exploration_id: str | None = None,
    ) -> BattleStartRecord:
        enemy = enemy_definition(enemy_key)
        operation_name = "battle.start" if battle_type == "pve.training" else f"battle.start.{battle_type}"
        request_hash = self._request_hash(
            operation_name,
            {
                "platform": platform,
                "platform_user_id": platform_user_id,
                "enemy_key": enemy.key,
                "battle_type": battle_type,
                "exploration_id": exploration_id,
                "content_version": CONTENT_VERSION,
                "rule_version": RULE_VERSION,
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
                return self._battle_start_from_payload(json.loads(existing["result_json"]), replay=True)

            player = self._require_player(connection, platform, platform_user_id)
            if str(player["location_key"]) != enemy.location_key and exploration_id is None:
                raise BattleRequirementError("battle requires a specific location")
            cooldown = player["battle_defeat_until"]
            if battle_type == "pve.training" and cooldown and now < datetime.fromisoformat(str(cooldown)):
                raise BattleCooldownError("battle defeat cooldown is active")
            if self._has_active_long_action(
                connection,
                int(player["id"]),
                ignore_exploration_id=exploration_id,
            ):
                raise BattleBusyError("another long action is active")
            exploration = None
            exploration_snapshot: dict[str, Any] = {}
            if exploration_id is not None:
                exploration = connection.execute(
                    "SELECT * FROM exploration_sessions WHERE exploration_id = ? AND player_id = ? AND status = 'combat_pending'",
                    (exploration_id, player["id"]),
                ).fetchone()
                if exploration is None:
                    raise BattleRequirementError("exploration encounter is not pending")
                exploration_snapshot = self._json_object(exploration["snapshot_json"], {})
                if str(exploration_snapshot.get("location_key", "")) != enemy.location_key:
                    raise BattleRequirementError("battle location differs from exploration snapshot")
                if not self._meets_realm_values(
                    str(exploration_snapshot.get("realm_key", "")),
                    int(exploration_snapshot.get("realm_layer", 0)),
                    enemy.required_realm,
                    enemy.required_layer,
                ):
                    raise BattleRequirementError("exploration snapshot does not meet encounter requirement")
            elif not self._meets_enemy_requirement(player, enemy.required_realm, enemy.required_layer):
                raise BattleRequirementError("realm requirement is not met")
            if exploration is not None:
                location_key = str(exploration_snapshot.get("location_key", enemy.location_key))
            else:
                location_key = enemy.location_key
            active = connection.execute(
                "SELECT 1 FROM battle_sessions WHERE player_id = ? AND status IN ('created', 'running') LIMIT 1",
                (player["id"],),
            ).fetchone()
            if active is not None:
                raise BattleBusyError("battle is already active")

            equipment = (
                tuple(exploration_snapshot.get("equipment", ()))
                if exploration is not None
                else self._battle_equipment_snapshot(connection, int(player["id"]))
            )
            qualification = (
                self._json_object(exploration_snapshot.get("qualification"), {})
                if exploration is not None
                else self._json_object(player["qualification_json"], {})
            )
            stats = player_stat_snapshot(
                qualification,
                max_hp=int(exploration_snapshot.get("max_hp", player["max_hp"])),
                initiative=int(exploration_snapshot.get("initiative", player["initiative"])),
                equipment=equipment,
            )
            battle_id = uuid4().hex
            snapshot = {
                "battle_type": battle_type,
                "exploration_id": exploration_id,
                "location_key": location_key,
                "player": {
                    "player_id": str(player["player_id"]),
                    "path_key": player["path_key"],
                    "qualification": qualification,
                    "stats": stats,
                    "equipment": list(equipment),
                },
                "enemy": {
                    "key": enemy.key,
                    "label": enemy.label,
                    "max_hp": enemy.max_hp,
                    "attack": enemy.attack,
                    "initiative": enemy.initiative,
                    "agility": enemy.agility,
                    "skill_key": enemy.skill_key,
                },
                "random_pool": enemy.random_pool,
                "random_seed": operation_id,
                "reward": dict(enemy.reward),
                "content_version": CONTENT_VERSION,
                "rule_version": RULE_VERSION,
            }
            state = {
                "round_no": 0,
                "player_hp": stats["max_hp"],
                "enemy_hp": enemy.max_hp,
                "timeout_count": 0,
            }
            turn_deadline = serialize_datetime(now + timedelta(seconds=TURN_TIMEOUT_SECONDS))
            connection.execute(
                """
                INSERT INTO battle_sessions(
                    battle_id, player_id, start_operation_id, battle_type, enemy_key, location_key,
                    status, reward_status, round_no, action_sequence, starts_at, turn_deadline,
                    snapshot_json, state_json, result_json, content_version, rule_version,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'created', 'none', 0, 0, ?, ?, ?, ?, '{}', ?, ?, ?, ?)
                """,
                (
                    battle_id,
                    player["id"],
                    operation_id,
                    battle_type,
                    enemy.key,
                    enemy.location_key,
                    now_text,
                    turn_deadline,
                    json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
                    json.dumps(state, ensure_ascii=False, sort_keys=True),
                    CONTENT_VERSION,
                    RULE_VERSION,
                    now_text,
                    now_text,
                ),
            )
            payload = {
                "player": self._player_payload(self._row_to_player(player)),
                "battle_id": battle_id,
                "enemy_key": enemy.key,
                "status": "created",
                "round_no": 0,
                "max_rounds": MAX_TURNS,
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
            if exploration is not None:
                result = self._json_object(exploration["result_json"], {})
                result["battle_id"] = battle_id
                result["battle_enemy_key"] = enemy.key
                connection.execute(
                    "UPDATE exploration_sessions SET result_json = ?, updated_at = ? WHERE id = ? AND status = 'combat_pending'",
                    (json.dumps(result, ensure_ascii=False, sort_keys=True), now_text, exploration["id"]),
                )
            return self._battle_start_from_payload(payload)

    def _run_battle_turn_once(self, battle_id: str, expected_round: int) -> BattleTurnRecord:
        if expected_round < 1 or expected_round > MAX_TURNS:
            raise ValueError("expected battle round is invalid")
        operation_id = f"battle.run_turn:{battle_id}:{expected_round}"
        operation_name = "battle.run_turn"
        request_hash = self._request_hash(
            operation_name,
            {"battle_id": battle_id, "expected_round": expected_round, "rule_version": RULE_VERSION},
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
                    raise OperationConflictError("automatic battle operation conflicts")
                return self._battle_turn_from_payload(json.loads(existing["result_json"]), replay=True)

            session = connection.execute(
                "SELECT * FROM battle_sessions WHERE battle_id = ?", (battle_id,)
            ).fetchone()
            if session is None:
                raise BattleNotFoundError("battle does not exist")
            state = self._json_object(session["state_json"], {})
            current_round = int(state.get("round_no", session["round_no"]))
            if current_round >= expected_round or str(session["status"]) not in {"created", "running"}:
                return self._battle_turn_record(session, state, already_completed=True)
            if current_round + 1 != expected_round:
                return self._battle_turn_record(session, state, already_completed=True)

            snapshot = self._json_object(session["snapshot_json"], {})
            player_stats = dict(snapshot["player"]["stats"])
            enemy = dict(snapshot["enemy"])
            is_tribulation_trial = str(snapshot.get("profile_key", "")) == PROFILE_KEY
            tribulation = self._json_object(snapshot.get("tribulation"), {})
            debt_shield_bp = int(tribulation.get("debt_shield_bp", 0)) if is_tribulation_trial else 0
            player_hp = int(state["player_hp"])
            enemy_hp = int(state["enemy_hp"])
            timeout = now >= datetime.fromisoformat(str(session["turn_deadline"]))
            timeout_count = int(state.get("timeout_count", 0)) + 1 if timeout else 0
            sequence = int(session["action_sequence"])
            actions: list[dict[str, object]] = []
            defending = False
            player_first = player_goes_first(
                player_initiative=int(player_stats["initiative"]),
                enemy_initiative=int(enemy["initiative"]),
                seed=f"{snapshot['random_seed']}:{expected_round}",
            )
            actor_order = ("player", "enemy") if player_first else ("enemy", "player")
            outcome: str | None = None
            reason = ""
            for actor in actor_order:
                phase = phase_for_hp(enemy_hp, int(enemy["max_hp"])) if is_tribulation_trial else None
                if actor == "player" and timeout:
                    action = self._defend_action(
                        battle_id=battle_id,
                        round_no=expected_round,
                        sequence=sequence + 1,
                        player_hp=player_hp,
                        enemy_hp=enemy_hp,
                        operation_id=operation_id,
                    )
                    defending = True
                elif actor == "player":
                    action = self._attack_action(
                        battle_id=battle_id,
                        round_no=expected_round,
                        sequence=sequence + 1,
                        actor_key="player",
                        skill_key="skill.basic_attack",
                        strategy_key="strategy.basic_attack.v0.1",
                        attacker_attack=int(player_stats["attack"]),
                        attacker_initiative=int(player_stats["initiative"]),
                        defender_agility=int(enemy["agility"]),
                        target_hp=(
                            enemy_hp
                            if not is_tribulation_trial
                            else max(enemy_hp, int(player_stats["attack"])) + int(player_stats["attack"])
                        ),
                        seed=str(snapshot["random_seed"]),
                        operation_id=operation_id,
                    )
                    if phase is not None:
                        effective_damage_bp = phase.player_damage_bp * (10_000 - debt_shield_bp) // 10_000
                        action["damage"] = min(
                            enemy_hp,
                            int(action["damage"])
                            * effective_damage_bp
                            // 10_000,
                        )
                    enemy_hp = max(0, enemy_hp - int(action["damage"]))
                else:
                    if actor == "enemy" and is_tribulation_trial:
                        phase = phase_for_hp(enemy_hp, int(enemy["max_hp"]))
                    action = self._attack_action(
                        battle_id=battle_id,
                        round_no=expected_round,
                        sequence=sequence + 1,
                        actor_key="enemy",
                        skill_key=phase.skill_key if phase is not None else str(enemy["skill_key"]),
                        strategy_key=(
                            "strategy.tribulation_phase.v0.6"
                            if phase is not None
                            else "strategy.training_dummy.v0.1"
                        ),
                        attacker_attack=phase.attack if phase is not None else int(enemy["attack"]),
                        attacker_initiative=int(enemy["initiative"]),
                        defender_agility=int(player_stats["agility"]),
                        target_hp=player_hp,
                        seed=str(snapshot["random_seed"]),
                        operation_id=operation_id,
                        skill_hit_bp=phase.enemy_hit_bonus_bp if phase is not None else 0,
                    )
                    if defending:
                        action["damage"] = int(action["damage"]) * 8_000 // 10_000
                    player_hp = max(0, player_hp - int(action["damage"]))
                sequence += 1
                action["state"] = {"player_hp": player_hp, "enemy_hp": enemy_hp}
                if phase is not None:
                    action["state"].update(
                        {
                            "tribulation_phase": phase.key,
                            "debt_shield_bp": debt_shield_bp,
                            "phase_player_damage_bp": phase.player_damage_bp,
                        }
                    )
                actions.append(action)
                if enemy_hp <= 0:
                    outcome, reason = "won", "enemy_defeated"
                    break
                if player_hp <= 0:
                    outcome, reason = "lost", "player_defeated"
                    break
            if outcome is None and timeout_count >= 3:
                outcome, reason = "lost", "three_turn_timeouts"
            if outcome is None and expected_round >= MAX_TURNS:
                outcome, reason = "lost", "turn_limit_reached"

            for action in actions:
                connection.execute(
                    """
                    INSERT INTO battle_actions(
                        action_id, battle_id, sequence_no, round_no, actor_key, strategy_key,
                        skill_key, target_key, hit_roll_bp, crit_roll_bp, hit_bp, damage,
                        state_json, operation_id, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        uuid4().hex,
                        battle_id,
                        action["sequence_no"],
                        expected_round,
                        action["actor_key"],
                        action["strategy_key"],
                        action["skill_key"],
                        action["target_key"],
                        action["hit_roll_bp"],
                        action["crit_roll_bp"],
                        action["hit_bp"],
                        action["damage"],
                        json.dumps(action["state"], ensure_ascii=False, sort_keys=True),
                        operation_id,
                        now_text,
                    ),
                )
            state = {
                "round_no": expected_round,
                "player_hp": player_hp,
                "enemy_hp": enemy_hp,
                "timeout_count": timeout_count,
            }
            if is_tribulation_trial:
                state.update(
                    {
                        "tribulation_phase": phase_for_hp(enemy_hp, int(enemy["max_hp"])).key,
                        "debt_shield_bp": debt_shield_bp,
                    }
                )
            status = outcome or "running"
            connection.execute(
                """
                UPDATE battle_sessions
                SET status = ?, round_no = ?, action_sequence = ?, turn_deadline = ?,
                    state_json = ?, result_json = CASE WHEN ? IS NULL THEN result_json ELSE ? END,
                    updated_at = ?
                WHERE battle_id = ?
                """,
                (
                    status,
                    expected_round,
                    sequence,
                    serialize_datetime(now + timedelta(seconds=TURN_TIMEOUT_SECONDS)),
                    json.dumps(state, ensure_ascii=False, sort_keys=True),
                    outcome,
                    json.dumps({"outcome": outcome, "reason": reason}, ensure_ascii=False, sort_keys=True),
                    now_text,
                    battle_id,
                ),
            )
            payload = {
                "battle_id": battle_id,
                "status": status,
                "outcome": outcome,
                "round_no": expected_round,
                "player_hp": player_hp,
                "enemy_hp": enemy_hp,
                "action_count": len(actions),
            }
            self._insert_operation(
                connection,
                operation_id=operation_id,
                operation_name=operation_name,
                player_id=int(session["player_id"]),
                request_hash=request_hash,
                payload=payload,
                now_text=now_text,
            )
            return self._battle_turn_from_payload(payload)

    def _resolve_battle_once(self, battle_id: str) -> BattleResolutionRecord:
        operation_id = f"battle.resolve:{battle_id}"
        operation_name = "battle.resolve"
        request_hash = self._request_hash(
            operation_name, {"battle_id": battle_id, "rule_version": RULE_VERSION}
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
                    raise OperationConflictError("battle resolution conflicts")
                return self._battle_resolution_from_payload(json.loads(existing["result_json"]), replay=True)
            session = connection.execute(
                "SELECT * FROM battle_sessions WHERE battle_id = ?", (battle_id,)
            ).fetchone()
            if session is None:
                raise BattleNotFoundError("battle does not exist")
            if str(session["status"]) in {"created", "running"}:
                raise BattleNotReadyError("battle is still running")
            if str(session["status"]) == "settled":
                raise BattleAlreadySettledError("battle is already settled")
            player = connection.execute(
                "SELECT * FROM players WHERE id = ?", (session["player_id"],)
            ).fetchone()
            if player is None:
                raise PlayerNotFoundError("battle player does not exist")
            result = self._json_object(session["result_json"], {})
            outcome = str(result.get("outcome", session["status"]))
            reason = str(result.get("reason", "battle_ended"))
            snapshot = self._json_object(session["snapshot_json"], {})
            reward = {
                str(key): int(value)
                for key, value in dict(snapshot.get("reward", {})).items()
            } if outcome == "won" else {}
            reward_status = "pending" if outcome == "won" and reward else "none"
            durability_loss = 0
            if outcome == "won" and str(session["battle_type"]) != "pve.tribulation_trial":
                durable_ids = [
                    str(item["instance_id"])
                    for item in list(snapshot.get("player", {}).get("equipment", []))
                    if str(item.get("slot", "")) in {"weapon", "armor"}
                ]
                if durable_ids:
                    placeholders = ", ".join("?" for _ in durable_ids)
                    connection.execute(
                        f"""
                        UPDATE equipment_instances
                        SET durability_bp = CASE WHEN durability_bp > 50 THEN durability_bp - 50 ELSE 0 END,
                            status = CASE WHEN durability_bp <= 50 THEN 'broken' ELSE status END,
                            updated_at = ?
                        WHERE player_id = ? AND instance_id IN ({placeholders}) AND status = 'active'
                        """,
                        (now_text, player["id"], *durable_ids),
                    )
                    durability_loss = 50
            elif outcome in {"lost", "expired"} and str(session["battle_type"]) == "pve.training":
                connection.execute(
                    "UPDATE players SET battle_defeat_until = ?, updated_at = ? WHERE id = ?",
                    (
                        serialize_datetime(now + timedelta(seconds=DEFEAT_COOLDOWN_SECONDS)),
                        now_text,
                        player["id"],
                    ),
                )
            result.update(
                {
                    "outcome": outcome,
                    "reason": reason,
                    "reward": reward,
                    "reward_status": reward_status,
                    "durability_loss_bp": durability_loss,
                    "settled_at": now_text,
                }
            )
            connection.execute(
                """
                UPDATE battle_sessions
                SET status = 'settled', reward_status = ?, resolved_operation_id = ?,
                    result_json = ?, updated_at = ?
                WHERE battle_id = ?
                """,
                (
                    reward_status,
                    operation_id,
                    json.dumps(result, ensure_ascii=False, sort_keys=True),
                    now_text,
                    battle_id,
                ),
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (player["id"],)).fetchone()
            if updated is None:
                raise PlayerNotFoundError("battle player disappeared")
            payload = {
                "player": self._player_payload(self._row_to_player(updated)),
                "battle_id": battle_id,
                "enemy_key": session["enemy_key"],
                "status": "settled",
                "outcome": outcome,
                "reason": reason,
                "round_no": int(session["round_no"]),
                "reward": reward,
                "reward_status": reward_status,
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
            return self._battle_resolution_from_payload(payload)

    def _claim_battle_reward_once(
        self, platform: str, platform_user_id: str, operation_id: str
    ) -> BattleRewardClaimRecord:
        operation_name = "battle.claim_reward"
        request_hash = self._request_hash(
            operation_name, {"platform": platform, "platform_user_id": platform_user_id}
        )
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            if existing is not None:
                if existing["operation_name"] != operation_name or existing["request_hash"] != request_hash:
                    raise OperationConflictError("battle reward claim conflicts")
                return self._battle_reward_from_payload(json.loads(existing["result_json"]), replay=True)
            player = self._require_player(connection, platform, platform_user_id)
            session = connection.execute(
                """
                SELECT * FROM battle_sessions
                WHERE player_id = ? AND status = 'settled' AND reward_status = 'pending'
                ORDER BY id DESC LIMIT 1
                """,
                (player["id"],),
            ).fetchone()
            if session is None:
                claimed = connection.execute(
                    "SELECT 1 FROM battle_sessions WHERE player_id = ? AND reward_status = 'claimed' LIMIT 1",
                    (player["id"],),
                ).fetchone()
                if claimed is not None:
                    raise BattleRewardAlreadyClaimedError("battle reward is already claimed")
                raise BattleRewardNotAvailableError("no battle reward is pending")
            result = self._json_object(session["result_json"], {})
            reward = {str(key): int(value) for key, value in dict(result.get("reward", {})).items()}
            if not reward:
                raise BattleRewardNotAvailableError("battle has no claimable reward")
            inventory = self._json_object(player["inventory_json"], {})
            stones = int(player["spirit_stones"])
            cultivation = int(player["cultivation"])
            total_cultivation = int(player["total_cultivation"])
            for key, quantity in reward.items():
                if key == "spirit_stones":
                    stones += quantity
                elif key == "cultivation":
                    cultivation += quantity
                    total_cultivation += quantity
                else:
                    inventory[key] = int(inventory.get(key, 0)) + quantity
            connection.execute(
                """
                UPDATE players
                SET spirit_stones = ?, cultivation = ?, total_cultivation = ?,
                    inventory_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    stones,
                    cultivation,
                    total_cultivation,
                    json.dumps(inventory, ensure_ascii=False, sort_keys=True),
                    now_text,
                    player["id"],
                ),
            )
            connection.execute(
                """
                INSERT INTO battle_reward_claims(battle_id, player_id, operation_id, reward_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    session["battle_id"],
                    player["id"],
                    operation_id,
                    json.dumps(reward, ensure_ascii=False, sort_keys=True),
                    now_text,
                ),
            )
            connection.execute(
                """
                UPDATE battle_sessions SET reward_status = 'claimed', claim_operation_id = ?, updated_at = ?
                WHERE battle_id = ? AND reward_status = 'pending'
                """,
                (operation_id, now_text, session["battle_id"]),
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (player["id"],)).fetchone()
            if updated is None:
                raise PlayerNotFoundError("battle player disappeared")
            payload = {
                "player": self._player_payload(self._row_to_player(updated)),
                "battle_id": session["battle_id"],
                "reward": reward,
                "reward_status": "claimed",
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
            return self._battle_reward_from_payload(payload)

    def _replay_battle_once(
        self, platform: str, platform_user_id: str, battle_id: str | None
    ) -> BattleReplayRecord:
        with self._connect() as connection:
            player = self._require_player(connection, platform, platform_user_id, writable=False)
            if battle_id:
                session = connection.execute(
                    "SELECT * FROM battle_sessions WHERE battle_id = ? AND player_id = ?",
                    (battle_id, player["id"]),
                ).fetchone()
            else:
                session = connection.execute(
                    "SELECT * FROM battle_sessions WHERE player_id = ? ORDER BY id DESC LIMIT 1",
                    (player["id"],),
                ).fetchone()
            if session is None:
                raise BattleNotFoundError("battle does not exist")
            action_rows = connection.execute(
                "SELECT * FROM battle_actions WHERE battle_id = ? ORDER BY sequence_no",
                (session["battle_id"],),
            ).fetchall()
            actions = tuple(
                {
                    "sequence_no": int(action["sequence_no"]),
                    "round_no": int(action["round_no"]),
                    "actor_key": str(action["actor_key"]),
                    "strategy_key": str(action["strategy_key"]),
                    "skill_key": str(action["skill_key"]),
                    "target_key": str(action["target_key"]),
                    "hit_roll_bp": int(action["hit_roll_bp"]),
                    "crit_roll_bp": int(action["crit_roll_bp"]),
                    "hit_bp": int(action["hit_bp"]),
                    "damage": int(action["damage"]),
                    "state": self._json_object(action["state_json"], {}),
                    "operation_id": str(action["operation_id"]),
                }
                for action in action_rows
            )
            return BattleReplayRecord(
                battle_id=str(session["battle_id"]),
                enemy_key=str(session["enemy_key"]),
                status=str(session["status"]),
                snapshot=self._json_object(session["snapshot_json"], {}),
                result=self._json_object(session["result_json"], {}),
                actions=actions,
            )

    @staticmethod
    def _meets_enemy_requirement(player: Any, required_realm: str, required_layer: int) -> bool:
        return CombatRepositoryMixin._meets_realm_values(
            str(player["realm_key"]), int(player["realm_layer"]), required_realm, required_layer
        )

    @staticmethod
    def _meets_realm_values(
        realm_key: str, layer: int, required_realm: str, required_layer: int
    ) -> bool:
        ranks = {
            "mortal": 0,
            "qi_sensing": 1,
            "qi_gathering": 2,
            "foundation": 3,
            "golden_core": 4,
            "nascent_soul": 5,
            "soul_transformation": 6,
            "void_refining": 7,
            "dao_union": 8,
            "tribulation": 9,
        }
        player_rank = ranks.get(str(realm_key), -1)
        required_rank = ranks.get(required_realm, 99)
        return (player_rank, int(layer)) >= (required_rank, required_layer)

    def _battle_equipment_snapshot(
        self, connection: sqlite3.Connection, player_id: int
    ) -> tuple[dict[str, object], ...]:
        rows = connection.execute(
            """
            SELECT instance_id, item_key, slot, durability_bp, temper_level, affixes_json
            FROM equipment_instances
            WHERE player_id = ? AND status = 'active' AND durability_bp > 0
            ORDER BY id
            """,
            (player_id,),
        ).fetchall()
        return tuple(
            {
                "instance_id": str(row["instance_id"]),
                "item_key": str(row["item_key"]),
                "slot": str(row["slot"]),
                "durability_bp": int(row["durability_bp"]),
                "temper_level": int(row["temper_level"]),
                "affixes": {
                    str(key): int(value)
                    for key, value in self._json_object(row["affixes_json"], {}).items()
                },
            }
            for row in rows
        )

    @staticmethod
    def _attack_action(
        *,
        battle_id: str,
        round_no: int,
        sequence: int,
        actor_key: str,
        skill_key: str,
        strategy_key: str,
        attacker_attack: int,
        attacker_initiative: int,
        defender_agility: int,
        target_hp: int,
        seed: str,
        operation_id: str,
        skill_hit_bp: int = 0,
    ) -> dict[str, object]:
        hit_bp = hit_chance_bp(
            attacker_initiative=attacker_initiative,
            defender_agility=defender_agility,
            skill_hit_bp=skill_hit_bp,
        )
        hit_roll = battle_roll_bp(f"{seed}:round:{round_no}:action:{sequence}:hit")
        crit_roll = battle_roll_bp(f"{seed}:round:{round_no}:action:{sequence}:crit")
        hit = hit_roll < hit_bp
        return {
            "battle_id": battle_id,
            "sequence_no": sequence,
            "actor_key": actor_key,
            "strategy_key": strategy_key,
            "skill_key": skill_key,
            "target_key": "enemy" if actor_key == "player" else "player",
            "hit_roll_bp": hit_roll,
            "crit_roll_bp": crit_roll,
            "hit_bp": hit_bp,
            "damage": min(target_hp, max(0, attacker_attack)) if hit else 0,
            "operation_id": operation_id,
        }

    @staticmethod
    def _defend_action(
        *,
        battle_id: str,
        round_no: int,
        sequence: int,
        player_hp: int,
        enemy_hp: int,
        operation_id: str,
    ) -> dict[str, object]:
        return {
            "battle_id": battle_id,
            "sequence_no": sequence,
            "actor_key": "player",
            "strategy_key": "strategy.timeout_defend.v0.1",
            "skill_key": "skill.defend",
            "target_key": "player",
            "hit_roll_bp": 0,
            "crit_roll_bp": 0,
            "hit_bp": 10_000,
            "damage": 0,
            "state": {"player_hp": player_hp, "enemy_hp": enemy_hp, "damage_reduction_bp": 2_000},
            "operation_id": operation_id,
        }

    def _battle_start_from_payload(
        self, payload: dict[str, Any], *, replay: bool = False
    ) -> BattleStartRecord:
        return BattleStartRecord(
            player=self._row_to_player(payload["player"]),
            battle_id=str(payload["battle_id"]),
            enemy_key=str(payload["enemy_key"]),
            status=str(payload["status"]),
            round_no=int(payload.get("round_no", 0)),
            max_rounds=int(payload.get("max_rounds", MAX_TURNS)),
            already_completed=replay,
        )

    @staticmethod
    def _battle_turn_from_payload(payload: dict[str, Any], *, replay: bool = False) -> BattleTurnRecord:
        return BattleTurnRecord(
            battle_id=str(payload["battle_id"]),
            status=str(payload["status"]),
            outcome=payload.get("outcome"),
            round_no=int(payload["round_no"]),
            player_hp=int(payload["player_hp"]),
            enemy_hp=int(payload["enemy_hp"]),
            action_count=int(payload.get("action_count", 0)),
            already_completed=replay,
        )

    def _battle_turn_record(
        self, session: sqlite3.Row, state: dict[str, Any], *, already_completed: bool
    ) -> BattleTurnRecord:
        result = self._json_object(session["result_json"], {})
        return BattleTurnRecord(
            battle_id=str(session["battle_id"]),
            status=str(session["status"]),
            outcome=result.get("outcome"),
            round_no=int(state.get("round_no", session["round_no"])),
            player_hp=int(state.get("player_hp", 0)),
            enemy_hp=int(state.get("enemy_hp", 0)),
            action_count=0,
            already_completed=already_completed,
        )

    def _battle_resolution_from_payload(
        self, payload: dict[str, Any], *, replay: bool = False
    ) -> BattleResolutionRecord:
        return BattleResolutionRecord(
            player=self._row_to_player(payload["player"]),
            battle_id=str(payload["battle_id"]),
            enemy_key=str(payload["enemy_key"]),
            status=str(payload["status"]),
            outcome=str(payload["outcome"]),
            reason=str(payload["reason"]),
            round_no=int(payload["round_no"]),
            reward={str(key): int(value) for key, value in dict(payload.get("reward", {})).items()},
            reward_status=str(payload.get("reward_status", "none")),
            already_completed=replay,
        )

    def _battle_reward_from_payload(
        self, payload: dict[str, Any], *, replay: bool = False
    ) -> BattleRewardClaimRecord:
        return BattleRewardClaimRecord(
            player=self._row_to_player(payload["player"]),
            battle_id=str(payload["battle_id"]),
            reward={str(key): int(value) for key, value in dict(payload.get("reward", {})).items()},
            reward_status=str(payload.get("reward_status", "claimed")),
            already_completed=replay,
        )

    @staticmethod
    def _insert_operation(
        connection: sqlite3.Connection,
        *,
        operation_id: str,
        operation_name: str,
        player_id: int,
        request_hash: str,
        payload: dict[str, Any],
        now_text: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                operation_id,
                operation_name,
                player_id,
                request_hash,
                json.dumps(payload, ensure_ascii=False, sort_keys=True),
                now_text,
            ),
        )
