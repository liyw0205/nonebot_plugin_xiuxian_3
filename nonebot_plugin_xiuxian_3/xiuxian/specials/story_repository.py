"""Transactional persistence for branching story runs."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from typing import Any
from uuid import uuid4

from ...contracts import serialize_datetime
from ..content import bundled_content
from ..rewards.rules import (
    local_reputation_maximum,
    reward_definition,
    reward_grant_from_snapshot,
    reward_totals,
)
from ..utils.json import json_object
from ..utils.player import grant_player_reward, player_reputation_state
from .codex_projection import record_codex_discovery
from .story_models import StoryBranchView, StoryRecord
from .codex_rules import category_for_entry
from .story_rules import (
    CLAIM_OPERATION,
    STORY_KEY,
    StoryContentError,
    StoryDefinition,
    story_definition,
)
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
            evidence = (
                self._story_evidence(
                    connection,
                    int(player["id"]),
                    story_definition(self.content),
                )
                if run is None or not run["selected_route"]
                else {}
            )
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
            },
        )
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._operation_payload(connection, operation_id, operation_name, request_hash)
            if existing is not None:
                return self._story_from_payload(existing, replay=True)
            player = self._require_player(connection, platform, platform_user_id)
            definition = story_definition(self.content)
            if str(player["stage"]) == "new_user":
                raise StoryRequirementError("seeking is required before starting the story")
            run = connection.execute(
                "SELECT * FROM story_runs WHERE player_id=? AND story_key=?",
                (player["id"], STORY_KEY),
            ).fetchone()
            if run is None:
                run_id = uuid4().hex
                snapshot = {
                    "entry_node": definition.entry_node,
                    "story_name": definition.name,
                    "story_description": definition.description,
                }
                connection.execute(
                    """
                    INSERT INTO story_runs(
                        story_run_id,player_id,story_key,status,current_node,start_operation_id,
                        snapshot_json,created_at,updated_at
                    ) VALUES(?,?,?,'active',?,?,?,?,?)
                    """,
                    (
                        run_id,
                        player["id"],
                        STORY_KEY,
                        definition.entry_node,
                        operation_id,
                        json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
                        now_text,
                        now_text,
                    ),
                )
                run = connection.execute(
                    "SELECT * FROM story_runs WHERE story_run_id=?", (run_id,)
                ).fetchone()
            evidence = self._story_evidence(connection, int(player["id"]), definition)
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
        operation_name = "specials.choose_story_node"
        request_hash = self._request_hash(
            operation_name,
            {
                "platform": platform,
                "platform_user_id": platform_user_id,
                "story_key": STORY_KEY,
                "route_key": route_key,
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
                definition = story_definition(self.content)
                branch = next((item for item in definition.branches if item.key == route_key), None)
                if branch is None:
                    raise StoryChoiceRequirementError("unsupported story route")
                if str(run["status"]) != "active":
                    raise StoryChoiceRequirementError("story is not awaiting a route choice")
                evidence = self._story_evidence(connection, int(player["id"]), definition)
                branch_evidence = evidence[route_key]
                if len(branch_evidence) < branch.required_source_count:
                    raise StoryChoiceRequirementError("route source requirements are not met")
                grant = reward_definition(
                    definition.reward_key,
                    self.content,
                    operation=CLAIM_OPERATION,
                )
                content = self.content or bundled_content()
                category = category_for_entry(branch.codex_entry_key, content)
                if category is None:
                    raise StoryContentError(
                        f"story branch {branch.key} has no active codex category"
                    )
                reputation_record = content.require(
                    "location",
                    definition.reputation_key.removeprefix("local."),
                    include_locked=False,
                )
                maximum = local_reputation_maximum(definition.reputation_key, content)
                nodes = branch.completed_nodes
                snapshot = json_object(run["snapshot_json"], {})
                snapshot["choice"] = {
                    "route_key": route_key,
                    "source_operation_ids": branch_evidence,
                    "completed_nodes": list(nodes),
                    "selected_at": now_text,
                    "branch": {
                        "key": branch.key,
                        "label": branch.label,
                        "description": branch.description,
                        "required_source_count": branch.required_source_count,
                        "source_label": branch.source_label,
                    },
                    "ending_key": branch.ending_key,
                    "flag_key": branch.flag_key,
                    "codex_entry_key": branch.codex_entry_key,
                    "codex_category": category,
                    "appearance_key": branch.appearance_key,
                    "reward": grant.snapshot(),
                    "reputation_key": definition.reputation_key,
                    "reputation_name": str(reputation_record["name"]),
                    "local_reputation_maximums": {definition.reputation_key: maximum},
                }
                connection.execute(
                    """
                    UPDATE story_runs SET status='ending_pending',current_node=?,selected_route=?,
                        choice_operation_id=?,snapshot_json=?,updated_at=?
                    WHERE id=? AND status='active' AND selected_route IS NULL
                    """,
                    (
                        branch.ending_key,
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
            else:
                evidence = {}
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
        operation_name = CLAIM_OPERATION
        request_hash = self._request_hash(
            operation_name,
            {
                "platform": platform,
                "platform_user_id": platform_user_id,
                "story_key": STORY_KEY,
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
            snapshot = json_object(run["snapshot_json"], {})
            choice = _frozen_story_choice(snapshot)
            route_key = choice["route_key"]
            if route_key != str(run["selected_route"]):
                raise StoryContentError("frozen story route differs from the active run")
            grant = reward_grant_from_snapshot(choice["reward"], operation=CLAIM_OPERATION)
            if set(grant.local_reputation) != {choice["reputation_key"]}:
                raise StoryContentError("frozen story reward does not match its reputation key")
            maximums = choice["local_reputation_maximums"]
            if set(maximums) != {choice["reputation_key"]}:
                raise StoryContentError("frozen story reputation maximum is invalid")
            before = player_reputation_state(connection, int(player["id"]))
            intro = json_object(player["intro_json"], {})
            flags = set(str(item) for item in intro.get("flags", []))
            flags.update((choice["flag_key"], choice["appearance_key"]))
            intro["flags"] = sorted(flags)
            grant_player_reward(
                connection,
                player,
                reward_totals(grant),
                updated_at=now_text,
                local_reputation_maximums=maximums,
                player_values={"intro_json": json.dumps(intro, ensure_ascii=False, sort_keys=True)},
            )
            after = player_reputation_state(connection, int(player["id"]))
            actual_reputation = (
                after.local.get(choice["reputation_key"], 0)
                - before.local.get(choice["reputation_key"], 0)
            )
            reward = {"local_reputation": actual_reputation}
            record_codex_discovery(
                connection,
                player_id=int(player["id"]),
                entry_key=choice["codex_entry_key"],
                operation_id=operation_id,
                occurred_at=now,
                content=self.content,
                category_snapshot=choice["codex_category"],
                snapshot={
                    "story_key": STORY_KEY,
                    "ending_key": choice["ending_key"],
                    "route_key": route_key,
                    "story_run_id": str(run["story_run_id"]),
                    "source_operation_ids": choice["source_operation_ids"],
                },
            )
            connection.execute(
                """
                INSERT INTO story_ending_claims(
                    story_run_id,player_id,story_key,ending_key,route_key,operation_id,
                    snapshot_json,reward_json,claimed_at
                ) VALUES(?,?,?,?,?,?,?,?,?)
                """,
                (
                    run["story_run_id"],
                    player["id"],
                    STORY_KEY,
                    choice["ending_key"],
                    route_key,
                    operation_id,
                    json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
                    json.dumps(reward, ensure_ascii=False, sort_keys=True),
                    now_text,
                ),
            )
            result = {"reward": reward, "claimed_at": now_text}
            connection.execute(
                "UPDATE story_runs SET status='ended',current_node=?,claim_operation_id=?,"
                "result_json=?,updated_at=? WHERE id=? AND status='ending_pending'",
                (
                    choice["ending_key"],
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
            record = self._story_record(updated_player, updated_run, {})
            self._insert_story_operation(
                connection, operation_id, operation_name, int(player["id"]), request_hash,
                self._story_payload(record), now_text,
            )
            return record

    def _story_evidence(
        self,
        connection: sqlite3.Connection,
        player_id: int,
        definition: StoryDefinition,
    ) -> dict[str, list[str]]:
        evidence: dict[str, list[str]] = {}
        for branch in definition.branches:
            if branch.source_kind == "commission":
                evidence[branch.key] = [
                    str(row["deliver_operation_id"])
                    for row in connection.execute(
                        "SELECT deliver_operation_id FROM town_commission_claims "
                        "WHERE player_id=? AND status='delivered' AND deliver_operation_id IS NOT NULL "
                        "ORDER BY delivered_at DESC,id DESC LIMIT ?",
                        (player_id, branch.required_source_count),
                    ).fetchall()
                ]
            elif branch.source_kind == "battle":
                wins: list[str] = []
                for row in connection.execute(
                    "SELECT resolved_operation_id,result_json FROM battle_sessions "
                    "WHERE player_id=? AND status='settled' AND resolved_operation_id IS NOT NULL "
                    "ORDER BY id DESC",
                    (player_id,),
                ).fetchall():
                    if json_object(row["result_json"], {}).get("outcome") == "won":
                        wins.append(str(row["resolved_operation_id"]))
                        if len(wins) == branch.required_source_count:
                            break
                evidence[branch.key] = wins
            else:
                harvests: list[str] = []
                for row in connection.execute(
                    "SELECT operation_id,result_json FROM operations "
                    "WHERE player_id=? AND operation_name=? "
                    "ORDER BY created_at DESC,rowid DESC LIMIT 20",
                    (player_id, branch.harvest_operation_name),
                ).fetchall():
                    result = json_object(row["result_json"], {})
                    if result.get("status") == "harvested" and result.get("plot_id"):
                        harvests.append(str(row["operation_id"]))
                        if len(harvests) == branch.required_source_count:
                            break
                dispatches: list[str] = []
                for row in connection.execute(
                    "SELECT settle_operation_id,result_json FROM dispatch_assignments "
                    "WHERE player_id=? AND dispatch_key=? AND status='settled' "
                    "AND settle_operation_id IS NOT NULL ORDER BY id DESC",
                    (player_id, branch.dispatch_key),
                ).fetchall():
                    if json_object(row["result_json"], {}).get("outcome") == "success":
                        dispatches.append(str(row["settle_operation_id"]))
                        if len(dispatches) == branch.required_source_count:
                            break
                evidence[branch.key] = (
                    harvests
                    if len(harvests) >= branch.required_source_count
                    else dispatches
                )
        return evidence

    def _story_record(
        self,
        player: sqlite3.Row,
        run: sqlite3.Row | None,
        evidence: dict[str, list[str]],
        *,
        replay: bool = False,
    ) -> StoryRecord:
        snapshot = json_object(run["snapshot_json"], {}) if run else {}
        selected = str(run["selected_route"]) if run and run["selected_route"] else None
        result = json_object(run["result_json"], {}) if run else {}
        choice = snapshot.get("choice", {}) if isinstance(snapshot.get("choice", {}), dict) else {}
        nodes = tuple(str(item) for item in choice.get("completed_nodes", ()))
        if run:
            story_name = snapshot.get("story_name")
            story_description = snapshot.get("story_description")
            if not isinstance(story_name, str) or not story_name or not isinstance(story_description, str) or not story_description:
                raise StoryContentError("frozen story display text is missing")
        else:
            definition = story_definition(self.content)
            story_name = definition.name
            story_description = definition.description
        if selected:
            frozen_choice = _frozen_story_choice(snapshot)
            branch = frozen_choice["branch"]
            branches = (
                StoryBranchView(
                    key=branch["key"],
                    label=branch["label"],
                    description=branch["description"],
                    required_source_count=branch["required_source_count"],
                    source_label=branch["source_label"],
                    evidence_operation_ids=tuple(frozen_choice["source_operation_ids"]),
                ),
            )
            ending_key = frozen_choice["ending_key"]
        else:
            definition = story_definition(self.content)
            branches = tuple(
                StoryBranchView(
                    key=branch.key,
                    label=branch.label,
                    description=branch.description,
                    required_source_count=branch.required_source_count,
                    source_label=branch.source_label,
                    evidence_operation_ids=tuple(evidence.get(branch.key, ())),
                )
                for branch in definition.branches
            )
            ending_key = None
        return StoryRecord(
            player=self._row_to_player(player),
            story_key=STORY_KEY,
            name=story_name,
            description=story_description,
            story_run_id=str(run["story_run_id"]) if run else None,
            status=str(run["status"]) if run else "available",
            current_node=str(run["current_node"]) if run else story_definition(self.content).entry_node,
            selected_route=selected,
            ending_key=ending_key,
            completed_nodes=nodes,
            branches=branches,
            snapshot=snapshot,
            reward={str(key): int(value) for key, value in result.get("reward", {}).items()},
            already_completed=replay,
        )

    def _story_payload(self, record: StoryRecord) -> dict[str, Any]:
        return {
            "player": self._player_payload(record.player),
            "story_key": record.story_key,
            "name": record.name,
            "description": record.description,
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
                    "description": branch.description,
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
            name=str(payload["name"]),
            description=str(payload["description"]),
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
                    description=str(item["description"]),
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


def _frozen_story_choice(snapshot: dict[str, Any]) -> dict[str, Any]:
    choice = snapshot.get("choice")
    required = {
        "route_key",
        "source_operation_ids",
        "completed_nodes",
        "branch",
        "ending_key",
        "flag_key",
        "codex_entry_key",
        "codex_category",
        "appearance_key",
        "reward",
        "reputation_key",
        "reputation_name",
        "local_reputation_maximums",
    }
    if not isinstance(choice, dict) or not required.issubset(choice):
        raise StoryContentError("frozen story choice is incomplete")
    text_fields = (
        "route_key",
        "ending_key",
        "flag_key",
        "codex_entry_key",
        "codex_category",
        "appearance_key",
        "reputation_key",
        "reputation_name",
    )
    if any(not isinstance(choice.get(field), str) or not choice[field] for field in text_fields):
        raise StoryContentError("frozen story choice contains invalid text")
    if not choice["flag_key"].startswith("flag.") or not choice["appearance_key"].startswith("appearance."):
        raise StoryContentError("frozen story choice contains invalid unlock keys")
    branch = choice["branch"]
    if (
        not isinstance(branch, dict)
        or branch.get("key") != choice["route_key"]
        or any(
            not isinstance(branch.get(field), str) or not branch[field]
            for field in ("label", "description", "source_label")
        )
        or isinstance(branch.get("required_source_count"), bool)
        or not isinstance(branch.get("required_source_count"), int)
        or branch["required_source_count"] <= 0
    ):
        raise StoryContentError("frozen story branch is invalid")
    for field in ("source_operation_ids", "completed_nodes"):
        values = choice[field]
        if (
            not isinstance(values, list)
            or not values
            or any(not isinstance(item, str) or not item for item in values)
        ):
            raise StoryContentError(f"frozen story choice {field} is invalid")
    maximums = choice["local_reputation_maximums"]
    if (
        not isinstance(maximums, dict)
        or set(maximums) != {choice["reputation_key"]}
        or isinstance(maximums[choice["reputation_key"]], bool)
        or not isinstance(maximums[choice["reputation_key"]], int)
        or maximums[choice["reputation_key"]] <= 0
    ):
        raise StoryContentError("frozen story reputation maximum is invalid")
    return choice

__all__ = ["StoryRepositoryMixin"]
