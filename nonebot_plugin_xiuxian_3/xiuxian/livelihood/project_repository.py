"""SQLite transactions for the weekly new-town public project."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from ...contracts import serialize_datetime
from ..utils.assets import (
    grant_player_assets,
    inventory_amount,
    spend_player_assets,
)
from ..utils.assets import player_currency
from ..utils.operations import player_operation
from ..utils.player import player_inventory
from ..persistence.errors import (
    OperationConflictError,
    ProjectAlreadyCompleteError,
    ProjectContributionLimitError,
    ProjectContributionRequirementError,
    ProjectContentClosedError,
    ProjectNotFoundError,
    ProjectNotReadyError,
    ProjectSourceAlreadyUsedError,
    ResourceInsufficientError,
)
from ..utils.json import json_object
from .project_models import ProjectContributionRecord, ProjectSettlementRecord, PublicProjectView
from .rules import (
    PublicProjectDefinition,
    public_project_definitions,
    project_definition,
    project_service_source,
    weekly_project_key,
)


class ProjectRepositoryMixin:
    """Own project generation, resource contributions and reward settlement."""

    async def list_projects(self, *, platform: str, platform_user_id: str) -> tuple[PublicProjectView, ...]:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._list_projects_sync, platform, platform_user_id)

    def _list_projects_sync(self, platform: str, platform_user_id: str) -> tuple[PublicProjectView, ...]:
        now = self._now()
        now_text = serialize_datetime(now)
        week = self._business_week(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            player = self._require_player(connection, platform, platform_user_id, writable=False)
            self._ensure_project(connection, week, now)
            # Authority-gated reconstruction projects are independent rows in
            # the same weekly ledger and are materialized only for eligible
            # players.
            for definition in public_project_definitions(self.content).values():
                if not (definition.required_faction or definition.required_sect_level):
                    continue
                if self._project_available(connection, player, definition):
                    self._ensure_project(connection, week, now, definition.key, player=player)
            projects = connection.execute(
                "SELECT * FROM livelihood_projects WHERE business_week = ? ORDER BY id",
                (week,),
            ).fetchall()
            for project in projects:
                self._refresh_status(project, connection, now, now_text)
            projects = connection.execute(
                "SELECT * FROM livelihood_projects WHERE business_week = ? ORDER BY id",
                (week,),
            ).fetchall()
            return tuple(self._project_view(project) for project in projects)

    async def contribute_project(
        self,
        *,
        platform: str,
        platform_user_id: str,
        project_key: str | None,
        resource_key: str | None,
        amount: int,
        operation_id: str,
        source_operation_id: str | None = None,
    ) -> ProjectContributionRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._contribute_project_once,
                platform,
                platform_user_id,
                project_key,
                resource_key,
                amount,
                operation_id,
                source_operation_id,
            )

    def _contribute_project_once(
        self,
        platform: str,
        platform_user_id: str,
        project_key: str | None,
        resource_key: str | None,
        amount: int,
        operation_id: str,
        source_operation_id: str | None,
    ) -> ProjectContributionRecord:
        try:
            definition = project_definition(project_key, self.content) if project_key else None
        except ValueError as exc:
            raise ProjectContentClosedError("unsupported project") from exc
        if source_operation_id and definition is None:
            raise ProjectContentClosedError("service contributions require an explicit project")
        points = 0
        if not source_operation_id:
            try:
                points = int(amount)
            except (TypeError, ValueError) as exc:
                raise ProjectContributionLimitError("contribution amount is invalid") from exc
            if points <= 0 or points > 30:
                raise ProjectContributionLimitError("one contribution is capped at 30 points")
        operation_name = "livelihood.contribute_project"
        request_hash = self._request_hash(
            operation_name,
            {
                "platform": platform,
                "platform_user_id": platform_user_id,
                "project_key": definition.key if definition else "",
                "resource_key": resource_key or "",
                "amount": points,
                "source_operation_id": source_operation_id or "",
            },
        )
        now = self._now()
        now_text = serialize_datetime(now)
        week = self._business_week(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._project_operation(connection, operation_id, operation_name, request_hash)
            if existing is not None:
                return self._contribution_from_payload(existing, replay=True)
            player = self._require_player(connection, platform, platform_user_id)
            project = self._ensure_project(
                connection,
                week,
                now,
                definition.key if definition is not None else None,
                player=player,
            )
            if definition is not None and definition.key != str(project["project_key"]):
                raise ProjectContentClosedError("project is not in this week's rotation")
            definition = project_definition(str(project["project_key"]), self.content)
            if definition.required_faction or definition.required_sect_level:
                self._require_project_day_quota(connection, project, player, now, points)
            self._refresh_status(project, connection, now, now_text)
            project = connection.execute("SELECT * FROM livelihood_projects WHERE id = ?", (project["id"],)).fetchone()
            if project is None:
                raise ProjectNotFoundError("project does not exist")
            if str(project["status"]) in {"active", "maintenance_due", "inactive"}:
                raise ProjectAlreadyCompleteError("project is already complete")
            resource = self._resolve_resource(definition, resource_key)
            if source_operation_id:
                return self._contribute_service_once(
                    connection,
                    player,
                    project,
                    definition,
                    source_operation_id,
                    operation_id,
                    request_hash,
                    now,
                    now_text,
                )
            if resource not in definition.contribution_resources:
                raise ProjectContributionRequirementError("resource cannot contribute to this project")
            cost_key, resource_amount = self._resource_cost(resource, points)
            inventory = player_inventory(player)
            if cost_key == "currency.spirit_stone":
                available = player_currency(player)
            else:
                available = inventory_amount(inventory, cost_key)
            if available < resource_amount:
                raise ResourceInsufficientError("project resource is insufficient")
            progress = json_object(project["progress_json"], {})
            required = int(definition.requirements.get(cost_key, 0))
            before = int(progress.get(cost_key, 0))
            if before >= required:
                raise ProjectContributionRequirementError("this project requirement is already complete")
            resource_amount = min(resource_amount, required - before)
            points = resource_amount if cost_key != "currency.spirit_stone" else resource_amount // 50
            if points <= 0:
                raise ProjectContributionRequirementError("the contribution does not complete a resource unit")
            if points > 30:
                raise ProjectContributionLimitError("one contribution is capped at 30 points")
            if cost_key == "currency.spirit_stone":
                resource_amount = points * 50
                spend_player_assets(
                    connection,
                    player,
                    {"spirit_stones": resource_amount},
                    now_text,
                )
            else:
                spend_player_assets(connection, player, {cost_key: resource_amount}, now_text)
            progress[cost_key] = before + resource_amount
            contribution_points = int(project["contribution_points"]) + points
            target_points = int(project["target_points"])
            complete = all(int(progress.get(key, 0)) >= int(value) for key, value in definition.requirements.items())
            status = "active" if complete else "proposed"
            effect_starts = now_text if complete else project["effect_starts_at"]
            effect_ends = serialize_datetime(now + timedelta(days=7)) if complete else project["effect_ends_at"]
            connection.execute(
                """
                UPDATE livelihood_projects
                SET status = ?, contribution_points = ?, progress_json = ?,
                    effect_starts_at = ?, effect_ends_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    status,
                    contribution_points,
                    json.dumps(progress, ensure_ascii=False, sort_keys=True),
                    effect_starts,
                    effect_ends,
                    now_text,
                    project["id"],
                ),
            )
            contribution_id = uuid4().hex
            connection.execute(
                """
                INSERT INTO livelihood_project_contributions(
                    contribution_id, project_id, player_id, operation_id,
                    source_operation_id, contribution_kind, service_key, quantity,
                    resource_key, resource_amount, contribution_points, created_at
                ) VALUES (?, ?, ?, ?, ?, 'resource', '', ?, ?, ?, ?, ?)
                """,
                (
                    contribution_id,
                    project["project_id"],
                    player["id"],
                    operation_id,
                    operation_id,
                    resource_amount,
                    cost_key,
                    resource_amount,
                    points,
                    now_text,
                ),
            )
            updated_project = connection.execute("SELECT * FROM livelihood_projects WHERE id = ?", (project["id"],)).fetchone()
            updated_player = connection.execute("SELECT * FROM players WHERE id = ?", (player["id"],)).fetchone()
            payload = {
                "player": self._player_payload(self._row_to_player(updated_player)),
                "project": self._project_payload(updated_project),
                "resource_key": cost_key,
                "resource_amount": resource_amount,
                "contribution_points": points,
                "source_operation_id": operation_id,
                "service_key": "",
                "quantity": resource_amount,
            }
            self._record_project_operation(connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text)
            return self._contribution_from_payload(payload)

    def _contribute_service_once(
        self,
        connection: Any,
        player: Any,
        project: Any,
        definition: PublicProjectDefinition,
        source_operation_id: str,
        operation_id: str,
        request_hash: str,
        now: datetime,
        now_text: str,
    ) -> ProjectContributionRecord:
        evidence = player_operation(connection, source_operation_id, player_id=int(player["id"]))
        if evidence is None:
            raise ProjectContributionRequirementError("service source is unavailable")
        operation_name, source_payload = evidence
        source = project_service_source(definition.key, operation_name, self.content)
        if source is None:
            raise ProjectContributionRequirementError("service source cannot contribute to this project")
        self._validate_project_service_source(
            connection,
            player,
            source_operation_id,
            operation_name,
            source_payload,
        )
        used = connection.execute(
            "SELECT 1 FROM livelihood_project_contributions WHERE player_id = ? AND source_operation_id = ? LIMIT 1",
            (player["id"], source_operation_id),
        ).fetchone()
        if used is not None:
            raise ProjectSourceAlreadyUsedError("service source has already contributed")
        self._require_project_day_quota(connection, project, player, now, source.contribution_points)
        contribution_points = int(project["contribution_points"]) + source.contribution_points
        connection.execute(
            "UPDATE livelihood_projects SET contribution_points = ?, updated_at = ? WHERE id = ?",
            (contribution_points, now_text, project["id"]),
        )
        contribution_id = uuid4().hex
        connection.execute(
            """
            INSERT INTO livelihood_project_contributions(
                contribution_id, project_id, player_id, operation_id,
                source_operation_id, contribution_kind, service_key, quantity,
                resource_key, resource_amount, contribution_points, created_at
            ) VALUES (?, ?, ?, ?, ?, 'service', ?, ?, ?, ?, ?, ?)
            """,
            (
                contribution_id,
                project["project_id"],
                player["id"],
                operation_id,
                source_operation_id,
                source.service_key,
                source.quantity,
                source.service_key,
                source.quantity,
                source.contribution_points,
                now_text,
            ),
        )
        updated_project = connection.execute("SELECT * FROM livelihood_projects WHERE id = ?", (project["id"],)).fetchone()
        updated_player = connection.execute("SELECT * FROM players WHERE id = ?", (player["id"],)).fetchone()
        if updated_project is None or updated_player is None:
            raise RuntimeError("service contribution returned no state")
        payload = {
            "player": self._player_payload(self._row_to_player(updated_player)),
            "project": self._project_payload(updated_project),
            "resource_key": source.service_key,
            "resource_amount": source.quantity,
            "contribution_points": source.contribution_points,
            "source_operation_id": source_operation_id,
            "service_key": source.service_key,
            "quantity": source.quantity,
        }
        self._record_project_operation(connection, operation_id, "livelihood.contribute_project", int(player["id"]), request_hash, payload, now_text)
        return self._contribution_from_payload(payload)

    @staticmethod
    def _validate_project_service_source(
        connection: Any,
        player: Any,
        source_operation_id: str,
        operation_name: str,
        payload: dict[str, Any],
    ) -> None:
        if operation_name == "livelihood.settle_route":
            row = connection.execute(
                "SELECT status, player_id, settle_operation_id, result_json "
                "FROM livelihood_trade_routes WHERE settle_operation_id = ?",
                (source_operation_id,),
            ).fetchone()
            if row is None or int(row["player_id"]) != int(player["id"]) or str(row["status"]) != "settled":
                raise ProjectContributionRequirementError("transport source is not settled")
            if str(row["settle_operation_id"]) != source_operation_id or str(payload.get("status")) != "settled":
                raise ProjectContributionRequirementError("transport source is not settled")
            return
        if operation_name == "production.purify_pollution":
            reduced = payload.get("pollution_reduced")
            before = payload.get("pollution_before")
            after = payload.get("pollution_after")
            event = connection.execute(
                "SELECT 1 FROM activity_events WHERE player_id = ? AND event_key = ? AND source_operation_id = ? LIMIT 1",
                (player["id"], operation_name, source_operation_id),
            ).fetchone()
            if (
                event is None
                or any(isinstance(value, bool) or not isinstance(value, int) for value in (before, after, reduced))
                or reduced <= 0
            ):
                raise ProjectContributionRequirementError("purification source is not settled")
            if after >= before or reduced != before - after:
                raise ProjectContributionRequirementError("purification source is not settled")
            return
        if operation_name in {"companion.bond", "companion.feed", "companion.rest"}:
            companion = payload.get("companion")
            if payload.get("changed") is not True or not isinstance(companion, dict):
                raise ProjectContributionRequirementError("companion source is not settled")
            instance_id = str(companion.get("instance_id", "")).strip()
            if not instance_id or str(companion.get("kind")) not in {"beast", "mount"}:
                raise ProjectContributionRequirementError("companion source is not settled")
            if str(companion.get("status")) not in {"active", "available"}:
                raise ProjectContributionRequirementError("companion source is not settled")
            row = connection.execute(
                "SELECT player_id, kind FROM companion_instances WHERE instance_id = ?",
                (instance_id,),
            ).fetchone()
            if (
                row is None
                or int(row["player_id"]) != int(player["id"])
                or str(row["kind"]) != str(companion["kind"])
            ):
                raise ProjectContributionRequirementError("companion source is not settled")
            return
        raise ProjectContributionRequirementError("unsupported service source")

    async def settle_project(
        self,
        *,
        platform: str,
        platform_user_id: str,
        project_id: str | None,
        operation_id: str,
    ) -> ProjectSettlementRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._settle_project_once,
                platform,
                platform_user_id,
                project_id,
                operation_id,
            )

    def _settle_project_once(
        self,
        platform: str,
        platform_user_id: str,
        project_id: str | None,
        operation_id: str,
    ) -> ProjectSettlementRecord:
        operation_name = "livelihood.settle_project"
        request_hash = self._request_hash(
            operation_name,
            {"platform": platform, "platform_user_id": platform_user_id, "project_id": project_id or ""},
        )
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._project_operation(connection, operation_id, operation_name, request_hash)
            if existing is not None:
                return self._project_settlement_from_payload(existing, replay=True)
            player = self._require_player(connection, platform, platform_user_id)
            if project_id:
                project = connection.execute("SELECT * FROM livelihood_projects WHERE project_id = ?", (project_id,)).fetchone()
            else:
                project = connection.execute(
                    """
                    SELECT p.*
                    FROM livelihood_projects p
                    JOIN livelihood_project_contributions c ON c.project_id = p.project_id
                    WHERE p.business_week = ? AND c.player_id = ?
                    ORDER BY p.id DESC
                    LIMIT 1
                    """,
                    (self._business_week(now), player["id"]),
                ).fetchone()
            if project is None:
                raise ProjectNotFoundError("project does not exist")
            self._refresh_status(project, connection, now, now_text)
            project = connection.execute("SELECT * FROM livelihood_projects WHERE id = ?", (project["id"],)).fetchone()
            if project is None or str(project["status"]) not in {"active", "maintenance_due"}:
                raise ProjectNotReadyError("project is not complete")
            prior = connection.execute(
                "SELECT eligible, reward_json FROM livelihood_project_rewards WHERE project_id = ? AND player_id = ?",
                (project["project_id"], player["id"]),
            ).fetchone()
            if prior is not None:
                reward = json_object(prior["reward_json"], {})
                payload = self._settlement_payload(player, project, bool(prior["eligible"]), bool(prior["eligible"]), reward)
                self._record_project_operation(connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text)
                return self._project_settlement_from_payload(payload, replay=True)
            contribution = connection.execute(
                "SELECT COALESCE(SUM(contribution_points), 0) AS points FROM livelihood_project_contributions WHERE project_id = ? AND player_id = ?",
                (project["project_id"], player["id"]),
            ).fetchone()
            eligible = int(contribution["points"] if contribution is not None else 0) >= 10
            reward: dict[str, int] = {}
            updated_player = player
            if eligible:
                definition = project_definition(str(project["project_key"]), self.content)
                reward = self._grant_reward(connection, player, definition, now_text, project["project_id"], operation_id)
                updated_player = connection.execute("SELECT * FROM players WHERE id = ?", (player["id"],)).fetchone()
                connection.execute(
                    "INSERT INTO livelihood_project_rewards(project_id, player_id, operation_id, eligible, reward_json, created_at) VALUES (?, ?, ?, 1, ?, ?)",
                    (project["project_id"], player["id"], operation_id, json.dumps(reward, ensure_ascii=False, sort_keys=True), now_text),
                )
            payload = self._settlement_payload(updated_player, project, eligible, eligible, reward)
            self._record_project_operation(connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text)
            return self._project_settlement_from_payload(payload)

    @staticmethod
    def _business_week(now: datetime) -> str:
        start = now.date() - timedelta(days=now.weekday())
        return start.isoformat()

    @staticmethod
    def _project_target(definition: PublicProjectDefinition) -> int:
        return sum(value if key != "currency.spirit_stone" else value // 50 for key, value in definition.requirements.items())

    def _ensure_project(
        self,
        connection: Any,
        week: str,
        now: datetime,
        project_key: str | None = None,
        *,
        player: Any | None = None,
    ) -> Any:
        key = weekly_project_key(week) if project_key is None else project_key
        definition = project_definition(key, self.content)
        if definition.required_faction or definition.required_sect_level:
            if player is None or not self._project_available(connection, player, definition):
                raise ProjectContentClosedError("project authority is not available")
        row = connection.execute(
            "SELECT * FROM livelihood_projects WHERE project_key = ? AND business_week = ?",
            (definition.key, week),
        ).fetchone()
        if row is not None:
            return row
        now_text = serialize_datetime(now)
        project_prefix = (
            "project.reconstruction"
            if definition.required_faction or definition.required_sect_level
            else "project.new_town"
        )
        project_id = f"{project_prefix}.{week}.{definition.key.rsplit('.', 1)[-1]}"
        requirements = dict(definition.requirements)
        progress = {key: 0 for key in requirements}
        connection.execute(
            """
            INSERT INTO livelihood_projects(
                project_id, project_key, business_week, status, target_points,
                contribution_points, requirements_json, progress_json, effect_key,
                snapshot_json, created_at, updated_at
            ) VALUES (?, ?, ?, 'proposed', ?, 0, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_id,
                definition.key,
                week,
                self._project_target(definition),
                json.dumps(requirements, ensure_ascii=False, sort_keys=True),
                json.dumps(progress, ensure_ascii=False, sort_keys=True),
                definition.effect_key,
                json.dumps({"label": definition.label}, ensure_ascii=False, sort_keys=True),
                now_text,
                now_text,
            ),
        )
        return connection.execute("SELECT * FROM livelihood_projects WHERE project_id = ?", (project_id,)).fetchone()

    @staticmethod
    def _project_available(connection: Any, player: Any, definition: PublicProjectDefinition) -> bool:
        """Check project authority without granting it implicitly."""

        has_access = False
        if definition.required_access_key:
            has_access = connection.execute(
                "SELECT 1 FROM activity_events WHERE player_id = ? AND event_key = ? LIMIT 1",
                (player["id"], definition.required_access_key),
            ).fetchone() is not None
        if definition.required_faction:
            faction = json_object(player["faction_reputation_json"], {})
            if int(faction.get(definition.required_faction, 0)) < definition.required_faction_reputation:
                return False
        if definition.required_sect_level:
            reputation = connection.execute(
                "SELECT local_json FROM player_reputations WHERE player_id = ?",
                (player["id"],),
            ).fetchone()
            local = json_object(reputation["local_json"], {}) if reputation else {}
            city_authorized = int(local.get("local.domain_refuge_authorized", 0)) > 0 or has_access
            sect_authorized = connection.execute(
                """
                SELECT 1
                FROM sect_members m JOIN sects s ON s.sect_id = m.sect_id
                WHERE m.player_id = ? AND m.status = 'active' AND s.status = 'active' AND s.level >= ?
                LIMIT 1
                """,
                (player["id"], definition.required_sect_level),
            ).fetchone()
            if not city_authorized and sect_authorized is None:
                return False
        return True

    @staticmethod
    def _require_project_day_quota(
        connection: Any,
        project: Any,
        player: Any,
        now: datetime,
        requested_points: int,
    ) -> None:
        """Cap each player's same-project contribution at 30 points/day."""

        day = now.date().isoformat()
        row = connection.execute(
            """
            SELECT COALESCE(SUM(contribution_points), 0) AS points
            FROM livelihood_project_contributions
            WHERE project_id = ? AND player_id = ? AND substr(created_at, 1, 10) = ?
            """,
            (project["project_id"], player["id"], day),
        ).fetchone()
        if int(row["points"] if row else 0) + int(requested_points) > 30:
            raise ProjectContributionLimitError("本项目今日贡献已达上限")

    @staticmethod
    def _refresh_status(project: Any, connection: Any, now: datetime, now_text: str) -> None:
        if str(project["status"]) == "active" and project["effect_ends_at"]:
            if now >= datetime.fromisoformat(str(project["effect_ends_at"])):
                connection.execute(
                    "UPDATE livelihood_projects SET status = 'maintenance_due', updated_at = ? WHERE id = ? AND status = 'active'",
                    (now_text, project["id"]),
                )

    @staticmethod
    def _public_project_effects(connection: Any, now: datetime) -> frozenset[str]:
        """Return only effects whose fixed seven-day window is still active."""

        now_text = serialize_datetime(now)
        rows = connection.execute(
            """
            SELECT effect_key FROM livelihood_projects
            WHERE status = 'active' AND effect_starts_at <= ? AND effect_ends_at > ?
            """,
            (now_text, now_text),
        ).fetchall()
        return frozenset(str(row["effect_key"]) for row in rows)

    @staticmethod
    def _resolve_resource(definition: PublicProjectDefinition, resource_key: str | None) -> str:
        aliases = {
            "木材": "item.mat.wood",
            "云铁": "item.material.cloud_iron",
            "灵石": "currency.spirit_stone",
            "灵叶": "item.herb.spirit_leaf",
            "灵米": "item.food.coarse_spirit_rice",
            "灵米饭": "item.food.coarse_spirit_rice",
            "血草": "item.herb.blood_grass",
            "阵砂": "item.mat.array_sand",
            "疗伤丹": "item.pill.healing_low",
        }
        value = aliases.get((resource_key or "").strip(), (resource_key or "").strip())
        return value or definition.contribution_resources[0]

    @staticmethod
    def _resource_cost(resource: str, points: int) -> tuple[str, int]:
        if resource == "currency.spirit_stone":
            return resource, points * 50
        return resource, points

    def _grant_reward(
        self,
        connection: Any,
        player: Any,
        definition: PublicProjectDefinition,
        now_text: str,
        project_id: str,
        operation_id: str,
    ) -> dict[str, int]:
        reward = {str(key): int(value) for key, value in definition.reward.items() if isinstance(value, int)}
        item_key = definition.reward.get("item")
        if item_key:
            reward[str(item_key)] = 1
        grant_player_assets(
            connection,
            player,
            {
                key: value
                for key, value in reward.items()
                if key == "spirit_stones" or key.startswith("item.")
            },
            now_text,
        )
        local_delta = int(reward.get("local_reputation", 0))
        service_delta = int(reward.get("service_reputation", 0))
        if local_delta or service_delta:
            row = connection.execute("SELECT local_json, service_reputation FROM player_reputations WHERE player_id = ?", (player["id"],)).fetchone()
            local = json_object(row["local_json"], {}) if row is not None else {}
            local_key = definition.local_reputation_key
            local[local_key] = min(1000, int(local.get(local_key, 0)) + local_delta)
            service = min(100, int(row["service_reputation"]) + service_delta) if row is not None else service_delta
            connection.execute(
                """
                INSERT INTO player_reputations(player_id, local_json, service_reputation, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(player_id) DO UPDATE SET local_json = excluded.local_json,
                    service_reputation = excluded.service_reputation, updated_at = excluded.updated_at
                """,
                (player["id"], json.dumps(local, ensure_ascii=False, sort_keys=True), service, now_text),
            )
        return reward

    @staticmethod
    def _project_payload(row: Any) -> dict[str, Any]:
        snapshot = json_object(row["snapshot_json"], {})
        return {
            "project_id": str(row["project_id"]),
            "project_key": str(row["project_key"]),
            "label": str(snapshot.get("label", row["project_key"])),
            "business_week": str(row["business_week"]),
            "status": str(row["status"]),
            "contribution_points": int(row["contribution_points"]),
            "target_points": int(row["target_points"]),
            "progress": json_object(row["progress_json"], {}),
            "requirements": json_object(row["requirements_json"], {}),
            "effect_key": str(row["effect_key"]),
            "effect_ends_at": str(row["effect_ends_at"] or ""),
        }

    @staticmethod
    def _project_view(row: Any) -> PublicProjectView:
        payload = ProjectRepositoryMixin._project_payload(row)
        return PublicProjectView(**payload)

    def _contribution_from_payload(self, payload: dict[str, Any], *, replay: bool = False) -> ProjectContributionRecord:
        return ProjectContributionRecord(
            player=self._row_to_player(payload["player"]),
            project=PublicProjectView(**payload["project"]),
            resource_key=str(payload["resource_key"]),
            resource_amount=int(payload["resource_amount"]),
            contribution_points=int(payload["contribution_points"]),
            source_operation_id=str(payload.get("source_operation_id", "")),
            service_key=str(payload.get("service_key", "")),
            quantity=int(payload.get("quantity", payload.get("resource_amount", 0))),
            already_completed=replay,
        )

    def _settlement_payload(self, player: Any, project: Any, eligible: bool, rewarded: bool, reward: dict[str, int]) -> dict[str, Any]:
        return {
            "player": self._player_payload(self._row_to_player(player)),
            "project": self._project_payload(project),
            "eligible": eligible,
            "rewarded": rewarded,
            "reward": reward,
        }

    def _project_settlement_from_payload(self, payload: dict[str, Any], *, replay: bool = False) -> ProjectSettlementRecord:
        return ProjectSettlementRecord(
            player=self._row_to_player(payload["player"]),
            project=PublicProjectView(**payload["project"]),
            eligible=bool(payload.get("eligible", False)),
            rewarded=bool(payload.get("rewarded", False)),
            reward={str(key): int(value) for key, value in payload.get("reward", {}).items() if isinstance(value, int)},
            already_completed=replay,
        )

    @staticmethod
    def _project_operation(connection: Any, operation_id: str, operation_name: str, request_hash: str) -> dict[str, Any] | None:
        existing = connection.execute("SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id = ?", (operation_id,)).fetchone()
        if existing is None:
            return None
        if existing["operation_name"] != operation_name or existing["request_hash"] != request_hash:
            raise OperationConflictError("operation input differs from its original request")
        try:
            payload = json.loads(existing["result_json"])
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise OperationConflictError("operation result is not valid JSON") from exc
        if not isinstance(payload, dict):
            raise OperationConflictError("operation result must be a JSON object")
        return payload

    @staticmethod
    def _record_project_operation(connection: Any, operation_id: str, operation_name: str, player_id: int, request_hash: str, payload: dict[str, Any], now_text: str) -> None:
        connection.execute(
            "INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (operation_id, operation_name, player_id, request_hash, json.dumps(payload, ensure_ascii=False, sort_keys=True), now_text),
        )


__all__ = ["ProjectRepositoryMixin"]
