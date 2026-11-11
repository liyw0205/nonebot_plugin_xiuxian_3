"""SQLite transactions for server-timed idle assignments."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta
from math import ceil
from typing import Any
from uuid import uuid4

from ...contracts import serialize_datetime
from ..content import bundled_content
from ..persistence.errors import (
    IdleAlreadySettledError,
    IdleBusyError,
    IdleCancellationExpiredError,
    IdleClaimTooEarlyError,
    IdleDailyLimitError,
    IdleNotFoundError,
    IdleRequirementError,
)
from .idle_models import (
    IdleAssignmentRecord,
    IdleCancelRecord,
    IdleRoutePreviewRecord,
    IdleSettlementRecord,
    IdleStatusRecord,
)
from .idle_rules import (
    ABSOLUTE_MAX_SECONDS,
    CANCEL_WINDOW_SECONDS,
    MAX_CLAIM_EXTENSION_SECONDS,
    IdleRouteDefinition,
    idle_route_order,
    idle_reward_label,
    journal_from_snapshot,
    patrol_journal_from_snapshot,
    reward_for,
    reward_local_reputation_maximums,
    reward_ranges,
    resolve_route,
)
from ..companions.interaction_content import companion_interaction_definition
from ..companions.rules import companion_definition, level_after_experience
from .codex_projection import record_codex_discovery, record_material_discoveries
from ..adventures.rules import meets_realm
from ..utils.assets import inventory_amount
from ..utils.player import (
    grant_player_reward,
    grant_player_state,
    local_reputation_with_delta,
    player_integer,
    player_inventory,
    player_reputation_state,
    spend_player_state,
)


class IdleRepositoryMixin:
    async def get_idle_status(self, *, platform: str, platform_user_id: str) -> IdleStatusRecord | None:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._get_idle_status_once, platform, platform_user_id)

    def _get_idle_status_once(self, platform: str, platform_user_id: str) -> IdleStatusRecord | None:
        now = self._now()
        with self._connect() as connection:
            player = self._require_player(connection, platform, platform_user_id, writable=False)
            row = connection.execute(
                "SELECT * FROM idle_assignments WHERE player_id = ? AND status = 'running' ORDER BY id DESC LIMIT 1",
                (player["id"],),
            ).fetchone()
            if row is None:
                return None
            snapshot = self._required_json_object(row["snapshot_json"], "idle snapshot")
            assignment = IdleAssignmentRecord(
                player=self._row_to_player(player), assignment_id=str(row["assignment_id"]),
                route_key=str(row["route_key"]), label=str(snapshot["label"]), status=str(row["status"]),
                starts_at=str(row["starts_at"]), claim_at=str(row["claim_at"]),
                max_claim_at=str(row["max_claim_at"]), cancel_until=str(row["cancel_until"]),
                cost=self._required_json_object(row["cost_json"], "idle cost"),
                tool_key=snapshot.get("tool_key"), facility_slot_key=snapshot.get("facility_slot_key"),
                companion_instance_id=snapshot.get("companion_instance_id"),
                companion_label=snapshot.get("companion_label"),
                journal={**journal_from_snapshot(snapshot), **patrol_journal_from_snapshot(snapshot)},
            )
            return IdleStatusRecord(
                assignment=assignment,
                remaining_seconds=max(0, ceil((datetime.fromisoformat(assignment.claim_at) - now).total_seconds())),
                claimable=now >= datetime.fromisoformat(assignment.claim_at),
                fallback=now > datetime.fromisoformat(assignment.max_claim_at),
                cancellable=now <= datetime.fromisoformat(assignment.cancel_until),
            )

    async def get_idle_journals(self, *, platform: str, platform_user_id: str) -> tuple[dict[str, Any], ...]:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._get_idle_journals_once, platform, platform_user_id)

    def _get_idle_journals_once(self, platform: str, platform_user_id: str) -> tuple[dict[str, Any], ...]:
        with self._connect() as connection:
            player = self._require_player(connection, platform, platform_user_id, writable=False)
            rows = connection.execute(
                "SELECT route_key, snapshot_json FROM idle_assignments WHERE id IN "
                "(SELECT MIN(id) FROM idle_assignments WHERE player_id = ? AND status = 'claimed' GROUP BY route_key) ORDER BY id",
                (player["id"],),
            ).fetchall()
            journals = []
            for row in rows:
                snapshot = self._required_json_object(row["snapshot_json"], "idle snapshot")
                journal = journal_from_snapshot(snapshot)
                if journal:
                    journals.append({"route_key": str(row["route_key"]), "label": str(snapshot["label"]), **journal})
            return tuple(journals)

    async def preview_idle(
        self, *, platform: str, platform_user_id: str, route_key: str | None
    ) -> tuple[IdleRoutePreviewRecord, ...]:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._preview_idle_once, platform, platform_user_id, route_key
            )

    def _preview_idle_once(
        self, platform: str, platform_user_id: str, route_key: str | None
    ) -> tuple[IdleRoutePreviewRecord, ...]:
        requested = (resolve_route(route_key, self.content),) if route_key else idle_route_order(self.content)
        now = self._now()
        with self._connect() as connection:
            player = self._require_player(connection, platform, platform_user_id, writable=False)
            return tuple(self._idle_preview(connection, player, definition, now) for definition in requested)

    def _idle_requirements_missing(
        self,
        connection: sqlite3.Connection,
        player: sqlite3.Row,
        definition: IdleRouteDefinition,
        now: datetime,
    ) -> list[str]:
        missing: list[str] = []
        stage_order = {"new_user": 0, "mortal": 1, "seeker": 2, "cultivator": 3, "suspended": -1}
        if stage_order.get(str(player["stage"]), -1) < stage_order.get(definition.required_stage, 1):
            stage_labels = {"mortal": "开始修仙", "seeker": "寻仙问道", "cultivator": "入道"}
            missing.append(f"角色尚未完成{stage_labels.get(definition.required_stage, '入道')}")
        if definition.required_location and str(player["location_key"]) != definition.required_location:
            missing.append(f"所在地点不符（需要抵达{(self.content or bundled_content()).label('location', definition.required_location)}）")
        local_reputation = player_reputation_state(connection, int(player["id"])).local
        for reputation_key, minimum in definition.required_local_reputation:
            if int(local_reputation.get(reputation_key, 0)) < minimum:
                missing.append(f"地方名望不足（需要 {minimum}）")
        if definition.required_realm is not None and not meets_realm(
            str(player["realm_key"]),
            player_integer(player, "realm_layer"),
            definition.required_realm,
            definition.required_layer,
            self.content,
        ):
            missing.append(f"境界不足（需要{(self.content or bundled_content()).label('realm', definition.required_realm)} L{definition.required_layer}）")
        if definition.required_permit and connection.execute(
            "SELECT 1 FROM trade_permits WHERE player_id = ? AND permit_key = ? AND expires_at > ? LIMIT 1",
            (player["id"], definition.required_permit, serialize_datetime(now)),
        ).fetchone() is None:
            missing.append("需要有效的贸易许可")
        if definition.required_project_contribution is not None:
            project_key, min_points = definition.required_project_contribution
            points_row = connection.execute(
                "SELECT COALESCE(SUM(c.contribution_points), 0) AS points "
                "FROM livelihood_project_contributions c "
                "JOIN livelihood_projects p ON p.project_id = c.project_id "
                "WHERE c.player_id = ? AND p.project_key = ?",
                (player["id"], project_key),
            ).fetchone()
            if int(points_row["points"]) < min_points:
                missing.append(f"参与度不足（需要 {min_points} 点）")
        if definition.required_dao_route and connection.execute(
            "SELECT 1 FROM sect_members m JOIN sects s ON s.sect_id = m.sect_id "
            "JOIN dao_route_state d ON d.sect_id = s.sect_id "
            "WHERE m.player_id = ? AND m.status = 'active' AND s.status = 'active' LIMIT 1",
            (player["id"],),
        ).fetchone() is None:
            missing.append("需要宗门已定道统")
        if definition.required_residence:
            residence = connection.execute(
                "SELECT 1 FROM residences WHERE player_id = ? AND status = 'active' AND ends_at > ? LIMIT 1",
                (player["id"], serialize_datetime(now)),
            ).fetchone()
            if residence is None:
                missing.append("需要有效居所或地块")
        if definition.required_unlock and not self._has_codex_unlock(
            connection, int(player["id"]), definition.required_unlock
        ):
            missing.append("需要已领取的图鉴见闻")
        if definition.required_companion_kind:
            companion = self._idle_select_companion(connection, player, definition, None)
            if companion is None:
                missing.append("需要一只可用的灵兽")
        selected_tool = self._idle_select_tool(connection, player, definition, None)
        facility = self._idle_select_facility(connection, player, definition, None)
        if definition.required_tool_keys and selected_tool is None and facility is None:
            missing.append("需要基础工具或作坊槽")
        if player_integer(player, "energy") < definition.energy_cost:
            missing.append(f"精力不足（需要 {definition.energy_cost}）")
        if player_integer(player, "stamina") < definition.stamina_cost:
            missing.append(f"体力不足（需要 {definition.stamina_cost}）")
        return missing

    def _idle_preview(
        self,
        connection: sqlite3.Connection,
        player: sqlite3.Row,
        definition: IdleRouteDefinition,
        now: datetime,
    ) -> IdleRoutePreviewRecord:
        missing = self._idle_requirements_missing(connection, player, definition, now)
        active = connection.execute(
            "SELECT 1 FROM idle_assignments WHERE player_id = ? AND status IN ('assigned', 'running') LIMIT 1",
            (player["id"],),
        ).fetchone()
        if active is not None:
            missing.append("已有进行中的挂机")
        if self._has_active_long_action(connection, int(player["id"])):
            missing.append("已有进行中的长时行动")
        used = connection.execute(
            "SELECT COUNT(*) AS count FROM idle_assignments WHERE player_id = ? AND route_key = ? AND business_date = ? AND status IN ('claimed', 'expired')",
            (player["id"], definition.key, now.date().isoformat()),
        ).fetchone()
        daily_used = int(used["count"]) if used is not None else 0
        if daily_used >= definition.daily_limit:
            missing.append("今日挂机结算次数已用尽")
        return IdleRoutePreviewRecord(
            route_key=definition.key,
            label=definition.label,
            description=definition.description,
            duration_seconds=definition.duration_seconds,
            stamina_cost=definition.stamina_cost,
            energy_cost=definition.energy_cost,
            daily_limit=definition.daily_limit,
            daily_used=daily_used,
            ready=not missing,
            missing=tuple(missing),
            requirements={
                "required_realm": definition.required_realm,
                "required_layer": definition.required_layer,
                "required_permit": definition.required_permit,
                "required_project_contribution": (
                    list(definition.required_project_contribution)
                    if definition.required_project_contribution
                    else None
                ),
                "required_dao_route": definition.required_dao_route,
                "required_location": definition.required_location,
                "required_local_reputation": dict(definition.required_local_reputation),
                "required_residence": definition.required_residence,
                "required_tool_keys": list(definition.required_tool_keys),
                "facility_kind": definition.facility_kind,
                "pool_key": definition.pool_key,
                "full_reward_ranges": reward_ranges(definition.pool_key, self.content),
                "fallback_reward_ranges": reward_ranges(definition.fallback_pool_key, self.content),
                "gathering_journal": definition.gathering_journal,
                "required_companion_kind": definition.required_companion_kind,
                "companion_progress": dict(definition.companion_progress),
                "patrol_journal": dict(definition.patrol_journal),
            },
        )

    async def start_idle(
        self,
        *,
        platform: str,
        platform_user_id: str,
        route_key: str,
        tool_or_facility: str | None,
        operation_id: str,
    ) -> IdleAssignmentRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._start_idle_once,
                platform,
                platform_user_id,
                route_key,
                tool_or_facility,
                operation_id,
            )

    def _start_idle_once(
        self,
        platform: str,
        platform_user_id: str,
        route_key: str,
        tool_or_facility: str | None,
        operation_id: str,
    ) -> IdleAssignmentRecord:
        operation_name = "specials.assign_idle"
        request_payload = {
            "platform": platform,
            "platform_user_id": platform_user_id,
            "route_selector": route_key,
            "tool_or_facility": tool_or_facility or "",
        }
        request_hash = self._request_hash(operation_name, request_payload)
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._idle_operation(connection, operation_id, operation_name, request_hash)
            if replay is not None:
                return self._assignment_from_payload(replay, replay=True)
            definition = resolve_route(route_key, self.content)
            player = self._require_player(connection, platform, platform_user_id)
            self._idle_validate(connection, player, definition, tool_or_facility, now)
            companion = self._idle_select_companion(connection, player, definition, tool_or_facility)
            tool = self._idle_select_tool(
                connection, player, definition, None if definition.required_companion_kind else tool_or_facility
            )
            facility = None
            if tool is None:
                facility = self._idle_select_facility(
                    connection, player, definition, None if definition.required_companion_kind else tool_or_facility
                )
            cost = {
                "stamina": definition.stamina_cost,
                "energy": definition.energy_cost,
            }
            starts_at = now
            claim_at = now + timedelta(seconds=definition.duration_seconds)
            max_claim_at = now + timedelta(
                seconds=min(definition.duration_seconds + MAX_CLAIM_EXTENSION_SECONDS, ABSOLUTE_MAX_SECONDS)
            )
            assignment_id = f"idle:{uuid4().hex}"
            random_seed = uuid4().hex
            full_reward = reward_for(definition, random_seed, fallback=False, content=self.content)
            fallback_reward = reward_for(definition, random_seed, fallback=True, content=self.content)
            reputation_maximums = reward_local_reputation_maximums(definition, self.content)
            reward_keys = set(full_reward) | set(fallback_reward)
            bundle = self.content or bundled_content()
            codex_entries = {
                key: bundle.require("codex_entry", key, include_locked=False)
                for key in reward_keys if key.startswith("codex.")
            }
            companion_snapshot: dict[str, Any] | None = None
            if companion is not None:
                companion_def = companion_definition(str(companion["companion_key"]), self.content)
                affinity_cap = companion_interaction_definition(
                    "interaction.companion.company", self.content
                ).affinity_cap
                companion_snapshot = {
                    "instance_id": str(companion["instance_id"]),
                    "companion_key": str(companion["companion_key"]),
                    "companion_label": companion_def.label,
                    "kind": str(companion["kind"]),
                    "status_before": str(companion["status"]),
                    "level_before": int(companion["level"]),
                    "experience_before": int(companion["experience"]),
                    "affinity_before": int(companion["affinity"]),
                    "affinity_cap": int(affinity_cap),
                    "progress": dict(definition.companion_progress),
                }
            snapshot = {
                "route_key": definition.key,
                "label": definition.label,
                "pool_key": definition.pool_key,
                "full_reward": full_reward,
                "fallback_reward": fallback_reward,
                "local_reputation_maximums": reputation_maximums,
                "duration_seconds": definition.duration_seconds,
                "cost": cost,
                "tool_key": str(tool["tool_key"]) if tool else None,
                "tool_durability_before": int(tool["durability"]) if tool else None,
                "durability_cost_bp": definition.durability_cost_bp,
                "facility_slot_key": str(facility["slot_key"]) if facility else None,
                "location_key": str(player["location_key"]),
                "random_seed": random_seed,
                "gathering_journal": definition.gathering_journal,
                "reward_labels": {key: idle_reward_label(key, self.content) for key in reward_keys},
                "codex_entries": codex_entries,
                "companion_instance_id": companion_snapshot["instance_id"] if companion_snapshot else None,
                "companion_label": companion_snapshot["companion_label"] if companion_snapshot else None,
                "companion": companion_snapshot,
                "patrol_journal": definition.patrol_journal,
            }
            spend_player_state(
                connection,
                player,
                updated_at=now_text,
                costs={str(tool["tool_key"]): 1} if tool else None,
                value_delta={
                    "stamina": -definition.stamina_cost,
                    "energy": -definition.energy_cost,
                },
            )
            if companion_snapshot is not None:
                connection.execute(
                    "UPDATE companion_instances SET status = 'travelling', updated_at = ? WHERE id = ? AND status IN ('active', 'available')",
                    (now_text, companion["id"]),
                )
                if connection.execute("SELECT changes()").fetchone()[0] != 1:
                    raise IdleRequirementError("requested companion is no longer available")
            connection.execute(
                """
                INSERT INTO idle_assignments(
                    assignment_id, player_id, operation_id, route_key, status, business_date,
                    starts_at, claim_at, max_claim_at, cancel_until, facility_slot_key, cost_json, snapshot_json,
                    result_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'running', ?, ?, ?, ?, ?, ?, ?, ?, '{}', ?, ?)
                """,
                (
                    assignment_id,
                    player["id"],
                    operation_id,
                    definition.key,
                    now.date().isoformat(),
                    serialize_datetime(starts_at),
                    serialize_datetime(claim_at),
                    serialize_datetime(max_claim_at),
                    serialize_datetime(starts_at + timedelta(seconds=CANCEL_WINDOW_SECONDS)),
                    snapshot["facility_slot_key"],
                    json.dumps(cost, ensure_ascii=False, sort_keys=True),
                    json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
                    now_text,
                    now_text,
                ),
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (player["id"],)).fetchone()
            if updated is None:
                raise RuntimeError("idle start returned no player")
            payload = {
                "player": self._player_payload(self._row_to_player(updated)),
                "assignment_id": assignment_id,
                "route_key": definition.key,
                "label": definition.label,
                "status": "running",
                "starts_at": serialize_datetime(starts_at),
                "claim_at": serialize_datetime(claim_at),
                "max_claim_at": serialize_datetime(max_claim_at),
                "cancel_until": serialize_datetime(starts_at + timedelta(seconds=CANCEL_WINDOW_SECONDS)),
                "cost": cost,
                "tool_key": snapshot["tool_key"],
                "facility_slot_key": snapshot["facility_slot_key"],
                "companion_instance_id": snapshot["companion_instance_id"],
                "companion_label": snapshot["companion_label"],
                "journal": definition.gathering_journal,
                "patrol_journal": definition.patrol_journal,
            }
            self._record_idle_operation(connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text)
            return self._assignment_from_payload(payload)

    async def claim_idle(
        self,
        *,
        platform: str,
        platform_user_id: str,
        assignment_id: str | None,
        operation_id: str,
    ) -> IdleSettlementRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._claim_idle_once, platform, platform_user_id, assignment_id, operation_id
            )

    def _claim_idle_once(
        self, platform: str, platform_user_id: str, assignment_id: str | None, operation_id: str
    ) -> IdleSettlementRecord:
        operation_name = "specials.claim_idle"
        request_payload = {
            "platform": platform,
            "platform_user_id": platform_user_id,
            "assignment_id": assignment_id or "",
        }
        request_hash = self._request_hash(operation_name, request_payload)
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._idle_operation(connection, operation_id, operation_name, request_hash)
            if replay is not None:
                return IdleRepositoryMixin._settlement_from_payload(replay, replay=True)
            player = self._require_player(connection, platform, platform_user_id)
            assignment = self._idle_assignment(connection, int(player["id"]), assignment_id)
            status = str(assignment["status"])
            if status != "running":
                raise IdleAlreadySettledError("idle assignment is not running")
            snapshot = self._required_json_object(assignment["snapshot_json"], "idle snapshot")
            journal = {**journal_from_snapshot(snapshot), **patrol_journal_from_snapshot(snapshot)}
            expected_claim_at = datetime.fromisoformat(str(assignment["claim_at"]))
            expected_max_claim_at = datetime.fromisoformat(str(assignment["max_claim_at"]))
            if now < expected_claim_at:
                raise IdleClaimTooEarlyError("idle assignment is not ready")
            fallback = now > expected_max_claim_at
            reward_value = snapshot["fallback_reward"] if fallback else snapshot["full_reward"]
            if not isinstance(reward_value, dict):
                raise ValueError("idle snapshot reward must be an object")
            reward = {str(key): int(quantity) for key, quantity in reward_value.items()}
            local_deltas = {key: value for key, value in reward.items() if key.startswith("local.")}
            codex_keys = tuple(key for key in reward if key.startswith("codex."))
            grant_reward = {key: value for key, value in reward.items() if not key.startswith("codex.")}
            maximums = snapshot["local_reputation_maximums"]
            if not isinstance(maximums, dict):
                raise ValueError("idle snapshot local reputation maximums must be an object")
            active_maximums = {key: int(maximums[key]) for key in local_deltas}
            reputation_before = player_reputation_state(connection, int(player["id"])).local
            reputation_after = (
                local_reputation_with_delta(
                    connection,
                    int(player["id"]),
                    local_deltas,
                    maximums=active_maximums,
                )
                if local_deltas
                else reputation_before
            )
            tool_key = snapshot.get("tool_key")
            durability_before = snapshot.get("tool_durability_before")
            durability_after = durability_before
            durability = self._required_json_object(player["durability_json"], "player durability")
            durability_cost_bp = int(snapshot["durability_cost_bp"])
            if tool_key and durability_cost_bp and not fallback:
                durability_after = max(0, int(durability_before or 10000) - durability_cost_bp)
                durability[str(tool_key)] = durability_after
            if tool_key:
                grant_reward[str(tool_key)] = grant_reward.get(str(tool_key), 0) + 1
            grant_player_reward(
                connection,
                player,
                grant_reward,
                now_text,
                player_values={"durability_json": json.dumps(durability, ensure_ascii=False, sort_keys=True)},
                local_reputation_maximums=active_maximums or None,
            )
            actual_reward = {key: value for key, value in reward.items() if not key.startswith("local.")}
            for key in local_deltas:
                actual = reputation_after.get(key, 0) - reputation_before.get(key, 0)
                if actual:
                    actual_reward[key] = actual
            for codex_key in codex_keys:
                entry = snapshot.get("codex_entries", {}).get(codex_key, {})
                record_codex_discovery(
                    connection,
                    player_id=int(player["id"]),
                    entry_key=codex_key,
                    operation_id=operation_id,
                    occurred_at=now,
                    snapshot={**snapshot, **({"label": entry["name"]} if entry else {})},
                    content=self.content,
                    category_snapshot=entry.get("category"),
                )
            record_material_discoveries(
                connection,
                player_id=int(player["id"]),
                operation_id=operation_id,
                occurred_at=now,
                reward=actual_reward,
                snapshot=snapshot,
                content=self.content,
            )
            companion_progress: dict[str, int] = {"experience": 0, "affinity": 0}
            companion_snapshot = snapshot.get("companion")
            if snapshot.get("companion_instance_id") and companion_snapshot is None:
                raise ValueError("idle snapshot companion_instance_id has no companion snapshot")
            if companion_snapshot is not None:
                if not isinstance(companion_snapshot, dict):
                    raise ValueError("idle snapshot companion must be an object")
                required = {
                    "instance_id", "companion_key", "companion_label", "kind", "status_before",
                    "level_before", "experience_before", "affinity_before", "affinity_cap", "progress",
                }
                if set(companion_snapshot) != required:
                    raise ValueError("idle snapshot companion has invalid fields")
                if snapshot.get("companion_instance_id") != companion_snapshot.get("instance_id"):
                    raise ValueError("idle snapshot companion instance does not match assignment")
                if any(
                    not isinstance(companion_snapshot[field], str) or not companion_snapshot[field].strip()
                    for field in ("instance_id", "companion_key", "companion_label", "kind", "status_before")
                ):
                    raise ValueError("idle snapshot companion identity is invalid")
                if companion_snapshot["status_before"] not in {"active", "available", "bonded"}:
                    raise ValueError("idle snapshot companion status is invalid")
                for field in ("level_before", "experience_before", "affinity_before", "affinity_cap"):
                    if isinstance(companion_snapshot[field], bool) or not isinstance(companion_snapshot[field], int):
                        raise ValueError(f"idle snapshot companion {field} is invalid")
                if any(
                    companion_snapshot[field] < 0
                    for field in ("level_before", "experience_before", "affinity_before", "affinity_cap")
                ):
                    raise ValueError("idle snapshot companion progress baseline is invalid")
                instance = connection.execute(
                    "SELECT * FROM companion_instances WHERE player_id = ? AND instance_id = ?",
                    (player["id"], str(companion_snapshot["instance_id"])),
                ).fetchone()
                if instance is None or str(instance["status"]) != "travelling":
                    raise IdleRequirementError("巡护灵兽状态已变化，未结算本次安排")
                if (
                    str(instance["companion_key"]) != companion_snapshot["companion_key"]
                    or str(instance["kind"]) != companion_snapshot["kind"]
                ):
                    raise IdleRequirementError("巡护灵兽实体已变化，未结算本次安排")
                if (
                    int(instance["level"]) != int(companion_snapshot["level_before"])
                    or int(instance["experience"]) != int(companion_snapshot["experience_before"])
                    or int(instance["affinity"]) != int(companion_snapshot["affinity_before"])
                ):
                    raise IdleRequirementError("巡护灵兽成长数据已变化，未结算本次安排")
                progress = companion_snapshot["progress"]
                if not isinstance(progress, dict):
                    raise ValueError("idle snapshot companion progress must be an object")
                if set(progress) != {"experience", "affinity"}:
                    raise ValueError("idle snapshot companion progress has invalid fields")
                if any(
                    isinstance(progress[field], bool) or not isinstance(progress[field], int) or progress[field] < 0
                    for field in ("experience", "affinity")
                ):
                    raise ValueError("idle snapshot companion progress is invalid")
                if not fallback:
                    companion_progress = {
                        "experience": int(progress.get("experience", 0)),
                        "affinity": int(progress.get("affinity", 0)),
                    }
                companion_def = companion_definition(str(companion_snapshot["companion_key"]), self.content)
                updated_experience = int(instance["experience"]) + companion_progress["experience"]
                updated_level = level_after_experience(companion_def, updated_experience)
                updated_affinity = min(
                    int(companion_snapshot["affinity_cap"]),
                    int(instance["affinity"]) + companion_progress["affinity"],
                )
                companion_progress["experience"] = updated_experience - int(instance["experience"])
                companion_progress["affinity"] = updated_affinity - int(instance["affinity"])
                connection.execute(
                    "UPDATE companion_instances SET status = ?, experience = ?, level = ?, affinity = ?, updated_at = ? WHERE id = ?",
                    (
                        str(companion_snapshot["status_before"]),
                        updated_experience,
                        updated_level,
                        updated_affinity,
                        now_text,
                        instance["id"],
                    ),
                )
            result = {
                **actual_reward,
                "fallback": fallback,
                "claimed_at": now_text,
                "tool_durability_before": durability_before,
                "tool_durability_after": durability_after,
                "companion_progress": companion_progress,
            }
            settled_status = "expired" if fallback else "claimed"
            connection.execute(
                "UPDATE idle_assignments SET status = ?, claim_operation_id = ?, result_json = ?, updated_at = ? WHERE id = ? AND status = 'running'",
                (settled_status, operation_id, json.dumps(result, ensure_ascii=False, sort_keys=True), now_text, assignment["id"]),
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (player["id"],)).fetchone()
            if updated is None:
                raise RuntimeError("idle claim returned no player")
            payload = {
                "player": self._player_payload(self._row_to_player(updated)),
                "assignment_id": str(assignment["assignment_id"]),
                "route_key": str(assignment["route_key"]),
                "label": str(snapshot["label"]),
                "status": settled_status,
                "reward": actual_reward,
                "fallback": fallback,
                "tool_durability_before": durability_before,
                "tool_durability_after": durability_after,
                "journal": journal,
                "reward_labels": snapshot.get("reward_labels", {}),
                "companion_instance_id": snapshot.get("companion_instance_id"),
                "companion_label": snapshot.get("companion_label"),
                "companion_progress": companion_progress,
            }
            self._record_idle_operation(connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text)
            return IdleRepositoryMixin._settlement_from_payload(payload)

    async def cancel_idle(
        self,
        *,
        platform: str,
        platform_user_id: str,
        assignment_id: str | None,
        operation_id: str,
    ) -> IdleCancelRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._cancel_idle_once, platform, platform_user_id, assignment_id, operation_id
            )

    def _cancel_idle_once(
        self, platform: str, platform_user_id: str, assignment_id: str | None, operation_id: str
    ) -> IdleCancelRecord:
        operation_name = "specials.cancel_idle"
        request_payload = {
            "platform": platform,
            "platform_user_id": platform_user_id,
            "assignment_id": assignment_id or "",
        }
        request_hash = self._request_hash(operation_name, request_payload)
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._idle_operation(connection, operation_id, operation_name, request_hash)
            if replay is not None:
                return IdleRepositoryMixin._cancel_from_payload(replay, replay=True)
            player = self._require_player(connection, platform, platform_user_id)
            assignment = self._idle_assignment(connection, int(player["id"]), assignment_id)
            if str(assignment["status"]) != "running":
                raise IdleAlreadySettledError("idle assignment is not running")
            if now > datetime.fromisoformat(str(assignment["cancel_until"])):
                raise IdleCancellationExpiredError("idle cancellation window expired")
            cost = self._required_json_object(assignment["cost_json"], "idle cost")
            snapshot = self._required_json_object(assignment["snapshot_json"], "idle snapshot")
            tool_key = snapshot.get("tool_key")
            grant_player_state(
                connection,
                player,
                updated_at=now_text,
                rewards={str(tool_key): 1} if tool_key else None,
                value_delta={
                    "stamina": int(cost.get("stamina", 0)),
                    "energy": int(cost.get("energy", 0)),
                },
                maximums={
                    "stamina": player["stamina_max"],
                    "energy": player["energy_max"],
                },
            )
            companion_snapshot = snapshot.get("companion")
            if companion_snapshot is not None:
                if not isinstance(companion_snapshot, dict) or not companion_snapshot.get("instance_id"):
                    raise ValueError("idle snapshot companion is invalid")
                restored = connection.execute(
                    "UPDATE companion_instances SET status = ?, updated_at = ? WHERE player_id = ? AND instance_id = ? AND status = 'travelling'",
                    (
                        str(companion_snapshot.get("status_before", "active")),
                        now_text,
                        player["id"],
                        str(companion_snapshot["instance_id"]),
                    ),
                )
                if restored.rowcount != 1:
                    raise IdleRequirementError("巡护灵兽状态已变化，无法撤回安排")
            connection.execute(
                "UPDATE idle_assignments SET status = 'cancelled', cancel_operation_id = ?, result_json = ?, updated_at = ? WHERE id = ? AND status = 'running'",
                (operation_id, json.dumps({"refunded": cost}, ensure_ascii=False, sort_keys=True), now_text, assignment["id"]),
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (player["id"],)).fetchone()
            if updated is None:
                raise RuntimeError("idle cancellation returned no player")
            payload = {
                "player": self._player_payload(self._row_to_player(updated)),
                "assignment_id": str(assignment["assignment_id"]),
                "route_key": str(assignment["route_key"]),
                "label": str(snapshot["label"]),
                "status": "cancelled",
                "refunded": cost,
                "returned_tool_key": str(tool_key) if tool_key else None,
                "companion_instance_id": snapshot.get("companion_instance_id"),
                "companion_label": snapshot.get("companion_label"),
            }
            self._record_idle_operation(connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text)
            return IdleRepositoryMixin._cancel_from_payload(payload)

    def _idle_validate(
        self,
        connection: sqlite3.Connection,
        player: sqlite3.Row,
        definition: IdleRouteDefinition,
        tool_or_facility: str | None,
        now: datetime,
    ) -> None:
        preview = self._idle_preview(connection, player, definition, now)
        if preview.daily_used >= definition.daily_limit:
            raise IdleDailyLimitError("idle daily limit reached")
        if self._has_active_long_action(connection, int(player["id"])):
            raise IdleBusyError("another long action is active")
        if not preview.ready:
            if "已有进行中的挂机" in preview.missing or "已有进行中的长时行动" in preview.missing:
                raise IdleBusyError("another long action is active")
            raise IdleRequirementError("; ".join(preview.missing))
        if definition.energy_cost and player_integer(player, "energy") < definition.energy_cost:
            raise IdleRequirementError("energy is insufficient")
        if definition.stamina_cost and player_integer(player, "stamina") < definition.stamina_cost:
            raise IdleRequirementError("stamina is insufficient")
        selected_tool = self._idle_select_tool(
            connection, player, definition, None if definition.required_companion_kind else tool_or_facility
        )
        selected_facility = self._idle_select_facility(
            connection, player, definition, None if definition.required_companion_kind else tool_or_facility
        )
        selected_companion = self._idle_select_companion(
            connection, player, definition, tool_or_facility
        )
        if tool_or_facility and not definition.required_companion_kind and selected_tool is None and selected_facility is None:
            raise IdleRequirementError("requested tool or facility is unavailable")
        if definition.required_tool_keys and selected_tool is None and selected_facility is None:
            raise IdleRequirementError("tool or facility is unavailable")
        if definition.required_companion_kind and selected_companion is None:
            raise IdleRequirementError("requested companion is unavailable")

    @staticmethod
    def _has_codex_unlock(connection: sqlite3.Connection, player_id: int, unlock_key: str) -> bool:
        """Return True when a claimed codex milestone granted this unlock."""

        for row in connection.execute(
            "SELECT unlocks_json FROM codex_milestone_claims WHERE player_id = ?",
            (player_id,),
        ).fetchall():
            try:
                unlocks = json.loads(str(row["unlocks_json"]))
            except (TypeError, json.JSONDecodeError):
                continue
            if isinstance(unlocks, list) and unlock_key in unlocks:
                return True
        return False

    @staticmethod
    def _required_json_object(value: Any, label: str) -> dict[str, Any]:
        try:
            decoded = json.loads(value) if isinstance(value, str) else value
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{label} is invalid JSON") from exc
        if not isinstance(decoded, dict):
            raise ValueError(f"{label} must be an object")
        return dict(decoded)

    def _idle_select_companion(
        self,
        connection: sqlite3.Connection,
        player: sqlite3.Row,
        definition: IdleRouteDefinition,
        requested: str | None,
    ) -> sqlite3.Row | None:
        kind = definition.required_companion_kind
        if kind is None:
            return None
        predicates = [
            "player_id = ?",
            "kind = ?",
            "status IN ('active', 'available')",
            "status <> 'retired'",
        ]
        values: list[object] = [player["id"], kind]
        if requested:
            predicates.append("(instance_id = ? OR companion_key = ?)")
            values.extend([str(requested), str(requested)])
        rows = connection.execute(
            f"SELECT * FROM companion_instances WHERE {' AND '.join(predicates)} ORDER BY id",
            tuple(values),
        ).fetchall()
        for row in rows:
            if self._idle_companion_reserved(connection, int(player["id"]), str(row["instance_id"])):
                continue
            return row
        return None

    @staticmethod
    def _idle_companion_reserved(connection: sqlite3.Connection, player_id: int, instance_id: str) -> bool:
        rows = connection.execute(
            "SELECT snapshot_json FROM idle_assignments WHERE player_id = ? AND status IN ('assigned', 'running')",
            (player_id,),
        ).fetchall()
        for row in rows:
            try:
                snapshot = json.loads(str(row["snapshot_json"]))
            except (TypeError, ValueError):
                continue
            if isinstance(snapshot, dict) and snapshot.get("companion_instance_id") == instance_id:
                return True
        return False

    @staticmethod
    def _idle_select_tool(connection: sqlite3.Connection, player: sqlite3.Row, definition: IdleRouteDefinition, requested: str | None) -> dict[str, object] | None:
        if not definition.required_tool_keys:
            return None
        inventory = player_inventory(player)
        if requested and requested.startswith("facility."):
            return None
        if requested and requested not in definition.required_tool_keys:
            return None
        candidates = (requested,) if requested else definition.required_tool_keys
        for key in candidates:
            if inventory_amount(inventory, key) > 0:
                raw_durability = json.loads(player["durability_json"]) if isinstance(player["durability_json"], str) else player["durability_json"]
                durability_map = dict(raw_durability) if isinstance(raw_durability, dict) else {}
                durability = durability_map.get(key, 10000)
                if int(durability) >= definition.durability_cost_bp:
                    return {"tool_key": key, "durability": int(durability)}
        return None

    @staticmethod
    def _idle_select_facility(connection: sqlite3.Connection, player: sqlite3.Row, definition: IdleRouteDefinition, requested: str | None) -> sqlite3.Row | None:
        if not definition.facility_kind:
            return None
        if requested and not requested.startswith("facility."):
            return None
        predicates = [
            "owner_type = 'personal'",
            "owner_id = ?",
            "status = 'active'",
            "facility_kind = ?",
            "location_key = ?",
        ]
        values: list[object] = [str(player["id"]), definition.facility_kind, str(player["location_key"])]
        if requested and requested.startswith("facility."):
            predicates.append("slot_key = ?")
            values.append(requested)
        predicates.extend(
            (
                "NOT EXISTS (SELECT 1 FROM production_orders p WHERE p.facility_slot_id = production_facility_slots.id AND p.status = 'processing')",
                "NOT EXISTS (SELECT 1 FROM idle_assignments i WHERE i.facility_slot_key = production_facility_slots.slot_key AND i.status IN ('assigned', 'running'))",
            )
        )
        return connection.execute(
            f"SELECT * FROM production_facility_slots WHERE {' AND '.join(predicates)} ORDER BY slot_index LIMIT 1",
            tuple(values),
        ).fetchone()

    @staticmethod
    def _idle_assignment(connection: sqlite3.Connection, player_id: int, assignment_id: str | None) -> sqlite3.Row:
        if assignment_id:
            row = connection.execute("SELECT * FROM idle_assignments WHERE assignment_id = ? AND player_id = ?", (assignment_id, player_id)).fetchone()
        else:
            row = connection.execute("SELECT * FROM idle_assignments WHERE player_id = ? AND status = 'running' ORDER BY id DESC LIMIT 1", (player_id,)).fetchone()
        if row is None:
            raise IdleNotFoundError("idle assignment does not exist")
        return row

    @staticmethod
    def _idle_operation(connection: sqlite3.Connection, operation_id: str, operation_name: str, request_hash: str) -> dict[str, Any] | None:
        row = connection.execute("SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id = ?", (operation_id,)).fetchone()
        if row is None:
            return None
        if str(row["operation_name"]) != operation_name or str(row["request_hash"]) != request_hash:
            from ..persistence.errors import OperationConflictError
            raise OperationConflictError("operation input differs from its original request")
        value = json.loads(row["result_json"]) if isinstance(row["result_json"], str) else row["result_json"]
        return dict(value) if isinstance(value, dict) else {}

    @staticmethod
    def _record_idle_operation(connection: sqlite3.Connection, operation_id: str, operation_name: str, player_id: int, request_hash: str, payload: dict[str, Any], now_text: str) -> None:
        connection.execute(
            "INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (operation_id, operation_name, player_id, request_hash, json.dumps(payload, ensure_ascii=False, sort_keys=True), now_text),
        )

    @staticmethod
    def _assignment_from_payload(payload: dict[str, Any], *, replay: bool = False) -> IdleAssignmentRecord:
        return IdleAssignmentRecord(
            player=SQLitePlayerRepository._row_to_player(payload["player"]),
            assignment_id=str(payload["assignment_id"]),
            route_key=str(payload["route_key"]),
            label=str(payload["label"]),
            status=str(payload["status"]),
            starts_at=str(payload["starts_at"]),
            claim_at=str(payload["claim_at"]),
            max_claim_at=str(payload["max_claim_at"]),
            cancel_until=str(payload["cancel_until"]),
            cost={str(key): int(value) for key, value in dict(payload.get("cost", {})).items()},
            tool_key=payload.get("tool_key"),
            facility_slot_key=payload.get("facility_slot_key"),
            companion_instance_id=payload.get("companion_instance_id"),
            companion_label=payload.get("companion_label"),
            already_completed=replay,
            journal={**dict(payload.get("journal", {})), **dict(payload.get("patrol_journal", {}))},
        )

    @staticmethod
    def _settlement_from_payload(payload: dict[str, Any], *, replay: bool = False) -> IdleSettlementRecord:
        return IdleSettlementRecord(
            player=SQLitePlayerRepository._row_to_player(payload["player"]),
            assignment_id=str(payload["assignment_id"]),
            route_key=str(payload["route_key"]),
            label=str(payload["label"]),
            status=str(payload["status"]),
            reward={str(key): int(value) for key, value in dict(payload.get("reward", {})).items()},
            fallback=bool(payload.get("fallback", False)),
            tool_durability_before=(int(payload["tool_durability_before"]) if payload.get("tool_durability_before") is not None else None),
            tool_durability_after=(int(payload["tool_durability_after"]) if payload.get("tool_durability_after") is not None else None),
            already_completed=replay,
            journal=dict(payload.get("journal", {})),
            reward_labels=dict(payload.get("reward_labels", {})),
            companion_progress={
                str(key): int(value) for key, value in dict(payload.get("companion_progress", {})).items()
            },
        )

    @staticmethod
    def _cancel_from_payload(payload: dict[str, Any], *, replay: bool = False) -> IdleCancelRecord:
        return IdleCancelRecord(
            player=SQLitePlayerRepository._row_to_player(payload["player"]),
            assignment_id=str(payload["assignment_id"]),
            route_key=str(payload["route_key"]),
            label=str(payload["label"]),
            status=str(payload["status"]),
            refunded={str(key): int(value) for key, value in dict(payload.get("refunded", {})).items()},
            returned_tool_key=(str(payload["returned_tool_key"]) if payload.get("returned_tool_key") else None),
            already_completed=replay,
        )


# Runtime composition binds the concrete repository after all mixins are loaded.
SQLitePlayerRepository: Any = None


__all__ = ["IdleRepositoryMixin"]
