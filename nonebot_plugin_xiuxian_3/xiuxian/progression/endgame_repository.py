"""SQLite transactions for the non-combat v0.6 endgame progression slice."""

from __future__ import annotations

import asyncio
import json

from ...contracts import serialize_datetime
from .endgame_models import (
    DaoUnionRecord,
    EndgameEndingRecord,
    FinalBattlePreviewRecord,
    TribulationEntryRecord,
)
from .endgame_rules import (
    ASCENDED_STATUS,
    ASCENSION_CERTIFICATE_KEY,
    ASCENSION_READY_STATUS,
    CONTENT_VERSION,
    DAO_UNION_FRAGMENT_COST,
    DAO_UNION_MERIT_COST,
    DAO_UNION_STONE_COST,
    DAO_UNION_TOTAL_CULTIVATION,
    ENDING_KEYS,
    FINAL_BATTLE_MIN_MERIT,
    FINAL_BATTLE_MIN_PROGRESS,
    RULE_VERSION,
    REMAINED_IN_WORLD_STATUS,
    TRIBULATION_TOTAL_CULTIVATION,
    TRIAL_ORDER,
)


class EndgameRepositoryMixin:
    """Persistence operations for 合道 and the ordered tribulation trials."""

    async def begin_dao_union(self, *, platform: str, platform_user_id: str, operation_id: str) -> DaoUnionRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._begin_dao_union_once, platform, platform_user_id, operation_id)

    def _begin_dao_union_once(self, platform: str, platform_user_id: str, operation_id: str) -> DaoUnionRecord:
        from ..repository import (
            DaoUnionRequirementError,
            MaterialInsufficientError,
            CurrencyInsufficientError,
            OperationConflictError,
            PlayerSuspendedError,
        )

        operation_name = "progression.begin_dao_union"
        request_hash = self._request_hash(operation_name, {"platform": platform, "platform_user_id": platform_user_id})
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id = ?", (operation_id,)
            ).fetchone()
            if existing is not None:
                if existing["operation_name"] != operation_name or existing["request_hash"] != request_hash:
                    raise OperationConflictError("operation input differs from its original request")
                payload = json.loads(existing["result_json"])
                return DaoUnionRecord(
                    player=self._row_to_player(payload["player"]),
                    changed=bool(payload.get("changed", True)),
                    already_completed=True,
                )
            row = self._require_player(connection, platform, platform_user_id)
            if str(row["status"]) != "active":
                raise PlayerSuspendedError("player is not active")
            if str(row["realm_key"]) != "void_refining" or int(row["realm_layer"]) != 10:
                raise DaoUnionRequirementError("dao union requires void refining L10")
            if int(row["total_cultivation"]) < DAO_UNION_TOTAL_CULTIVATION:
                raise DaoUnionRequirementError("total cultivation is insufficient")
            flags = set(str(item) for item in self._json_object(row["intro_json"], {}).get("flags", []))
            if "quest.dao_union" not in flags:
                raise DaoUnionRequirementError("dao union quest is missing")
            from ..quests.rules import DAO_UNION_CHALLENGE, DAO_UNION_MAINLINE, DAO_UNION_QUEST, DAO_UNION_WORK

            qualification_counts = {
                component: (
                    self._valid_dao_union_mainline_event_count(connection, int(row["id"]))
                    if component == DAO_UNION_MAINLINE
                    else self._event_count(connection, int(row["id"]), DAO_UNION_QUEST, component)
                )
                for component in (DAO_UNION_MAINLINE, DAO_UNION_CHALLENGE, DAO_UNION_WORK)
            }
            if any(count < 1 for count in qualification_counts.values()):
                raise DaoUnionRequirementError("dao union evidence is incomplete or invalid")
            inventory = self._json_object(row["inventory_json"], {})
            if int(inventory.get("item.dao_fruit_fragment", 0)) < DAO_UNION_FRAGMENT_COST:
                raise MaterialInsufficientError("dao fruit fragments are insufficient")
            if int(row["world_merit"]) < DAO_UNION_MERIT_COST:
                raise DaoUnionRequirementError("world merit is insufficient")
            if int(row["spirit_stones"]) < DAO_UNION_STONE_COST:
                raise CurrencyInsufficientError("spirit stones are insufficient")
            inventory["item.dao_fruit_fragment"] = int(inventory["item.dao_fruit_fragment"]) - DAO_UNION_FRAGMENT_COST
            if inventory["item.dao_fruit_fragment"] == 0:
                inventory.pop("item.dao_fruit_fragment")
            intro = self._json_object(row["intro_json"], {})
            flags.add("endgame.dao_union")
            flags.update({"fruit.clue.body", "fruit.clue.spell", "fruit.clue.support"})
            intro["flags"] = sorted(flags)
            connection.execute(
                "UPDATE players SET realm_key='dao_union', realm_layer=1, cultivation=0, inventory_json=?, world_merit=world_merit-?, spirit_stones=spirit_stones-?, intro_json=?, endgame_status='dao_union', updated_at=? WHERE id=?",
                (
                    json.dumps(inventory, ensure_ascii=False, sort_keys=True),
                    DAO_UNION_MERIT_COST,
                    DAO_UNION_STONE_COST,
                    json.dumps(intro, ensure_ascii=False, sort_keys=True),
                    now_text,
                    row["id"],
                ),
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (row["id"],)).fetchone()
            if updated is None:
                raise RuntimeError("dao union returned no player")
            player = self._row_to_player(updated)
            payload = {"player": self._player_payload(player), "changed": True}
            connection.execute(
                "INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (operation_id, operation_name, row["id"], request_hash, json.dumps(payload, ensure_ascii=False, sort_keys=True), now_text),
            )
            return DaoUnionRecord(player=player, changed=True)

    async def choose_ending(
        self,
        *,
        platform: str,
        platform_user_id: str,
        ending_key: str,
        operation_id: str,
    ) -> EndgameEndingRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._choose_ending_once,
                platform,
                platform_user_id,
                ending_key,
                operation_id,
            )

    def _choose_ending_once(
        self,
        platform: str,
        platform_user_id: str,
        ending_key: str,
        operation_id: str,
    ) -> EndgameEndingRecord:
        ending_key = ending_key.strip().lower()
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            return self._choose_ending_in_transaction(
                connection,
                platform=platform,
                platform_user_id=platform_user_id,
                ending_key=ending_key,
                operation_id=operation_id,
                now_text=now_text,
            )

    def _choose_ending_in_transaction(
        self,
        connection,
        *,
        platform: str,
        platform_user_id: str,
        ending_key: str,
        operation_id: str,
        now_text: str,
        allow_final_battle: bool = False,
    ) -> EndgameEndingRecord:
        from ..repository import (
            AscensionRequirementError,
            EndingAlreadyChosenError,
            EndingInvalidError,
            OperationConflictError,
            PlayerSuspendedError,
        )

        ending_key = ending_key.strip().lower()
        if ending_key not in ENDING_KEYS:
            raise EndingInvalidError("unsupported ending key")
        operation_name = "ascension.choose_ending"
        request_hash = self._request_hash(
            operation_name,
            {
                "platform": platform,
                "platform_user_id": platform_user_id,
                "ending_key": ending_key,
                "content_version": CONTENT_VERSION,
                "rule_version": RULE_VERSION,
            },
        )
        existing = connection.execute(
            "SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id = ?",
            (operation_id,),
        ).fetchone()
        if existing is not None:
            if existing["operation_name"] != operation_name or existing["request_hash"] != request_hash:
                raise OperationConflictError("operation input differs from its original request")
            return self._ending_from_payload(json.loads(existing["result_json"]), replay=True)

        row = self._require_player(connection, platform, platform_user_id, writable=False)
        if str(row["status"]) != "active":
            raise PlayerSuspendedError("player is not active")
        current_key = str(row["ending_key"] or "")
        if current_key:
            if current_key != ending_key:
                raise EndingAlreadyChosenError("a different ending has already been chosen")
            payload = self._ending_payload(row, ending_key=current_key, status=str(row["endgame_status"]))
            connection.execute(
                "INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (operation_id, operation_name, row["id"], request_hash, json.dumps(payload, ensure_ascii=False, sort_keys=True), now_text),
            )
            return self._ending_from_payload(payload, replay=True)
        fruit_key = str(row["dao_fruit_key"] or "") or None
        if allow_final_battle and str(row["endgame_status"]) == "tribulation" and ending_key == "remain_in_world":
            if not fruit_key:
                raise AscensionRequirementError("remain in world requires a locked dao fruit")
            connection.execute(
                "UPDATE players SET endgame_status=?, location_key='ascension.heaven_path', updated_at=? WHERE id=?",
                (ASCENSION_READY_STATUS, now_text, row["id"]),
            )
            row = connection.execute("SELECT * FROM players WHERE id=?", (row["id"],)).fetchone()
        if str(row["endgame_status"]) != ASCENSION_READY_STATUS:
            raise AscensionRequirementError("player is not ready for an ending")
        if ending_key == "remain_in_world" and not fruit_key:
            raise AscensionRequirementError("remain in world requires a locked dao fruit")
        status = ASCENDED_STATUS if ending_key == "ascend" else REMAINED_IN_WORLD_STATUS
        inventory = self._json_object(row["inventory_json"], {})
        inventory["item.title.ascended"] = max(1, int(inventory.get("item.title.ascended", 0)))
        connection.execute(
            "UPDATE players SET endgame_status = ?, ending_key = ?, inventory_json = ?, updated_at = ? WHERE id = ?",
            (status, ending_key, json.dumps(inventory, ensure_ascii=False, sort_keys=True), now_text, row["id"]),
        )
        updated = connection.execute("SELECT * FROM players WHERE id = ?", (row["id"],)).fetchone()
        if updated is None:
            raise RuntimeError("ending choice returned no player")
        payload = self._ending_payload(updated, ending_key=ending_key, status=status)
        connection.execute(
            "INSERT INTO endgame_endings(player_id, ending_key, status, fruit_key, snapshot_json, operation_id, content_version, rule_version, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                updated["id"],
                ending_key,
                status,
                fruit_key,
                json.dumps(payload["snapshot"], ensure_ascii=False, sort_keys=True),
                operation_id,
                CONTENT_VERSION,
                RULE_VERSION,
                now_text,
            ),
        )
        connection.execute(
            "INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (operation_id, operation_name, updated["id"], request_hash, json.dumps(payload, ensure_ascii=False, sort_keys=True), now_text),
        )
        return self._ending_from_payload(payload, replay=False)

    async def preview_final_battle(
        self,
        *,
        platform: str,
        platform_user_id: str,
    ) -> FinalBattlePreviewRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._preview_final_battle_once,
                platform,
                platform_user_id,
            )

    def _preview_final_battle_once(
        self,
        platform: str,
        platform_user_id: str,
    ) -> FinalBattlePreviewRecord:
        from ..repository import PlayerSuspendedError

        with self._connect() as connection:
            row = self._require_player(connection, platform, platform_user_id, writable=False)
            if str(row["status"]) != "active":
                raise PlayerSuspendedError("player is not active")
            completed = tuple(
                str(item["trial_key"])
                for item in connection.execute(
                    "SELECT trial_key FROM tribulation_trial_sessions "
                    "WHERE player_id = ? AND status = 'succeeded' ORDER BY id",
                    (row["id"],),
                ).fetchall()
            )
            completed_set = set(completed)
            inventory = self._json_object(row["inventory_json"], {})
            missing: list[str] = []
            if str(row["realm_key"]) != "tribulation" or int(row["realm_layer"]) != 10:
                missing.append("TRIBULATION_L10_REQUIRED")
            if not set(TRIAL_ORDER).issubset(completed_set):
                missing.append("TRIBULATION_TRIALS_INCOMPLETE")
            if int(row["dao_fruit_progress"]) < FINAL_BATTLE_MIN_PROGRESS:
                missing.append("DAO_FRUIT_PROGRESS_INSUFFICIENT")
            if int(row["ascension_merit"]) < FINAL_BATTLE_MIN_MERIT:
                missing.append("ASCENSION_MERIT_INSUFFICIENT")
            if int(row["tribulation_debt"]) >= 100:
                missing.append("TRIBULATION_DEBT_BLOCKED")
            certificate_count = int(inventory.get(ASCENSION_CERTIFICATE_KEY, 0))
            if certificate_count < 1:
                missing.append("ASCENSION_CERTIFICATE_MISSING")
            if str(row["endgame_status"] or "none") == ASCENSION_READY_STATUS:
                missing = []
            return FinalBattlePreviewRecord(
                player=self._row_to_player(row),
                ready=not missing,
                missing=tuple(missing),
                trial_keys=completed,
                certificate_count=certificate_count,
                runtime_open=True,
            )

    async def begin_tribulation(self, *, platform: str, platform_user_id: str, operation_id: str) -> TribulationEntryRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._begin_tribulation_once, platform, platform_user_id, operation_id)

    def _begin_tribulation_once(self, platform: str, platform_user_id: str, operation_id: str) -> TribulationEntryRecord:
        from ..repository import OperationConflictError, TribulationEntryRequirementError, PlayerSuspendedError

        operation_name = "progression.begin_tribulation"
        request_hash = self._request_hash(operation_name, {"platform": platform, "platform_user_id": platform_user_id})
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id = ?", (operation_id,)
            ).fetchone()
            if existing is not None:
                if existing["operation_name"] != operation_name or existing["request_hash"] != request_hash:
                    raise OperationConflictError("operation input differs from its original request")
                payload = json.loads(existing["result_json"])
                return TribulationEntryRecord(player=self._row_to_player(payload["player"]), changed=True, already_completed=True)
            row = self._require_player(connection, platform, platform_user_id)
            if str(row["status"]) != "active":
                raise PlayerSuspendedError("player is not active")
            if str(row["realm_key"]) != "dao_union" or int(row["realm_layer"]) != 10:
                raise TribulationEntryRequirementError("tribulation requires dao union L10")
            if int(row["total_cultivation"]) < TRIBULATION_TOTAL_CULTIVATION:
                raise TribulationEntryRequirementError("total cultivation is insufficient")
            connection.execute(
                "UPDATE players SET realm_key='tribulation', realm_layer=1, cultivation=0, endgame_status='tribulation', updated_at=? WHERE id=?",
                (now_text, row["id"]),
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (row["id"],)).fetchone()
            if updated is None:
                raise RuntimeError("tribulation entry returned no player")
            player = self._row_to_player(updated)
            payload = {"player": self._player_payload(player), "changed": True}
            connection.execute(
                "INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (operation_id, operation_name, row["id"], request_hash, json.dumps(payload, ensure_ascii=False, sort_keys=True), now_text),
            )
            return TribulationEntryRecord(player=player, changed=True)

    @staticmethod
    def _ending_payload(row, *, ending_key: str, status: str) -> dict:
        from ..repository import SQLitePlayerRepository

        player = SQLitePlayerRepository._row_to_player(row)
        player_payload = SQLitePlayerRepository._player_payload(player)
        return {
            "player": player_payload,
            "ending_key": ending_key,
            "status": status,
            "fruit_key": player.dao_fruit_key,
            "snapshot": player_payload,
            "content_version": CONTENT_VERSION,
            "rule_version": RULE_VERSION,
        }

    @staticmethod
    def _ending_from_payload(payload: dict, *, replay: bool) -> EndgameEndingRecord:
        from ..repository import SQLitePlayerRepository

        return EndgameEndingRecord(
            player=SQLitePlayerRepository._row_to_player(payload["player"]),
            ending_key=str(payload["ending_key"]),
            status=str(payload["status"]),
            already_completed=replay,
        )


__all__ = ["EndgameRepositoryMixin"]
