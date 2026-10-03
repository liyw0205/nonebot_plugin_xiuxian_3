"""Atomic queries and milestone claims for the discovery codex."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from ...contracts import serialize_datetime
from ..persistence.errors import (
    CodexMilestoneAlreadyClaimedError,
    CodexMilestoneNotFoundError,
    CodexMilestoneNotReadyError,
    OperationConflictError,
)
from ..rewards.rules import local_reputation_maximum
from ..utils.player import grant_player_state, local_reputation_with_delta
from .codex_models import (
    CodexEntryRecord,
    CodexMilestoneClaimRecord,
    CodexMilestoneRecord,
    CodexOverviewRecord,
)
from .codex_rules import (
    codex_milestones,
    label_for_entry,
    unlock_label,
)


class CodexRepositoryMixin:
    async def get_codex(
        self, *, platform: str, platform_user_id: str
    ) -> CodexOverviewRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._get_codex_once, platform, platform_user_id)

    def _get_codex_once(self, platform: str, platform_user_id: str) -> CodexOverviewRecord:
        milestones = codex_milestones(self.content)
        with self._connect() as connection:
            player = self._require_player(connection, platform, platform_user_id, writable=False)
            entries = connection.execute(
                "SELECT entry_key, category, first_seen_at FROM codex_entries "
                "WHERE player_id = ? ORDER BY category, first_seen_at, entry_key",
                (player["id"],),
            ).fetchall()
            claims = {
                str(row["milestone_key"]): json.loads(row["reward_json"])
                for row in connection.execute(
                    "SELECT milestone_key, reward_json FROM codex_milestone_claims "
                    "WHERE player_id = ?",
                    (player["id"],),
                ).fetchall()
            }
            discovered = {str(row["entry_key"]) for row in entries}
            return CodexOverviewRecord(
                entries=tuple(
                    CodexEntryRecord(
                        entry_key=str(row["entry_key"]),
                        category=str(row["category"]),
                        label=label_for_entry(str(row["entry_key"]), self.content),
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
                        reputation_key=(
                            next(iter(claims[definition.key]), definition.reputation_key)
                            if definition.key in claims
                            else definition.reputation_key
                        ),
                        reputation_reward=(
                            next(iter(claims[definition.key].values()), 0)
                            if definition.key in claims
                            else definition.reputation_reward
                        ),
                        unlocks=definition.unlocks,
                    )
                    for definition in milestones.values()
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
        operation_name = "specials.claim_codex_milestone"
        request_payload = {
            "platform": platform,
            "platform_user_id": platform_user_id,
            "milestone_key": milestone_key,
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

            definition = codex_milestones(self.content).get(milestone_key)
            if definition is None:
                raise CodexMilestoneNotFoundError("unsupported codex milestone")

            player = self._require_player(connection, platform, platform_user_id)
            prior = connection.execute(
                "SELECT 1 FROM codex_milestone_claims "
                "WHERE player_id = ? AND milestone_key = ?",
                (player["id"], milestone_key),
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

            reward: dict[str, int] = {}
            if definition.reputation_key is not None and definition.reputation_reward:
                reputation_key = definition.reputation_key
                local_before = local_reputation_with_delta(
                    connection, int(player["id"]), {}
                ).get(reputation_key, 0)
                grant_player_state(
                    connection,
                    player,
                    rewards=None,
                    updated_at=now_text,
                    local_reputation_delta={reputation_key: definition.reputation_reward},
                    local_reputation_maximums={
                        reputation_key: local_reputation_maximum(reputation_key, self.content)
                    },
                )
                local_after = local_reputation_with_delta(
                    connection, int(player["id"]), {}
                ).get(reputation_key, 0)
                actual_reward = local_after - local_before
                if actual_reward:
                    reward[reputation_key] = actual_reward

            snapshot = {
                "entry_keys": list(entry_keys),
                "milestone_key": milestone_key,
            }
            connection.execute(
                """
                INSERT INTO codex_milestone_claims(
                    player_id, milestone_key, operation_id,
                    snapshot_json, reward_json, unlocks_json, claimed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    player["id"],
                    milestone_key,
                    operation_id,
                    json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
                    json.dumps(reward, ensure_ascii=False, sort_keys=True),
                    json.dumps(definition.unlocks, ensure_ascii=False),
                    now_text,
                ),
            )
            payload = {
                "milestone_key": milestone_key,
                "milestone_label": definition.label,
                "reward": reward,
                "reputation_name": definition.reputation_name,
                "unlocks": list(definition.unlocks),
                "unlock_labels": [unlock_label(key, self.content) for key in definition.unlocks],
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
            milestone_label=str(payload["milestone_label"]),
            reward={str(key): int(value) for key, value in dict(payload.get("reward", {})).items()},
            reputation_name=(
                str(payload["reputation_name"])
                if payload.get("reputation_name") is not None
                else None
            ),
            unlocks=tuple(str(key) for key in payload.get("unlocks", [])),
            unlock_labels=tuple(str(key) for key in payload["unlock_labels"]),
            already_completed=replay,
        )


__all__ = ["CodexRepositoryMixin"]
