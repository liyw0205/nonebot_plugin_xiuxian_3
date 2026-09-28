"""Transactional persistence for the v0.3 three-realms tower."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from typing import Any
from uuid import uuid4

from ...contracts import serialize_datetime
from ..persistence.errors import (
    OperationConflictError,
    ResourceInsufficientError,
    TowerAlreadyClaimedError,
    TowerBusyError,
    TowerFloorLockedError,
    TowerNotFoundError,
    TowerNotReadyError,
    TowerQuotaError,
    TowerRequirementError,
    TowerRewardNotAvailableError,
    TowerStartFailedError,
)
from .codex_projection import record_codex_discovery, record_material_discoveries
from .three_realms_arena_rules import player_faction
from .three_realms_tower_models import (
    ThreeRealmsTowerPreviewRecord,
    ThreeRealmsTowerRewardRecord,
    ThreeRealmsTowerRunRecord,
)
from .three_realms_tower_rules import (
    FACTIONS,
    MAX_FLOOR,
    V03_MAX_FLOOR,
    TOWER_KEY,
    enemy_key_for,
    floor_definition,
    rebuild_reputation_total,
    reward_for,
    versions_for_floor,
    week_start,
)


class ThreeRealmsTowerRepositoryMixin:
    async def preview_three_realms_tower(
        self, *, platform: str, platform_user_id: str
    ) -> ThreeRealmsTowerPreviewRecord:
        await self.initialize()
        return await asyncio.to_thread(
            self._preview_three_realms_tower_sync, platform, platform_user_id
        )

    def _preview_three_realms_tower_sync(
        self, platform: str, platform_user_id: str
    ) -> ThreeRealmsTowerPreviewRecord:
        now = self._now()
        with self._connect() as connection:
            player = self._require_player(connection, platform, platform_user_id, writable=False)
            highest = int(connection.execute(
                "SELECT COALESCE(MAX(floor_no), 0) FROM tower_runs "
                "WHERE player_id=? AND tower_key=? AND first_clear=1 AND status='claimed'",
                (player["id"], TOWER_KEY),
            ).fetchone()[0])
            next_floor = min(highest + 1, MAX_FLOOR)
            active = connection.execute(
                "SELECT floor_no, status FROM tower_runs WHERE player_id=? AND tower_key=? "
                "AND status IN ('battle_running','reward_pending') ORDER BY id DESC LIMIT 1",
                (player["id"], TOWER_KEY),
            ).fetchone()
            used = int(connection.execute(
                "SELECT COUNT(*) FROM tower_runs WHERE player_id=? AND tower_key=? AND floor_no=? "
                "AND status<>'aborted' AND substr(created_at,1,10)>=? AND substr(created_at,1,10)<=?",
                (player["id"], TOWER_KEY, next_floor, week_start(now), now.date().isoformat()),
            ).fetchone()[0])
            definition = floor_definition(next_floor)
            return ThreeRealmsTowerPreviewRecord(
                player=self._row_to_player(player),
                highest_floor=highest,
                next_floor=next_floor,
                active_floor=int(active["floor_no"]) if active else None,
                active_status=str(active["status"]) if active else None,
                stamina_cost=definition.stamina_cost,
                weekly_limit=definition.weekly_limit,
                weekly_used=used,
            )

    async def start_three_realms_tower_run(
        self, *, platform: str, platform_user_id: str, floor_no: int, operation_id: str
    ) -> ThreeRealmsTowerRunRecord:
        await self.initialize()
        async with self._inflight:
            record = await asyncio.to_thread(
                self._start_three_realms_tower_run_once,
                platform,
                platform_user_id,
                floor_no,
                operation_id,
            )
        if record.status != "battle_running":
            return record
        operation = f"specials.three_realms_tower.battle.start:{record.run_id}"
        try:
            battle = await self.start_quest_battle(
                platform=platform,
                platform_user_id=platform_user_id,
                enemy_key=enemy_key_for(floor_no, self._tower_run_faction(record.run_id)),
                battle_type="pve.tower",
                operation_id=operation,
                ignore_tower_run_id=record.run_id,
            )
        except Exception as exc:
            await asyncio.to_thread(self._abort_three_realms_tower_run, record.run_id)
            raise TowerStartFailedError("three-realms tower battle could not be started") from exc
        record = await asyncio.to_thread(
            self._attach_three_realms_tower_battle, record.run_id, battle.battle_id
        )
        return await self._resolve_three_realms_tower_run(record)

    def _start_three_realms_tower_run_once(
        self, platform: str, platform_user_id: str, floor_no: int, operation_id: str
    ) -> ThreeRealmsTowerRunRecord:
        try:
            definition = floor_definition(floor_no)
        except ValueError as exc:
            raise TowerRequirementError(str(exc)) from exc
        content_version, rule_version = versions_for_floor(floor_no)
        operation_name = "specials.start_three_realms_tower"
        payload = {
            "platform": platform,
            "platform_user_id": platform_user_id,
            "tower_key": TOWER_KEY,
            "floor_no": floor_no,
            "content_version": content_version,
            "rule_version": rule_version,
        }
        request_hash = self._request_hash(operation_name, payload)
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id=?",
                (operation_id,),
            ).fetchone()
            if existing is not None:
                if existing["operation_name"] != operation_name or existing["request_hash"] != request_hash:
                    raise OperationConflictError("operation input differs from its original request")
                run_id = str(json.loads(existing["result_json"])["run_id"])
                run = connection.execute("SELECT * FROM tower_runs WHERE run_id=?", (run_id,)).fetchone()
                if run is None:
                    raise TowerNotFoundError("three-realms tower run no longer exists")
                player = connection.execute("SELECT * FROM players WHERE id=?", (run["player_id"],)).fetchone()
                return self._three_realms_tower_run_from_rows(run, player, replay=True)

            player = self._require_player(connection, platform, platform_user_id)
            flags = self._json_object(player["intro_json"], {}).get("flags", ())
            has_story_permit = "story.mainline.three_realms" in {str(value) for value in flags}
            meets_realm = self._meets_realm_values(
                str(player["realm_key"]),
                int(player["realm_layer"]),
                definition.required_realm,
                definition.required_layer,
            )
            if floor_no <= V03_MAX_FLOOR:
                if not meets_realm and not has_story_permit:
                    raise TowerRequirementError("nascent-soul rank or three-realms story permit is required")
            elif not meets_realm:
                reputation = connection.execute(
                    "SELECT local_json FROM player_reputations WHERE player_id=?",
                    (player["id"],),
                ).fetchone()
                local = self._json_object(reputation["local_json"], {}) if reputation else {}
                if rebuild_reputation_total(local) < 500:
                    raise TowerRequirementError("soul-transformation rank or 500 rebuild reputation is required")
            if self._has_active_long_action(connection, int(player["id"])):
                raise TowerBusyError("another long action is active")
            active = connection.execute(
                "SELECT 1 FROM tower_runs WHERE player_id=? AND status IN ('battle_running','reward_pending') LIMIT 1",
                (player["id"],),
            ).fetchone()
            if active is not None:
                raise TowerBusyError("another tower run is active")
            if floor_no > 1:
                previous = connection.execute(
                    "SELECT 1 FROM tower_runs WHERE player_id=? AND tower_key=? AND floor_no=? "
                    "AND first_clear=1 AND status='claimed' LIMIT 1",
                    (player["id"], TOWER_KEY, floor_no - 1),
                ).fetchone()
                if previous is None:
                    raise TowerFloorLockedError("previous three-realms tower floor is not claimed")
            existing_clear = connection.execute(
                "SELECT 1 FROM tower_runs WHERE player_id=? AND tower_key=? AND floor_no=? "
                "AND first_clear=1 AND status='claimed' LIMIT 1",
                (player["id"], TOWER_KEY, floor_no),
            ).fetchone()
            first_clear = existing_clear is None
            used = int(connection.execute(
                "SELECT COUNT(*) FROM tower_runs WHERE player_id=? AND tower_key=? AND floor_no=? "
                "AND status<>'aborted' AND substr(created_at,1,10)>=? AND substr(created_at,1,10)<=?",
                (player["id"], TOWER_KEY, floor_no, week_start(now), now.date().isoformat()),
            ).fetchone()[0])
            if used >= definition.weekly_limit:
                raise TowerQuotaError("weekly attempts for this tower floor are exhausted")
            if int(player["stamina"]) < definition.stamina_cost:
                raise ResourceInsufficientError("stamina is insufficient")

            faction = player_faction(player)
            context = self._three_realms_tower_context(
                connection,
                player,
                faction,
                now_text,
                content_version=content_version,
                rule_version=rule_version,
            )
            run_id = uuid4().hex
            reward = reward_for(floor_no, run_id, first_clear=first_clear)
            connection.execute(
                "UPDATE players SET stamina=stamina-?, updated_at=? WHERE id=? AND stamina>=?",
                (definition.stamina_cost, now_text, player["id"], definition.stamina_cost),
            )
            connection.execute(
                "INSERT INTO tower_runs(run_id,player_id,tower_key,floor_no,status,battle_id,first_clear,"
                "starts_at,result_json,reward_json,content_version,rule_version,created_at,updated_at) "
                "VALUES (?,?,?,?,'battle_running',NULL,?,?,?, ?,?,?,?,?)",
                (
                    run_id,
                    player["id"],
                    TOWER_KEY,
                    floor_no,
                    int(first_clear),
                    now_text,
                    json.dumps({"tower_context": context}, ensure_ascii=False, sort_keys=True),
                    json.dumps(reward, ensure_ascii=False, sort_keys=True),
                    content_version,
                    rule_version,
                    now_text,
                    now_text,
                ),
            )
            updated = connection.execute("SELECT * FROM players WHERE id=?", (player["id"],)).fetchone()
            run = connection.execute("SELECT * FROM tower_runs WHERE run_id=?", (run_id,)).fetchone()
            self._insert_three_realms_tower_operation(
                connection,
                operation_id,
                operation_name,
                int(player["id"]),
                request_hash,
                {"run_id": run_id, "tower_key": TOWER_KEY, "floor_no": floor_no},
                now_text,
            )
            return self._three_realms_tower_run_from_rows(run, updated)

    def _three_realms_tower_context(
        self,
        connection: sqlite3.Connection,
        player: sqlite3.Row,
        faction: str,
        captured_at: str,
        *,
        content_version: str,
        rule_version: str,
    ) -> dict[str, Any]:
        intro = self._json_object(player["intro_json"], {})
        qualification = self._json_object(player["qualification_json"], {})
        reputation = connection.execute(
            "SELECT local_json FROM player_reputations WHERE player_id=?", (player["id"],)
        ).fetchone()
        local_reputation = (
            self._json_object(reputation["local_json"], {})
            if reputation else {}
        )
        alliance = faction
        for source in (qualification, intro):
            for key in ("cross_realm_alliance", "alliance_key", "alliance", "盟约"):
                value = str(source.get(key) or "").strip().lower()
                if value.startswith("alliance."):
                    value = value.split(".", 1)[1]
                if value in FACTIONS:
                    alliance = value
                    break
            if alliance != faction:
                break
        return {
            "tower_key": TOWER_KEY,
            "faction": faction,
            "alliance": alliance,
            "faction_reputation": self._json_object(player["faction_reputation_json"], {}),
            "local_reputation": local_reputation,
            "pollution": int(player["pollution"]),
            "bloodline_stability": int(player["bloodline_stability"]),
            "content_version": content_version,
            "rule_version": rule_version,
            "captured_at": captured_at,
        }

    def _tower_run_faction(self, run_id: str) -> str:
        with self._connect() as connection:
            run = connection.execute(
                "SELECT player_id,result_json FROM tower_runs WHERE run_id=?", (run_id,)
            ).fetchone()
            if run is None:
                raise TowerNotFoundError("three-realms tower run does not exist")
            result = self._json_object(run["result_json"], {})
            context = self._json_object(result.get("tower_context", {}), {})
            faction = str(context.get("faction", ""))
            if faction not in FACTIONS:
                raise TowerRequirementError("tower faction snapshot is invalid")
            return faction

    def _attach_three_realms_tower_battle(
        self, run_id: str, battle_id: str
    ) -> ThreeRealmsTowerRunRecord:
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            run = connection.execute("SELECT * FROM tower_runs WHERE run_id=?", (run_id,)).fetchone()
            if run is None:
                raise TowerNotFoundError("three-realms tower run does not exist")
            if run["battle_id"] is None:
                connection.execute(
                    "UPDATE tower_runs SET battle_id=?, updated_at=? WHERE id=?",
                    (battle_id, now_text, run["id"]),
                )
                battle = connection.execute(
                    "SELECT snapshot_json FROM battle_sessions WHERE battle_id=?", (battle_id,)
                ).fetchone()
                if battle is not None:
                    battle_snapshot = self._json_object(battle["snapshot_json"], {})
                    run_result = self._json_object(run["result_json"], {})
                    battle_snapshot["tower_context"] = run_result.get("tower_context", {})
                    battle_snapshot["tower_key"] = TOWER_KEY
                    battle_snapshot["tower_floor"] = int(run["floor_no"])
                    connection.execute(
                        "UPDATE battle_sessions SET snapshot_json=?, updated_at=? WHERE battle_id=?",
                        (json.dumps(battle_snapshot, ensure_ascii=False, sort_keys=True), now_text, battle_id),
                    )
            player = connection.execute("SELECT * FROM players WHERE id=?", (run["player_id"],)).fetchone()
            updated = connection.execute("SELECT * FROM tower_runs WHERE run_id=?", (run_id,)).fetchone()
            return self._three_realms_tower_run_from_rows(updated, player)

    async def _resolve_three_realms_tower_run(
        self, record: ThreeRealmsTowerRunRecord
    ) -> ThreeRealmsTowerRunRecord:
        if record.status != "battle_running" or not record.battle_id:
            return record
        turn = None
        for expected_round in range(1, 21):
            turn = await self.run_battle_turn(battle_id=record.battle_id, expected_round=expected_round)
            if turn.status not in {"created", "running"}:
                break
        if turn is None or turn.status in {"created", "running"}:
            raise TowerNotReadyError("three-realms tower battle is still running")
        resolved = await self.resolve_battle(battle_id=record.battle_id)
        return await asyncio.to_thread(
            self._record_three_realms_tower_outcome,
            record.run_id,
            resolved.outcome,
            resolved.reason,
        )

    def _record_three_realms_tower_outcome(
        self, run_id: str, outcome: str, reason: str
    ) -> ThreeRealmsTowerRunRecord:
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            run = connection.execute("SELECT * FROM tower_runs WHERE run_id=?", (run_id,)).fetchone()
            if run is None:
                raise TowerNotFoundError("three-realms tower run does not exist")
            if str(run["status"]) == "battle_running":
                status = "reward_pending" if outcome == "won" else "lost"
                result = self._json_object(run["result_json"], {})
                result.update({"outcome": outcome, "reason": reason, "resolved_at": now_text})
                connection.execute(
                    "UPDATE tower_runs SET status=?, result_json=?, updated_at=? "
                    "WHERE id=? AND status='battle_running'",
                    (status, json.dumps(result, ensure_ascii=False, sort_keys=True), now_text, run["id"]),
                )
                if outcome == "won" and bool(run["first_clear"]):
                    connection.execute(
                        "INSERT OR IGNORE INTO activity_events("
                        "player_id,event_key,source_operation_id,occurred_at,payload_json) "
                        "VALUES (?,?,?,?,?)",
                        (
                            run["player_id"],
                            f"specials.three_realms_tower.floor.{run['floor_no']}",
                            f"battle.resolve:{run['battle_id']}",
                            now_text,
                            json.dumps(
                                {
                                    "tower_key": TOWER_KEY,
                                    "floor_no": int(run["floor_no"]),
                                    "battle_id": run["battle_id"],
                                    "tower_context": result.get("tower_context", {}),
                                    "content_version": str(run["content_version"]),
                                    "rule_version": str(run["rule_version"]),
                                },
                                ensure_ascii=False,
                                sort_keys=True,
                            ),
                        ),
                    )
            updated = connection.execute("SELECT * FROM tower_runs WHERE run_id=?", (run_id,)).fetchone()
            player = connection.execute("SELECT * FROM players WHERE id=?", (run["player_id"],)).fetchone()
            return self._three_realms_tower_run_from_rows(updated, player)

    async def claim_three_realms_tower_reward(
        self, *, platform: str, platform_user_id: str, operation_id: str
    ) -> ThreeRealmsTowerRewardRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._claim_three_realms_tower_reward_once,
                platform,
                platform_user_id,
                operation_id,
            )

    def _claim_three_realms_tower_reward_once(
        self, platform: str, platform_user_id: str, operation_id: str
    ) -> ThreeRealmsTowerRewardRecord:
        operation_name = "specials.claim_three_realms_tower_reward"
        request_hash = self._request_hash(
            operation_name,
            {"platform": platform, "platform_user_id": platform_user_id, "tower_key": TOWER_KEY},
        )
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT operation_name,request_hash,result_json FROM operations WHERE operation_id=?",
                (operation_id,),
            ).fetchone()
            if existing is not None:
                if existing["operation_name"] != operation_name or existing["request_hash"] != request_hash:
                    raise OperationConflictError("operation input differs from its original request")
                return self._three_realms_tower_reward_from_payload(
                    json.loads(existing["result_json"]), replay=True
                )
            player = self._require_player(connection, platform, platform_user_id)
            run = connection.execute(
                "SELECT * FROM tower_runs WHERE player_id=? AND tower_key=? AND status='reward_pending' "
                "ORDER BY id DESC LIMIT 1",
                (player["id"], TOWER_KEY),
            ).fetchone()
            if run is None:
                claimed = connection.execute(
                    "SELECT 1 FROM tower_reward_claims c JOIN tower_runs r ON r.run_id=c.run_id "
                    "WHERE c.player_id=? AND r.tower_key=? LIMIT 1",
                    (player["id"], TOWER_KEY),
                ).fetchone()
                if claimed is not None:
                    raise TowerAlreadyClaimedError("three-realms tower reward was already claimed")
                raise TowerRewardNotAvailableError("no three-realms tower reward is pending")

            reward = {str(key): int(value) for key, value in json.loads(run["reward_json"]).items()}
            if any(key not in {"spirit_stones", "item.mat.array_sand"} or value < 0 for key, value in reward.items()):
                raise TowerRequirementError("three-realms tower reward contains an unsupported asset")
            inventory = self._json_object(player["inventory_json"], {})
            inventory["item.mat.array_sand"] = int(inventory.get("item.mat.array_sand", 0)) + reward.get(
                "item.mat.array_sand", 0
            )
            stones = int(player["spirit_stones"]) + reward.get("spirit_stones", 0)
            connection.execute(
                "UPDATE players SET spirit_stones=?, inventory_json=?, updated_at=? WHERE id=?",
                (stones, json.dumps(inventory, ensure_ascii=False, sort_keys=True), now_text, player["id"]),
            )
            result = self._json_object(run["result_json"], {})
            tower_context = self._json_object(result.get("tower_context", {}), {})
            codex_snapshot = {
                **tower_context,
                "tower_key": TOWER_KEY,
                "floor_no": int(run["floor_no"]),
                "run_id": str(run["run_id"]),
                "practice": not bool(run["first_clear"]),
            }
            content_version = str(run["content_version"])
            rule_version = str(run["rule_version"])
            record_material_discoveries(
                connection,
                player_id=int(player["id"]),
                operation_id=operation_id,
                occurred_at=now,
                reward=reward,
                snapshot=codex_snapshot,
            )
            record_codex_discovery(
                connection,
                player_id=int(player["id"]),
                entry_key=f"codex.challenge.three_realms.floor_{run['floor_no']}",
                operation_id=operation_id,
                occurred_at=now,
                snapshot=codex_snapshot,
                content_version=content_version,
                rule_version=rule_version,
            )
            faction = str(tower_context.get("faction", ""))
            story_entry = None
            if bool(run["first_clear"]) and int(run["floor_no"]) in {10, 20}:
                if faction not in FACTIONS:
                    raise TowerRequirementError("tower faction snapshot is invalid")
                story_entry = f"codex.story.three_realms.faction_{faction}"
            elif bool(run["first_clear"]) and int(run["floor_no"]) == 30:
                if faction not in FACTIONS:
                    raise TowerRequirementError("tower faction snapshot is invalid")
                story_entry = f"codex.story.three_realms.reconstruction_{faction}"
            elif bool(run["first_clear"]) and int(run["floor_no"]) == 40:
                if faction not in FACTIONS:
                    raise TowerRequirementError("tower faction snapshot is invalid")
                story_entry = f"codex.story.three_realms.domain_{faction}"
            if story_entry is not None:
                record_codex_discovery(
                    connection,
                    player_id=int(player["id"]),
                    entry_key=story_entry,
                    operation_id=operation_id,
                    occurred_at=now,
                    snapshot=codex_snapshot,
                    content_version=content_version,
                    rule_version=rule_version,
                )
            connection.execute(
                "INSERT INTO tower_reward_claims(run_id,player_id,floor_no,first_clear,operation_id,reward_json,"
                "content_version,rule_version,claimed_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    run["run_id"], player["id"], run["floor_no"], run["first_clear"], operation_id,
                    json.dumps(reward, ensure_ascii=False, sort_keys=True), content_version, rule_version, now_text,
                ),
            )
            connection.execute(
                "UPDATE tower_runs SET status='claimed',claim_operation_id=?,updated_at=? "
                "WHERE id=? AND status='reward_pending'",
                (operation_id, now_text, run["id"]),
            )
            updated = connection.execute("SELECT * FROM players WHERE id=?", (player["id"],)).fetchone()
            payload = {
                "player": self._player_payload(self._row_to_player(updated)),
                "run_id": str(run["run_id"]),
                "floor_no": int(run["floor_no"]),
                "first_clear": bool(run["first_clear"]),
                "faction": faction,
                "reward": reward,
                "content_version": content_version,
                "rule_version": rule_version,
            }
            self._insert_three_realms_tower_operation(
                connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text
            )
            return self._three_realms_tower_reward_from_payload(payload)

    def _abort_three_realms_tower_run(self, run_id: str) -> None:
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            run = connection.execute(
                "SELECT * FROM tower_runs WHERE run_id=? AND tower_key=? AND status='battle_running'",
                (run_id, TOWER_KEY),
            ).fetchone()
            if run is None:
                return
            stamina_cost = floor_definition(int(run["floor_no"])).stamina_cost
            connection.execute(
                "UPDATE players SET stamina=MIN(stamina_max,stamina+?),updated_at=? WHERE id=?",
                (stamina_cost, now_text, run["player_id"]),
            )
            result = self._json_object(run["result_json"], {})
            result["reason"] = "battle_start_failed"
            connection.execute(
                "UPDATE tower_runs SET status='aborted',result_json=?,updated_at=? WHERE id=?",
                (json.dumps(result, ensure_ascii=False, sort_keys=True), now_text, run["id"]),
            )

    def _three_realms_tower_run_from_rows(
        self, run: sqlite3.Row, player: sqlite3.Row, *, replay: bool = False
    ) -> ThreeRealmsTowerRunRecord:
        result = self._json_object(run["result_json"], {})
        return ThreeRealmsTowerRunRecord(
            player=self._row_to_player(player),
            run_id=str(run["run_id"]),
            tower_key=str(run["tower_key"]),
            floor_no=int(run["floor_no"]),
            status=str(run["status"]),
            battle_id=str(run["battle_id"]) if run["battle_id"] else None,
            first_clear=bool(run["first_clear"]),
            outcome=str(result["outcome"]) if result.get("outcome") else None,
            reason=str(result["reason"]) if result.get("reason") else None,
            reward={str(key): int(value) for key, value in json.loads(run["reward_json"]).items()}
            if str(run["status"]) == "reward_pending" else {},
            already_completed=replay,
        )

    def _three_realms_tower_reward_from_payload(
        self, payload: dict[str, Any], *, replay: bool = False
    ) -> ThreeRealmsTowerRewardRecord:
        return ThreeRealmsTowerRewardRecord(
            player=self._row_to_player(payload["player"]),
            run_id=str(payload["run_id"]),
            floor_no=int(payload["floor_no"]),
            first_clear=bool(payload["first_clear"]),
            faction=str(payload.get("faction", "")),
            reward={str(key): int(value) for key, value in dict(payload.get("reward", {})).items()},
            already_completed=replay,
        )

    @staticmethod
    def _insert_three_realms_tower_operation(
        connection: sqlite3.Connection,
        operation_id: str,
        operation_name: str,
        player_id: int,
        request_hash: str,
        payload: dict[str, Any],
        now_text: str,
    ) -> None:
        connection.execute(
            "INSERT INTO operations(operation_id,operation_name,player_id,request_hash,result_json,created_at) "
            "VALUES (?,?,?,?,?,?)",
            (
                operation_id,
                operation_name,
                player_id,
                request_hash,
                json.dumps(payload, ensure_ascii=False, sort_keys=True),
                now_text,
            ),
        )


__all__ = ["ThreeRealmsTowerRepositoryMixin"]
