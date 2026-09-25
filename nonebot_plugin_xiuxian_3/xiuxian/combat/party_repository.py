"""Persistence for explicit multi-member automatic PVE sessions.

Party battles intentionally use their own tables and state machine. The
single-player ``battle_sessions`` contract is not widened to carry implicit
participants.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from ...contracts import serialize_datetime
from ..persistence.errors import (
    OperationConflictError,
    PartyBattleBusyError,
    PartyBattleNotFoundError,
    PartyBattleNotReadyError,
    PartyBattlePermissionError,
    PartyBattleRequirementError,
    BoundaryRealmRequirementError,
    BoundaryRealmResourceError,
    CrossRealmPartyRequirementError,
    FactionReputationInsufficientError,
    PollutionTooHighError,
    PartyNotFoundError,
    SoulExhaustionActiveError,
    SoulPowerInsufficientError,
)
from .party_models import PartyBattleReplayRecord, PartyBattleResolutionRecord, PartyBattleStartRecord
from .party_rules import (
    PARTY_BATTLE_CONTENT_VERSION,
    PARTY_BATTLE_MAX_TURNS,
    PARTY_BATTLE_REWARD,
    PARTY_BATTLE_RULE_VERSION,
    PARTY_BATTLE_TYPE,
    BOUNDARY_REALM_LOCATION,
    BOUNDARY_REALM_REWARD,
    BOUNDARY_REALM_STAMINA_COST,
    BOUNDARY_REALM_TICKET,
    BOUNDARY_REALM_TICKET_COST,
    BEAST_REALM_LOCATION,
    BEAST_REALM_REWARD,
    BEAST_REALM_STAMINA_COST,
    DEMON_REALM_LOCATION,
    DEMON_REALM_REWARD,
    DEMON_REALM_STAMINA_COST,
    party_enemy_for_location,
)
from .rules import TURN_TIMEOUT_SECONDS, battle_roll_bp, hit_chance_bp, player_stat_snapshot
from ..social.party_rules import (
    party_definition_for,
    PARTY_TYPE_BOUNDARY_REALM,
    PARTY_TYPE_PARTY_BOUNDARY,
    PARTY_TYPE_DEMON_REALM,
    PARTY_TYPE_BEAST_REALM,
)


class PartyCombatRepositoryMixin:
    """Run a server-authoritative battle for the already-confirmed party."""

    async def start_party_battle(
        self,
        *,
        platform: str,
        platform_user_id: str,
        party_id: str | None,
        operation_id: str,
    ) -> PartyBattleStartRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._retry_sync,
                self._start_party_battle_once,
                platform,
                platform_user_id,
                party_id,
                operation_id,
            )

    async def settle_party_battle(
        self,
        *,
        platform: str,
        platform_user_id: str,
        battle_id: str | None,
        operation_id: str,
    ) -> PartyBattleResolutionRecord:
        await self.initialize()
        selected = await asyncio.to_thread(
            self._party_battle_access_once,
            platform,
            platform_user_id,
            battle_id,
        )
        current_battle_id = str(selected["battle_id"])
        current_round = int(selected["round_no"])
        status = str(selected["status"])
        for expected_round in range(current_round + 1, PARTY_BATTLE_MAX_TURNS + 1):
            if status not in {"created", "running"}:
                break
            turn = await self.run_party_battle_turn(
                battle_id=current_battle_id,
                expected_round=expected_round,
            )
            status = str(turn["status"])
        if status in {"created", "running"}:
            raise PartyBattleNotReadyError("party battle did not reach a terminal result")
        return await self.resolve_party_battle(
            platform=platform,
            platform_user_id=platform_user_id,
            battle_id=current_battle_id,
            operation_id=f"{operation_id}:resolve",
        )

    async def run_party_battle_turn(self, *, battle_id: str, expected_round: int) -> dict[str, Any]:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._retry_sync,
                self._run_party_battle_turn_once,
                battle_id,
                expected_round,
            )

    async def resolve_party_battle(
        self,
        *,
        platform: str,
        platform_user_id: str,
        battle_id: str,
        operation_id: str,
    ) -> PartyBattleResolutionRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._retry_sync,
                self._resolve_party_battle_once,
                platform,
                platform_user_id,
                battle_id,
                operation_id,
            )

    async def replay_party_battle(
        self,
        *,
        platform: str,
        platform_user_id: str,
        battle_id: str | None = None,
    ) -> PartyBattleReplayRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._replay_party_battle_once,
                platform,
                platform_user_id,
                battle_id,
            )

    def _start_party_battle_once(
        self,
        platform: str,
        platform_user_id: str,
        party_id: str | None,
        operation_id: str,
    ) -> PartyBattleStartRecord:
        operation_name = "battle.party.start"
        request_hash = self._request_hash(
            operation_name,
            {"platform": platform, "platform_user_id": platform_user_id, "party_id": party_id},
        )
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._party_battle_operation(connection, operation_id, operation_name, request_hash)
            if existing is not None:
                return self._party_battle_start_from_payload(existing, replay=True)
            leader = self._require_player(connection, platform, platform_user_id)
            membership = connection.execute(
                "SELECT * FROM party_members WHERE player_id = ? AND status = 'active' ORDER BY id DESC LIMIT 1",
                (leader["id"],),
            ).fetchone()
            if membership is None or str(membership["role"]) != "leader":
                raise PartyBattlePermissionError("only the party leader can start a party battle")
            resolved_party_id = str(party_id or membership["party_id"])
            if resolved_party_id != str(membership["party_id"]):
                raise PartyBattlePermissionError("leader is not a member of the requested party")
            party = connection.execute("SELECT * FROM parties WHERE party_id = ?", (resolved_party_id,)).fetchone()
            if party is None:
                raise PartyNotFoundError("party does not exist")
            party_type = str(party["party_type"])
            if party_type not in {
                "exploration_pair",
                PARTY_TYPE_BOUNDARY_REALM,
                PARTY_TYPE_PARTY_BOUNDARY,
                PARTY_TYPE_DEMON_REALM,
                PARTY_TYPE_BEAST_REALM,
            }:
                raise PartyBattleRequirementError("this party type cannot start party PVE")
            if str(party["status"]) != "ready":
                raise PartyBattleRequirementError("party is not ready")
            if party["current_session_id"]:
                raise PartyBattleBusyError("party already has a battle")
            members = connection.execute(
                "SELECT m.id AS membership_id, m.player_id AS database_player_id, m.role AS member_role, "
                "m.confirmed_at AS member_confirmed_at, p.player_id AS stable_player_id, "
                "p.platform_user_id, p.path_key, p.qualification_json, p.max_hp, p.initiative, "
                "p.realm_key, p.realm_layer, p.location_key, p.status AS player_status, p.endgame_status, "
                "p.stamina, p.inventory_json, p.pollution, p.bloodline_stability, p.cross_realm_penalty_bp, "
                "p.faction_reputation_json, p.intro_json, p.soul_power, p.soul_power_max, p.soul_fatigue_until "
                "FROM party_members m JOIN players p ON p.id = m.player_id "
                "WHERE m.party_id = ? AND m.status = 'active' ORDER BY m.id",
                (resolved_party_id,),
            ).fetchall()
            definition = party_definition_for(party_type)
            if not (definition.min_members <= len(members) <= definition.max_members) or any(not row["member_confirmed_at"] for row in members):
                raise PartyBattleRequirementError("all party members must confirm")
            try:
                enemy = party_enemy_for_location(str(party["location_key"]))
            except ValueError as exc:
                raise PartyBattleRequirementError("party PVE is not available at this location") from exc
            snapshots: list[dict[str, Any]] = []
            boundary_party = party_type in {PARTY_TYPE_BOUNDARY_REALM, PARTY_TYPE_PARTY_BOUNDARY}
            demon_party = party_type == PARTY_TYPE_DEMON_REALM
            beast_party = party_type == PARTY_TYPE_BEAST_REALM
            leader_ticket_inventory: dict[str, int] | None = None
            for row in members:
                if str(row["location_key"]) != str(party["location_key"]):
                    if boundary_party:
                        raise BoundaryRealmRequirementError("party members must share the frozen location")
                    raise PartyBattleRequirementError("party members must share the frozen location")
                if not self._meets_realm_values(
                    str(row["realm_key"]), int(row["realm_layer"]), enemy.required_realm, enemy.required_layer
                ):
                    if boundary_party:
                        raise BoundaryRealmRequirementError("a party member does not meet the encounter realm")
                    raise PartyBattleRequirementError("a party member does not meet the encounter realm")
                if boundary_party and not self._boundary_mainline_ready(connection, row):
                    raise BoundaryRealmRequirementError("three-realms mainline evidence is missing")
                if demon_party and not self._intro_flag(row, "access.demon.fallen_ruins"):
                    raise CrossRealmPartyRequirementError("demon fallen ruins access is missing")
                if demon_party and int(row["pollution"]) >= 80:
                    raise PollutionTooHighError("pollution is too high for the demon dungeon")
                if beast_party and self._faction_reputation(row, "beast") < 200:
                    raise FactionReputationInsufficientError("beast reputation is insufficient")
                if boundary_party and int(row["stamina"]) < BOUNDARY_REALM_STAMINA_COST:
                    raise BoundaryRealmResourceError("a party member lacks boundary-realm stamina")
                if demon_party and int(row["stamina"]) < DEMON_REALM_STAMINA_COST:
                    raise CrossRealmPartyRequirementError("a party member lacks demon-dungeon stamina")
                if beast_party and int(row["stamina"]) < BEAST_REALM_STAMINA_COST:
                    raise CrossRealmPartyRequirementError("a party member lacks beast-dungeon stamina")
                if boundary_party or demon_party or beast_party:
                    fatigue_until = row["soul_fatigue_until"]
                    if fatigue_until:
                        try:
                            if datetime.fromisoformat(str(fatigue_until)) > now:
                                raise SoulExhaustionActiveError("soul exhaustion is active")
                        except ValueError:
                            pass
                    if int(row["soul_power"]) <= 0:
                        raise SoulPowerInsufficientError("soul power is insufficient")
                if self._has_active_long_action(connection, int(row["database_player_id"])):
                    raise PartyBattleBusyError("a party member has another active action")
                locked = connection.execute(
                    "SELECT 1 FROM party_battle_members WHERE player_id = ? AND asset_lock_status = 'locked' LIMIT 1",
                    (row["database_player_id"],),
                ).fetchone()
                if locked is not None:
                    raise PartyBattleBusyError("a party member has locked battle assets")
                equipment = self._battle_equipment_snapshot(connection, int(row["database_player_id"]))
                skills = self._battle_skill_snapshot(
                    connection,
                    int(row["database_player_id"]),
                    str(row["path_key"] or ""),
                )
                qualification = self._json_object(row["qualification_json"], {})
                inventory = self._json_object(row["inventory_json"], {})
                if boundary_party and row["database_player_id"] == leader["id"]:
                    leader_ticket_inventory = inventory
                stats = player_stat_snapshot(
                    qualification,
                    max_hp=int(row["max_hp"]),
                    initiative=int(row["initiative"]),
                    equipment=equipment,
                )
                cross_realm_snapshot = {
                    "pollution": int(row["pollution"]),
                    "bloodline_stability": int(row["bloodline_stability"]),
                    "cross_realm_penalty_bp": int(row["cross_realm_penalty_bp"]),
                    "faction_reputation": self._json_object(row["faction_reputation_json"], {}),
                    "alliance_key": self._alliance_key_from_row(row),
                    "content_version": str(party["content_version"]),
                    "rule_version": str(party["rule_version"]),
                }
                snapshots.append(
                    {
                        "player_id": str(row["stable_player_id"]),
                        "database_id": int(row["database_player_id"]),
                        "role": str(row["member_role"]),
                        "realm_key": str(row["realm_key"]),
                        "realm_layer": int(row["realm_layer"]),
                        "path_key": row["path_key"],
                        "qualification": qualification,
                        "stats": stats,
                        "equipment": list(equipment),
                        "skills": skills,
                        "soul_power": int(row["soul_power"]),
                        "cross_realm": cross_realm_snapshot,
                        "pollution": cross_realm_snapshot["pollution"],
                        "bloodline_stability": cross_realm_snapshot["bloodline_stability"],
                        "cross_realm_penalty_bp": cross_realm_snapshot["cross_realm_penalty_bp"],
                        "alliance_key": cross_realm_snapshot["alliance_key"],
                    }
                )
            if boundary_party:
                if str(party["location_key"]) != BOUNDARY_REALM_LOCATION:
                    raise BoundaryRealmRequirementError("boundary party must use cave.boundary_realm")
                if leader_ticket_inventory is None or int(leader_ticket_inventory.get(BOUNDARY_REALM_TICKET, 0)) < BOUNDARY_REALM_TICKET_COST:
                    raise BoundaryRealmResourceError("boundary-realm ticket is insufficient")
                leader_ticket_inventory[BOUNDARY_REALM_TICKET] = int(leader_ticket_inventory[BOUNDARY_REALM_TICKET]) - BOUNDARY_REALM_TICKET_COST
                if leader_ticket_inventory[BOUNDARY_REALM_TICKET] <= 0:
                    leader_ticket_inventory.pop(BOUNDARY_REALM_TICKET, None)
                # All validation above happens before this atomic resource debit.
                for row in members:
                    connection.execute(
                        "UPDATE players SET stamina = stamina - ?, updated_at = ? WHERE id = ?",
                        (BOUNDARY_REALM_STAMINA_COST, now_text, row["database_player_id"]),
                    )
                connection.execute(
                    "UPDATE players SET inventory_json = ?, updated_at = ? WHERE id = ?",
                    (json.dumps(leader_ticket_inventory, ensure_ascii=False, sort_keys=True), now_text, leader["id"]),
                )
            elif demon_party or beast_party:
                expected_location = DEMON_REALM_LOCATION if demon_party else BEAST_REALM_LOCATION
                if str(party["location_key"]) != expected_location:
                    raise CrossRealmPartyRequirementError("cross-realm party location is invalid")
                stamina_cost = DEMON_REALM_STAMINA_COST if demon_party else BEAST_REALM_STAMINA_COST
                for row in members:
                    connection.execute(
                        "UPDATE players SET stamina = stamina - ?, updated_at = ? WHERE id = ? AND stamina >= ?",
                        (stamina_cost, now_text, row["database_player_id"], stamina_cost),
                    )
                    if connection.execute("SELECT changes()").fetchone()[0] != 1:
                        raise CrossRealmPartyRequirementError("party stamina changed during start")
            dungeon_reward = (
                DEMON_REALM_REWARD
                if demon_party
                else BEAST_REALM_REWARD
                if beast_party
                else BOUNDARY_REALM_REWARD
                if boundary_party
                else PARTY_BATTLE_REWARD
            )
            dungeon_content_version = "content-0.3" if (boundary_party or demon_party or beast_party) else PARTY_BATTLE_CONTENT_VERSION
            dungeon_rule_version = "combat-0.3.0" if (boundary_party or demon_party or beast_party) else PARTY_BATTLE_RULE_VERSION
            battle_id = f"party-battle-{uuid4().hex}"
            snapshot = {
                "battle_type": PARTY_BATTLE_TYPE,
                "party_id": resolved_party_id,
                "location_key": str(party["location_key"]),
                "members": snapshots,
                "cross_realm": {member["player_id"]: member["cross_realm"] for member in snapshots},
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
                "reward": dict(dungeon_reward),
                "party_type": party_type,
                "resource_cost": {
                    "stamina": (
                        BOUNDARY_REALM_STAMINA_COST
                        if boundary_party
                        else DEMON_REALM_STAMINA_COST
                        if demon_party
                        else BEAST_REALM_STAMINA_COST
                        if beast_party
                        else 0
                    ),
                    "ticket": {BOUNDARY_REALM_TICKET: BOUNDARY_REALM_TICKET_COST} if boundary_party else {},
                },
                "content_version": dungeon_content_version,
                "rule_version": dungeon_rule_version,
            }
            state = {
                "round_no": 0,
                "member_hp": {member["player_id"]: member["stats"]["max_hp"] for member in snapshots},
                "member_status": {member["player_id"]: "active" for member in snapshots},
                "member_soul_power": {member["player_id"]: int(member.get("soul_power", 0)) for member in snapshots},
                "member_pollution": {
                    member["player_id"]: int(member.get("pollution", 0)) for member in snapshots
                },
                "revive_count": {member["player_id"]: 0 for member in snapshots},
                "contribution": {member["player_id"]: 1 for member in snapshots},
                "enemy_hp": enemy.max_hp,
                "target_index": 0,
            }
            deadline = serialize_datetime(now + timedelta(seconds=TURN_TIMEOUT_SECONDS))
            connection.execute(
                "INSERT INTO party_battle_sessions(battle_id, party_id, start_operation_id, battle_type, enemy_key, location_key, status, round_no, action_sequence, starts_at, turn_deadline, snapshot_json, state_json, content_version, rule_version, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, 'created', 0, 0, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    battle_id,
                    resolved_party_id,
                    operation_id,
                    PARTY_BATTLE_TYPE,
                    enemy.key,
                    str(party["location_key"]),
                    now_text,
                    deadline,
                    json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
                    json.dumps(state, ensure_ascii=False, sort_keys=True),
                    dungeon_content_version,
                    dungeon_rule_version,
                    now_text,
                    now_text,
                ),
            )
            for member in snapshots:
                connection.execute(
                    "INSERT INTO party_battle_members(battle_id, party_id, player_id, role, asset_lock_status, snapshot_json, created_at, updated_at) VALUES (?, ?, ?, ?, 'locked', ?, ?, ?)",
                    (battle_id, resolved_party_id, member["database_id"], member["role"], json.dumps(member, ensure_ascii=False, sort_keys=True), now_text, now_text),
                )
            connection.execute(
                "UPDATE parties SET current_session_id = ?, updated_at = ? WHERE party_id = ? AND current_session_id IS NULL",
                (battle_id, now_text, resolved_party_id),
            )
            payload = {
                "battle_id": battle_id,
                "party_id": resolved_party_id,
                "enemy_key": enemy.key,
                "status": "created",
                "round_no": 0,
                "max_rounds": PARTY_BATTLE_MAX_TURNS,
                "member_player_ids": [member["player_id"] for member in snapshots],
            }
            self._party_battle_record_operation(connection, operation_id, operation_name, int(leader["id"]), request_hash, payload, now_text)
            return self._party_battle_start_from_payload(payload)

    def _party_battle_access_once(self, platform: str, platform_user_id: str, battle_id: str | None) -> sqlite3.Row:
        with self._connect() as connection:
            player = self._require_player(connection, platform, platform_user_id, writable=False)
            if battle_id:
                row = connection.execute(
                    "SELECT b.* FROM party_battle_sessions b JOIN party_battle_members m ON m.battle_id = b.battle_id WHERE b.battle_id = ? AND m.player_id = ?",
                    (battle_id, player["id"]),
                ).fetchone()
            else:
                row = connection.execute(
                    "SELECT b.* FROM party_battle_sessions b JOIN party_battle_members m ON m.battle_id = b.battle_id WHERE m.player_id = ? AND b.status IN ('created', 'running', 'won', 'lost', 'expired') ORDER BY b.id DESC LIMIT 1",
                    (player["id"],),
                ).fetchone()
            if row is None:
                raise PartyBattleNotFoundError("party battle does not exist")
            return row

    def _run_party_battle_turn_once(self, battle_id: str, expected_round: int) -> dict[str, Any]:
        if expected_round < 1 or expected_round > PARTY_BATTLE_MAX_TURNS:
            raise ValueError("party battle round is invalid")
        operation_id = f"party-battle.turn:{battle_id}:{expected_round}"
        operation_name = "battle.party.turn"
        request_hash = self._request_hash(operation_name, {"battle_id": battle_id, "expected_round": expected_round, "rule_version": PARTY_BATTLE_RULE_VERSION})
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._party_battle_operation(connection, operation_id, operation_name, request_hash)
            if existing is not None:
                return existing
            session = connection.execute("SELECT * FROM party_battle_sessions WHERE battle_id = ?", (battle_id,)).fetchone()
            if session is None:
                raise PartyBattleNotFoundError("party battle does not exist")
            if str(session["status"]) not in {"created", "running"}:
                return {"battle_id": battle_id, "status": session["status"], "outcome": self._json_object(session["result_json"], {}).get("outcome"), "round_no": session["round_no"]}
            deadline = session["turn_deadline"]
            if deadline:
                try:
                    deadline_at = datetime.fromisoformat(str(deadline))
                except ValueError:
                    deadline_at = None
                if deadline_at is not None and self._now() >= deadline_at:
                    expired_result = {"outcome": "expired", "reason": "party_battle_timeout"}
                    connection.execute(
                        "UPDATE party_battle_sessions SET status='expired', result_json=?, updated_at=? WHERE battle_id=?",
                        (json.dumps(expired_result, ensure_ascii=False, sort_keys=True), now_text, battle_id),
                    )
                    payload = {"battle_id": battle_id, "status": "expired", "outcome": "expired", "round_no": int(session["round_no"]), "action_count": 0}
                    operation_player = connection.execute(
                        "SELECT player_id FROM party_battle_members WHERE battle_id=? ORDER BY id LIMIT 1", (battle_id,)
                    ).fetchone()
                    if operation_player is None:
                        raise PartyBattleNotFoundError("party battle has no members")
                    self._party_battle_record_operation(connection, operation_id, operation_name, int(operation_player["player_id"]), request_hash, payload, now_text)
                    return payload
            if int(session["round_no"]) != expected_round - 1:
                raise PartyBattleBusyError("party battle round is not next")
            snapshot = self._json_object(session["snapshot_json"], {})
            state = self._json_object(session["state_json"], {})
            enemy = snapshot["enemy"]
            member_hp = {str(key): int(value) for key, value in dict(state.get("member_hp", {})).items()}
            member_status = {
                str(key): str(value)
                for key, value in dict(state.get("member_status", {})).items()
            }
            member_status.update(
                {
                    str(key): ("active" if int(value) > 0 else "downed")
                    for key, value in member_hp.items()
                    if str(key) not in member_status
                }
            )
            member_soul_power = {
                str(key): int(value)
                for key, value in dict(state.get("member_soul_power", {})).items()
            }
            member_soul_power.update(
                {
                    str(member["player_id"]): int(member.get("soul_power", 0))
                    for member in snapshot.get("members", [])
                    if str(member["player_id"]) not in member_soul_power
                }
            )
            member_pollution = {
                str(key): int(value)
                for key, value in dict(state.get("member_pollution", {})).items()
            }
            member_pollution.update(
                {
                    str(member["player_id"]): int(member.get("pollution", 0))
                    for member in snapshot.get("members", [])
                    if str(member["player_id"]) not in member_pollution
                }
            )
            revive_count = {
                str(key): int(value)
                for key, value in dict(state.get("revive_count", {})).items()
            }
            revive_count.update(
                {
                    str(member["player_id"]): 0
                    for member in snapshot.get("members", [])
                    if str(member["player_id"]) not in revive_count
                }
            )
            contribution = {
                str(key): int(value)
                for key, value in dict(state.get("contribution", {})).items()
            }
            contribution.update(
                {
                    str(member["player_id"]): 1
                    for member in snapshot.get("members", [])
                    if str(member["player_id"]) not in contribution
                }
            )
            enemy_hp = int(state.get("enemy_hp", enemy["max_hp"]))
            summon_count = int(state.get("summon_count", 0))
            target_index = int(state.get("target_index", 0))
            actions: list[dict[str, Any]] = []
            sequence = int(session["action_sequence"])
            boundary_party = str(snapshot.get("party_type", "")) in {
                PARTY_TYPE_BOUNDARY_REALM,
                PARTY_TYPE_PARTY_BOUNDARY,
            }
            demon_party = str(snapshot.get("party_type", "")) == PARTY_TYPE_DEMON_REALM
            beast_party = str(snapshot.get("party_type", "")) == PARTY_TYPE_BEAST_REALM
            members = sorted(
                [member for member in snapshot.get("members", []) if member["player_id"] in member_hp],
                key=lambda member: (-int(member["stats"]["initiative"]), str(member["player_id"]),),
            )
            timeline_defenders: set[str] = set()
            for member in members:
                player_id = str(member["player_id"])
                if member_hp[player_id] <= 0 or member_status.get(player_id) == "downed" or enemy_hp <= 0:
                    continue
                sequence += 1
                timeline_defend = boundary_party and expected_round in {5, 10}
                if timeline_defend:
                    timeline_defenders.add(player_id)
                    contribution[player_id] += 2
                    actions.append(
                        {
                            "sequence_no": sequence,
                            "actor_key": f"member:{player_id}",
                            "strategy_key": "party.timeline_defend",
                            "skill_key": "skill.defend",
                            "target_key": f"member:{player_id}",
                            "hit_roll_bp": 0,
                            "damage": 0,
                        }
                    )
                    continue
                if beast_party and summon_count > 0:
                    summon_count -= 1
                    contribution[player_id] += 1
                    actions.append(
                        {
                            "sequence_no": sequence,
                            "actor_key": f"member:{player_id}",
                            "strategy_key": "party.clear_summon",
                            "skill_key": "skill.beast.ancestral_form",
                            "target_key": "enemy.summon",
                            "hit_roll_bp": 10_000,
                            "damage": 0,
                            "summon_remaining": summon_count,
                        }
                    )
                    continue
                selected_skill = self._select_battle_skill(list(member.get("skills", [])))
                roll = battle_roll_bp(f"{session['battle_id']}:{expected_round}:{sequence}:player")
                hit_bp = hit_chance_bp(
                    attacker_initiative=int(member["stats"]["initiative"]),
                    defender_agility=int(enemy["agility"]),
                )
                multiplier = self._skill_damage_multiplier(selected_skill)
                damage = int(member["stats"]["attack"]) * multiplier // 10_000 if roll < hit_bp else 0
                damage = min(enemy_hp, max(0, damage))
                enemy_hp = max(0, enemy_hp - damage)
                contribution[player_id] += damage
                actions.append(
                    {
                        "sequence_no": sequence,
                        "actor_key": f"member:{player_id}",
                        "strategy_key": "party.auto_skill",
                        "skill_key": str(selected_skill.get("skill_key", "skill.basic_attack")),
                        "target_key": "enemy",
                        "hit_roll_bp": roll,
                        "damage": damage,
                    }
                )
            alive = [
                member
                for member in members
                if member_hp[str(member["player_id"])] > 0
                and member_status.get(str(member["player_id"])) != "downed"
            ]
            if enemy_hp > 0 and alive:
                target_index %= len(alive)
                target = alive[target_index]
                target_id = str(target["player_id"])
                sequence += 1
                roll = battle_roll_bp(f"{session['battle_id']}:{expected_round}:{sequence}:enemy")
                hit_bp = hit_chance_bp(attacker_initiative=int(enemy["initiative"]), defender_agility=int(target["stats"]["agility"]))
                damage = int(enemy["attack"]) if roll < hit_bp else 0
                if beast_party and summon_count > 0:
                    damage = damage * 12_000 // 10_000
                if len(timeline_defenders) >= 2 and expected_round in {5, 10}:
                    damage = damage * 8_000 // 10_000
                member_hp[target_id] = max(0, member_hp[target_id] - damage)
                if member_hp[target_id] <= 0:
                    member_status[target_id] = "downed"
                actions.append({"sequence_no": sequence, "actor_key": "enemy", "strategy_key": "enemy.auto", "skill_key": str(enemy["skill_key"]), "target_key": f"member:{target_id}", "hit_roll_bp": roll, "damage": damage})
                target_index += 1
            if demon_party and expected_round % 3 == 0:
                for member in members:
                    player_id = str(member["player_id"])
                    member_pollution[player_id] = min(100, member_pollution.get(player_id, 0) + 8)
                    connection.execute(
                        "UPDATE players SET pollution=MIN(100, pollution+8), updated_at=? WHERE id=?",
                        (now_text, member["database_id"]),
                    )
                sequence += 1
                actions.append(
                    {
                        "sequence_no": sequence,
                        "actor_key": "enemy",
                        "strategy_key": "enemy.abyss_pollution",
                        "skill_key": "skill.demonic.abyss_communion",
                        "target_key": "party",
                        "hit_roll_bp": 0,
                        "damage": 0,
                        "pollution_gain": 8,
                    }
                )
            if beast_party and expected_round % 4 == 0:
                summon_count = 2
                sequence += 1
                actions.append(
                    {
                        "sequence_no": sequence,
                        "actor_key": "enemy",
                        "strategy_key": "enemy.ancestral_summon",
                        "skill_key": "skill.beast.ancestral_form",
                        "target_key": "enemy",
                        "hit_roll_bp": 0,
                        "damage": 0,
                        "summon_count": 2,
                    }
                )
            if boundary_party and expected_round in {5, 10} and len(timeline_defenders) < 2:
                for member in members:
                    player_id = str(member["player_id"])
                    member_soul_power[player_id] = max(0, member_soul_power[player_id] - 10)
                    connection.execute(
                        "UPDATE players SET soul_power=MAX(0, soul_power-10), updated_at=? WHERE id=?",
                        (now_text, member["database_id"]),
                    )
                sequence += 1
                actions.append(
                    {
                        "sequence_no": sequence,
                        "actor_key": "system",
                        "strategy_key": "enemy.timeline_impact",
                        "skill_key": "skill.soul.suppression",
                        "target_key": "party",
                        "hit_roll_bp": 0,
                        "damage": 0,
                        "soul_power_loss": 10,
                    }
                )
            # Revive deterministically after the enemy action; each downed
            # member can be restored once and the debit is guarded in SQL.
            if boundary_party or demon_party or beast_party:
                alive = [
                    member
                    for member in members
                    if member_hp[str(member["player_id"])] > 0
                    and member_status.get(str(member["player_id"])) != "downed"
                ]
                for downed in sorted(members, key=lambda item: str(item["player_id"])):
                    downed_id = str(downed["player_id"])
                    if member_status.get(downed_id) != "downed" or revive_count.get(downed_id, 0) >= 1 or not alive:
                        continue
                    reviver = next(
                        (
                            candidate
                            for candidate in alive
                            if member_soul_power.get(str(candidate["player_id"]), 0) >= 25
                        ),
                        None,
                    )
                    if reviver is None:
                        continue
                    reviver_id = str(reviver["player_id"])
                    debited = connection.execute(
                        "UPDATE players SET soul_power=soul_power-25, updated_at=? WHERE id=? AND soul_power>=25",
                        (now_text, reviver["database_id"]),
                    ).rowcount
                    if debited != 1:
                        continue
                    member_soul_power[reviver_id] = max(0, member_soul_power.get(reviver_id, 0) - 25)
                    member_hp[downed_id] = max(1, int(downed["stats"]["max_hp"]) // 2)
                    member_status[downed_id] = "active"
                    revive_count[downed_id] = 1
                    contribution[reviver_id] += 25
                    sequence += 1
                    actions.append(
                        {
                            "sequence_no": sequence,
                            "actor_key": f"member:{reviver_id}",
                            "strategy_key": "party.revive",
                            "skill_key": "skill.soul.revival",
                            "target_key": f"member:{downed_id}",
                            "hit_roll_bp": 10_000,
                            "damage": 0,
                            "soul_power_cost": 25,
                        }
                    )
                    alive.append(downed)
            for action in actions:
                state_after = {
                    "member_hp": member_hp,
                    "member_status": member_status,
                    "member_soul_power": member_soul_power,
                    "member_pollution": member_pollution,
                    "revive_count": revive_count,
                    "contribution": contribution,
                    "enemy_hp": enemy_hp,
                }
                for metadata_key in ("soul_power_cost", "soul_power_loss", "pollution_gain", "summon_count"):
                    if metadata_key in action:
                        state_after[metadata_key] = int(action[metadata_key])
                connection.execute(
                    "INSERT INTO party_battle_actions(action_id, battle_id, sequence_no, round_no, actor_key, strategy_key, skill_key, target_key, hit_roll_bp, damage, state_json, operation_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (uuid4().hex, battle_id, action["sequence_no"], expected_round, action["actor_key"], action["strategy_key"], action["skill_key"], action["target_key"], action["hit_roll_bp"], action["damage"], json.dumps(state_after, ensure_ascii=False, sort_keys=True), f"{operation_id}:{action['sequence_no']}", now_text),
                )
            unresolved_downed = (boundary_party or demon_party or beast_party) and any(
                member_status.get(player_id) == "downed" for player_id in member_hp
            )
            outcome = "won" if enemy_hp <= 0 else ("lost" if unresolved_downed else (
                "lost"
                if not any(
                    value > 0 and member_status.get(player_id) != "downed"
                    for player_id, value in member_hp.items()
                )
                else None
            ))
            status = outcome or "running"
            if expected_round >= PARTY_BATTLE_MAX_TURNS and status == "running":
                status, outcome = "expired", "expired"
            state.update(
                {
                    "round_no": expected_round,
                    "member_hp": member_hp,
                    "member_status": member_status,
                    "member_soul_power": member_soul_power,
                    "member_pollution": member_pollution,
                    "revive_count": revive_count,
                    "contribution": contribution,
                    "enemy_hp": enemy_hp,
                    "summon_count": summon_count,
                    "target_index": target_index,
                }
            )
            connection.execute(
                "UPDATE party_battle_sessions SET status=?, round_no=?, action_sequence=?, turn_deadline=?, state_json=?, result_json=?, updated_at=? WHERE battle_id=?",
                (status, expected_round, sequence, serialize_datetime(self._now() + timedelta(seconds=TURN_TIMEOUT_SECONDS)), json.dumps(state, ensure_ascii=False, sort_keys=True), json.dumps({"outcome": outcome, "reason": "party_battle_ended"} if outcome else {}, ensure_ascii=False, sort_keys=True), now_text, battle_id),
            )
            payload = {"battle_id": battle_id, "status": status, "outcome": outcome, "round_no": expected_round, "action_count": len(actions)}
            operation_player = connection.execute(
                "SELECT player_id FROM party_battle_members WHERE battle_id=? ORDER BY id LIMIT 1",
                (battle_id,),
            ).fetchone()
            if operation_player is None:
                raise PartyBattleNotFoundError("party battle has no members")
            self._party_battle_record_operation(connection, operation_id, operation_name, int(operation_player["player_id"]), request_hash, payload, now_text)
            return payload

    def _resolve_party_battle_once(self, platform: str, platform_user_id: str, battle_id: str, operation_id: str) -> PartyBattleResolutionRecord:
        operation_name = "battle.party.resolve"
        request_hash = self._request_hash(operation_name, {"platform": platform, "platform_user_id": platform_user_id, "battle_id": battle_id})
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._party_battle_operation(connection, operation_id, operation_name, request_hash)
            if existing is not None:
                return self._party_battle_resolution_from_payload(existing, replay=True)
            actor = self._require_player(connection, platform, platform_user_id, writable=False)
            session = connection.execute("SELECT * FROM party_battle_sessions WHERE battle_id = ?", (battle_id,)).fetchone()
            member = connection.execute("SELECT 1 FROM party_battle_members WHERE battle_id = ? AND player_id = ?", (battle_id, actor["id"])).fetchone()
            if session is None or member is None:
                raise PartyBattlePermissionError("actor is not a party battle member")
            if str(session["status"]) == "settled":
                result = self._json_object(session["result_json"], {})
                payload = {"battle_id": battle_id, "party_id": session["party_id"], "enemy_key": session["enemy_key"], "status": "settled", "outcome": result.get("outcome", "expired"), "reason": result.get("reason", "party_battle_ended"), "round_no": int(session["round_no"]), "rewards": result.get("rewards", {}), "contributions": result.get("contribution", {}), "reward_order": result.get("reward_order", []), "reward_rolls": result.get("reward_rolls", {})}
                self._party_battle_record_operation(connection, operation_id, operation_name, int(actor["id"]), request_hash, payload, now_text)
                return self._party_battle_resolution_from_payload(payload, replay=True)
            if str(session["status"]) not in {"won", "lost", "expired"}:
                raise PartyBattleNotReadyError("party battle is still running")
            result = self._json_object(session["result_json"], {})
            outcome = str(result.get("outcome", session["status"]))
            reward_map: dict[str, dict[str, int]] = {}
            snapshot = self._json_object(session["snapshot_json"], {})
            boundary_party = str(snapshot.get("party_type", "")) in {PARTY_TYPE_BOUNDARY_REALM, PARTY_TYPE_PARTY_BOUNDARY}
            demon_party = str(snapshot.get("party_type", "")) == PARTY_TYPE_DEMON_REALM
            beast_party = str(snapshot.get("party_type", "")) == PARTY_TYPE_BEAST_REALM
            cross_realm_party = boundary_party or demon_party or beast_party
            reward_template = {
                str(key): int(value)
                for key, value in dict(snapshot.get("reward", BOUNDARY_REALM_REWARD if boundary_party else PARTY_BATTLE_REWARD)).items()
            }
            battle_members = connection.execute("SELECT * FROM party_battle_members WHERE battle_id = ? ORDER BY id", (battle_id,)).fetchall()
            state = self._json_object(session["state_json"], {})
            contribution = {
                str(key): int(value)
                for key, value in dict(state.get("contribution", {})).items()
            }
            snapshot_by_database_id = {
                int(member.get("database_id")): member
                for member in snapshot.get("members", [])
                if member.get("database_id") is not None
            }
            reward_order = sorted(
                battle_members,
                key=lambda row: (
                    -contribution.get(
                        str(snapshot_by_database_id.get(int(row["player_id"]), {}).get("player_id", "")),
                        0,
                    ),
                    int(row["id"]),
                ),
            )
            ordered_player_ids = [
                str(snapshot_by_database_id.get(int(row["player_id"]), {}).get("player_id", row["player_id"]))
                for row in reward_order
            ]
            reward_rolls = {
                str(snapshot_by_database_id.get(int(row["player_id"]), {}).get("player_id", row["player_id"])): battle_roll_bp(
                    f"{battle_id}:reward:{snapshot_by_database_id.get(int(row['player_id']), {}).get('player_id', row['player_id'])}"
                )
                for row in battle_members
            }
            for battle_member in battle_members:
                stable_player_id = str(
                    snapshot_by_database_id.get(int(battle_member["player_id"]), {}).get(
                        "player_id", battle_member["player_id"]
                    )
                )
                score = contribution.get(stable_player_id, 0)
                role_cap = 1 if str(battle_member["role"]) in {"leader", "member"} else 0
                if outcome == "won" and score > 0 and role_cap > 0:
                    reward = dict(reward_template)
                    for key, value in tuple(reward.items()):
                        if key.startswith("item."):
                            reward[key] = min(value, role_cap)
                else:
                    reward = {}
                if cross_realm_party and outcome in {"lost", "expired"} and score > 0:
                    reward = {"world_merit": min(10, max(1, score // 100))}
                reward_map[str(battle_member["player_id"])] = reward
                player = connection.execute("SELECT * FROM players WHERE id = ?", (battle_member["player_id"],)).fetchone()
                if player is None:
                    raise PartyBattleNotFoundError("party battle member no longer exists")
                if reward:
                    inventory = self._json_object(player["inventory_json"], {})
                    cultivation = int(player["cultivation"]) + int(reward.get("cultivation", 0))
                    total_cultivation = int(player["total_cultivation"]) + int(reward.get("cultivation", 0))
                    spirit_stones = int(player["spirit_stones"]) + int(reward.get("spirit_stones", 0))
                    world_merit = int(player["world_merit"]) + int(reward.get("world_merit", 0))
                    faction = self._json_object(player["faction_reputation_json"], {})
                    for item_key, quantity in reward.items():
                        if item_key.startswith("item."):
                            inventory[item_key] = int(inventory.get(item_key, 0)) + int(quantity)
                        elif item_key.startswith("faction_reputation."):
                            faction_key = item_key.removeprefix("faction_reputation.")
                            faction[faction_key] = int(faction.get(faction_key, 0)) + int(quantity)
                    connection.execute(
                        "UPDATE players SET cultivation=?, total_cultivation=?, spirit_stones=?, world_merit=?, inventory_json=?, faction_reputation_json=?, updated_at=? WHERE id=?",
                        (cultivation, total_cultivation, spirit_stones, world_merit, json.dumps(inventory, ensure_ascii=False, sort_keys=True), json.dumps(faction, ensure_ascii=False, sort_keys=True), now_text, player["id"]),
                    )
                if cross_realm_party and outcome in {"lost", "expired"}:
                    fatigue_until = serialize_datetime(self._now() + timedelta(hours=2))
                    connection.execute(
                        "UPDATE players SET soul_power=MAX(0, soul_power-2000), soul_fatigue_until=?, updated_at=? WHERE id=?",
                        (fatigue_until, now_text, player["id"]),
                    )
                connection.execute(
                    "INSERT INTO party_battle_rewards(battle_id, party_id, player_id, reward_json, status, operation_id, claimed_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (battle_id, session["party_id"], battle_member["player_id"], json.dumps(reward, ensure_ascii=False, sort_keys=True), "claimed" if reward else "none", f"{operation_id}:{battle_member['player_id']}", now_text),
                )
                connection.execute("UPDATE party_battle_members SET asset_lock_status='released', reward_json=?, settled_at=?, updated_at=? WHERE id=?", (json.dumps(reward, ensure_ascii=False, sort_keys=True), now_text, now_text, battle_member["id"]))
            result.update(
                {
                    "outcome": outcome,
                    "reason": result.get("reason", "party_battle_ended"),
                    "rewards": reward_map,
                    "contribution": contribution,
                    "reward_order": ordered_player_ids,
                    "reward_rolls": reward_rolls,
                    "settled_at": now_text,
                }
            )
            connection.execute("UPDATE party_battle_sessions SET status='settled', result_json=?, updated_at=? WHERE battle_id=?", (json.dumps(result, ensure_ascii=False, sort_keys=True), now_text, battle_id))
            connection.execute("UPDATE parties SET current_session_id=NULL, updated_at=? WHERE party_id=? AND current_session_id=?", (now_text, session["party_id"], battle_id))
            payload = {"battle_id": battle_id, "party_id": session["party_id"], "enemy_key": session["enemy_key"], "status": "settled", "outcome": outcome, "reason": result["reason"], "round_no": int(session["round_no"]), "rewards": reward_map, "contributions": contribution, "reward_order": ordered_player_ids, "reward_rolls": reward_rolls}
            self._party_battle_record_operation(connection, operation_id, operation_name, int(actor["id"]), request_hash, payload, now_text)
            return self._party_battle_resolution_from_payload(payload)

    def _replay_party_battle_once(self, platform: str, platform_user_id: str, battle_id: str | None) -> PartyBattleReplayRecord:
        row = self._party_battle_access_once(platform, platform_user_id, battle_id)
        with self._connect() as connection:
            snapshot = self._json_object(row["snapshot_json"], {})
            result = self._json_object(row["result_json"], {})
            actions = tuple(dict(action) for action in connection.execute("SELECT * FROM party_battle_actions WHERE battle_id=? ORDER BY sequence_no", (row["battle_id"],)).fetchall())
            return PartyBattleReplayRecord(str(row["battle_id"]), str(row["party_id"]), str(row["enemy_key"]), str(row["status"]), snapshot, result, actions)

    @staticmethod
    def _party_battle_operation(connection: sqlite3.Connection, operation_id: str, operation_name: str, request_hash: str) -> dict[str, Any] | None:
        row = connection.execute("SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id=?", (operation_id,)).fetchone()
        if row is None:
            return None
        if row["operation_name"] != operation_name or row["request_hash"] != request_hash:
            raise OperationConflictError("operation input differs from its original request")
        return json.loads(row["result_json"])

    @staticmethod
    def _alliance_key_from_row(row: Any) -> str | None:
        try:
            qualification = json.loads(str(row["qualification_json"] or "{}"))
        except (TypeError, json.JSONDecodeError):
            qualification = {}
        try:
            intro = json.loads(str(row["intro_json"] or "{}"))
        except (TypeError, json.JSONDecodeError):
            intro = {}
        qualification = qualification if isinstance(qualification, dict) else {}
        intro = intro if isinstance(intro, dict) else {}
        for source in (qualification, intro):
            for key in ("cross_realm_alliance", "alliance_key", "alliance", "盟约"):
                value = source.get(key)
                if value:
                    return str(value)
        return None

    @staticmethod
    def _boundary_mainline_ready(connection: sqlite3.Connection, row: Any) -> bool:
        """Accept either the explicit v0.3 quest row or its projected access flag."""

        try:
            intro = json.loads(str(row["intro_json"] or "{}"))
        except (TypeError, json.JSONDecodeError):
            intro = {}
        intro = intro if isinstance(intro, dict) else {}
        if "story.mainline.three_realms" in {str(item) for item in intro.get("flags", [])}:
            return True
        progress = connection.execute(
            "SELECT status FROM quest_progress WHERE player_id = ? AND quest_key = ?",
            (row["database_player_id"], "story.mainline.three_realms"),
        ).fetchone()
        return progress is not None and str(progress["status"]) in {"completed", "claimed"}

    @staticmethod
    def _intro_flag(row: Any, flag: str) -> bool:
        try:
            intro = json.loads(str(row["intro_json"] or "{}"))
        except (TypeError, json.JSONDecodeError):
            intro = {}
        if not isinstance(intro, dict):
            return False
        flags = intro.get("flags", [])
        return flag in flags if isinstance(flags, list) else False

    @staticmethod
    def _faction_reputation(row: Any, faction: str) -> int:
        try:
            reputation = json.loads(str(row["faction_reputation_json"] or "{}"))
        except (TypeError, json.JSONDecodeError):
            reputation = {}
        return int(reputation.get(faction, 0)) if isinstance(reputation, dict) else 0

    @staticmethod
    def _party_battle_record_operation(connection: sqlite3.Connection, operation_id: str, operation_name: str, player_id: int, request_hash: str, payload: dict[str, Any], now_text: str) -> None:
        connection.execute("INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)", (operation_id, operation_name, player_id, request_hash, json.dumps(payload, ensure_ascii=False, sort_keys=True), now_text))

    @staticmethod
    def _party_battle_start_from_payload(payload: dict[str, Any], replay: bool = False) -> PartyBattleStartRecord:
        return PartyBattleStartRecord(str(payload["battle_id"]), str(payload["party_id"]), str(payload["enemy_key"]), str(payload["status"]), int(payload["round_no"]), int(payload["max_rounds"]), tuple(str(value) for value in payload.get("member_player_ids", [])), replay)

    @staticmethod
    def _party_battle_resolution_from_payload(payload: dict[str, Any], replay: bool = False) -> PartyBattleResolutionRecord:
        return PartyBattleResolutionRecord(
            str(payload["battle_id"]),
            str(payload["party_id"]),
            str(payload["enemy_key"]),
            str(payload["status"]),
            str(payload["outcome"]),
            str(payload["reason"]),
            int(payload["round_no"]),
            {str(player): {str(key): int(value) for key, value in dict(reward).items()} for player, reward in dict(payload.get("rewards", {})).items()},
            {str(player): int(value) for player, value in dict(payload.get("contributions", {})).items()},
            tuple(str(value) for value in payload.get("reward_order", [])),
            {str(player): int(value) for player, value in dict(payload.get("reward_rolls", {})).items()},
            replay,
        )


__all__ = ["PartyCombatRepositoryMixin"]
