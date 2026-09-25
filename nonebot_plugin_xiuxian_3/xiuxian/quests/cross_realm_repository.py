"""Transactional source validation for the v0.3 demon mainline quest."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from ...contracts import serialize_datetime
from ..persistence.errors import (
    QuestAlreadyCompletedError,
    QuestNotCompletedError,
    QuestRequirementError,
)
from .cross_realm_rules import (
    DEMON_MAINLINE,
    DEMON_MAINLINE_ACCESS_FLAG,
    DEMON_MAINLINE_CONTENT_VERSION,
    DEMON_MAINLINE_EXPLORATION,
    DEMON_MAINLINE_EXPLORATION_TARGET,
    DEMON_MAINLINE_REQUIRED_REPUTATION,
    DEMON_MAINLINE_RULE_VERSION,
    demon_mainline_realm_ready,
)
from ..exploration.rules import V03_RULE_VERSION
from .models import QuestClaimRecord


class DemonQuestRepositoryMixin:
    """Keep cross-realm evidence and unlock writes out of generic quests."""

    async def claim_demon_mainline(
        self, *, platform: str, platform_user_id: str, operation_id: str
    ) -> QuestClaimRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._claim_demon_mainline_sync,
                platform,
                platform_user_id,
                operation_id,
            )

    def _claim_demon_mainline_sync(
        self, platform: str, platform_user_id: str, operation_id: str
    ) -> QuestClaimRecord:
        operation_name = f"{DEMON_MAINLINE}.claim"
        request_hash = self._request_hash(
            operation_name,
            {
                "platform": platform,
                "platform_user_id": platform_user_id,
                "quest_key": DEMON_MAINLINE,
            },
        )
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._quest_operation_replay(connection, operation_id, operation_name, request_hash)
            if replay is not None:
                return self._claim_from_payload(replay, replay=True)

            player = self._require_player(connection, platform, platform_user_id)
            player_id = int(player["id"])
            existing = connection.execute(
                "SELECT status FROM quest_progress WHERE player_id = ? AND quest_key = ?",
                (player_id, DEMON_MAINLINE),
            ).fetchone()
            if existing is not None and str(existing["status"]) in {"completed", "claimed"}:
                raise QuestAlreadyCompletedError("demon mainline is already claimed")
            if not demon_mainline_realm_ready(str(player["realm_key"]), int(player["realm_layer"])):
                raise QuestRequirementError("demon mainline requires nascent soul L1")

            reputation = self._json_object(player["faction_reputation_json"], {})
            demon_reputation = int(reputation.get("demon", 0))
            if demon_reputation < DEMON_MAINLINE_REQUIRED_REPUTATION:
                raise QuestRequirementError("demon reputation is insufficient")

            evidence = self._valid_demon_exploration_evidence(connection, player_id)
            if len(evidence) < DEMON_MAINLINE_EXPLORATION_TARGET:
                raise QuestNotCompletedError("demon abyss exploration evidence is incomplete")
            evidence = evidence[:DEMON_MAINLINE_EXPLORATION_TARGET]
            snapshot: dict[str, object] = {
                "quest_key": DEMON_MAINLINE,
                "content_version": DEMON_MAINLINE_CONTENT_VERSION,
                "rule_version": DEMON_MAINLINE_RULE_VERSION,
                "required_realm": "nascent_soul",
                "required_layer": 1,
                "required_reputation": DEMON_MAINLINE_REQUIRED_REPUTATION,
                "exploration_mode": DEMON_MAINLINE_EXPLORATION,
                "exploration_target": DEMON_MAINLINE_EXPLORATION_TARGET,
                "demon_reputation": demon_reputation,
                "exploration_operation_ids": [item["operation_id"] for item in evidence],
                "exploration_ids": [item["exploration_id"] for item in evidence],
            }

            intro = self._json_object(player["intro_json"], {})
            flags = {str(item) for item in intro.get("flags", [])}
            flags.update({DEMON_MAINLINE, DEMON_MAINLINE_ACCESS_FLAG})
            intro["flags"] = sorted(flags)
            connection.execute(
                "UPDATE players SET intro_json = ?, updated_at = ? WHERE id = ?",
                (json.dumps(intro, ensure_ascii=False, sort_keys=True), now_text, player_id),
            )
            for item in evidence:
                self._insert_quest_event(
                    connection,
                    player_id=player_id,
                    quest_key=DEMON_MAINLINE,
                    component_key=DEMON_MAINLINE_EXPLORATION,
                    source_operation_id=item["operation_id"],
                    outcome="won",
                    payload={"claim_operation_id": operation_id, "exploration_id": item["exploration_id"]},
                    now_text=now_text,
                    content_version=DEMON_MAINLINE_CONTENT_VERSION,
                    rule_version=DEMON_MAINLINE_RULE_VERSION,
                )
            progress = {
                DEMON_MAINLINE_EXPLORATION: DEMON_MAINLINE_EXPLORATION_TARGET,
            }
            self._upsert_progress(
                connection,
                player_id,
                DEMON_MAINLINE,
                "completed",
                progress,
                snapshot,
                operation_id,
                now_text,
                content_version=DEMON_MAINLINE_CONTENT_VERSION,
                rule_version=DEMON_MAINLINE_RULE_VERSION,
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (player_id,)).fetchone()
            payload = {
                "player": self._player_payload(self._row_to_player(updated)),
                "quest_key": DEMON_MAINLINE,
                "status": "completed",
                "progress": progress,
                "snapshot": snapshot,
            }
            self._insert_operation(
                connection,
                operation_id=operation_id,
                operation_name=operation_name,
                player_id=player_id,
                request_hash=request_hash,
                payload=payload,
                now_text=now_text,
            )
            return self._claim_from_payload(payload)

    @staticmethod
    def _valid_demon_exploration_evidence(
        connection: sqlite3.Connection, player_id: int
    ) -> list[dict[str, str]]:
        rows = connection.execute(
            """
            SELECT exploration_id, operation_id, location_key, snapshot_json, result_json
            FROM exploration_sessions
            WHERE player_id = ? AND mode_key = ? AND status = 'settled'
            ORDER BY id ASC
            """,
            (player_id, DEMON_MAINLINE_EXPLORATION),
        ).fetchall()
        evidence: list[dict[str, str]] = []
        seen_operations: set[str] = set()
        for row in rows:
            snapshot = DemonQuestRepositoryMixin._json_object(row["snapshot_json"], {})
            result = DemonQuestRepositoryMixin._json_object(row["result_json"], {})
            if snapshot.get("content_version") != DEMON_MAINLINE_CONTENT_VERSION:
                continue
            if snapshot.get("rule_version") != V03_RULE_VERSION:
                continue
            if str(row["location_key"]) != "demon.fallen_ruins":
                continue
            if result.get("battle_outcome") != "won":
                continue
            operation_id = str(row["operation_id"])
            if operation_id in seen_operations:
                continue
            seen_operations.add(operation_id)
            evidence.append(
                {
                    "exploration_id": str(row["exploration_id"]),
                    "operation_id": operation_id,
                }
            )
        return evidence

    @staticmethod
    def _json_object(value: Any, default: dict[str, object]) -> dict[str, object]:
        if isinstance(value, dict):
            return dict(value)
        try:
            loaded = json.loads(str(value or "{}"))
        except (TypeError, json.JSONDecodeError):
            return dict(default)
        return dict(loaded) if isinstance(loaded, dict) else dict(default)


__all__ = ["DemonQuestRepositoryMixin"]
