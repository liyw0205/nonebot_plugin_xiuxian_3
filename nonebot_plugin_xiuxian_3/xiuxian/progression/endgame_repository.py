"""SQLite transactions for the non-combat v0.6 endgame progression slice."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from uuid import uuid4

from ...contracts import serialize_datetime
from .endgame_models import (
    DaoUnionRecord,
    EndgameEndingRecord,
    FinalBattlePreviewRecord,
    TribulationEntryRecord,
    TrialSessionRecord,
    TrialSettlementRecord,
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
    FRUIT_KEYS,
    RULE_VERSION,
    REMAINED_IN_WORLD_STATUS,
    TRIBULATION_TRIAL_DURATION_SECONDS,
    TRIBULATION_TOTAL_CULTIVATION,
    TRIBULATION_WORLD_MERIT_REWARD,
    THREE_REALM_KEYS,
    TRIAL_ORDER,
    fruit_for_path,
    trial_definition,
    trial_roll_bp,
    trial_success,
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
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
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
            if str(row["endgame_status"]) != ASCENSION_READY_STATUS:
                raise AscensionRequirementError("player is not ready for an ending")
            fruit_key = str(row["dao_fruit_key"] or "") or None
            if ending_key == "remain_in_world" and not fruit_key:
                raise AscensionRequirementError("remain in world requires a locked dao fruit")
            status = ASCENDED_STATUS if ending_key == "ascend" else REMAINED_IN_WORLD_STATUS
            connection.execute(
                "UPDATE players SET endgame_status = ?, ending_key = ?, updated_at = ? WHERE id = ?",
                (status, ending_key, now_text, row["id"]),
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
                runtime_open=False,
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
            ThreeRealmReputationInsufficientError,
            TribulationCooldownError,
            TribulationDebtBlockedError,
            TribulationTokenInsufficientError,
            TrialSequenceError,
            TribulationTrialBusyError,
        )

        if trial_key not in TRIAL_ORDER:
            raise TrialSequenceError("unknown tribulation trial")
        definition = trial_definition(trial_key)
        operation_name = "tribulation.start_trial"
        request_hash = self._request_hash(
            operation_name,
            {"platform": platform, "platform_user_id": platform_user_id, "trial_key": trial_key, "choice_key": choice_key},
        )
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id = ?", (operation_id,)
            ).fetchone()
            if existing is not None:
                if existing["operation_name"] != operation_name or existing["request_hash"] != request_hash:
                    raise OperationConflictError("operation input differs from its original request")
                payload = json.loads(existing["result_json"])
                return TrialSessionRecord(
                    player=self._row_to_player(payload["player"]),
                    session_id=str(payload["session_id"]),
                    trial_key=str(payload["trial_key"]),
                    choice_key=payload.get("choice_key"),
                    status=str(payload["status"]),
                    starts_at=str(payload["starts_at"]),
                    ends_at=str(payload["ends_at"]),
                    debt_before=int(payload.get("debt_before", 0)),
                    already_completed=True,
                )
            row = self._require_player(connection, platform, platform_user_id)
            if str(row["realm_key"]) != "tribulation" or int(row["realm_layer"]) < definition.required_layer:
                raise TrialSequenceError("tribulation layer is insufficient")
            if int(row["tribulation_debt"]) >= 100:
                raise TribulationDebtBlockedError("tribulation debt is too high")
            if connection.execute(
                "SELECT 1 FROM tribulation_trial_sessions WHERE player_id=? AND status='preparing' LIMIT 1", (row["id"],)
            ).fetchone() is not None:
                raise TribulationTrialBusyError("tribulation trial is already preparing")
            if connection.execute(
                "SELECT 1 FROM endgame_sessions WHERE player_id=? AND status='preparing' LIMIT 1", (row["id"],)
            ).fetchone() is not None:
                raise TribulationTrialBusyError("an endgame recipe is already preparing")
            if connection.execute(
                "SELECT 1 FROM travel_sessions WHERE player_id=? AND status='running' LIMIT 1", (row["id"],)
            ).fetchone() is not None:
                raise TribulationTrialBusyError("travel is already running")
            if str(row["location_key"]) != "tribulation.sky_terrace":
                raise LocationRequirementError("tribulation trial requires the sky terrace")
            previous = connection.execute(
                "SELECT trial_key, status, result_json FROM tribulation_trial_sessions WHERE player_id=? ORDER BY id",
                (row["id"],),
            ).fetchall()
            successful = {str(item["trial_key"]) for item in previous if str(item["status"]) == "succeeded"}
            index = TRIAL_ORDER.index(trial_key)
            if trial_key in successful:
                raise TrialSequenceError("tribulation trial has already succeeded")
            if any(required not in successful for required in TRIAL_ORDER[:index]):
                raise TrialSequenceError("tribulation trials must be completed in order")
            last_failed = next((item for item in reversed(previous) if str(item["trial_key"]) == trial_key and str(item["status"]) == "failed"), None)
            if last_failed is not None:
                result = self._json_object(last_failed["result_json"], {})
                cooldown_until = result.get("cooldown_until")
                if cooldown_until:
                    try:
                        if now < datetime.fromisoformat(str(cooldown_until)):
                            raise TribulationCooldownError("tribulation trial cooldown is active")
                    except ValueError:
                        pass
            if trial_key == "trial.dao_choice":
                if int(row["dao_fruit_progress"]) < 280:
                    raise TrialSequenceError("dao fruit progress is insufficient")
                fruit_key = fruit_for_path(row["path_key"])
                if not choice_key or choice_key not in FRUIT_KEYS or choice_key != fruit_key:
                    raise DaoFruitChoiceError("dao fruit does not match the primary path")
                if row["dao_fruit_key"]:
                    raise DaoFruitChoiceError("dao fruit is already locked")
            if trial_key == "trial.three_realms":
                reputation = self._json_object(row["faction_reputation_json"], {})
                reputation_row = connection.execute(
                    "SELECT local_json FROM player_reputations WHERE player_id = ?", (row["id"],)
                ).fetchone()
                if reputation_row is not None:
                    for key, value in self._json_object(reputation_row["local_json"], {}).items():
                        if str(key).startswith("faction."):
                            reputation[str(key).split(".", 1)[1]] = int(value)
                if any(int(reputation.get(key, 0)) < 2_000 for key in THREE_REALM_KEYS):
                    raise ThreeRealmReputationInsufficientError("three realm reputation is insufficient")
            inventory = self._json_object(row["inventory_json"], {})
            if int(inventory.get("item.tribulation_token", 0)) < definition.token_cost:
                raise TribulationTokenInsufficientError("tribulation token is insufficient")
            inventory["item.tribulation_token"] = int(inventory["item.tribulation_token"]) - definition.token_cost
            if inventory["item.tribulation_token"] == 0:
                inventory.pop("item.tribulation_token")
            guard_used = int(inventory.get("item.tribulation_guard", 0)) > 0
            if guard_used:
                inventory["item.tribulation_guard"] = int(inventory["item.tribulation_guard"]) - 1
                if inventory["item.tribulation_guard"] == 0:
                    inventory.pop("item.tribulation_guard")
            session_id = uuid4().hex
            ends_at = serialize_datetime(now + timedelta(seconds=TRIBULATION_TRIAL_DURATION_SECONDS))
            snapshot = {
                "trial_key": trial_key,
                "choice_key": choice_key,
                "random_pool": definition.random_pool,
                "random_seed": operation_id,
                "content_version": CONTENT_VERSION,
                "rule_version": RULE_VERSION,
                "debt_before": int(row["tribulation_debt"]),
                "progress_before": int(row["dao_fruit_progress"]),
                "guard_used": guard_used,
            }
            connection.execute(
                "UPDATE players SET inventory_json=?, updated_at=? WHERE id=?",
                (json.dumps(inventory, ensure_ascii=False, sort_keys=True), now_text, row["id"]),
            )
            connection.execute(
                "INSERT INTO tribulation_trial_sessions(session_id, player_id, operation_id, trial_key, choice_key, status, starts_at, ends_at, snapshot_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 'preparing', ?, ?, ?, ?, ?)",
                (session_id, row["id"], operation_id, trial_key, choice_key, now_text, ends_at, json.dumps(snapshot, ensure_ascii=False, sort_keys=True), now_text, now_text),
            )
            updated = connection.execute("SELECT * FROM players WHERE id=?", (row["id"],)).fetchone()
            player = self._row_to_player(updated)
            payload = {
                "player": self._player_payload(player),
                "session_id": session_id,
                "trial_key": trial_key,
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
            return TrialSessionRecord(
                player=player,
                session_id=session_id,
                trial_key=trial_key,
                choice_key=choice_key,
                status="preparing",
                starts_at=now_text,
                ends_at=ends_at,
                debt_before=int(row["tribulation_debt"]),
            )

    async def settle_tribulation_trial(self, *, platform: str, platform_user_id: str, operation_id: str) -> TrialSettlementRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._settle_tribulation_trial_once, platform, platform_user_id, operation_id)

    def _settle_tribulation_trial_once(self, platform: str, platform_user_id: str, operation_id: str) -> TrialSettlementRecord:
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
                "SELECT * FROM tribulation_trial_sessions WHERE player_id=? AND status='preparing' ORDER BY id DESC LIMIT 1", (row["id"],)
            ).fetchone()
            if session is None:
                raise TribulationTrialNotFoundError("no preparing tribulation trial")
            if now < datetime.fromisoformat(str(session["ends_at"])):
                raise TribulationTrialNotReadyError("tribulation trial is not ready")
            snapshot = self._json_object(session["snapshot_json"], {})
            trial_key = str(session["trial_key"])
            definition = trial_definition(trial_key)
            roll_bp = trial_roll_bp(str(snapshot.get("random_seed", session["operation_id"])))
            success = trial_success(trial_key, roll_bp)
            debt_delta = 0 if success else max(0, definition.debt_delta - (5 if snapshot.get("guard_used") else 0))
            progress = definition.progress_reward if success else 0
            merit = definition.merit_reward if success else 0
            world_merit = TRIBULATION_WORLD_MERIT_REWARD[trial_key] if success else 0
            reward_items = {"item.dao_fruit_fragment": 1} if success and trial_key == "trial.body_and_mind" else {}
            inventory = self._json_object(row["inventory_json"], {})
            if success and snapshot.get("guard_used"):
                inventory["item.tribulation_guard"] = int(inventory.get("item.tribulation_guard", 0)) + 1
            for key, value in reward_items.items():
                inventory[key] = int(inventory.get(key, 0)) + value
            fruit_key = str(snapshot.get("choice_key")) if success and trial_key == "trial.dao_choice" else None
            new_progress = min(1300, int(row["dao_fruit_progress"]) + progress)
            new_debt = int(row["tribulation_debt"]) + debt_delta
            cooldown_until = serialize_datetime(now + timedelta(seconds=definition.cooldown_seconds)) if not success else None
            if success and fruit_key:
                connection.execute(
                    "UPDATE players SET dao_fruit_progress=?, ascension_merit=ascension_merit+?, world_merit=world_merit+?, dao_fruit_key=?, inventory_json=?, updated_at=? WHERE id=?",
                    (new_progress, merit, world_merit, fruit_key, json.dumps(inventory, ensure_ascii=False, sort_keys=True), now_text, row["id"]),
                )
            else:
                connection.execute(
                    "UPDATE players SET dao_fruit_progress=?, ascension_merit=ascension_merit+?, world_merit=world_merit+?, tribulation_debt=?, inventory_json=?, updated_at=? WHERE id=?",
                    (new_progress, merit, world_merit, new_debt, json.dumps(inventory, ensure_ascii=False, sort_keys=True), now_text, row["id"]),
                )
            result = {
                "success": success,
                "roll_bp": roll_bp,
                "debt_delta": debt_delta,
                "reward_progress": progress,
                "reward_merit": merit,
                "reward_world_merit": world_merit,
                "reward_items": reward_items,
                "dao_fruit_key": fruit_key,
                "cooldown_until": cooldown_until,
                "status": "succeeded" if success else "failed",
            }
            connection.execute(
                "UPDATE tribulation_trial_sessions SET status=?, result_json=?, updated_at=? WHERE id=?",
                (result["status"], json.dumps(result, ensure_ascii=False, sort_keys=True), now_text, session["id"]),
            )
            updated = connection.execute("SELECT * FROM players WHERE id=?", (row["id"],)).fetchone()
            if updated is None:
                raise RuntimeError("tribulation settlement returned no player")
            payload = {"player": self._player_payload(self._row_to_player(updated)), "session_id": session["session_id"], "trial_key": trial_key, **result}
            connection.execute(
                "INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (operation_id, operation_name, row["id"], request_hash, json.dumps(payload, ensure_ascii=False, sort_keys=True), now_text),
            )
            return self._trial_settlement_from_payload(payload, replay=False)

    @staticmethod
    def _trial_settlement_from_payload(payload: dict, *, replay: bool) -> TrialSettlementRecord:
        from ..repository import SQLitePlayerRepository

        return TrialSettlementRecord(
            player=SQLitePlayerRepository._row_to_player(payload["player"]),
            session_id=str(payload["session_id"]),
            trial_key=str(payload["trial_key"]),
            status=str(payload.get("status", "failed")),
            success=bool(payload.get("success", False)),
            roll_bp=int(payload.get("roll_bp", 0)),
            debt_delta=int(payload.get("debt_delta", 0)),
            reward_progress=int(payload.get("reward_progress", 0)),
            reward_merit=int(payload.get("reward_merit", 0)),
            reward_world_merit=int(payload.get("reward_world_merit", 0)),
            reward_items={str(key): int(value) for key, value in dict(payload.get("reward_items", {})).items()},
            dao_fruit_key=payload.get("dao_fruit_key"),
            already_completed=replay,
        )

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
