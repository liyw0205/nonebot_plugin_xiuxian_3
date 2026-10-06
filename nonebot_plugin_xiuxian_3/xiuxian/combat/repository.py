"""SQLite transactions for server-authoritative automatic battle sessions."""

from __future__ import annotations

import asyncio
from copy import deepcopy
import json
import sqlite3
import time
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from ...contracts import serialize_datetime
from ..content import ContentError, bundled_content
from ..advancement.constitution_effects import constitution_effect_snapshot
from ..items.manual_rules import manual_effect_totals
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
    QuestWeeklyLimitError,
    RepositoryBusyError,
)
from .models import (
    BattleReplayRecord,
    BattleResolutionRecord,
    BattleRewardClaimRecord,
    BattleStartRecord,
    BattleTurnRecord,
    SpectatorPreviewRecord,
)
from .skill_effects import (
    apply_player_skill_style,
    mitigate_enemy_attack,
    mitigate_player_damage,
    prepare_skill_action,
    reflected_enemy_damage,
)
from .rules import (
    ANCESTRAL_SPIRIT,
    DEMON_WAR_FRONT,
    MAX_TURNS,
    TURN_TIMEOUT_SECONDS,
    battle_roll_bp,
    enemy_definition,
    hit_chance_bp,
    player_goes_first,
    player_stat_snapshot,
)
from .spectator_rules import (
    public_spectator_summary,
    simulate_spectator_match,
    spar_definition,
    spectator_seed,
    training_dummy_preview_rounds,
)
from .tribulation_rules import PROFILE_KEY, phase_for_hp
from ..specials.codex_projection import record_codex_discovery, record_material_discoveries
from ..utils.player import grant_player_state, player_combat_values, player_realm_values
from ..utils.equipment import equipment_instance_rows


class CombatRepositoryMixin:
    """Persist every automatic combat transition as an independently replayable write."""

    async def preview_training_dummy(
        self, *, platform: str, platform_user_id: str
    ) -> SpectatorPreviewRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._retry_sync, self._preview_training_dummy_once, platform, platform_user_id
            )

    async def preview_player_spar(
        self, *, platform: str, platform_user_id: str, target_ref: str
    ) -> SpectatorPreviewRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._retry_sync,
                self._preview_player_spar_once,
                platform,
                platform_user_id,
                target_ref,
            )

    async def start_quest_battle(
        self,
        *,
        platform: str,
        platform_user_id: str,
        enemy_key: str,
        battle_type: str,
        operation_id: str,
        ignore_secret_realm_run_id: str | None = None,
        ignore_tower_run_id: str | None = None,
        ignore_void_spire_run_id: str | None = None,
        ignore_ancestral_hall_run_id: str | None = None,
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
                None,
                ignore_secret_realm_run_id,
                ignore_tower_run_id,
                ignore_void_spire_run_id,
                ignore_ancestral_hall_run_id,
            )

    async def start_demon_war_front_battle(
        self, *, platform: str, platform_user_id: str, operation_id: str
    ) -> BattleStartRecord:
        """Start the fixed, rewardless war-front encounter."""

        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._retry_sync,
                self._start_training_battle_once,
                platform,
                platform_user_id,
                operation_id,
                DEMON_WAR_FRONT.key,
                "pve.demon_war_front",
            )

    async def start_domain_front_battle(
        self,
        *,
        platform: str,
        platform_user_id: str,
        operation_id: str,
        event_operation_id: str,
    ) -> BattleStartRecord:
        """Start a domain-front battle and bind its round in the same transaction."""

        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._retry_sync,
                self._start_training_battle_once,
                platform,
                platform_user_id,
                operation_id,
                "enemy.domain_front_guardian",
                "pve.domain_front",
                None,
                None,
                None,
                None,
                None,
                event_operation_id,
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

    async def expire_battle_session(self, *, battle_id: str, reason: str) -> bool:
        """Close an unstarted automatic battle when its owning activity expires."""

        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._retry_sync, self._expire_battle_session_sync, battle_id, reason
            )

    def _expire_battle_session_sync(self, battle_id: str, reason: str) -> bool:
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            session = connection.execute(
                "SELECT status, result_json FROM battle_sessions WHERE battle_id=?",
                (battle_id,),
            ).fetchone()
            if session is None or str(session["status"]) == "settled":
                return False
            if str(session["status"]) in {"created", "running"}:
                result = self._json_object(session["result_json"], {})
                result.update({"outcome": "expired", "reason": reason})
                connection.execute(
                    "UPDATE battle_sessions SET status='expired', result_json=?, updated_at=? "
                    "WHERE battle_id=? AND status IN ('created','running')",
                    (json.dumps(result, ensure_ascii=False, sort_keys=True), now_text, battle_id),
                )
            return True

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
        enemy_key: str,
        battle_type: str,
        exploration_id: str | None = None,
        ignore_secret_realm_run_id: str | None = None,
        ignore_tower_run_id: str | None = None,
        ignore_void_spire_run_id: str | None = None,
        ignore_ancestral_hall_run_id: str | None = None,
        domain_front_operation_id: str | None = None,
    ) -> BattleStartRecord:
        operation_name = f"battle.start.{battle_type}"
        request_payload = {
            "platform": platform,
            "platform_user_id": platform_user_id,
            "enemy_key": enemy_key,
            "battle_type": battle_type,
            "exploration_id": exploration_id,
        }
        if domain_front_operation_id is not None:
            request_payload["domain_front_operation_id"] = domain_front_operation_id
        request_hash = self._request_hash(operation_name, request_payload)
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

            content = getattr(self, "content", None)
            enemy = enemy_definition(enemy_key, content=content)

            if battle_type == "pve.demon_war_front":
                from ..events.demon_rules import DEMON_EVENT_KEY
                from ..events.public_event_rules import public_event_is_open
                from ..persistence.errors import EventNotActiveError

                if not public_event_is_open(DEMON_EVENT_KEY, now, content):
                    raise EventNotActiveError("demon invasion war front is closed")

            player = self._require_player(connection, platform, platform_user_id)
            domain_front_round_id = None
            if battle_type == "pve.domain_front":
                if not domain_front_operation_id:
                    raise ValueError("domain-front battle requires its event operation")
                event = self._domain_refresh_round(
                    connection,
                    self._domain_select_round(connection, None, now),
                    now,
                )
                self._domain_require_open(event, now)
                self._domain_require_participant(
                    connection, int(player["id"]), str(event["round_id"])
                )
                domain_front_round_id = str(event["round_id"])
            elif domain_front_operation_id is not None:
                raise ValueError("event operation is only valid for domain-front battles")
            player_state = player_combat_values(player)
            if battle_type == "pve.void_wall_trial":
                from ..quests.rules import (
                    VOID_QUEST,
                    VOID_TRIAL_WEEKLY_LIMIT,
                    VOID_WALL_TRIAL,
                    utc_week_bounds,
                )

                week_start, week_end = utc_week_bounds(now)
                trial_count = connection.execute(
                    """
                    SELECT COUNT(*) AS count FROM quest_events
                    WHERE player_id = ? AND quest_key = ? AND component_key = ?
                      AND substr(created_at, 1, 10) >= ? AND substr(created_at, 1, 10) < ?
                    """,
                    (
                        player["id"],
                        VOID_QUEST,
                        VOID_WALL_TRIAL,
                        week_start.isoformat(),
                        week_end.isoformat(),
                    ),
                ).fetchone()
                if int(trial_count["count"]) >= VOID_TRIAL_WEEKLY_LIMIT:
                    raise QuestWeeklyLimitError("void wall trial weekly limit reached")
            if (
                player_state["location_key"] != enemy.location_key
                and exploration_id is None
                and battle_type not in {"pve.archive_keeper", "pve.tower"}
            ):
                raise BattleRequirementError("battle requires a specific location")
            cooldown = player["battle_defeat_until"]
            if cooldown and now < datetime.fromisoformat(str(cooldown)):
                raise BattleCooldownError("battle defeat cooldown is active")
            if self._has_active_long_action(
                connection,
                int(player["id"]),
                ignore_exploration_id=exploration_id,
                ignore_secret_realm_run_id=ignore_secret_realm_run_id,
                ignore_tower_run_id=ignore_tower_run_id,
                ignore_void_spire_run_id=ignore_void_spire_run_id,
                ignore_ancestral_hall_run_id=ignore_ancestral_hall_run_id,
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
            elif battle_type == "pve.tower":
                location_key = player_state["location_key"]
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
                else player_state["qualification"]
            )
            constitution_effect = (
                dict(exploration_snapshot.get("constitution_effect", {}))
                if exploration is not None
                else constitution_effect_snapshot(connection, int(player["id"]))
            )
            manual_effects = manual_effect_totals(
                player_state["inventory"], self.content
            )
            manual_stat_bonus = manual_effects["combat_stat_bonus_bp"]
            if not isinstance(manual_stat_bonus, dict):
                raise ValueError("manual combat stat bonuses must be an object")
            stats = player_stat_snapshot(
                qualification,
                max_hp=int(exploration_snapshot.get("max_hp", player_state["max_hp"])),
                initiative=int(exploration_snapshot.get("initiative", player_state["initiative"])),
                equipment=equipment,
                constitution_effect=constitution_effect,
                manual_stat_bonus_bp=manual_stat_bonus,
            )
            skills = self._battle_skill_snapshot(
                connection,
                int(player["id"]),
                str(player_state["path_key"] or ""),
            )
            companion_snapshot = (
                tuple(dict(item) for item in exploration_snapshot.get("companions", ()))
                if exploration is not None
                else self.companion_battle_snapshot(connection, int(player["id"])).companions
            )
            battle_id = uuid4().hex
            snapshot = {
                "battle_type": battle_type,
                "exploration_id": exploration_id,
                "location_key": location_key,
                "player": {
                    "player_id": player_state["player_id"],
                    "path_key": player_state["path_key"],
                    "qualification": qualification,
                    "stats": stats,
                    "constitution_effect": constitution_effect,
                    "manual_effects": manual_effects,
                    "equipment": list(equipment),
                    "skills": skills,
                    "companions": [dict(item) for item in companion_snapshot],
                    "cross_realm_penalty_bp": int(exploration_snapshot.get("cross_realm_penalty_bp", 0)),
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
            }
            state = {
                "round_no": 0,
                "player_hp": stats["max_hp"],
                "player_mana": stats["max_mana"],
                "enemy_hp": enemy.max_hp,
                "manual_reflect_damage_bp": min(
                    10_000,
                    int(manual_effects["damage_reflection_bp"])
                    + int(stats.get("damage_reflection_bp", 0)),
                ),
                "timeout_count": 0,
            }
            turn_deadline = serialize_datetime(now + timedelta(seconds=TURN_TIMEOUT_SECONDS))
            connection.execute(
                """
                INSERT INTO battle_sessions(
                    battle_id, player_id, start_operation_id, battle_type, enemy_key, location_key,
                    status, reward_status, round_no, action_sequence, starts_at, turn_deadline,
                    snapshot_json, state_json, result_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'created', 'none', 0, 0, ?, ?, ?, ?, '{}', ?, ?)
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
                    now_text,
                    now_text,
                ),
            )
            if domain_front_round_id is not None:
                connection.execute(
                    """
                    INSERT INTO domain_front_battle_links(
                        battle_id, round_id, player_id, event_operation_id,
                        combat_operation_id, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        battle_id,
                        domain_front_round_id,
                        player["id"],
                        domain_front_operation_id,
                        operation_id,
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

    def _preview_training_dummy_once(
        self, platform: str, platform_user_id: str
    ) -> SpectatorPreviewRecord:
        content = getattr(self, "content", None) or bundled_content()
        enemy = enemy_definition("enemy.training_dummy", content=content)
        max_rounds = training_dummy_preview_rounds(content)
        with self._connect() as connection:
            player = self._require_player(connection, platform, platform_user_id, writable=False)
            realm = player_realm_values(player)
            if (
                realm["location_key"] != enemy.location_key
                or not self._meets_enemy_requirement(player, enemy.required_realm, enemy.required_layer)
            ):
                raise BattleRequirementError("training dummy spectator requires its configured location and realm")
            player_snapshot, selected_skill = self._spectator_player_snapshot(connection, player)

        enemy_snapshot = {
            "dao_name": enemy.label,
            "path_key": "training_dummy",
            "realm_key": "mortal",
            "realm_layer": 0,
            "stats": {
                "max_hp": enemy.max_hp,
                "attack": enemy.attack,
                "initiative": enemy.initiative,
                "agility": enemy.agility,
            },
        }
        rules = {"enemy_key": enemy.key, "max_rounds": max_rounds, "random_pool": enemy.random_pool}
        seed = spectator_seed(
            participants={"player": player_snapshot, "enemy": enemy_snapshot}, rules=rules
        )
        outcome, rounds, actions = simulate_spectator_match(
            player_snapshot,
            enemy_snapshot,
            seed=seed,
            max_rounds=max_rounds,
            challenger_skill_key=selected_skill,
            defender_skill_key=enemy.skill_key,
            strategy_key="strategy.spectator.training_dummy",
        )
        return SpectatorPreviewRecord(
            outcome=outcome,
            rounds=rounds,
            snapshots={
                "player": public_spectator_summary(player_snapshot),
                "enemy": public_spectator_summary(enemy_snapshot),
            },
            actions=tuple(self._rename_spectator_sides(actions)),
        )

    def _preview_player_spar_once(
        self, platform: str, platform_user_id: str, target_ref: str
    ) -> SpectatorPreviewRecord:
        content = getattr(self, "content", None) or bundled_content()
        definition = spar_definition(content)
        with self._connect() as connection:
            challenger = self._require_player(connection, platform, platform_user_id, writable=False)
            target = target_ref.strip()
            defender = connection.execute(
                "SELECT * FROM players WHERE dao_name = ? OR player_id = ? LIMIT 1", (target, target)
            ).fetchone()
            if defender is None:
                raise PlayerNotFoundError("target player does not exist")
            if str(defender["status"]) != "active":
                raise PlayerSuspendedError("target player is not readable")
            if int(challenger["id"]) == int(defender["id"]):
                raise BattleRequirementError("cannot spectate a spar between the same player")
            if str(challenger["stage"]) != "cultivator" or str(defender["stage"]) != "cultivator":
                raise BattleRequirementError("spar spectator requires two active cultivators")
            challenger_snapshot, challenger_skill = self._spectator_player_snapshot(connection, challenger)
            defender_snapshot, defender_skill = self._spectator_player_snapshot(connection, defender)

        environment = {"environment_key": definition.environment_key, "relation": "neutral"}
        rules = {"max_rounds": definition.max_rounds, "environment": environment}
        seed = spectator_seed(
            participants={"challenger": challenger_snapshot, "defender": defender_snapshot},
            rules=rules,
        )
        outcome, rounds, actions = simulate_spectator_match(
            challenger_snapshot,
            defender_snapshot,
            seed=seed,
            environment=environment,
            max_rounds=definition.max_rounds,
            challenger_skill_key=challenger_skill,
            defender_skill_key=defender_skill,
            strategy_key="strategy.spectator.player_spar",
        )
        return SpectatorPreviewRecord(
            outcome=outcome,
            rounds=rounds,
            snapshots={
                "challenger": public_spectator_summary(challenger_snapshot),
                "defender": public_spectator_summary(defender_snapshot),
            },
            actions=tuple(actions),
        )

    def _spectator_player_snapshot(
        self, connection: sqlite3.Connection, player: sqlite3.Row
    ) -> tuple[dict[str, object], str]:
        player_state = player_combat_values(player)
        qualification = player_state["qualification"]
        equipment = self._battle_equipment_snapshot(connection, int(player["id"]))
        constitution_effect = constitution_effect_snapshot(connection, int(player["id"]))
        manual_effects = manual_effect_totals(player_state["inventory"], self.content)
        manual_bonus = manual_effects["combat_stat_bonus_bp"]
        if not isinstance(manual_bonus, dict):
            raise ValueError("manual combat stat bonuses must be an object")
        stats = player_stat_snapshot(
            qualification,
            max_hp=player_state["max_hp"],
            initiative=player_state["initiative"],
            equipment=equipment,
            constitution_effect=constitution_effect,
            manual_stat_bonus_bp=manual_bonus,
        )
        skills = self._battle_skill_snapshot(connection, int(player["id"]), str(player_state["path_key"] or ""))
        selected_skill = self._select_battle_skill(skills, available_mana=stats["max_mana"])
        return (
            {
                "dao_name": player_state["dao_name"],
                "path_key": str(player_state["path_key"] or ""),
                "realm_key": player_state["realm_key"],
                "realm_layer": player_state["realm_layer"],
                "qualification": qualification,
                "stats": stats,
                "equipment": list(equipment),
                "selected_skill_key": str(selected_skill["skill_key"]),
            },
            str(selected_skill["skill_key"]),
        )

    @staticmethod
    def _rename_spectator_sides(actions: list[dict[str, object]]) -> list[dict[str, object]]:
        renamed = []
        for source in actions:
            action = dict(source)
            for field in ("actor_key", "target_key"):
                action[field] = {"challenger": "player", "defender": "enemy"}.get(
                    str(action[field]), action[field]
                )
            state = action.get("state")
            if isinstance(state, dict):
                action["state"] = {
                    "player_hp": state.get("challenger_hp", 0),
                    "enemy_hp": state.get("defender_hp", 0),
                }
            renamed.append(action)
        return renamed

    def _run_battle_turn_once(self, battle_id: str, expected_round: int) -> BattleTurnRecord:
        if expected_round < 1 or expected_round > MAX_TURNS:
            raise ValueError("expected battle round is invalid")
        operation_id = f"battle.run_turn:{battle_id}:{expected_round}"
        operation_name = "battle.run_turn"
        request_hash = self._request_hash(
            operation_name,
            {"battle_id": battle_id, "expected_round": expected_round},
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
            player_skills = list(snapshot.get("player", {}).get("skills", []))
            player_mana = int(state.get("player_mana", player_stats.get("max_mana", 0)))
            selected_skill = self._select_battle_skill(player_skills, available_mana=player_mana)
            player_hp = int(state["player_hp"])
            enemy_hp = int(state["enemy_hp"])
            timeout = now >= datetime.fromisoformat(str(session["turn_deadline"]))
            timeout_count = int(state.get("timeout_count", 0)) + 1 if timeout else 0
            sequence = int(session["action_sequence"])
            actions: list[dict[str, object]] = []
            defending = False
            is_ancestral_spirit = str(enemy.get("key", "")) == ANCESTRAL_SPIRIT.key
            bloodline_shadow = bool(state.get("bloodline_shadow", False)) if is_ancestral_spirit else False
            shadow_at_round_start = bloodline_shadow
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
                if actor == "player" and bloodline_shadow and not timeout:
                    action = {
                        "battle_id": battle_id,
                        "sequence_no": sequence + 1,
                        "actor_key": "player",
                        "strategy_key": "strategy.ancestral_spirit.clear_shadow",
                        "skill_key": "skill.ancestral_spirit.shadow_clear",
                        "target_key": "bloodline_shadow",
                        "hit_roll_bp": 0,
                        "crit_roll_bp": 0,
                        "hit_bp": 10_000,
                        "damage": 0,
                        "operation_id": operation_id,
                    }
                    bloodline_shadow = False
                elif actor == "player" and timeout:
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
                    damage_multiplier_bp, skill_hit_bonus_bp, charging = prepare_skill_action(
                        selected_skill, state, expected_round
                    )
                    if charging:
                        action = {
                            "battle_id": battle_id,
                            "sequence_no": sequence + 1,
                            "actor_key": "player",
                            "strategy_key": "strategy.skill.charge",
                            "skill_key": str(selected_skill.get("skill_key", "skill.basic_attack")),
                            "target_key": "self",
                            "hit_roll_bp": 0,
                            "crit_roll_bp": 0,
                            "hit_bp": 10_000,
                            "damage": 0,
                            "operation_id": operation_id,
                        }
                    else:
                        action = self._attack_action(
                            battle_id=battle_id,
                            round_no=expected_round,
                            sequence=sequence + 1,
                            actor_key="player",
                            skill_key=str(selected_skill.get("skill_key", "skill.basic_attack")),
                            strategy_key=(
                                "strategy.basic_attack"
                                if str(selected_skill.get("skill_key", "skill.basic_attack")) == "skill.basic_attack"
                                else "strategy.mastered_skill"
                            ),
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
                            skill_hit_bp=skill_hit_bonus_bp,
                            damage_multiplier_bp=damage_multiplier_bp,
                            accuracy_bp=int(player_stats.get("accuracy_bp", 0)),
                            crit_chance_bp=int(player_stats.get("crit_chance_bp", 0)),
                            crit_damage_bp=int(player_stats.get("crit_damage_bp", 0)),
                        )
                        mana_cost = int(selected_skill.get("mana_cost", 0))
                        if mana_cost > 0:
                            player_mana = max(0, player_mana - mana_cost)
                    hit = int(action["hit_roll_bp"]) < int(action["hit_bp"])
                    ongoing_damage = apply_player_skill_style(
                        selected_skill,
                        state,
                        round_no=expected_round,
                        player_attack=int(player_stats["attack"]),
                        hit=hit,
                        enemy_acted=actor_order[0] == "enemy",
                        direct_damage=int(action["damage"]),
                    )
                    action["damage"] = min(enemy_hp, int(action["damage"]) + ongoing_damage)
                    if phase is not None:
                        effective_damage_bp = phase.player_damage_bp * (10_000 - debt_shield_bp) // 10_000
                        base_damage = int(action["damage"])
                        action["damage"] = min(
                            enemy_hp,
                            max(1, base_damage * effective_damage_bp // 10_000) if base_damage > 0 else 0,
                        )
                    elif int(snapshot["player"].get("cross_realm_penalty_bp", 0)) > 0:
                        base_damage = int(action["damage"])
                        action["damage"] = min(
                            enemy_hp,
                            max(
                                1,
                                base_damage
                                * (10_000 - int(snapshot["player"].get("cross_realm_penalty_bp", 0)))
                                // 10_000,
                            ) if base_damage > 0 else 0,
                        )
                    enemy_hp = max(0, enemy_hp - int(action["damage"]))
                    dealt = int(action["damage"])
                    healing = min(
                        max(0, int(player_stats["max_hp"]) - player_hp),
                        dealt * int(player_stats.get("lifesteal_bp", 0)) // 10_000,
                    )
                    player_hp += healing
                    mana_recovered = min(
                        max(0, int(player_stats.get("max_mana", 0)) - player_mana),
                        max(0, int(player_stats.get("mana_regen", 0)))
                        + dealt * int(player_stats.get("mana_leech_bp", 0)) // 10_000,
                    )
                    player_mana += mana_recovered
                    hp_regen = min(
                        max(0, int(player_stats["max_hp"]) - player_hp),
                        max(0, int(player_stats.get("hp_regen", 0))),
                    )
                    player_hp += hp_regen
                    if healing or mana_recovered or hp_regen:
                        action["recovery"] = {"hp": healing + hp_regen, "mana": mana_recovered}
                elif actor == "enemy" and is_ancestral_spirit and expected_round % 4 == 0 and not bloodline_shadow:
                    action = {
                        "battle_id": battle_id,
                        "sequence_no": sequence + 1,
                        "actor_key": "enemy",
                        "strategy_key": "strategy.ancestral_spirit.bloodline_call",
                        "skill_key": "skill.beast.ancestral_form",
                        "target_key": "bloodline_shadow",
                        "hit_roll_bp": 0,
                        "crit_roll_bp": 0,
                        "hit_bp": 10_000,
                        "damage": 0,
                        "operation_id": operation_id,
                    }
                    bloodline_shadow = True
                else:
                    if actor == "enemy" and is_tribulation_trial:
                        phase = phase_for_hp(enemy_hp, int(enemy["max_hp"]))
                    enemy_attack = phase.attack if phase is not None else int(enemy["attack"])
                    enemy_attack = mitigate_enemy_attack(enemy_attack, state, round_no=expected_round)
                    action = self._attack_action(
                        battle_id=battle_id,
                        round_no=expected_round,
                        sequence=sequence + 1,
                        actor_key="enemy",
                        skill_key=phase.skill_key if phase is not None else str(enemy["skill_key"]),
                        strategy_key=(
                            "strategy.tribulation_phase"
                            if phase is not None
                            else "strategy.ancestral_spirit"
                            if is_ancestral_spirit
                            else "strategy.enemy.automatic"
                        ),
                        attacker_attack=enemy_attack,
                        attacker_initiative=int(enemy["initiative"]),
                        defender_agility=int(player_stats["agility"]),
                        target_hp=player_hp,
                        seed=str(snapshot["random_seed"]),
                        operation_id=operation_id,
                        skill_hit_bp=phase.enemy_hit_bonus_bp if phase is not None else 0,
                        evasion_bp=int(player_stats.get("evasion_bp", 0)),
                        crit_chance_bp=500,
                        defender_anti_crit_bp=int(player_stats.get("anti_crit_bp", 0)),
                    )
                    if defending:
                        action["damage"] = int(action["damage"]) * 8_000 // 10_000
                    action["damage"] = mitigate_player_damage(
                        int(action["damage"]), state, round_no=expected_round,
                        equipment_reduction_bp=int(player_stats.get("damage_reduction_bp", 0)),
                    )
                    reflected = reflected_enemy_damage(
                        int(action["damage"]), state, round_no=expected_round
                    )
                    if reflected:
                        action["reflected_damage"] = reflected
                        enemy_hp = max(0, enemy_hp - reflected)
                    player_hp = max(0, player_hp - int(action["damage"]))
                sequence += 1
                action["state"] = {
                    "player_hp": player_hp,
                    "player_mana": player_mana,
                    "enemy_hp": enemy_hp,
                }
                if action.get("critical"):
                    action["state"]["critical"] = True
                if "recovery" in action:
                    action["state"]["recovery"] = action["recovery"]
                if int(action.get("reflected_damage", 0)) > 0:
                    action["state"]["reflected_damage"] = int(action["reflected_damage"])
                for key in (
                    "charged_skill_key",
                    "charged_skill_round",
                    "skill_statuses",
                    "player_guard_bp",
                    "player_guard_until_round",
                    "player_reflect_damage_bp",
                    "player_reflect_until_round",
                    "manual_reflect_damage_bp",
                    "enemy_attack_reduction_bp",
                    "enemy_debuff_until_round",
                ):
                    if key in state:
                        action["state"][key] = deepcopy(state[key])
                if is_ancestral_spirit:
                    action["state"]["bloodline_shadow"] = bloodline_shadow
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
            if is_ancestral_spirit and shadow_at_round_start and timeout and bloodline_shadow:
                recovery = max(1, int(enemy["max_hp"]) * 500 // 10_000)
                recovery = recovery * (
                    10_000 - min(10_000, int(player_stats.get("healing_reduction_bp", 0)))
                ) // 10_000
                recovery = recovery * (
                    10_000 - min(10_000, int(player_stats.get("recovery_reduction_bp", 0)))
                ) // 10_000
                enemy_hp = min(int(enemy["max_hp"]), enemy_hp + recovery)
                bloodline_shadow = False
                sequence += 1
                recovery_action = {
                    "battle_id": battle_id,
                    "sequence_no": sequence,
                    "actor_key": "enemy",
                    "strategy_key": "strategy.ancestral_spirit.bloodline_recovery",
                    "skill_key": "skill.beast.ancestral_form",
                    "target_key": "enemy",
                    "hit_roll_bp": 0,
                    "crit_roll_bp": 0,
                    "hit_bp": 10_000,
                    "damage": 0,
                    "state": {
                        "player_hp": player_hp,
                        "enemy_hp": enemy_hp,
                        "bloodline_shadow": False,
                        "recovery": recovery,
                    },
                    "operation_id": operation_id,
                }
                actions.append(recovery_action)
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
            skill_state = state
            state = {
                "round_no": expected_round,
                "player_hp": player_hp,
                "player_mana": player_mana,
                "enemy_hp": enemy_hp,
                "timeout_count": timeout_count,
            }
            for key in (
                "charged_skill_key",
                "charged_skill_round",
                "skill_statuses",
                "player_guard_bp",
                "player_guard_until_round",
                "player_reflect_damage_bp",
                "player_reflect_until_round",
                "manual_reflect_damage_bp",
                "enemy_attack_reduction_bp",
                "enemy_debuff_until_round",
            ):
                if key in skill_state:
                    state[key] = deepcopy(skill_state[key])
            if is_ancestral_spirit:
                state["bloodline_shadow"] = bloodline_shadow
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
            operation_name, {"battle_id": battle_id}
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
            if outcome == "won" and str(session["battle_type"]) not in {"pve.tribulation_trial", "pve.tower"}:
                durable_ids = [
                    str(item["instance_id"])
                    for item in list(snapshot.get("player", {}).get("equipment", []))
                    if str(item.get("slot", "")) in {"weapon", "armor", "accessory"}
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
            enemy_record = (self.content or bundled_content()).get(
                "enemy", str(session["enemy_key"]), include_locked=False
            )
            creature_entry = enemy_record.get("codex_entry_key") if enemy_record is not None else None
            if (
                outcome == "won"
                and isinstance(creature_entry, str)
            ):
                record_codex_discovery(
                    connection,
                    player_id=int(player["id"]),
                    entry_key=creature_entry,
                    operation_id=operation_id,
                    occurred_at=now,
                    snapshot={
                        "battle_id": battle_id,
                        "enemy_key": str(session["enemy_key"]),
                        "battle_type": str(session["battle_type"]),
                    },
                    content=self.content,
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
            asset_reward = {key: quantity for key, quantity in reward.items() if key != "cultivation"}
            cultivation_reward = int(reward.get("cultivation", 0))
            grant_player_state(
                connection,
                player,
                rewards=asset_reward or None,
                updated_at=now_text,
                value_delta={
                    "cultivation": cultivation_reward,
                    "total_cultivation": cultivation_reward,
                },
            )
            record_material_discoveries(
                connection,
                player_id=int(player["id"]),
                operation_id=operation_id,
                occurred_at=self._now(),
                reward=reward,
                snapshot={"source": "battle.claim_reward", "battle_id": str(session["battle_id"])},
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
        realm = player_realm_values(player)
        return CombatRepositoryMixin._meets_realm_values(
            realm["realm_key"], realm["realm_layer"], required_realm, required_layer
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
        rows = equipment_instance_rows(
            connection, player_id, equipped_only=True, durable_only=True, active_only=True
        )
        content = self.content or bundled_content()
        player = connection.execute("SELECT path_key FROM players WHERE id = ?", (player_id,)).fetchone()
        path_key = str(player["path_key"] or "") if player is not None else ""
        equipment = []
        for row in rows:
            item_key = str(row["item_key"])
            item_definition = content.require("item", item_key, include_locked=False)
            if item_definition.get("path_key") not in {None, path_key}:
                continue
            equipment.append(
                {
                    "instance_id": str(row["instance_id"]),
                    "item_key": item_key,
                    "slot": str(row["slot"]),
                    "effects": list(item_definition.get("effects", [])),
                    "durability_bp": int(row["durability_bp"]),
                    "temper_level": int(row["temper_level"]),
                    "affixes": {
                        str(key): int(value)
                        for key, value in self._json_object(row["affixes_json"], {}).items()
                    },
                }
            )
        return tuple(equipment)

    def _battle_skill_snapshot(
        self,
        connection: sqlite3.Connection,
        player_id: int,
        path_key: str,
    ) -> list[dict[str, object]]:
        """Freeze mastered skills and their effective effects at battle start."""

        rows = connection.execute(
            "SELECT skill_key, level, snapshot_json FROM skill_masteries "
            "WHERE player_id = ? ORDER BY level DESC, skill_key",
            (player_id,),
        ).fetchall()
        skills: list[dict[str, object]] = []
        for row in rows:
            stored = self._json_object(row["snapshot_json"], {})
            try:
                stored_path = stored["path_key"]
                effect = dict(stored["effective_effect"])
                style = dict(stored["combat_style"])
                mana_cost = max(0, int(stored["mana_cost"]))
            except (KeyError, TypeError, ValueError) as exc:
                raise ContentError("mastered skill snapshot is invalid") from exc
            if stored_path not in {None, path_key}:
                continue
            level = int(stored.get("level", row["level"]))
            skills.append(
                {
                    "skill_key": str(row["skill_key"]),
                    "path_key": stored_path,
                    "level": level,
                    "effect": effect,
                    "mana_cost": mana_cost,
                    "combat_style": style,
                }
            )
        return skills

    @staticmethod
    def _select_battle_skill(
        skills: list[dict[str, object]], *, available_mana: int | None = None
    ) -> dict[str, object]:
        """Choose the strongest mastered active skill deterministically."""

        affordable = [
            skill for skill in skills
            if available_mana is None or int(skill.get("mana_cost", 0)) <= available_mana
        ]
        if not affordable:
            return {"skill_key": "skill.basic_attack", "effect": {"value": 10000, "level": 0}}
        return sorted(
            affordable,
            key=lambda item: (
                str(item.get("skill_key", "")) == "skill.basic_attack",
                -int(item.get("level", 0)),
                str(item.get("skill_key", "")),
            ),
        )[0]

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
        damage_multiplier_bp: int = 10_000,
        accuracy_bp: int = 0,
        evasion_bp: int = 0,
        crit_chance_bp: int = 0,
        crit_damage_bp: int = 0,
        defender_anti_crit_bp: int = 0,
    ) -> dict[str, object]:
        hit_bp = hit_chance_bp(
            attacker_initiative=attacker_initiative,
            defender_agility=defender_agility,
            skill_hit_bp=skill_hit_bp,
            accuracy_bp=accuracy_bp,
            evasion_bp=evasion_bp,
        )
        hit_roll = battle_roll_bp(f"{seed}:round:{round_no}:action:{sequence}:hit")
        crit_roll = battle_roll_bp(f"{seed}:round:{round_no}:action:{sequence}:crit")
        hit = hit_roll < hit_bp
        effective_crit_bp = max(0, int(crit_chance_bp) - max(0, int(defender_anti_crit_bp)))
        critical = hit and crit_roll < min(10_000, effective_crit_bp)
        base_damage = max(0, attacker_attack) * max(0, int(damage_multiplier_bp)) // 10_000
        if critical:
            base_damage = base_damage * (15_000 + max(0, int(crit_damage_bp))) // 10_000
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
            "critical": critical,
            "damage": min(target_hp, base_damage) if hit else 0,
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
            "strategy_key": "strategy.timeout_defend",
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
