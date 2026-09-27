"""Transactional persistence for v0.1 branching story runs."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from typing import Any
from uuid import uuid4

from ...contracts import serialize_datetime
from .codex_projection import record_codex_discovery
from .story_models import StoryBranchView, StoryRecord
from .story_rules import BRANCHES, CONTENT_VERSION, RULE_VERSION, STORY_KEY, completed_nodes
from ..persistence.errors import (
    OperationConflictError,
    PlayerNotFoundError,
    PlayerSuspendedError,
    RepositoryBusyError,
    StoryChoiceConflictError,
    StoryChoiceRequirementError,
    StoryEndingAlreadyClaimedError,
    StoryEndingNotAvailableError,
    StoryNotStartedError,
    StoryRequirementError,
)


class StoryRepositoryMixin:
    async def get_story_status(self, *, platform: str, platform_user_id: str) -> StoryRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._get_story_status_once, platform, platform_user_id)

    def _get_story_status_once(self, platform: str, platform_user_id: str) -> StoryRecord:
        with self._connect() as connection:
            player = self._require_player(connection, platform, platform_user_id, writable=False)
            run = connection.execute(
                "SELECT * FROM story_runs WHERE player_id=? AND story_key=?",
                (player["id"], STORY_KEY),
            ).fetchone()
            evidence = self._story_evidence(connection, int(player["id"]))
            return self._story_record(player, run, evidence)

    async def start_story(self, *, platform: str, platform_user_id: str, operation_id: str) -> StoryRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._start_story_once, platform, platform_user_id, operation_id
            )

    def _start_story_once(self, platform: str, platform_user_id: str, operation_id: str) -> StoryRecord:
        operation_name = "specials.start_story"
        request_hash = self._request_hash(
            operation_name,
            {
                "platform": platform,
                "platform_user_id": platform_user_id,
                "story_key": STORY_KEY,
                "content_version": CONTENT_VERSION,
                "rule_version": RULE_VERSION,
            },
        )
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._operation_payload(connection, operation_id, operation_name, request_hash)
            if existing is not None:
                return self._story_from_payload(existing, replay=True)
            player = self._require_player(connection, platform, platform_user_id)
            if str(player["stage"]) == "new_user":
                raise StoryRequirementError("seeking is required before starting the story")
            run = connection.execute(
                "SELECT * FROM story_runs WHERE player_id=? AND story_key=?",
                (player["id"], STORY_KEY),
            ).fetchone()
            if run is None:
                run_id = uuid4().hex
                snapshot = {"entry_node": "node.arrival"}
                connection.execute(
                    """
                    INSERT INTO story_runs(
                        story_run_id,player_id,story_key,status,current_node,start_operation_id,
                        snapshot_json,content_version,rule_version,created_at,updated_at
                    ) VALUES(?,?,?,'active','node.arrival',?,?,?,?,?,?)
                    """,
                    (
                        run_id,
                        player["id"],
                        STORY_KEY,
                        operation_id,
                        json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
                        CONTENT_VERSION,
                        RULE_VERSION,
                        now_text,
                        now_text,
                    ),
                )
                run = connection.execute(
                    "SELECT * FROM story_runs WHERE story_run_id=?", (run_id,)
                ).fetchone()
            evidence = self._story_evidence(connection, int(player["id"]))
            record = self._story_record(player, run, evidence)
            self._insert_story_operation(
                connection, operation_id, operation_name, int(player["id"]), request_hash,
                self._story_payload(record), now_text,
            )
            return record

    async def choose_story_route(
        self, *, platform: str, platform_user_id: str, route_key: str, operation_id: str
    ) -> StoryRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._choose_story_route_once,
                platform,
                platform_user_id,
                route_key,
                operation_id,
            )

    def _choose_story_route_once(
        self, platform: str, platform_user_id: str, route_key: str, operation_id: str
    ) -> StoryRecord:
        if route_key not in BRANCHES:
            raise StoryChoiceRequirementError("unsupported story route")
        operation_name = "specials.choose_story_node"
        request_hash = self._request_hash(
            operation_name,
            {
                "platform": platform,
                "platform_user_id": platform_user_id,
                "story_key": STORY_KEY,
                "route_key": route_key,
                "content_version": CONTENT_VERSION,
                "rule_version": RULE_VERSION,
            },
        )
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._operation_payload(connection, operation_id, operation_name, request_hash)
            if existing is not None:
                return self._story_from_payload(existing, replay=True)
            player = self._require_player(connection, platform, platform_user_id)
            run = connection.execute(
                "SELECT * FROM story_runs WHERE player_id=? AND story_key=?",
                (player["id"], STORY_KEY),
            ).fetchone()
            if run is None:
                raise StoryNotStartedError("story has not been started")
            current_route = str(run["selected_route"]) if run["selected_route"] else None
            if current_route is not None and current_route != route_key:
                raise StoryChoiceConflictError("story route is already locked")
            if current_route is None:
                if str(run["status"]) != "active":
                    raise StoryChoiceRequirementError("story is not awaiting a route choice")
                evidence = self._story_evidence(connection, int(player["id"]))
                branch_evidence = evidence[route_key]
                if len(branch_evidence) < BRANCHES[route_key].required_source_count:
                    raise StoryChoiceRequirementError("route source requirements are not met")
                nodes = completed_nodes(route_key, len(branch_evidence))
                snapshot = self._json_object(run["snapshot_json"], {})
                snapshot["choice"] = {
                    "route_key": route_key,
                    "source_operation_ids": branch_evidence,
                    "completed_nodes": list(nodes),
                    "selected_at": now_text,
                    "content_version": str(run["content_version"]),
                    "rule_version": str(run["rule_version"]),
                }
                connection.execute(
                    """
                    UPDATE story_runs SET status='ending_pending',current_node=?,selected_route=?,
                        choice_operation_id=?,snapshot_json=?,updated_at=?
                    WHERE id=? AND status='active' AND selected_route IS NULL
                    """,
                    (
                        BRANCHES[route_key].ending_key,
                        route_key,
                        operation_id,
                        json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
                        now_text,
                        run["id"],
                    ),
                )
                run = connection.execute(
                    "SELECT * FROM story_runs WHERE id=?", (run["id"],)
                ).fetchone()
                evidence = self._story_evidence(connection, int(player["id"]))
            else:
                evidence = self._story_evidence(connection, int(player["id"]))
            record = self._story_record(player, run, evidence)
            self._insert_story_operation(
                connection, operation_id, operation_name, int(player["id"]), request_hash,
                self._story_payload(record), now_text,
            )
            return record

    async def claim_story_ending(
        self, *, platform: str, platform_user_id: str, operation_id: str
    ) -> StoryRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._claim_story_ending_once, platform, platform_user_id, operation_id
            )

    def _claim_story_ending_once(
        self, platform: str, platform_user_id: str, operation_id: str
    ) -> StoryRecord:
        operation_name = "specials.claim_story_ending"
        request_hash = self._request_hash(
            operation_name,
            {
                "platform": platform,
                "platform_user_id": platform_user_id,
                "story_key": STORY_KEY,
                "content_version": CONTENT_VERSION,
                "rule_version": RULE_VERSION,
            },
        )
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._operation_payload(connection, operation_id, operation_name, request_hash)
            if existing is not None:
                return self._story_from_payload(existing, replay=True)
            player = self._require_player(connection, platform, platform_user_id)
            run = connection.execute(
                "SELECT * FROM story_runs WHERE player_id=? AND story_key=?",
                (player["id"], STORY_KEY),
            ).fetchone()
            if run is None or not run["selected_route"]:
                raise StoryNotStartedError("no selected story route exists")
            if str(run["status"]) == "ended":
                raise StoryEndingAlreadyClaimedError("story ending has already been claimed")
            if str(run["status"]) != "ending_pending":
                raise StoryEndingNotAvailableError("story ending is not ready to claim")
            route_key = str(run["selected_route"])
            branch = BRANCHES[route_key]
            snapshot = self._json_object(run["snapshot_json"], {})
            reward = {"local_reputation": 10}
            reputation = connection.execute(
                "SELECT local_json,service_reputation FROM player_reputations WHERE player_id=?",
                (player["id"],),
            ).fetchone()
            local = self._json_object(reputation["local_json"], {}) if reputation else {}
            service_reputation = int(reputation["service_reputation"]) if reputation else 0
            local_key = "local.xuantian.new_town"
            local[local_key] = min(1000, int(local.get(local_key, 0)) + 10)
            connection.execute(
                """
                INSERT INTO player_reputations(player_id,local_json,service_reputation,updated_at)
                VALUES(?,?,?,?)
                ON CONFLICT(player_id) DO UPDATE SET local_json=excluded.local_json,
                    updated_at=excluded.updated_at
                """,
                (
                    player["id"],
                    json.dumps(local, ensure_ascii=False, sort_keys=True),
                    service_reputation,
                    now_text,
                ),
            )
            intro = self._json_object(player["intro_json"], {})
            flags = set(str(item) for item in intro.get("flags", []))
            flags.update((branch.flag_key, branch.appearance_key))
            intro["flags"] = sorted(flags)
            connection.execute(
                "UPDATE players SET intro_json=?,updated_at=? WHERE id=?",
                (json.dumps(intro, ensure_ascii=False, sort_keys=True), now_text, player["id"]),
            )
            record_codex_discovery(
                connection,
                player_id=int(player["id"]),
                entry_key=branch.codex_entry_key,
                operation_id=operation_id,
                occurred_at=now,
                snapshot={
                    "story_key": STORY_KEY,
                    "ending_key": branch.ending_key,
                    "route_key": route_key,
                    "story_run_id": str(run["story_run_id"]),
                    "source_operation_ids": snapshot.get("choice", {}).get("source_operation_ids", []),
                    "content_version": str(run["content_version"]),
                    "rule_version": str(run["rule_version"]),
                },
            )
            connection.execute(
                """
                INSERT INTO story_ending_claims(
                    story_run_id,player_id,story_key,ending_key,route_key,operation_id,
                    snapshot_json,reward_json,content_version,rule_version,claimed_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    run["story_run_id"],
                    player["id"],
                    STORY_KEY,
                    branch.ending_key,
                    route_key,
                    operation_id,
                    json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
                    json.dumps(reward, ensure_ascii=False, sort_keys=True),
                    run["content_version"],
                    run["rule_version"],
                    now_text,
                ),
            )
            result = {"reward": reward, "claimed_at": now_text}
            connection.execute(
                "UPDATE story_runs SET status='ended',current_node=?,claim_operation_id=?,"
                "result_json=?,updated_at=? WHERE id=? AND status='ending_pending'",
                (
                    branch.ending_key,
                    operation_id,
                    json.dumps(result, ensure_ascii=False, sort_keys=True),
                    now_text,
                    run["id"],
                ),
            )
            updated_player = connection.execute(
                "SELECT * FROM players WHERE id=?", (player["id"],)
            ).fetchone()
            updated_run = connection.execute(
                "SELECT * FROM story_runs WHERE id=?", (run["id"],)
            ).fetchone()
            evidence = self._story_evidence(connection, int(player["id"]))
            record = self._story_record(updated_player, updated_run, evidence)
            self._insert_story_operation(
                connection, operation_id, operation_name, int(player["id"]), request_hash,
                self._story_payload(record), now_text,
            )
            return record

    def _story_evidence(self, connection: sqlite3.Connection, player_id: int) -> dict[str, list[str]]:
        commissions = [
            str(row["deliver_operation_id"])
            for row in connection.execute(
                "SELECT deliver_operation_id FROM town_commission_claims "
                "WHERE player_id=? AND status='delivered' AND deliver_operation_id IS NOT NULL "
                "ORDER BY delivered_at DESC,id DESC LIMIT 3",
                (player_id,),
            ).fetchall()
        ]
        battle_ids: list[str] = []
        for row in connection.execute(
            "SELECT battle_id,resolved_operation_id,result_json FROM battle_sessions "
            "WHERE player_id=? AND status='settled' AND resolved_operation_id IS NOT NULL "
            "ORDER BY id DESC",
            (player_id,),
        ).fetchall():
            result = self._json_object(row["result_json"], {})
            if result.get("outcome") == "won":
                battle_ids.append(str(row["resolved_operation_id"]))
                if len(battle_ids) == BRANCHES["warden"].required_source_count:
                    break
        harvests: list[str] = []
        for row in connection.execute(
            "SELECT operation_id,result_json FROM operations "
            "WHERE player_id=? AND operation_name='livelihood.harvest' "
            "ORDER BY created_at DESC,rowid DESC LIMIT 20",
            (player_id,),
        ).fetchall():
            result = self._json_object(row["result_json"], {})
            if result.get("status") == "harvested" and result.get("plot_id"):
                harvests.append(str(row["operation_id"]))
                if len(harvests) == BRANCHES["gardener"].required_source_count:
                    break
        dispatches: list[str] = []
        for row in connection.execute(
            "SELECT settle_operation_id,result_json FROM dispatch_assignments "
            "WHERE player_id=? AND dispatch_key='dispatch.herb_search' AND status='settled' "
            "AND settle_operation_id IS NOT NULL "
            "ORDER BY id DESC",
            (player_id,),
        ).fetchall():
            result = self._json_object(row["result_json"], {})
            if result.get("outcome") == "success":
                dispatches.append(str(row["settle_operation_id"]))
                if len(dispatches) == BRANCHES["gardener"].required_source_count:
                    break
        gardener_sources = (
            harvests
            if len(harvests) >= BRANCHES["gardener"].required_source_count
            else dispatches
        )
        return {"merchant": commissions, "warden": battle_ids, "gardener": gardener_sources}

    def _story_record(
        self,
        player: sqlite3.Row,
        run: sqlite3.Row | None,
        evidence: dict[str, list[str]],
        *,
        replay: bool = False,
    ) -> StoryRecord:
        snapshot = self._json_object(run["snapshot_json"], {}) if run else {}
        selected = str(run["selected_route"]) if run and run["selected_route"] else None
        result = self._json_object(run["result_json"], {}) if run else {}
        choice = snapshot.get("choice", {}) if isinstance(snapshot.get("choice", {}), dict) else {}
        nodes = tuple(str(item) for item in choice.get("completed_nodes", ()))
        return StoryRecord(
            player=self._row_to_player(player),
            story_key=STORY_KEY,
            story_run_id=str(run["story_run_id"]) if run else None,
            status=str(run["status"]) if run else "available",
            current_node=str(run["current_node"]) if run else "node.arrival",
            selected_route=selected,
            ending_key=BRANCHES[selected].ending_key if selected else None,
            completed_nodes=nodes,
            branches=tuple(
                StoryBranchView(
                    key=key,
                    label=definition.label,
                    required_source_count=definition.required_source_count,
                    source_label=definition.source_label,
                    evidence_operation_ids=tuple(evidence[key]),
                )
                for key, definition in BRANCHES.items()
            ),
            snapshot=snapshot,
            reward={str(key): int(value) for key, value in result.get("reward", {}).items()},
            already_completed=replay,
        )

    def _story_payload(self, record: StoryRecord) -> dict[str, Any]:
        return {
            "player": self._player_payload(record.player),
            "story_key": record.story_key,
            "story_run_id": record.story_run_id,
            "status": record.status,
            "current_node": record.current_node,
            "selected_route": record.selected_route,
            "ending_key": record.ending_key,
            "completed_nodes": list(record.completed_nodes),
            "branches": [
                {
                    "key": branch.key,
                    "label": branch.label,
                    "required_source_count": branch.required_source_count,
                    "source_label": branch.source_label,
                    "evidence_operation_ids": list(branch.evidence_operation_ids),
                }
                for branch in record.branches
            ],
            "snapshot": record.snapshot,
            "reward": record.reward,
        }

    def _story_from_payload(
        self, payload: dict[str, Any], *, replay: bool = False
    ) -> StoryRecord:
        return StoryRecord(
            player=self._row_to_player(payload["player"]),
            story_key=str(payload["story_key"]),
            story_run_id=str(payload["story_run_id"]) if payload.get("story_run_id") else None,
            status=str(payload["status"]),
            current_node=str(payload["current_node"]),
            selected_route=str(payload["selected_route"]) if payload.get("selected_route") else None,
            ending_key=str(payload["ending_key"]) if payload.get("ending_key") else None,
            completed_nodes=tuple(str(item) for item in payload.get("completed_nodes", ())),
            branches=tuple(
                StoryBranchView(
                    key=str(item["key"]),
                    label=str(item["label"]),
                    required_source_count=int(item["required_source_count"]),
                    source_label=str(item["source_label"]),
                    evidence_operation_ids=tuple(
                        str(value) for value in item.get("evidence_operation_ids", ())
                    ),
                )
                for item in payload.get("branches", ())
            ),
            snapshot=dict(payload.get("snapshot", {})),
            reward={str(key): int(value) for key, value in dict(payload.get("reward", {})).items()},
            already_completed=replay,
        )

    @staticmethod
    def _operation_payload(
        connection: sqlite3.Connection,
        operation_id: str,
        operation_name: str,
        request_hash: str,
    ) -> dict[str, Any] | None:
        existing = connection.execute(
            "SELECT operation_name,request_hash,result_json FROM operations WHERE operation_id=?",
            (operation_id,),
        ).fetchone()
        if existing is None:
            return None
        if existing["operation_name"] != operation_name or existing["request_hash"] != request_hash:
            raise OperationConflictError("story operation input differs from its original request")
        return json.loads(existing["result_json"])

    @staticmethod
    def _insert_story_operation(
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
            "VALUES(?,?,?,?,?,?)",
            (
                operation_id,
                operation_name,
                player_id,
                request_hash,
                json.dumps(payload, ensure_ascii=False, sort_keys=True),
                now_text,
            ),
        )

    @staticmethod
    def _json_object(value: Any, default: dict[str, Any]) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except (TypeError, ValueError):
                return default
            return parsed if isinstance(parsed, dict) else default
        return default


__all__ = ["StoryRepositoryMixin"]
