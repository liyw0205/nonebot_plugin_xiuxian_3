"""Transactions for the two-player three-realms tower challenge."""

from __future__ import annotations

import asyncio
import json
from uuid import uuid4

from ...contracts import serialize_datetime
from ..persistence.errors import (
    OperationConflictError,
    PartyBattleRequirementError,
    PartyNotFoundError,
    ResourceInsufficientError,
    TowerAlreadyClaimedError,
    TowerFloorLockedError,
    TowerNotFoundError,
    TowerQuotaError,
    TowerRequirementError,
    TowerRewardNotAvailableError,
    TowerStartFailedError,
)
from .three_realms_tower_duo_models import ThreeRealmsTowerDuoRewardRecord, ThreeRealmsTowerDuoRunRecord
from .three_realms_tower_duo_rules import (
    PARTY_TYPE_THREE_REALMS_TOWER_DUO,
    TOWER_DUO_CONTENT_VERSION,
    TOWER_DUO_RULE_VERSION,
    TOWER_DUO_STAMINA_COST,
    TOWER_KEY,
    enemy_key_for,
    floor_definition,
    rebuild_reputation_total,
    reward_for,
    week_start,
)


class ThreeRealmsTowerDuoRepositoryMixin:
    async def start_three_realms_tower_duo(
        self, *, platform: str, platform_user_id: str, floor_no: int, operation_id: str
    ) -> ThreeRealmsTowerDuoRunRecord:
        await self.initialize()
        async with self._inflight:
            record = await asyncio.to_thread(
                self._start_three_realms_tower_duo_once,
                platform,
                platform_user_id,
                floor_no,
                operation_id,
            )
        try:
            battle = await self.start_party_battle(
                platform=platform,
                platform_user_id=platform_user_id,
                party_id=record.party_id,
                operation_id=f"{operation_id}:battle",
                three_realms_tower_duo_run_id=record.duo_run_id,
            )
            resolved = await self.settle_party_battle(
                platform=platform,
                platform_user_id=platform_user_id,
                battle_id=battle.battle_id,
                operation_id=f"{operation_id}:settle",
            )
        except Exception as exc:
            await asyncio.to_thread(self._abort_three_realms_tower_duo, record.duo_run_id)
            raise TowerStartFailedError("three-realms tower duo battle could not start") from exc
        return await asyncio.to_thread(
            self._finish_three_realms_tower_duo,
            record.duo_run_id,
            resolved.outcome,
            resolved.reason,
        )

    async def claim_three_realms_tower_duo_reward(
        self, *, platform: str, platform_user_id: str, operation_id: str
    ) -> ThreeRealmsTowerDuoRewardRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._claim_three_realms_tower_duo_reward_once,
                platform,
                platform_user_id,
                operation_id,
            )

    def _start_three_realms_tower_duo_once(
        self, platform: str, platform_user_id: str, floor_no: int, operation_id: str
    ) -> ThreeRealmsTowerDuoRunRecord:
        try:
            definition = floor_definition(floor_no)
        except ValueError as exc:
            raise TowerRequirementError(str(exc)) from exc
        request = {"platform": platform, "platform_user_id": platform_user_id, "floor_no": floor_no, "tower_key": TOWER_KEY}
        operation_name = "specials.start_three_realms_tower_duo"
        request_hash = self._request_hash(operation_name, request)
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._duo_operation(connection, operation_id, operation_name, request_hash)
            if existing is not None:
                return self._duo_run_from_payload(existing, replay=True)
            leader = self._require_player(connection, platform, platform_user_id)
            membership = connection.execute(
                "SELECT * FROM party_members WHERE player_id=? AND status='active' ORDER BY id DESC LIMIT 1",
                (leader["id"],),
            ).fetchone()
            if membership is None or str(membership["role"]) != "leader":
                raise PartyNotFoundError("leader has no active tower duo party")
            party = connection.execute("SELECT * FROM parties WHERE party_id=?", (membership["party_id"],)).fetchone()
            if party is None or str(party["party_type"]) != PARTY_TYPE_THREE_REALMS_TOWER_DUO:
                raise PartyNotFoundError("active party is not a tower duo")
            if str(party["status"]) != "ready" or party["current_session_id"]:
                raise TowerRequirementError("tower duo party is not ready")
            members = connection.execute(
                "SELECT m.player_id AS database_id,m.role,m.confirmed_at,p.* FROM party_members m JOIN players p ON p.id=m.player_id "
                "WHERE m.party_id=? AND m.status='active' ORDER BY m.id",
                (party["party_id"],),
            ).fetchall()
            if len(members) != 2 or any(not row["confirmed_at"] for row in members):
                raise TowerRequirementError("tower duo requires two confirmed members")
            if any(str(row["location_key"]) != str(party["location_key"]) for row in members):
                raise TowerRequirementError("tower duo members must share a location")
            for row in members:
                if not self._meets_realm_values(str(row["realm_key"]), int(row["realm_layer"]), definition.required_realm, definition.required_layer):
                    has_v03_permit = floor_no <= 20 and self._intro_flag(row, "story.mainline.three_realms")
                    if not has_v03_permit and rebuild_reputation_total(self._local_reputations(connection, int(row["id"]))) < 500:
                        raise TowerRequirementError("tower duo member lacks realm or reconstruction reputation")
                used = connection.execute(
                    "SELECT COUNT(*) FROM three_realms_tower_duo_member_runs WHERE player_id=? AND floor_no=? AND status<>'aborted' AND substr(created_at,1,10)>=?",
                    (row["id"], floor_no, week_start(now)),
                ).fetchone()[0]
                if int(used) >= definition.weekly_limit:
                    raise TowerQuotaError("tower duo member weekly quota exhausted")
                if int(row["stamina"]) < TOWER_DUO_STAMINA_COST:
                    raise ResourceInsufficientError("tower duo member lacks stamina")
                highest = connection.execute(
                    "SELECT COALESCE(MAX(floor_no),0) FROM three_realms_tower_duo_member_runs WHERE player_id=? AND status='claimed'",
                    (row["id"],),
                ).fetchone()[0]
                if floor_no > int(highest) + 1:
                    raise TowerFloorLockedError("tower duo floor is locked")
            connection.execute(
                "UPDATE players SET stamina=stamina-?, updated_at=? WHERE id IN (?,?) AND stamina>=?",
                (TOWER_DUO_STAMINA_COST, now_text, members[0]["id"], members[1]["id"], TOWER_DUO_STAMINA_COST),
            )
            if connection.execute("SELECT changes()").fetchone()[0] != 2:
                raise ResourceInsufficientError("tower duo stamina changed during start")
            duo_run_id = f"tower-duo-{uuid4().hex}"
            member_run_ids = [f"{duo_run_id}:member:{row['id']}" for row in members]
            content_version = TOWER_DUO_CONTENT_VERSION
            rule_version = TOWER_DUO_RULE_VERSION
            result = {
                "enemy_key": enemy_key_for(floor_no, self._tower_run_faction_for_player(connection, int(leader["id"]))),
                "member_database_ids": [int(row["id"]) for row in members],
                "member_stable_ids": [str(row["player_id"]) for row in members],
                "party_type": PARTY_TYPE_THREE_REALMS_TOWER_DUO,
                "floor_no": floor_no,
            }
            connection.execute(
                "INSERT INTO three_realms_tower_duo_runs(duo_run_id,party_id,tower_key,floor_no,status,battle_id,member_run_ids_json,result_json,content_version,rule_version,start_operation_id,created_at,updated_at) VALUES (?,?,?,?, 'battle_running',NULL,?,?,?,?,?,?,?)",
                (duo_run_id, party["party_id"], TOWER_KEY, floor_no, json.dumps(member_run_ids), json.dumps(result, ensure_ascii=False, sort_keys=True), content_version, rule_version, operation_id, now_text, now_text),
            )
            payload = {"duo_run_id": duo_run_id, "party_id": str(party["party_id"]), "battle_id": None, "floor_no": floor_no, "status": "battle_running", "member_run_ids": member_run_ids, "first_clear_by_player": {}, "reward_by_player": {}}
            self._insert_duo_operation(connection, operation_id, operation_name, int(leader["id"]), request_hash, payload, now_text)
            return self._duo_run_from_payload(payload)

    def _finish_three_realms_tower_duo(self, duo_run_id: str, outcome: str, reason: str) -> ThreeRealmsTowerDuoRunRecord:
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM three_realms_tower_duo_runs WHERE duo_run_id=?", (duo_run_id,)).fetchone()
            if row is None:
                raise TowerNotFoundError("tower duo run does not exist")
            if str(row["status"]) != "battle_running":
                return self._duo_run_from_row(row)
            members = self._json_object(row["result_json"], {}).get("member_database_ids", [])
            result = self._json_object(row["result_json"], {})
            result.update({"outcome": outcome, "reason": reason})
            member_run_ids = json.loads(row["member_run_ids_json"])
            first_clear_by_player: dict[str, bool] = {}
            reward_by_player: dict[str, dict[str, int]] = {}
            for database_id, run_id in zip(members, member_run_ids):
                player = connection.execute("SELECT player_id FROM players WHERE id=?", (database_id,)).fetchone()
                if player is None:
                    continue
                prior = connection.execute(
                    "SELECT 1 FROM three_realms_tower_duo_member_runs WHERE player_id=? AND floor_no=? AND status='claimed' LIMIT 1",
                    (database_id, row["floor_no"]),
                ).fetchone()
                first = prior is None
                first_clear_by_player[str(player["player_id"])] = first
                reward = reward_for(int(row["floor_no"]), f"{duo_run_id}:{database_id}", first_clear=first) if outcome == "won" else {}
                reward_by_player[str(player["player_id"])] = reward
                connection.execute(
                    "INSERT INTO three_realms_tower_duo_member_runs(run_id,duo_run_id,player_id,floor_no,first_clear,status,reward_json,created_at,updated_at) VALUES (?,?,?,?,?,?,?, ?, ?)",
                    (run_id, duo_run_id, database_id, row["floor_no"], int(first), "reward_pending" if outcome == "won" else "lost", json.dumps(reward, ensure_ascii=False, sort_keys=True), now_text, now_text),
                )
            result.update({"first_clear_by_player": first_clear_by_player, "reward_by_player": reward_by_player})
            status = "reward_pending" if outcome == "won" else "lost"
            connection.execute("UPDATE three_realms_tower_duo_runs SET status=?,result_json=?,updated_at=? WHERE duo_run_id=?", (status, json.dumps(result, ensure_ascii=False, sort_keys=True), now_text, duo_run_id))
            updated = connection.execute("SELECT * FROM three_realms_tower_duo_runs WHERE duo_run_id=?", (duo_run_id,)).fetchone()
            return self._duo_run_from_row(updated)

    def _abort_three_realms_tower_duo(self, duo_run_id: str) -> None:
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM three_realms_tower_duo_runs WHERE duo_run_id=? AND status='battle_running'", (duo_run_id,)).fetchone()
            if row is None:
                return
            ids = self._json_object(row["result_json"], {}).get("member_database_ids", [])
            for player_id in ids:
                connection.execute("UPDATE players SET stamina=MIN(stamina_max,stamina+?),updated_at=? WHERE id=?", (TOWER_DUO_STAMINA_COST, now_text, player_id))
            connection.execute("UPDATE three_realms_tower_duo_runs SET status='aborted',result_json=?,updated_at=? WHERE duo_run_id=?", (json.dumps({"reason": "battle_start_failed"}), now_text, duo_run_id))

    def _claim_three_realms_tower_duo_reward_once(self, platform: str, platform_user_id: str, operation_id: str) -> ThreeRealmsTowerDuoRewardRecord:
        operation_name = "specials.claim_three_realms_tower_duo_reward"
        request = {"platform": platform, "platform_user_id": platform_user_id, "tower_key": TOWER_KEY}
        request_hash = self._request_hash(operation_name, request)
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._duo_operation(connection, operation_id, operation_name, request_hash)
            if existing is not None:
                return ThreeRealmsTowerDuoRewardRecord(str(existing["duo_run_id"]), str(existing["run_id"]), str(existing["player_id"]), int(existing["floor_no"]), bool(existing["first_clear"]), dict(existing["reward"]), True)
            player = self._require_player(connection, platform, platform_user_id)
            row = connection.execute("SELECT m.*,r.duo_run_id,r.floor_no,r.status AS run_status FROM three_realms_tower_duo_member_runs m JOIN three_realms_tower_duo_runs r ON r.duo_run_id=m.duo_run_id WHERE m.player_id=? AND m.status='reward_pending' ORDER BY m.id DESC LIMIT 1", (player["id"],)).fetchone()
            if row is None:
                raise TowerRewardNotAvailableError("no tower duo reward is pending")
            reward = self._json_object(row["reward_json"], {})
            inventory = self._json_object(player["inventory_json"], {})
            inventory["item.mat.array_sand"] = int(inventory.get("item.mat.array_sand", 0)) + int(reward.get("item.mat.array_sand", 0))
            connection.execute("UPDATE players SET spirit_stones=spirit_stones+?,inventory_json=?,updated_at=? WHERE id=?", (int(reward.get("spirit_stones", 0)), json.dumps(inventory, ensure_ascii=False, sort_keys=True), now_text, player["id"]))
            connection.execute("UPDATE three_realms_tower_duo_member_runs SET status='claimed',claim_operation_id=?,updated_at=? WHERE id=? AND status='reward_pending'", (operation_id, now_text, row["id"]))
            payload = {"duo_run_id": str(row["duo_run_id"]), "run_id": str(row["run_id"]), "player_id": str(player["player_id"]), "floor_no": int(row["floor_no"]), "first_clear": bool(row["first_clear"]), "reward": reward}
            self._insert_duo_operation(connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text)
            return ThreeRealmsTowerDuoRewardRecord(**payload)

    @staticmethod
    def _local_reputations(connection, player_id: int) -> dict[str, int]:
        row = connection.execute("SELECT local_json FROM player_reputations WHERE player_id=?", (player_id,)).fetchone()
        return json.loads(row[0]) if row and row[0] else {}

    def _tower_run_faction_for_player(self, connection, player_id: int) -> str:
        row = connection.execute("SELECT intro_json FROM players WHERE id=?", (player_id,)).fetchone()
        intro = self._json_object(row[0], {}) if row else {}
        for faction in ("xuantian", "demon", "beast"):
            if f"alliance.{faction}" in intro.get("flags", []):
                return faction
        return "xuantian"

    @staticmethod
    def _duo_operation(connection, operation_id: str, operation_name: str, request_hash: str):
        row = connection.execute("SELECT operation_name,request_hash,result_json FROM operations WHERE operation_id=?", (operation_id,)).fetchone()
        if row is None:
            return None
        if row["operation_name"] != operation_name or row["request_hash"] != request_hash:
            raise OperationConflictError("operation input differs from its original request")
        return json.loads(row["result_json"])

    @staticmethod
    def _insert_duo_operation(connection, operation_id, operation_name, player_id, request_hash, payload, now_text):
        connection.execute("INSERT INTO operations(operation_id,operation_name,player_id,request_hash,result_json,created_at) VALUES (?,?,?,?,?,?)", (operation_id, operation_name, player_id, request_hash, json.dumps(payload, ensure_ascii=False, sort_keys=True), now_text))

    @staticmethod
    def _duo_run_from_payload(payload, replay=False):
        return ThreeRealmsTowerDuoRunRecord(str(payload["duo_run_id"]), str(payload["party_id"]), payload.get("battle_id"), int(payload["floor_no"]), str(payload["status"]), payload.get("outcome"), payload.get("reason"), tuple(payload.get("member_run_ids", [])), dict(payload.get("first_clear_by_player", {})), dict(payload.get("reward_by_player", {})), replay)

    def _duo_run_from_row(self, row, replay=False):
        result = self._json_object(row["result_json"], {})
        return self._duo_run_from_payload({"duo_run_id": row["duo_run_id"], "party_id": row["party_id"], "battle_id": row["battle_id"], "floor_no": row["floor_no"], "status": row["status"], "outcome": result.get("outcome"), "reason": result.get("reason"), "member_run_ids": json.loads(row["member_run_ids_json"]), "first_clear_by_player": result.get("first_clear_by_player", {}), "reward_by_player": result.get("reward_by_player", {})}, replay)


__all__ = ["ThreeRealmsTowerDuoRepositoryMixin"]
