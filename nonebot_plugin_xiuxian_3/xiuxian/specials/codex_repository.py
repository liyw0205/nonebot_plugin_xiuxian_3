"""Atomic queries and milestone claims for the discovery codex."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime
from typing import Any

from ...contracts import serialize_datetime
from ..persistence.errors import (
    CodexMilestoneAlreadyClaimedError,
    CodexMilestoneNotFoundError,
    CodexMilestoneNotReadyError,
    OperationConflictError,
)
from .codex_models import (
    CodexEntryRecord,
    CodexMilestoneClaimRecord,
    CodexMilestoneRecord,
    CodexOverviewRecord,
)
from .codex_rules import CONTENT_VERSION, MILESTONES, RULE_VERSION, label_for_entry


class CodexRepositoryMixin:
    async def get_codex(
        self, *, platform: str, platform_user_id: str
    ) -> CodexOverviewRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._get_codex_once, platform, platform_user_id)

    def _get_codex_once(self, platform: str, platform_user_id: str) -> CodexOverviewRecord:
        with self._connect() as connection:
            player = self._require_player(connection, platform, platform_user_id, writable=False)
            entries = connection.execute(
                "SELECT entry_key, category, first_seen_at FROM codex_entries "
                "WHERE player_id = ? ORDER BY category, first_seen_at, entry_key",
                (player["id"],),
            ).fetchall()
            claims = {
                str(row["milestone_key"])
                for row in connection.execute(
                    "SELECT milestone_key FROM codex_milestone_claims "
                    "WHERE player_id = ? AND content_version = ?",
                    (player["id"], CONTENT_VERSION),
                ).fetchall()
            }
            discovered = {str(row["entry_key"]) for row in entries}
            return CodexOverviewRecord(
                entries=tuple(
                    CodexEntryRecord(
                        entry_key=str(row["entry_key"]),
                        category=str(row["category"]),
                        label=label_for_entry(str(row["entry_key"])),
                        first_seen_at=str(row["first_seen_at"]),
                    )
                    for row in entries
                ),
                milestones=tuple(
                    CodexMilestoneRecord(
                        milestone_key=definition.key,
                        label=definition.label,
                        discovered_count=sum(key in discovered for key in definition.entry_keys),
                        required_count=len(definition.entry_keys),
                        ready=all(key in discovered for key in definition.entry_keys),
                        claimed=definition.key in claims,
                        reputation_reward=definition.reputation_reward,
                        unlocks=definition.unlocks,
                    )
                    for definition in MILESTONES.values()
                ),
            )

    async def claim_codex_milestone(
        self,
        *,
        platform: str,
        platform_user_id: str,
        milestone_key: str,
        operation_id: str,
    ) -> CodexMilestoneClaimRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._claim_codex_milestone_once,
                platform,
                platform_user_id,
                milestone_key,
                operation_id,
            )

    def _claim_codex_milestone_once(
        self,
        platform: str,
        platform_user_id: str,
        milestone_key: str,
        operation_id: str,
    ) -> CodexMilestoneClaimRecord:
        definition = MILESTONES.get(milestone_key)
        if definition is None:
            raise CodexMilestoneNotFoundError("unsupported codex milestone")
        operation_name = "specials.claim_codex_milestone"
        request_payload = {
            "platform": platform,
            "platform_user_id": platform_user_id,
            "milestone_key": milestone_key,
            "content_version": CONTENT_VERSION,
        }
        request_hash = self._request_hash(operation_name, request_payload)
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            operation = connection.execute(
                "SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            if operation is not None:
                if operation["operation_name"] != operation_name or operation["request_hash"] != request_hash:
                    raise OperationConflictError("codex claim operation input differs")
                return self._codex_milestone_claim_from_payload(
                    json.loads(operation["result_json"]), replay=True
                )

            player = self._require_player(connection, platform, platform_user_id)
            prior = connection.execute(
                "SELECT 1 FROM codex_milestone_claims "
                "WHERE player_id = ? AND milestone_key = ? AND content_version = ?",
                (player["id"], milestone_key, CONTENT_VERSION),
            ).fetchone()
            if prior is not None:
                raise CodexMilestoneAlreadyClaimedError("codex milestone is already claimed")

            placeholders = ",".join("?" for _ in definition.entry_keys)
            entries = connection.execute(
                f"SELECT entry_key FROM codex_entries WHERE player_id = ? AND entry_key IN ({placeholders}) ORDER BY entry_key",
                (player["id"], *definition.entry_keys),
            ).fetchall()
            entry_keys = tuple(str(row["entry_key"]) for row in entries)
            if len(entry_keys) != len(definition.entry_keys):
                raise CodexMilestoneNotReadyError("codex milestone requirements are incomplete")

            reward = (
                {"local.xuantian.new_town": definition.reputation_reward}
                if definition.reputation_reward
                else {}
            )
            if reward:
                reputation = connection.execute(
                    "SELECT local_json, service_reputation FROM player_reputations WHERE player_id = ?",
                    (player["id"],),
                ).fetchone()
                local = self._json_object(reputation["local_json"], {}) if reputation else {}
                service = int(reputation["service_reputation"]) if reputation else 0
                for key, amount in reward.items():
                    local[key] = min(1000, int(local.get(key, 0)) + amount)
                connection.execute(
                    """
                    INSERT INTO player_reputations(player_id, local_json, service_reputation, updated_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(player_id) DO UPDATE SET
                        local_json = excluded.local_json,
                        updated_at = excluded.updated_at
                    """,
                    (player["id"], json.dumps(local, ensure_ascii=False, sort_keys=True), service, now_text),
                )

            snapshot = {
                "entry_keys": list(entry_keys),
                "milestone_key": milestone_key,
                "content_version": CONTENT_VERSION,
                "rule_version": RULE_VERSION,
            }
            connection.execute(
                """
                INSERT INTO codex_milestone_claims(
                    player_id, milestone_key, content_version, operation_id,
                    snapshot_json, reward_json, unlocks_json, claimed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    player["id"],
                    milestone_key,
                    CONTENT_VERSION,
                    operation_id,
                    json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
                    json.dumps(reward, ensure_ascii=False, sort_keys=True),
                    json.dumps(definition.unlocks, ensure_ascii=False),
                    now_text,
                ),
            )
            payload = {
                "milestone_key": milestone_key,
                "reward": reward,
                "unlocks": list(definition.unlocks),
                "snapshot": snapshot,
            }
            connection.execute(
                "INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    operation_id,
                    operation_name,
                    player["id"],
                    request_hash,
                    json.dumps(payload, ensure_ascii=False, sort_keys=True),
                    now_text,
                ),
            )
            connection.execute("COMMIT")
            return self._codex_milestone_claim_from_payload(payload)

    @staticmethod
    def _codex_milestone_claim_from_payload(
        payload: dict[str, Any], *, replay: bool = False
    ) -> CodexMilestoneClaimRecord:
        return CodexMilestoneClaimRecord(
            milestone_key=str(payload["milestone_key"]),
            reward={str(key): int(value) for key, value in dict(payload.get("reward", {})).items()},
            unlocks=tuple(str(key) for key in payload.get("unlocks", [])),
            already_completed=replay,
        )


__all__ = ["CodexRepositoryMixin"]
