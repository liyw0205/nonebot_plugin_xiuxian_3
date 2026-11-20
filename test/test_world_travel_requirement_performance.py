from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from nonebot_plugin_xiuxian_3.contracts import CommandContext, serialize_datetime
from nonebot_plugin_xiuxian_3.runtime import create_runtime


@pytest.mark.parametrize("adapter", ("onebot.v11", "qq.official"))
def test_travel_requirement_state_uses_one_indexed_gate_read(tmp_path, adapter: str) -> None:
    async def run() -> None:
        runtime = create_runtime(data_dir=tmp_path / adapter / "data", adapters=(adapter,))
        now = datetime(2026, 11, 15, 12, tzinfo=timezone.utc)
        try:
            for user in ("travel-apprentice", "travel-master"):
                result = await runtime.adapters.dispatch(
                    adapter,
                    CommandContext(adapter=adapter, user_id=user, request_id=f"create-{user}"),
                    "开始修仙",
                )
                assert result.code == "PLAYER_CREATED"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.row_factory = sqlite3.Row
                apprentice = connection.execute(
                    "SELECT * FROM players WHERE platform=? AND platform_user_id=?",
                    (adapter, "travel-apprentice"),
                ).fetchone()
                master = connection.execute(
                    "SELECT id FROM players WHERE platform=? AND platform_user_id=?",
                    (adapter, "travel-master"),
                ).fetchone()
                assert apprentice is not None and master is not None
                timestamp = serialize_datetime(now)
                connection.execute(
                    "INSERT INTO quest_progress(player_id, quest_key, status, progress_json, snapshot_json, created_at, updated_at) "
                    "VALUES (?, ?, 'completed', '{}', '{}', ?, ?)",
                    (apprentice["id"], "quest.travel.gate", timestamp, timestamp),
                )
                connection.execute(
                    "INSERT INTO mentor_relations(relation_id, master_id, apprentice_id, status, expires_at, invited_at, created_at, updated_at) "
                    "VALUES (?, ?, ?, 'invited', ?, ?, ?, ?)",
                    (
                        "travel-gate-relation",
                        master["id"],
                        apprentice["id"],
                        serialize_datetime(now + timedelta(days=1)),
                        timestamp,
                        timestamp,
                        timestamp,
                    ),
                )
                trace: list[str] = []
                connection.set_trace_callback(trace.append)
                state = runtime.repository._travel_requirement_state_in(connection, apprentice, now)
                connection.set_trace_callback(None)

                gate_queries = [
                    statement
                    for statement in trace
                    if "quest_progress" in statement or "mentor_relations" in statement
                ]
                assert len(gate_queries) == 1
                assert "UNION ALL" in gate_queries[0]
                assert state["completed_quests"] == {"quest.travel.gate"}
                assert state["mentor_invitation"] is True

                index_names = {
                    row["name"]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='index'"
                    ).fetchall()
                }
                assert "idx_quest_progress_player_status" in index_names
                assert "idx_mentor_relations_apprentice_status_expiry" in index_names
                assert connection.execute(
                    "SELECT 1 FROM schema_migrations WHERE migration_key=?",
                    ("world.travel_requirement_indexes",),
                ).fetchone() is not None

                plan = connection.execute(
                    """
                    EXPLAIN QUERY PLAN
                    SELECT quest_key AS value, 0 AS mentor
                    FROM quest_progress
                    WHERE player_id = ? AND status IN ('completed', 'claimed')
                    UNION ALL
                    SELECT NULL AS value,
                           EXISTS(
                               SELECT 1
                               FROM mentor_relations
                               WHERE apprentice_id = ?
                                 AND (status = 'active' OR (status = 'invited' AND expires_at > ?))
                               LIMIT 1
                           ) AS mentor
                    """,
                    (apprentice["id"], apprentice["id"], timestamp),
                ).fetchall()
                details = " ".join(str(row[3]).upper() for row in plan)
                assert "SCAN QUEST_PROGRESS" not in details
                assert "SCAN MENTOR_RELATIONS" not in details
                assert "IDX_QUEST_PROGRESS_PLAYER_STATUS" in details
                assert "IDX_MENTOR_RELATIONS_APPRENTICE_STATUS_EXPIRY" in details
        finally:
            await runtime.close()

    asyncio.run(run())
