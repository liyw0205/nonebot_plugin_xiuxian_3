from __future__ import annotations

import copy
import json
import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle, ContentError
from nonebot_plugin_xiuxian_3.xiuxian.events.season_content import (
    FINAL_HEAVEN_SEASON_KEY,
    season_record,
)
from nonebot_plugin_xiuxian_3.xiuxian.events.rules import final_heaven_season_window
from nonebot_plugin_xiuxian_3.xiuxian.quests.rules import (
    DAO_ORIGIN_TASKS,
    dao_origin_task_definition,
)


ROOT = Path(__file__).resolve().parents[1]


class MutableClock:
    def __init__(self) -> None:
        self.value = datetime(2026, 10, 1, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.value


def _context(adapter: str, user: str, operation: str) -> CommandContext:
    return CommandContext(adapter=adapter, user_id=user, operation_id=operation)


async def _create_player(runtime, adapter: str, user: str) -> int:
    result = await runtime.dispatch(_context(adapter, user, f"create:{user}"), "开始修仙")
    assert result.ok
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE players SET stage='cultivator', realm_key='dao_union', realm_layer=1, endgame_status='dao_union' "
            "WHERE platform=? AND platform_user_id=?",
            (adapter, user),
        )
        return int(
            connection.execute(
                "SELECT id FROM players WHERE platform=? AND platform_user_id=?",
                (adapter, user),
            ).fetchone()[0]
        )


def _insert_task_evidence(
    runtime,
    player_id: int,
    apprentice_id: int,
    clock: MutableClock,
    counts: dict[str, int],
) -> str:
    season_id, starts_at, _ends_at = final_heaven_season_window(clock.value)
    now_text = clock.value.isoformat()
    with sqlite3.connect(runtime.settings.database_path) as connection:
        for task_key in DAO_ORIGIN_TASKS:
            snapshot = dao_origin_task_definition(task_key).snapshot(season_id)
            completed = counts.get(task_key, 0)
            for index in range(completed):
                source_operation_id = f"evidence:{task_key}:{index}"
                evidence_id = f"evidence-{task_key}-{index}"
                if task_key == "task.dao_origin.guard":
                    connection.execute(
                        "INSERT INTO battle_sessions("
                        "battle_id, player_id, start_operation_id, battle_type, enemy_key, location_key, "
                        "status, reward_status, starts_at, turn_deadline, result_json, created_at, updated_at) "
                        "VALUES (?, ?, ?, 'pve.dao_union_challenge', 'enemy.cross_realm_sentinel', "
                        "'cave.boundary_realm', 'settled', 'claimed', ?, ?, '{\"outcome\":\"won\"}', ?, ?)",
                        (
                            evidence_id,
                            player_id,
                            source_operation_id,
                            starts_at.isoformat(),
                            now_text,
                            now_text,
                            now_text,
                        ),
                    )
                    source_kind = "battle_sessions"
                elif task_key == "task.dao_origin.build":
                    project_id = f"project-{evidence_id}"
                    connection.execute(
                        "INSERT INTO livelihood_projects("
                        "project_id, project_key, business_week, status, target_points, effect_key, created_at, updated_at) "
                        "VALUES (?, 'project.town_well', ?, 'active', 1, 'town_well', ?, ?)",
                        (project_id, f"week-{evidence_id}", now_text, now_text),
                    )
                    connection.execute(
                        "INSERT INTO livelihood_project_rewards("
                        "project_id, player_id, operation_id, eligible, created_at) VALUES (?, ?, ?, 1, ?)",
                        (project_id, player_id, source_operation_id, starts_at.isoformat()),
                    )
                    evidence_id = project_id
                    source_kind = "livelihood_project_rewards"
                else:
                    connection.execute(
                        "INSERT INTO mentor_relations("
                        "relation_id, master_id, apprentice_id, status, expires_at, invited_at, graduated_at, "
                        "graduate_operation_id, created_at, updated_at) VALUES (?, ?, ?, 'graduated', ?, ?, ?, ?, ?, ?)",
                        (
                            evidence_id,
                            player_id,
                            apprentice_id,
                            starts_at.isoformat(),
                            starts_at.isoformat(),
                            starts_at.isoformat(),
                            source_operation_id,
                            starts_at.isoformat(),
                            starts_at.isoformat(),
                        ),
                    )
                    source_kind = "mentor_relations"
                payload = {
                    "count": index + 1,
                    "reward": {},
                    "season_id": season_id,
                    "task_snapshot": snapshot,
                    "event_key": "event.dao_origin",
                    "discovery": {},
                    "source_kind": source_kind,
                    "source_operation_id": source_operation_id,
                    "evidence_id": evidence_id,
                    "occurred_at": starts_at.isoformat(),
                    **({"source_key": "project.town_well"} if task_key == "task.dao_origin.build" else {}),
                }
                connection.execute(
                    "INSERT INTO quest_events(player_id, quest_key, component_key, source_operation_id, outcome, payload_json, created_at) "
                    "VALUES (?, ?, 'completed', ?, 'success', ?, ?)",
                    (player_id, task_key, source_operation_id, json.dumps(payload), now_text),
                )
            connection.execute(
                "INSERT INTO quest_progress(player_id, quest_key, status, progress_json, snapshot_json, source_operation_id, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    player_id,
                    task_key,
                    "completed" if completed >= int(snapshot["target"]) else "active",
                    json.dumps({"completed": completed, "target": snapshot["target"]}),
                    json.dumps(snapshot),
                    f"progress:{task_key}",
                    now_text,
                    now_text,
                ),
            )
    return season_id


def test_qualification_requires_all_current_season_tasks_and_is_idempotent() -> None:
    async def run() -> None:
        clock = MutableClock()
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, adapters=("qq.official", "onebot.v11"), clock=clock)
            try:
                player_id = await _create_player(runtime, "qq.official", "dao-qualification")
                apprentice_id = await _create_player(runtime, "qq.official", "dao-qualification-apprentice")
                season_id = _insert_task_evidence(
                    runtime,
                    player_id,
                    apprentice_id,
                    clock,
                    {DAO_ORIGIN_TASKS[0]: 3, DAO_ORIGIN_TASKS[1]: 3, DAO_ORIGIN_TASKS[2]: 2},
                )
                pending = await runtime.dispatch(
                    _context("qq.official", "dao-qualification", "status"), "道源资格"
                )
                assert pending.code == "DAO_ORIGIN_QUALIFICATION_STATUS"
                assert pending.data["season_id"] == season_id
                assert pending.data["status"] == "pending"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    row = connection.execute(
                        "SELECT id, payload_json FROM quest_events WHERE player_id=? AND quest_key=? ORDER BY id LIMIT 1",
                        (player_id, DAO_ORIGIN_TASKS[0]),
                    ).fetchone()
                    forged_payload = json.loads(row[1])
                    forged_payload["evidence_id"] = "forged-battle-id"
                    connection.execute(
                        "UPDATE quest_events SET payload_json=? WHERE id=?",
                        (json.dumps(forged_payload), row[0]),
                    )
                forged = await runtime.dispatch(
                    _context("qq.official", "dao-qualification", "forged-source"), "道源资格"
                )
                assert forged.code == "CONTENT_UNAVAILABLE"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    row = connection.execute(
                        "SELECT id, payload_json FROM quest_events WHERE player_id=? AND quest_key=? ORDER BY id LIMIT 1",
                        (player_id, DAO_ORIGIN_TASKS[0]),
                    ).fetchone()
                    restored_payload = json.loads(row[1])
                    restored_payload["evidence_id"] = f"evidence-{DAO_ORIGIN_TASKS[0]}-0"
                    connection.execute(
                        "UPDATE quest_events SET payload_json=? WHERE id=?",
                        (json.dumps(restored_payload), row[0]),
                    )
                blocked = await runtime.dispatch(
                    _context("qq.official", "dao-qualification", "blocked"), "领取道源资格"
                )
                assert blocked.code == "ENDGAME_EVENT_REQUIREMENT_MISSING"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    assert connection.execute("SELECT COUNT(*) FROM dao_origin_qualifications").fetchone()[0] == 0

                with sqlite3.connect(runtime.settings.database_path) as connection:
                    task_key = DAO_ORIGIN_TASKS[2]
                    snapshot = dao_origin_task_definition(task_key).snapshot(season_id)
                    source_operation_id = f"evidence:{task_key}:2"
                    evidence_id = f"evidence-{task_key}-2"
                    season_start = final_heaven_season_window(clock.value)[1]
                    connection.execute(
                        "INSERT INTO mentor_relations("
                        "relation_id, master_id, apprentice_id, status, expires_at, invited_at, graduated_at, "
                        "graduate_operation_id, created_at, updated_at) VALUES (?, ?, ?, 'graduated', ?, ?, ?, ?, ?, ?)",
                        (
                            evidence_id,
                            player_id,
                            apprentice_id,
                            season_start.isoformat(),
                            season_start.isoformat(),
                            season_start.isoformat(),
                            source_operation_id,
                            clock.value.isoformat(),
                            clock.value.isoformat(),
                        ),
                    )
                    payload = {
                        "count": 3,
                        "reward": {},
                        "season_id": season_id,
                        "task_snapshot": snapshot,
                        "event_key": "event.dao_origin",
                        "discovery": {},
                        "source_kind": "mentor_relations",
                        "source_operation_id": source_operation_id,
                        "evidence_id": evidence_id,
                        "occurred_at": season_start.isoformat(),
                    }
                    connection.execute(
                        "INSERT INTO quest_events(player_id, quest_key, component_key, source_operation_id, outcome, payload_json, created_at) "
                        "VALUES (?, ?, 'completed', ?, 'success', ?, ?)",
                        (player_id, task_key, source_operation_id, json.dumps(payload), clock.value.isoformat()),
                    )
                    connection.execute(
                        "UPDATE quest_progress SET status='completed', progress_json=? WHERE player_id=? AND quest_key=?",
                        (json.dumps({"completed": 3, "target": 3}), player_id, task_key),
                    )

                claimed = await runtime.dispatch(
                    _context("qq.official", "dao-qualification", "claim"), "领取道源资格"
                )
                assert claimed.code == "DAO_ORIGIN_QUALIFICATION_GRANTED"
                assert claimed.data["status"] == "qualified"
                assert claimed.data["readiness_flag"] == "access.final_heaven"
                replay = await runtime.dispatch(
                    _context("qq.official", "dao-qualification", "claim"), "领取道源资格"
                )
                assert replay.code == "DAO_ORIGIN_QUALIFICATION_GRANTED"
                assert replay.data["idempotent_replay"] is True
                duplicate = await runtime.dispatch(
                    _context("qq.official", "dao-qualification", "claim-again"), "领取道源资格"
                )
                assert duplicate.code == "QUEST_ALREADY_COMPLETED"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    assert connection.execute("SELECT COUNT(*) FROM dao_origin_qualifications").fetchone()[0] == 1
                    flags = json.loads(connection.execute("SELECT intro_json FROM players WHERE id=?", (player_id,)).fetchone()[0])["flags"]
                    assert flags == ["access.final_heaven"]
            finally:
                await runtime.close()

    import asyncio

    asyncio.run(run())


def test_qualification_snapshot_survives_rollover_and_rejects_forged_event() -> None:
    async def run() -> None:
        clock = MutableClock()
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, adapters=("qq.official",), clock=clock)
            try:
                player_id = await _create_player(runtime, "qq.official", "dao-rollover")
                apprentice_id = await _create_player(runtime, "qq.official", "dao-rollover-apprentice")
                season_id = _insert_task_evidence(
                    runtime,
                    player_id,
                    apprentice_id,
                    clock,
                    {task_key: 3 for task_key in DAO_ORIGIN_TASKS},
                )
                claimed = await runtime.dispatch(
                    _context("qq.official", "dao-rollover", "claim"), "领取道源资格"
                )
                assert claimed.ok
                clock.value += timedelta(days=36)
                current = await runtime.dispatch(
                    _context("qq.official", "dao-rollover", "status-next"), "道源资格"
                )
                assert current.data["season_id"] != season_id
                assert current.data["status"] == "pending"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    assert connection.execute("SELECT COUNT(*) FROM dao_origin_qualifications").fetchone()[0] == 1
                    connection.execute(
                        "UPDATE quest_events SET payload_json=? WHERE player_id=? AND quest_key=?",
                        ("{bad-json", player_id, DAO_ORIGIN_TASKS[0]),
                    )
                forged = await runtime.dispatch(
                    _context("qq.official", "dao-rollover", "status-forged"), "道源资格"
                )
                assert forged.code == "CONTENT_UNAVAILABLE"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    assert connection.execute("SELECT COUNT(*) FROM dao_origin_qualifications").fetchone()[0] == 1
            finally:
                await runtime.close()

    import asyncio

    asyncio.run(run())


def test_final_heaven_qualification_contract_is_strict() -> None:
    bundle = ContentBundle.load(ROOT / "data")
    record = copy.deepcopy(bundle._records[("season", FINAL_HEAVEN_SEASON_KEY)])
    record["qualification"] = {"task_keys": ["task.dao_origin.guard"], "readiness_flag": "access.final_heaven"}
    malformed = replace(
        bundle,
        _records={**bundle._records, ("season", FINAL_HEAVEN_SEASON_KEY): record},
    )
    with pytest.raises(ContentError, match="three dao-origin"):
        season_record(FINAL_HEAVEN_SEASON_KEY, malformed)
