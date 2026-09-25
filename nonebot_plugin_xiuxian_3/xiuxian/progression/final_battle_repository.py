"""Persistence for the five-player terminal battle and its escrowed certificate."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import timedelta
from typing import Any
from uuid import uuid4

from ...contracts import serialize_datetime
from ..persistence.errors import (
    FinalBattleBusyError,
    FinalBattleCooldownError,
    FinalBattleMemberLimitError,
    FinalBattleNotFoundError,
    FinalBattleNotReadyError,
    FinalBattlePermissionError,
    FinalBattleRequirementError,
    OperationConflictError,
)
from ..combat.rules import TURN_TIMEOUT_SECONDS, battle_roll_bp, hit_chance_bp
from ..combat.tribulation_rules import stat_snapshot
from .endgame_models import (
    FinalBattleReplayRecord,
    FinalBattleResolutionRecord,
    FinalBattleSessionRecord,
)
from .endgame_rules import (
    ASCENSION_CERTIFICATE_KEY,
    ASCENSION_READY_STATUS,
    CONTENT_VERSION,
    FINAL_BATTLE_ASSIST_MERIT_CAP,
    FINAL_BATTLE_ASSIST_MERIT_PER_DAMAGE,
    FINAL_BATTLE_COOLDOWN_SECONDS,
    FINAL_BATTLE_ENEMY_AGILITY,
    FINAL_BATTLE_ENEMY_ATTACK,
    FINAL_BATTLE_ENEMY_INITIATIVE,
    FINAL_BATTLE_ENEMY_KEY,
    FINAL_BATTLE_ENEMY_MAX_HP,
    FINAL_BATTLE_LOBBY_SECONDS,
    FINAL_BATTLE_MAX_MEMBERS,
    FINAL_BATTLE_MAX_TURNS,
    FINAL_BATTLE_MIN_MERIT,
    FINAL_BATTLE_MIN_PROGRESS,
    RULE_VERSION,
    TRIAL_ORDER,
)

FINAL_BATTLE_RULE_VERSION = "combat-final-0.1.0"
FINAL_BATTLE_LOCATION = "tribulation.sky_terrace"


class FinalBattleRepositoryMixin:
    """Own the final battle lobby, automatic turns, escrow, and settlement."""

    async def create_final_battle(
        self, *, platform: str, platform_user_id: str, operation_id: str
    ) -> FinalBattleSessionRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._retry_sync,
                self._create_final_battle_once,
                platform,
                platform_user_id,
                operation_id,
            )

    async def join_final_battle(
        self, *, platform: str, platform_user_id: str, battle_id: str, operation_id: str
    ) -> FinalBattleSessionRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._retry_sync,
                self._join_final_battle_once,
                platform,
                platform_user_id,
                battle_id,
                operation_id,
            )

    async def start_final_battle(
        self, *, platform: str, platform_user_id: str, battle_id: str | None, operation_id: str
    ) -> FinalBattleSessionRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._retry_sync,
                self._start_final_battle_once,
                platform,
                platform_user_id,
                battle_id,
                operation_id,
            )

    async def choose_final_battle(
        self,
        *,
        platform: str,
        platform_user_id: str,
        battle_id: str | None,
        choice: str,
        operation_id: str,
    ) -> dict[str, Any]:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._retry_sync,
                self._choose_final_battle_once,
                platform,
                platform_user_id,
                battle_id,
                choice,
                operation_id,
            )

    async def run_final_battle_turn(self, *, battle_id: str, expected_round: int) -> dict[str, Any]:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._retry_sync, self._run_final_battle_turn_once, battle_id, expected_round
            )

    async def resolve_final_battle(
        self, *, platform: str, platform_user_id: str, battle_id: str, operation_id: str
    ) -> FinalBattleResolutionRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._retry_sync,
                self._resolve_final_battle_once,
                platform,
                platform_user_id,
                battle_id,
                operation_id,
            )

    async def cancel_final_battle(
        self, *, platform: str, platform_user_id: str, battle_id: str | None, operation_id: str
    ) -> FinalBattleSessionRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._retry_sync,
                self._cancel_final_battle_once,
                platform,
                platform_user_id,
                battle_id,
                operation_id,
            )

    async def final_battle_access(
        self, *, platform: str, platform_user_id: str, battle_id: str | None = None
    ) -> dict[str, Any]:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._final_battle_access_once, platform, platform_user_id, battle_id
            )

    async def replay_final_battle(
        self, *, platform: str, platform_user_id: str, battle_id: str | None = None
    ) -> FinalBattleReplayRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._replay_final_battle_once, platform, platform_user_id, battle_id
            )

    def _create_final_battle_once(
        self, platform: str, platform_user_id: str, operation_id: str
    ) -> FinalBattleSessionRecord:
        operation_name = "ascension.final_battle.create"
        request_hash = self._request_hash(operation_name, {"platform": platform, "platform_user_id": platform_user_id})
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._final_battle_operation(connection, operation_id, operation_name, request_hash)
            if existing is not None:
                return self._final_battle_session_from_payload(existing, replay=True)
            player = self._require_player(connection, platform, platform_user_id, writable=False)
            active = connection.execute(
                "SELECT * FROM final_battle_sessions WHERE initiator_id=? AND status IN ('lobby','running','won','lost') ORDER BY id DESC LIMIT 1",
                (player["id"],),
            ).fetchone()
            if active is not None:
                if str(active["status"]) != "lobby" or now_text < str(active["expires_at"]):
                    raise FinalBattleBusyError("initiator already has an unresolved final battle")
                expired_snapshot = self._json_object(active["snapshot_json"], {})
                escrow = expired_snapshot.get("certificate_escrow", {})
                inventory = self._json_object(player["inventory_json"], {})
                item_key = str(escrow.get("item_key", ASCENSION_CERTIFICATE_KEY))
                inventory[item_key] = int(inventory.get(item_key, 0)) + int(escrow.get("quantity", 1))
                connection.execute("UPDATE players SET inventory_json=?, updated_at=? WHERE id=?", (json.dumps(inventory, ensure_ascii=False, sort_keys=True), now_text, player["id"]))
                connection.execute("UPDATE final_battle_members SET asset_lock_status='released', updated_at=? WHERE battle_id=?", (now_text, active["battle_id"]))
                connection.execute("UPDATE final_battle_sessions SET status='expired', result_json=?, updated_at=? WHERE battle_id=?", (json.dumps({"outcome": "expired", "reason": "lobby_timeout"}, ensure_ascii=False, sort_keys=True), now_text, active["battle_id"]))
                player = connection.execute("SELECT * FROM players WHERE id=?", (player["id"],)).fetchone()
                if player is None:
                    raise FinalBattleNotFoundError("initiator disappeared")
            self._require_final_battle_candidate(connection, player, now_text)
            if self._has_active_long_action(connection, int(player["id"])):
                raise FinalBattleBusyError("initiator has another active action")
            inventory = self._json_object(player["inventory_json"], {})
            if int(inventory.get(ASCENSION_CERTIFICATE_KEY, 0)) < 1:
                raise FinalBattleRequirementError("ascension certificate is missing")
            inventory[ASCENSION_CERTIFICATE_KEY] = int(inventory[ASCENSION_CERTIFICATE_KEY]) - 1
            if inventory[ASCENSION_CERTIFICATE_KEY] == 0:
                inventory.pop(ASCENSION_CERTIFICATE_KEY)

            battle_id = f"final-battle-{uuid4().hex}"
            initiator_snapshot = self._final_battle_member_snapshot(connection, player, role="initiator")
            snapshot = {
                "battle_type": "pve.ascension_final",
                "initiator_player_id": str(player["player_id"]),
                "location_key": FINAL_BATTLE_LOCATION,
                "members": [initiator_snapshot],
                "enemy": {
                    "key": FINAL_BATTLE_ENEMY_KEY,
                    "label": "飛升守界尊者",
                    "max_hp": FINAL_BATTLE_ENEMY_MAX_HP,
                    "attack": FINAL_BATTLE_ENEMY_ATTACK,
                    "initiative": FINAL_BATTLE_ENEMY_INITIATIVE,
                    "agility": FINAL_BATTLE_ENEMY_AGILITY,
                    "skill_key": "skill.ascension.guardian_strike",
                },
                "certificate_escrow": {"item_key": ASCENSION_CERTIFICATE_KEY, "quantity": 1},
                "random_seed": operation_id,
                "content_version": CONTENT_VERSION,
                "rule_version": FINAL_BATTLE_RULE_VERSION,
            }
            expires_at = serialize_datetime(now + timedelta(seconds=FINAL_BATTLE_LOBBY_SECONDS))
            connection.execute(
                "UPDATE players SET inventory_json=?, updated_at=? WHERE id=?",
                (json.dumps(inventory, ensure_ascii=False, sort_keys=True), now_text, player["id"]),
            )
            connection.execute(
                "INSERT INTO final_battle_sessions(battle_id, initiator_id, create_operation_id, status, round_no, action_sequence, starts_at, expires_at, snapshot_json, state_json, result_json, content_version, rule_version, created_at, updated_at) "
                "VALUES (?, ?, ?, 'lobby', 0, 0, ?, ?, ?, '{}', '{}', ?, ?, ?, ?)",
                (battle_id, player["id"], operation_id, now_text, expires_at, json.dumps(snapshot, ensure_ascii=False, sort_keys=True), CONTENT_VERSION, FINAL_BATTLE_RULE_VERSION, now_text, now_text),
            )
            self._insert_final_battle_member(connection, battle_id, player, initiator_snapshot, now_text)
            payload = {
                "battle_id": battle_id,
                "status": "lobby",
                "member_player_ids": [str(player["player_id"])],
                "expires_at": expires_at,
            }
            self._record_final_battle_operation(connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text)
            return self._final_battle_session_from_payload(payload)

    def _join_final_battle_once(
        self, platform: str, platform_user_id: str, battle_id: str, operation_id: str
    ) -> FinalBattleSessionRecord:
        operation_name = "ascension.final_battle.join"
        request_hash = self._request_hash(operation_name, {"platform": platform, "platform_user_id": platform_user_id, "battle_id": battle_id})
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._final_battle_operation(connection, operation_id, operation_name, request_hash)
            if existing is not None:
                return self._final_battle_session_from_payload(existing, replay=True)
            player = self._require_player(connection, platform, platform_user_id, writable=False)
            session = connection.execute("SELECT * FROM final_battle_sessions WHERE battle_id=?", (battle_id,)).fetchone()
            if session is None:
                raise FinalBattleNotFoundError("final battle does not exist")
            if str(session["status"]) == "lobby" and now_text >= str(session["expires_at"]):
                self._expire_final_battle_lobby(connection, session, now_text)
                raise FinalBattleNotReadyError("final battle lobby is closed")
            if str(session["status"]) != "lobby" or now_text >= str(session["expires_at"]):
                raise FinalBattleNotReadyError("final battle lobby is closed")
            if connection.execute("SELECT 1 FROM final_battle_members WHERE battle_id=? AND player_id=?", (battle_id, player["id"])).fetchone():
                raise FinalBattleBusyError("player already joined this final battle")
            member_count = int(connection.execute("SELECT COUNT(*) FROM final_battle_members WHERE battle_id=?", (battle_id,)).fetchone()[0])
            if member_count >= FINAL_BATTLE_MAX_MEMBERS:
                raise FinalBattleMemberLimitError("final battle is full")
            if str(player["realm_key"]) != "tribulation" or int(player["realm_layer"]) < 3 or str(player["location_key"]) != FINAL_BATTLE_LOCATION:
                raise FinalBattleRequirementError("helper must be at the sky terrace from tribulation L3")
            if str(player["endgame_status"] or "none") != "tribulation":
                raise FinalBattleRequirementError("helper is not on the tribulation route")
            if self._has_active_long_action(connection, int(player["id"])):
                raise FinalBattleBusyError("helper has another active action")
            member_snapshot = self._final_battle_member_snapshot(connection, player, role="helper")
            self._insert_final_battle_member(connection, battle_id, player, member_snapshot, now_text)
            snapshot = self._json_object(session["snapshot_json"], {})
            snapshot.setdefault("members", []).append(member_snapshot)
            connection.execute(
                "UPDATE final_battle_sessions SET snapshot_json=?, updated_at=? WHERE battle_id=? AND status='lobby'",
                (json.dumps(snapshot, ensure_ascii=False, sort_keys=True), now_text, battle_id),
            )
            member_ids = [str(member["player_id"]) for member in snapshot["members"]]
            payload = {"battle_id": battle_id, "status": "lobby", "member_player_ids": member_ids, "expires_at": str(session["expires_at"])}
            self._record_final_battle_operation(connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text)
            return self._final_battle_session_from_payload(payload)

    def _start_final_battle_once(
        self, platform: str, platform_user_id: str, battle_id: str | None, operation_id: str
    ) -> FinalBattleSessionRecord:
        operation_name = "ascension.final_battle.start"
        request_hash = self._request_hash(operation_name, {"platform": platform, "platform_user_id": platform_user_id, "battle_id": battle_id})
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._final_battle_operation(connection, operation_id, operation_name, request_hash)
            if existing is not None:
                return self._final_battle_session_from_payload(existing, replay=True)
            actor = self._require_player(connection, platform, platform_user_id, writable=False)
            session = self._select_final_battle_for_actor(connection, int(actor["id"]), battle_id)
            if str(session["status"]) == "lobby" and now_text >= str(session["expires_at"]):
                self._expire_final_battle_lobby(connection, session, now_text)
                session = connection.execute("SELECT * FROM final_battle_sessions WHERE battle_id=?", (session["battle_id"],)).fetchone()
            if int(session["initiator_id"]) != int(actor["id"]):
                raise FinalBattlePermissionError("only the initiator can start the final battle")
            if str(session["status"]) != "lobby":
                raise FinalBattleNotReadyError("final battle is not in its lobby state")
            if now_text >= str(session["expires_at"]):
                raise FinalBattleNotReadyError("final battle lobby expired")
            snapshot = self._json_object(session["snapshot_json"], {})
            members = snapshot.get("members", [])
            state = {
                "round_no": 0,
                "member_hp": {str(member["player_id"]): int(member["stats"]["max_hp"]) for member in members},
                "enemy_hp": int(snapshot["enemy"]["max_hp"]),
                "target_index": 0,
                "phase": "guardian",
            }
            connection.execute(
                "UPDATE final_battle_sessions SET status='running', start_operation_id=?, state_json=?, expires_at=?, updated_at=? WHERE battle_id=? AND status='lobby'",
                (operation_id, json.dumps(state, ensure_ascii=False, sort_keys=True), serialize_datetime(now + timedelta(seconds=30 * 60)), now_text, session["battle_id"]),
            )
            payload = {"battle_id": str(session["battle_id"]), "status": "running", "member_player_ids": [str(member["player_id"]) for member in members], "expires_at": serialize_datetime(now + timedelta(seconds=30 * 60))}
            self._record_final_battle_operation(connection, operation_id, operation_name, int(actor["id"]), request_hash, payload, now_text)
            return self._final_battle_session_from_payload(payload)

    def _run_final_battle_turn_once(self, battle_id: str, expected_round: int) -> dict[str, Any]:
        if expected_round < 1 or expected_round > FINAL_BATTLE_MAX_TURNS:
            raise ValueError("final battle round is invalid")
        operation_id = f"final-battle.turn:{battle_id}:{expected_round}"
        operation_name = "ascension.final_battle.turn"
        request_hash = self._request_hash(operation_name, {"battle_id": battle_id, "expected_round": expected_round, "rule_version": FINAL_BATTLE_RULE_VERSION})
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._final_battle_operation(connection, operation_id, operation_name, request_hash)
            if existing is not None:
                return existing
            session = connection.execute("SELECT * FROM final_battle_sessions WHERE battle_id=?", (battle_id,)).fetchone()
            if session is None:
                raise FinalBattleNotFoundError("final battle does not exist")
            if str(session["status"]) != "running":
                result = self._json_object(session["result_json"], {})
                return {"battle_id": battle_id, "status": str(session["status"]), "outcome": result.get("outcome"), "round_no": int(session["round_no"])}
            if int(session["round_no"]) != expected_round - 1:
                raise FinalBattleBusyError("final battle round is not next")
            snapshot = self._json_object(session["snapshot_json"], {})
            state = self._json_object(session["state_json"], {})
            if now_text >= str(session["expires_at"]):
                result = {"outcome": "expired", "reason": "battle_timeout"}
                connection.execute(
                    "UPDATE final_battle_sessions SET status='expired', result_json=?, updated_at=? WHERE battle_id=?",
                    (json.dumps(result, ensure_ascii=False, sort_keys=True), now_text, battle_id),
                )
                session_actor = connection.execute("SELECT initiator_id FROM final_battle_sessions WHERE battle_id=?", (battle_id,)).fetchone()
                payload = {"battle_id": battle_id, "status": "expired", "outcome": "expired", "round_no": int(session["round_no"]), "action_count": 0, "phase": str(state.get("phase", "guardian"))}
                self._record_final_battle_operation(connection, operation_id, operation_name, int(session_actor["initiator_id"]), request_hash, payload, now_text)
                return payload
            if str(state.get("phase", "guardian")) == "temptation":
                return {"battle_id": battle_id, "status": "running", "outcome": None, "round_no": int(session["round_no"]), "action_count": 0, "phase": "temptation", "choice_required": True}
            enemy = snapshot["enemy"]
            hp = {str(key): int(value) for key, value in dict(state.get("member_hp", {})).items()}
            enemy_hp = int(state.get("enemy_hp", enemy["max_hp"]))
            target_index = int(state.get("target_index", 0))
            members = sorted(snapshot.get("members", []), key=lambda item: (-int(item["stats"]["initiative"]), str(item["player_id"])))
            battle_seed = str(snapshot.get("random_seed", battle_id))
            actions: list[dict[str, Any]] = []
            sequence = int(session["action_sequence"])
            for member in members:
                player_id = str(member["player_id"])
                if hp.get(player_id, 0) <= 0 or enemy_hp <= 0:
                    continue
                sequence += 1
                roll = battle_roll_bp(f"{battle_seed}:{expected_round}:{sequence}:player")
                hit_bp = hit_chance_bp(attacker_initiative=int(member["stats"]["initiative"]), defender_agility=int(enemy["agility"]))
                damage = int(member["stats"]["attack"]) if roll < hit_bp else 0
                enemy_hp = max(0, enemy_hp - damage)
                actions.append({"sequence_no": sequence, "actor_key": f"member:{player_id}", "strategy_key": "final.basic_attack", "skill_key": "skill.basic_attack", "target_key": "enemy", "hit_roll_bp": roll, "damage": damage})
                if damage:
                    connection.execute("UPDATE final_battle_members SET contribution_damage=contribution_damage+?, updated_at=? WHERE battle_id=? AND player_id=(SELECT id FROM players WHERE player_id=?)", (damage, now_text, battle_id, player_id))
            alive = [member for member in members if hp.get(str(member["player_id"]), 0) > 0]
            if enemy_hp > 0 and alive:
                target_index %= len(alive)
                target = alive[target_index]
                target_id = str(target["player_id"])
                sequence += 1
                roll = battle_roll_bp(f"{battle_seed}:{expected_round}:{sequence}:enemy")
                hit_bp = hit_chance_bp(attacker_initiative=int(enemy["initiative"]), defender_agility=int(target["stats"]["agility"]))
                damage = int(enemy["attack"]) if roll < hit_bp else 0
                hp[target_id] = max(0, hp[target_id] - damage)
                actions.append({"sequence_no": sequence, "actor_key": "enemy", "strategy_key": "enemy.ascension_guardian", "skill_key": str(enemy["skill_key"]), "target_key": f"member:{target_id}", "hit_roll_bp": roll, "damage": damage})
                target_index += 1
            phase = "temptation" if enemy_hp * 2 <= int(enemy["max_hp"]) and not state.get("temptation_choice") else "guardian"
            for action in actions:
                state_after = {"member_hp": hp, "enemy_hp": enemy_hp, "phase": phase}
                connection.execute(
                    "INSERT INTO final_battle_actions(action_id, battle_id, sequence_no, round_no, actor_key, strategy_key, skill_key, target_key, hit_roll_bp, damage, state_json, operation_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (uuid4().hex, battle_id, action["sequence_no"], expected_round, action["actor_key"], action["strategy_key"], action["skill_key"], action["target_key"], action["hit_roll_bp"], action["damage"], json.dumps(state_after, ensure_ascii=False, sort_keys=True), f"{operation_id}:{action['sequence_no']}", now_text),
                )
            outcome = "won" if enemy_hp <= 0 else ("lost" if not any(value > 0 for value in hp.values()) else None)
            status = outcome or "running"
            if expected_round >= FINAL_BATTLE_MAX_TURNS and status == "running":
                status, outcome = "expired", "expired"
            state.update({"round_no": expected_round, "member_hp": hp, "enemy_hp": enemy_hp, "target_index": target_index, "phase": phase})
            connection.execute(
                "UPDATE final_battle_sessions SET status=?, round_no=?, action_sequence=?, state_json=?, result_json=?, updated_at=? WHERE battle_id=?",
                (status, expected_round, sequence, json.dumps(state, ensure_ascii=False, sort_keys=True), json.dumps({"outcome": outcome, "reason": "final_battle_ended"} if outcome else {}, ensure_ascii=False, sort_keys=True), now_text, battle_id),
            )
            session_actor = connection.execute("SELECT initiator_id FROM final_battle_sessions WHERE battle_id=?", (battle_id,)).fetchone()
            payload = {"battle_id": battle_id, "status": status, "outcome": outcome, "round_no": expected_round, "action_count": len(actions), "phase": phase}
            self._record_final_battle_operation(connection, operation_id, operation_name, int(session_actor["initiator_id"]), request_hash, payload, now_text)
            return payload

    def _choose_final_battle_once(
        self,
        platform: str,
        platform_user_id: str,
        battle_id: str | None,
        choice: str,
        operation_id: str,
    ) -> dict[str, Any]:
        operation_name = "ascension.final_battle.choice"
        request_hash = self._request_hash(operation_name, {"platform": platform, "platform_user_id": platform_user_id, "battle_id": battle_id, "choice": choice})
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._final_battle_operation(connection, operation_id, operation_name, request_hash)
            if existing is not None:
                return existing
            actor = self._require_player(connection, platform, platform_user_id, writable=False)
            session = self._select_final_battle_for_actor(connection, int(actor["id"]), battle_id)
            if int(session["initiator_id"]) != int(actor["id"]):
                raise FinalBattlePermissionError("only the initiator can choose at the temptation phase")
            if str(session["status"]) != "running":
                raise FinalBattleNotReadyError("final battle is not running")
            state = self._json_object(session["state_json"], {})
            if str(state.get("phase", "guardian")) != "temptation":
                raise FinalBattleNotReadyError("guardian temptation is not active")
            if choice not in {"continue", "remain"}:
                raise FinalBattleNotReadyError("unsupported final battle choice")
            if choice == "remain":
                ending_operation_id = f"ascension.final_battle.ending:{session['battle_id']}"
                ending = self._choose_ending_in_transaction(
                    connection,
                    platform=platform,
                    platform_user_id=platform_user_id,
                    ending_key="remain_in_world",
                    operation_id=ending_operation_id,
                    now_text=now_text,
                    allow_final_battle=True,
                )
                state["temptation_choice"] = "remain"
                state["phase"] = "ended"
                status = "won"
                outcome = "remained"
            else:
                state["temptation_choice"] = "continue"
                state["phase"] = "guardian"
                status = "running"
                outcome = None
            connection.execute(
                "UPDATE final_battle_sessions SET status=?, state_json=?, result_json=?, updated_at=? WHERE battle_id=? AND status='running'",
                (status, json.dumps(state, ensure_ascii=False, sort_keys=True), json.dumps({"outcome": outcome, "ending_key": "remain_in_world"} if outcome else {}, ensure_ascii=False, sort_keys=True), now_text, session["battle_id"]),
            )
            payload = {"battle_id": str(session["battle_id"]), "status": status, "choice": choice, "outcome": outcome, "round_no": int(session["round_no"]), "phase": str(state["phase"]), "ending_status": ending.status if choice == "remain" else None}
            self._record_final_battle_operation(connection, operation_id, operation_name, int(actor["id"]), request_hash, payload, now_text)
            return payload

    def _resolve_final_battle_once(
        self, platform: str, platform_user_id: str, battle_id: str, operation_id: str
    ) -> FinalBattleResolutionRecord:
        operation_name = "ascension.final_battle.resolve"
        request_hash = self._request_hash(operation_name, {"platform": platform, "platform_user_id": platform_user_id, "battle_id": battle_id})
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._final_battle_operation(connection, operation_id, operation_name, request_hash)
            if existing is not None:
                return self._final_battle_resolution_from_payload(existing, replay=True)
            actor = self._require_player(connection, platform, platform_user_id, writable=False)
            session = connection.execute("SELECT * FROM final_battle_sessions WHERE battle_id=?", (battle_id,)).fetchone()
            if session is None:
                raise FinalBattleNotFoundError("final battle does not exist")
            if int(session["initiator_id"]) != int(actor["id"]):
                raise FinalBattlePermissionError("only the initiator settles the final battle")
            if str(session["status"]) == "settled":
                result = self._json_object(session["result_json"], {})
                payload = {"battle_id": battle_id, "status": "settled", "outcome": result.get("outcome", "expired"), "round_no": int(session["round_no"]), "debt_delta": int(result.get("debt_delta", 0)), "cooldown_until": result.get("cooldown_until"), "rewards": result.get("rewards", {})}
                self._record_final_battle_operation(connection, operation_id, operation_name, int(actor["id"]), request_hash, payload, now_text)
                return self._final_battle_resolution_from_payload(payload, replay=True)
            if str(session["status"]) not in {"won", "lost", "expired"}:
                raise FinalBattleNotReadyError("final battle has not ended")
            result = self._json_object(session["result_json"], {})
            outcome = str(result.get("outcome", session["status"]))
            success = outcome == "won"
            failed = outcome in {"lost", "expired"}
            members = connection.execute(
                "SELECT m.id AS member_row_id, m.player_id AS database_player_id, m.role, "
                "m.contribution_damage, p.player_id AS stable_player_id "
                "FROM final_battle_members m JOIN players p ON p.id=m.player_id "
                "WHERE m.battle_id=? ORDER BY m.id",
                (battle_id,),
            ).fetchall()
            reward_map: dict[str, dict[str, int]] = {}
            debt_delta = 25 if failed else 0
            cooldown_until = serialize_datetime(now + timedelta(seconds=FINAL_BATTLE_COOLDOWN_SECONDS)) if failed else None
            for member in members:
                player_id = str(member["stable_player_id"])
                reward: dict[str, int] = {}
                if (success or outcome == "remained") and str(member["role"]) == "helper":
                    merit = min(FINAL_BATTLE_ASSIST_MERIT_CAP, int(member["contribution_damage"]) // FINAL_BATTLE_ASSIST_MERIT_PER_DAMAGE)
                    if merit:
                        reward["world_merit"] = merit
                        connection.execute("UPDATE players SET world_merit=world_merit+?, updated_at=? WHERE id=?", (merit, now_text, member["database_player_id"]))
                reward_map[player_id] = reward
                connection.execute(
                    "INSERT INTO final_battle_rewards(battle_id, player_id, reward_json, status, operation_id, claimed_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (battle_id, member["database_player_id"], json.dumps(reward, ensure_ascii=False, sort_keys=True), "claimed" if reward else "none", f"{operation_id}:{player_id}", now_text),
                )
                connection.execute("UPDATE final_battle_members SET asset_lock_status='released', reward_json=?, updated_at=? WHERE id=?", (json.dumps(reward, ensure_ascii=False, sort_keys=True), now_text, member["member_row_id"]))
            inventory = self._json_object(actor["inventory_json"], {})
            if success:
                connection.execute("UPDATE players SET endgame_status=?, location_key='ascension.heaven_path', inventory_json=?, updated_at=? WHERE id=?", (ASCENSION_READY_STATUS, json.dumps(inventory, ensure_ascii=False, sort_keys=True), now_text, actor["id"]))
            elif failed:
                inventory[ASCENSION_CERTIFICATE_KEY] = int(inventory.get(ASCENSION_CERTIFICATE_KEY, 0)) + 1
                connection.execute("UPDATE players SET tribulation_debt=tribulation_debt+?, inventory_json=?, updated_at=? WHERE id=?", (debt_delta, json.dumps(inventory, ensure_ascii=False, sort_keys=True), now_text, actor["id"]))
            result.update({"outcome": outcome, "reason": result.get("reason", "final_battle_ended"), "debt_delta": debt_delta, "cooldown_until": cooldown_until, "rewards": reward_map, "settled_at": now_text})
            connection.execute("UPDATE final_battle_sessions SET status='settled', cooldown_until=?, result_json=?, updated_at=? WHERE battle_id=?", (cooldown_until, json.dumps(result, ensure_ascii=False, sort_keys=True), now_text, battle_id))
            payload = {"battle_id": battle_id, "status": "settled", "outcome": outcome, "round_no": int(session["round_no"]), "debt_delta": debt_delta, "cooldown_until": cooldown_until, "rewards": reward_map}
            self._record_final_battle_operation(connection, operation_id, operation_name, int(actor["id"]), request_hash, payload, now_text)
            return self._final_battle_resolution_from_payload(payload)

    def _cancel_final_battle_once(
        self, platform: str, platform_user_id: str, battle_id: str | None, operation_id: str
    ) -> FinalBattleSessionRecord:
        operation_name = "ascension.final_battle.cancel"
        request_hash = self._request_hash(operation_name, {"platform": platform, "platform_user_id": platform_user_id, "battle_id": battle_id})
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._final_battle_operation(connection, operation_id, operation_name, request_hash)
            if existing is not None:
                return self._final_battle_session_from_payload(existing, replay=True)
            actor = self._require_player(connection, platform, platform_user_id, writable=False)
            session = self._select_final_battle_for_actor(connection, int(actor["id"]), battle_id)
            if str(session["status"]) == "lobby" and now_text >= str(session["expires_at"]):
                self._expire_final_battle_lobby(connection, session, now_text)
                return self._final_battle_session_from_payload(
                    {"battle_id": str(session["battle_id"]), "status": "expired", "member_player_ids": [], "expires_at": str(session["expires_at"])},
                )
            if int(session["initiator_id"]) != int(actor["id"]):
                raise FinalBattlePermissionError("only the initiator can cancel a final battle")
            if str(session["status"]) != "lobby":
                raise FinalBattleNotReadyError("only a lobby can be cancelled")
            snapshot = self._json_object(session["snapshot_json"], {})
            initiator = connection.execute("SELECT * FROM players WHERE id=?", (actor["id"],)).fetchone()
            inventory = self._json_object(initiator["inventory_json"], {})
            escrow = snapshot.get("certificate_escrow", {})
            item_key = str(escrow.get("item_key", ASCENSION_CERTIFICATE_KEY))
            inventory[item_key] = int(inventory.get(item_key, 0)) + int(escrow.get("quantity", 1))
            connection.execute("UPDATE players SET inventory_json=?, updated_at=? WHERE id=?", (json.dumps(inventory, ensure_ascii=False, sort_keys=True), now_text, actor["id"]))
            connection.execute("UPDATE final_battle_members SET asset_lock_status='released', updated_at=? WHERE battle_id=?", (now_text, session["battle_id"]))
            connection.execute("UPDATE final_battle_sessions SET status='expired', result_json=?, updated_at=? WHERE battle_id=?", (json.dumps({"outcome": "cancelled", "reason": "initiator_cancelled", "settled_at": now_text}, ensure_ascii=False, sort_keys=True), now_text, session["battle_id"]))
            payload = {"battle_id": str(session["battle_id"]), "status": "expired", "member_player_ids": [str(row[0]) for row in connection.execute("SELECT p.player_id FROM final_battle_members m JOIN players p ON p.id=m.player_id WHERE m.battle_id=? ORDER BY m.id", (session["battle_id"],)).fetchall()], "expires_at": str(session["expires_at"])}
            self._record_final_battle_operation(connection, operation_id, operation_name, int(actor["id"]), request_hash, payload, now_text)
            return self._final_battle_session_from_payload(payload)

    def _final_battle_access_once(self, platform: str, platform_user_id: str, battle_id: str | None) -> dict[str, Any]:
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            actor = self._require_player(connection, platform, platform_user_id, writable=False)
            session = self._select_final_battle_for_actor(connection, int(actor["id"]), battle_id)
            if str(session["status"]) == "lobby" and now_text >= str(session["expires_at"]):
                connection.execute("BEGIN IMMEDIATE")
                self._expire_final_battle_lobby(connection, session, now_text)
                session = connection.execute("SELECT * FROM final_battle_sessions WHERE battle_id=?", (session["battle_id"],)).fetchone()
            access = dict(session)
            access["result"] = self._json_object(session["result_json"], {})
            access["actor_is_initiator"] = int(session["initiator_id"]) == int(actor["id"])
            return access

    def _replay_final_battle_once(
        self, platform: str, platform_user_id: str, battle_id: str | None
    ) -> FinalBattleReplayRecord:
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            actor = self._require_player(connection, platform, platform_user_id, writable=False)
            session = self._select_final_battle_for_actor(connection, int(actor["id"]), battle_id)
            if str(session["status"]) == "lobby" and now_text >= str(session["expires_at"]):
                connection.execute("BEGIN IMMEDIATE")
                self._expire_final_battle_lobby(connection, session, now_text)
                session = connection.execute("SELECT * FROM final_battle_sessions WHERE battle_id=?", (session["battle_id"],)).fetchone()
            return FinalBattleReplayRecord(
                str(session["battle_id"]),
                str(session["status"]),
                self._json_object(session["snapshot_json"], {}),
                self._json_object(session["state_json"], {}),
                self._json_object(session["result_json"], {}),
                tuple(dict(row) for row in connection.execute("SELECT * FROM final_battle_actions WHERE battle_id=? ORDER BY sequence_no", (session["battle_id"],)).fetchall()),
            )

    def _expire_final_battle_lobby(self, connection: sqlite3.Connection, session: sqlite3.Row, now_text: str) -> None:
        """Release the initiator's escrow exactly once when a lobby times out."""

        if str(session["status"]) != "lobby":
            return
        snapshot = self._json_object(session["snapshot_json"], {})
        escrow = snapshot.get("certificate_escrow", {})
        initiator = connection.execute("SELECT * FROM players WHERE id=?", (session["initiator_id"],)).fetchone()
        if initiator is None:
            raise FinalBattleNotFoundError("initiator disappeared")
        inventory = self._json_object(initiator["inventory_json"], {})
        item_key = str(escrow.get("item_key", ASCENSION_CERTIFICATE_KEY))
        inventory[item_key] = int(inventory.get(item_key, 0)) + int(escrow.get("quantity", 1))
        connection.execute(
            "UPDATE players SET inventory_json=?, updated_at=? WHERE id=?",
            (json.dumps(inventory, ensure_ascii=False, sort_keys=True), now_text, initiator["id"]),
        )
        connection.execute("UPDATE final_battle_members SET asset_lock_status='released', updated_at=? WHERE battle_id=?", (now_text, session["battle_id"]))
        connection.execute(
            "UPDATE final_battle_sessions SET status='expired', result_json=?, updated_at=? WHERE battle_id=? AND status='lobby'",
            (json.dumps({"outcome": "expired", "reason": "lobby_timeout", "settled_at": now_text}, ensure_ascii=False, sort_keys=True), now_text, session["battle_id"]),
        )

    def _require_final_battle_candidate(self, connection: sqlite3.Connection, player: sqlite3.Row, now_text: str) -> None:
        if str(player["realm_key"]) != "tribulation" or int(player["realm_layer"]) != 10:
            raise FinalBattleRequirementError("initiator must be at tribulation L10")
        if str(player["endgame_status"] or "none") != "tribulation" or str(player["location_key"]) != FINAL_BATTLE_LOCATION:
            raise FinalBattleRequirementError("initiator must be on the sky terrace tribulation route")
        trials = {str(row["trial_key"]) for row in connection.execute("SELECT trial_key FROM tribulation_trial_sessions WHERE player_id=? AND status='succeeded'", (player["id"],)).fetchall()}
        if not set(TRIAL_ORDER).issubset(trials):
            raise FinalBattleRequirementError("all three tribulation trials must be complete")
        if int(player["dao_fruit_progress"]) < FINAL_BATTLE_MIN_PROGRESS or int(player["ascension_merit"]) < FINAL_BATTLE_MIN_MERIT or int(player["tribulation_debt"]) >= 100:
            raise FinalBattleRequirementError("final battle progression requirements are not met")
        inventory = self._json_object(player["inventory_json"], {})
        if int(inventory.get(ASCENSION_CERTIFICATE_KEY, 0)) < 1:
            raise FinalBattleRequirementError("ascension certificate is missing")
        prior = connection.execute("SELECT cooldown_until FROM final_battle_sessions WHERE initiator_id=? AND cooldown_until IS NOT NULL ORDER BY id DESC LIMIT 1", (player["id"],)).fetchone()
        if prior is not None and str(prior["cooldown_until"]) > now_text:
            raise FinalBattleCooldownError("final battle retry cooldown is active")

    def _final_battle_member_snapshot(self, connection: sqlite3.Connection, player: sqlite3.Row, *, role: str) -> dict[str, Any]:
        equipment = self._battle_equipment_snapshot(connection, int(player["id"]))
        qualification = self._json_object(player["qualification_json"], {})
        stats = stat_snapshot(qualification, realm_layer=int(player["realm_layer"]), equipment=equipment)
        return {
            "player_id": str(player["player_id"]),
            "database_id": int(player["id"]),
            "role": role,
            "realm_key": str(player["realm_key"]),
            "realm_layer": int(player["realm_layer"]),
            "path_key": player["path_key"],
            "qualification": qualification,
            "stats": stats,
            "equipment": list(equipment),
        }

    @staticmethod
    def _insert_final_battle_member(connection: sqlite3.Connection, battle_id: str, player: sqlite3.Row, snapshot: dict[str, Any], now_text: str) -> None:
        connection.execute(
            "INSERT INTO final_battle_members(battle_id, player_id, role, asset_lock_status, snapshot_json, created_at, updated_at) VALUES (?, ?, ?, 'locked', ?, ?, ?)",
            (battle_id, player["id"], snapshot["role"], json.dumps(snapshot, ensure_ascii=False, sort_keys=True), now_text, now_text),
        )

    @staticmethod
    def _select_final_battle_for_actor(connection: sqlite3.Connection, player_id: int, battle_id: str | None) -> sqlite3.Row:
        if battle_id:
            row = connection.execute("SELECT b.* FROM final_battle_sessions b JOIN final_battle_members m ON m.battle_id=b.battle_id WHERE b.battle_id=? AND m.player_id=?", (battle_id, player_id)).fetchone()
        else:
            row = connection.execute("SELECT b.* FROM final_battle_sessions b JOIN final_battle_members m ON m.battle_id=b.battle_id WHERE m.player_id=? ORDER BY b.id DESC LIMIT 1", (player_id,)).fetchone()
        if row is None:
            raise FinalBattleNotFoundError("final battle does not exist")
        return row

    @staticmethod
    def _final_battle_operation(connection: sqlite3.Connection, operation_id: str, operation_name: str, request_hash: str) -> dict[str, Any] | None:
        row = connection.execute("SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id=?", (operation_id,)).fetchone()
        if row is None:
            return None
        if str(row["operation_name"]) != operation_name or str(row["request_hash"]) != request_hash:
            raise OperationConflictError("operation input differs from its original request")
        return json.loads(row["result_json"])

    @staticmethod
    def _record_final_battle_operation(connection: sqlite3.Connection, operation_id: str, operation_name: str, player_id: int, request_hash: str, payload: dict[str, Any], now_text: str) -> None:
        connection.execute("INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)", (operation_id, operation_name, player_id, request_hash, json.dumps(payload, ensure_ascii=False, sort_keys=True), now_text))

    @staticmethod
    def _final_battle_session_from_payload(payload: dict[str, Any], replay: bool = False) -> FinalBattleSessionRecord:
        return FinalBattleSessionRecord(str(payload["battle_id"]), str(payload["status"]), tuple(str(item) for item in payload.get("member_player_ids", [])), str(payload.get("expires_at", "")), replay)

    @staticmethod
    def _final_battle_resolution_from_payload(payload: dict[str, Any], replay: bool = False) -> FinalBattleResolutionRecord:
        return FinalBattleResolutionRecord(str(payload["battle_id"]), str(payload["status"]), str(payload["outcome"]), int(payload["round_no"]), int(payload.get("debt_delta", 0)), payload.get("cooldown_until"), {str(player): {str(key): int(value) for key, value in dict(reward).items()} for player, reward in dict(payload.get("rewards", {})).items()}, replay)


__all__ = ["FINAL_BATTLE_RULE_VERSION", "FinalBattleRepositoryMixin"]
