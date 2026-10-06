from __future__ import annotations

import asyncio
import json
import shutil
import sqlite3
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

from nonebot_plugin_xiuxian_3.adapters.onebot import normalize_event
from nonebot_plugin_xiuxian_3.adapters.qq import normalize_event as normalize_qq_event
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle, ContentError
from nonebot_plugin_xiuxian_3.xiuxian.events.rules import final_heaven_season_window
from nonebot_plugin_xiuxian_3.xiuxian.quests.rules import (
    DAO_ORIGIN_TASKS,
    dao_origin_task_definition,
)
from test_adapter_simulation import _onebot_group_event, _qq_group_event
from test_dao_origin_build_codex import FixedClock, _prepare_player


BUILD = "task.dao_origin.build"
ADAPTERS = ("qq.official", "onebot.v11")


def _content(tmp_path: Path) -> Path:
    root = tmp_path / "content"
    shutil.copytree(Path(__file__).parents[1] / "data", root)
    return root


def _edit(root: Path, filename: str, key: str, **changes) -> None:
    path = root / filename
    document = json.loads(path.read_text(encoding="utf-8"))
    next(row for row in document["records"] if row["key"] == key).update(changes)
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")


def _message(adapter: str, command: str):
    if adapter == "qq.official":
        return normalize_qq_event(_qq_group_event(command))
    return normalize_event(_onebot_group_event(command))


async def _send(
    runtime, adapter: str, operation: str, command: str = "完成道源任务 建设"
):
    message = _message(adapter, command)
    return await runtime.adapters.dispatch(
        adapter, replace(message.context, operation_id=operation), message.text
    )


def _state(runtime) -> dict[str, list]:
    with sqlite3.connect(runtime.settings.database_path) as db:
        return {
            table: db.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
            for table in (
                "players",
                "operations",
                "quest_progress",
                "quest_events",
                "codex_entries",
            )
        }


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_origin_freezes_content_recovers_and_replays_without_current_labels(
    tmp_path: Path, adapter: str
) -> None:
    async def run() -> None:
        root, clock = _content(tmp_path), FixedClock()
        reward = {
            "dao_fruit_progress": 999,
            "ascension_merit": 888,
            "world_merit": 77,
            "item.tribulation_token": 2,
        }
        _edit(root, "任务/任务.json", BUILD, name="修缮山门", target=2, reward=reward)
        runtime = create_runtime(data_dir=root, clock=clock, adapters=(adapter,))
        player_id = await _prepare_player(
            runtime, adapter, _message(adapter, "").context.user_id
        )
        before = _state(runtime)
        preview = await _send(runtime, adapter, "preview", "高阶任务")
        assert preview.data["quests"][BUILD]["progress"] == {
            "completed": 0,
            "target": 2,
        }
        assert _state(runtime) == before
        first = await _send(runtime, adapter, "first")
        assert first.code == "DAO_ORIGIN_TASK_RECORDED", first
        assert first.data["progress"] == {"completed": 1, "target": 2}
        assert first.data["reward"] == {}
        await runtime.close()

        _edit(root, "任务/任务.json", BUILD, status="closed")
        runtime = create_runtime(data_dir=root, clock=clock, adapters=(adapter,))
        before = _state(runtime)
        rejected = await _send(runtime, adapter, "complete")
        assert rejected.code == "ENDGAME_EVENT_REQUIREMENT_MISSING"
        preview = await _send(runtime, adapter, "preview-closed", "高阶任务")
        assert preview.data["quests"][BUILD]["status"] == "closed"
        assert preview.data["quests"][BUILD]["progress"] == {
            "completed": 1,
            "target": 2,
        }
        assert (await _send(runtime, adapter, "first")).message == first.message
        assert _state(runtime) == before
        await runtime.close()

        _edit(
            root,
            "任务/任务.json",
            BUILD,
            status="open",
            name="重修山门",
            target=1,
            reward={key: 1 for key in reward},
        )
        _edit(
            root,
            "图鉴/条目.json",
            "codex.dao.service_settlement",
            name="新见闻",
            status="closed",
        )
        _edit(root, "道具/材料.json", "item.tribulation_token", name="新凭证")
        runtime = create_runtime(data_dir=root, clock=clock, adapters=(adapter,))
        preview = await _send(runtime, adapter, "preview-frozen", "高阶任务")
        assert preview.data["quests"][BUILD]["progress"] == {
            "completed": 1,
            "target": 2,
        }
        completed = await _send(runtime, adapter, "complete")
        assert completed.code == "DAO_ORIGIN_TASK_RECORDED", completed
        assert completed.data["reward"] == reward
        assert completed.data["progress"] == {"completed": 2, "target": 2}
        assert "修缮山门" in completed.message and "重修山门" not in completed.message
        assert "天劫凭证" in completed.message and "新凭证" not in completed.message
        assert completed.data["discovery"]["label"] == "道统服务结算"
        with sqlite3.connect(runtime.settings.database_path) as db:
            assert db.execute(
                "SELECT dao_fruit_progress, ascension_merit, world_merit FROM players WHERE id=?",
                (player_id,),
            ).fetchone() == (999, 888, 77)
            assert (
                json.loads(
                    db.execute(
                        "SELECT inventory_json FROM players WHERE id=?", (player_id,)
                    ).fetchone()[0]
                )["item.tribulation_token"]
                == 2
            )
            snapshots = [
                json.loads(row[0])["task_snapshot"]
                for row in db.execute(
                    "SELECT payload_json FROM quest_events WHERE player_id=? AND quest_key=?",
                    (player_id, BUILD),
                )
            ]
            assert len(snapshots) == 2 and snapshots[0] == snapshots[1]
            assert snapshots[0]["target"] == 2 and snapshots[0]["reward"] == reward
        exhausted = await _send(runtime, adapter, "exhausted")
        assert exhausted.code == "QUEST_ALREADY_COMPLETED"
        await runtime.close()

        _edit(root, "任务/任务.json", BUILD, status="closed", reward={})
        _edit(root, "道具/材料.json", "item.tribulation_token", status="closed")
        runtime = create_runtime(data_dir=root, clock=clock, adapters=(adapter,))
        before = _state(runtime)
        replay = await _send(runtime, adapter, "complete")
        assert replay.ok and replay.data["idempotent_replay"] is True
        assert replay.message == completed.message
        assert (await _send(runtime, adapter, "first")).message == first.message
        conflict = await _send(runtime, adapter, "complete", "完成道源任务 传承")
        assert conflict.code == "OPERATION_CONFLICT"
        assert not (await _send(runtime, adapter, "closed")).ok
        assert _state(runtime) == before
        await runtime.close()

        _edit(
            root,
            "任务/任务.json",
            BUILD,
            status="open",
            reward={key: 1 for key in reward},
        )
        _edit(root, "图鉴/条目.json", "codex.dao.service_settlement", status="active")
        _edit(root, "道具/材料.json", "item.tribulation_token", status="open")
        clock.value += timedelta(days=36)
        runtime = create_runtime(data_dir=root, clock=clock, adapters=(adapter,))
        with sqlite3.connect(runtime.settings.database_path) as db:
            db.execute(
                "UPDATE livelihood_project_rewards SET created_at=?",
                (clock.value.isoformat(),),
            )
        next_season = await _send(runtime, adapter, "next-season")
        assert next_season.ok, next_season
        assert next_season.data["reward"] == {key: 1 for key in reward}
        assert next_season.data["progress"] == {"completed": 1, "target": 1}
        assert "重修山门" in next_season.message
        await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_origin_operation_failure_rolls_back_all_writes_and_retries(
    tmp_path: Path, adapter: str
) -> None:
    async def run() -> None:
        root = _content(tmp_path)
        _edit(root, "任务/任务.json", BUILD, target=1)
        runtime = create_runtime(data_dir=root, clock=FixedClock(), adapters=(adapter,))
        await _prepare_player(runtime, adapter, _message(adapter, "").context.user_id)
        before = _state(runtime)
        with sqlite3.connect(runtime.settings.database_path) as db:
            db.execute(
                "CREATE TRIGGER fail_origin BEFORE INSERT ON operations "
                "WHEN NEW.operation_id='award' BEGIN SELECT RAISE(ABORT, 'injected failure'); END"
            )
        failed = await _send(runtime, adapter, "award")
        assert failed.code == "PERSISTENCE_ERROR"
        assert _state(runtime) == before
        with sqlite3.connect(runtime.settings.database_path) as db:
            db.execute("DROP TRIGGER fail_origin")
        results = await asyncio.gather(
            _send(runtime, adapter, "award"), _send(runtime, adapter, "award")
        )
        assert all(result.ok for result in results)
        assert sorted(result.data["idempotent_replay"] for result in results) == [
            False,
            True,
        ]
        state = _state(runtime)
        assert len(state["quest_events"]) == 2 and len(state["codex_entries"]) == 1
        await runtime.close()
        runtime = create_runtime(data_dir=root, clock=FixedClock(), adapters=(adapter,))
        replay = await _send(runtime, adapter, "award")
        assert replay.data["idempotent_replay"] is True
        assert _state(runtime) == state
        await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_closed_teaching_refuses_available_evidence_without_writes(
    tmp_path: Path, adapter: str
) -> None:
    async def run() -> None:
        from test_endgame_producers import _create, _insert_origin_evidence

        root, clock = _content(tmp_path), FixedClock()
        task_key = "task.dao_origin.teach"
        _edit(root, "任务/任务.json", task_key, status="closed")
        runtime = create_runtime(data_dir=root, clock=clock, adapters=(adapter,))
        player_id = await _prepare_player(
            runtime, adapter, _message(adapter, "").context.user_id
        )
        await _create(runtime, adapter, "apprentice")
        with sqlite3.connect(runtime.settings.database_path) as db:
            apprentice = db.execute(
                "SELECT id FROM players WHERE platform_user_id='apprentice'"
            ).fetchone()[0]
            _insert_origin_evidence(
                db,
                adapter=adapter,
                player_id=player_id,
                apprentice_ids=(apprentice,),
                task_key=task_key,
                now=clock.value,
                count=1,
            )
        before = _state(runtime)
        rejected = await _send(runtime, adapter, "teach", "完成道源任务 传承")
        assert rejected.code == "ENDGAME_EVENT_REQUIREMENT_MISSING"
        assert _state(runtime) == before
        await runtime.close()
        _edit(root, "任务/任务.json", task_key, status="open")
        runtime = create_runtime(data_dir=root, clock=clock, adapters=(adapter,))
        accepted = await _send(runtime, adapter, "teach", "完成道源任务 传承")
        assert accepted.ok and accepted.data["progress"]["completed"] == 1
        await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize(
    "damage",
    [
        {"target": 0},
        {"target": True},
        {"target": "3"},
        {"reward": {}},
        {
            "reward": {
                "dao_fruit_progress": 1,
                "ascension_merit": 1,
                "world_merit": -1,
                "item.tribulation_token": 1,
            }
        },
        {
            "reward": {
                "dao_fruit_progress": 1,
                "ascension_merit": 1,
                "world_merit": True,
                "item.tribulation_token": 1,
            }
        },
        {
            "reward": {
                "dao_fruit_progress": 1,
                "ascension_merit": 1,
                "world_merit": 1,
                "item.tribulation_token": 1,
                "item.missing": 2,
            }
        },
        {
            "reward": {
                "dao_fruit_progress": 1,
                "ascension_merit": 1,
                "world_merit": 1,
                "item.tribulation_token": 1,
                "unsupported": 2,
            }
        },
        {"claim_policy": "once_per_player"},
        {"expires": True},
    ],
)
def test_invalid_origin_content_rejects_before_progress_or_rewards(
    tmp_path: Path, damage: dict
) -> None:
    async def run() -> None:
        root = _content(tmp_path)
        _edit(root, "任务/任务.json", BUILD, **damage)
        with pytest.raises(ContentError):
            dao_origin_task_definition(BUILD, ContentBundle.load(root))
        runtime = create_runtime(data_dir=root, clock=FixedClock())
        adapter = "qq.official"
        await _prepare_player(runtime, adapter, _message(adapter, "").context.user_id)
        before = _state(runtime)
        assert (await _send(runtime, adapter, "invalid")).code == "CONTENT_UNAVAILABLE"
        assert _state(runtime) == before
        await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize(
    "damage", ["unreadable", "progress_reward", "event_target", "event_season"]
)
def test_origin_damaged_snapshot_cannot_grant_or_replace_frozen_rewards(
    tmp_path: Path, damage: str
) -> None:
    async def run() -> None:
        runtime = create_runtime(data_dir=tmp_path, clock=FixedClock())
        adapter = "qq.official"
        player_id = await _prepare_player(
            runtime, adapter, _message(adapter, "").context.user_id
        )
        first = await _send(runtime, adapter, "first")
        assert first.ok
        with sqlite3.connect(runtime.settings.database_path) as db:
            if damage == "unreadable":
                db.execute(
                    "UPDATE quest_progress SET snapshot_json='{' WHERE player_id=?",
                    (player_id,),
                )
            elif damage == "progress_reward":
                snapshot = json.loads(
                    db.execute(
                        "SELECT snapshot_json FROM quest_progress WHERE player_id=?",
                        (player_id,),
                    ).fetchone()[0]
                )
                snapshot["reward"]["world_merit"] += 1
                db.execute(
                    "UPDATE quest_progress SET snapshot_json=? WHERE player_id=?",
                    (json.dumps(snapshot), player_id),
                )
            else:
                row = db.execute(
                    "SELECT id, payload_json FROM quest_events WHERE player_id=? AND quest_key=?",
                    (player_id, BUILD),
                ).fetchone()
                payload = json.loads(row[1])
                if damage == "event_target":
                    payload["task_snapshot"]["target"] = 2
                else:
                    payload["season_id"] = "different-season"
                db.execute(
                    "UPDATE quest_events SET payload_json=? WHERE id=?",
                    (json.dumps(payload), row[0]),
                )
        before = _state(runtime)
        assert (await _send(runtime, adapter, "second")).code == "CONTENT_UNAVAILABLE"
        assert (
            await _send(runtime, adapter, "preview", "高阶任务")
        ).code == "CONTENT_UNAVAILABLE"
        assert (await _send(runtime, adapter, "first")).message == first.message
        assert _state(runtime) == before
        await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("adapter", ADAPTERS)
@pytest.mark.parametrize(
    "target,expected", [(2, "REALM_LAYER_ADVANCED"), (4, "TRIAL_SEQUENCE_INVALID")]
)
def test_origin_historical_qualification_uses_frozen_target(
    tmp_path: Path, adapter: str, target: int, expected: str
) -> None:
    async def run() -> None:
        runtime = create_runtime(data_dir=tmp_path, clock=FixedClock())
        player_id = await _prepare_player(
            runtime, adapter, _message(adapter, "").context.user_id
        )
        season = final_heaven_season_window(FixedClock()() - timedelta(days=36))[0]
        with sqlite3.connect(runtime.settings.database_path) as db:
            db.execute(
                "UPDATE players SET realm_key='tribulation', realm_layer=9, cultivation=2400000 WHERE id=?",
                (player_id,),
            )
            for index, trial in enumerate(
                ("trial.body_and_mind", "trial.three_realms", "trial.dao_choice")
            ):
                db.execute(
                    "INSERT INTO tribulation_trial_sessions(session_id, player_id, operation_id, trial_key, status, starts_at, ends_at, result_json, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, 'succeeded', 'start', 'end', '{}', 'created', 'updated')",
                    (f"trial-{index}", player_id, f"trial-op-{index}", trial),
                )
            for key in DAO_ORIGIN_TASKS:
                snapshot = replace(
                    dao_origin_task_definition(key), target=target
                ).snapshot(season)
                for count in range(min(target, 3)):
                    db.execute(
                        "INSERT INTO quest_events(player_id, quest_key, component_key, source_operation_id, outcome, payload_json, created_at) "
                        "VALUES (?, ?, 'completed', ?, 'success', ?, 'created')",
                        (
                            player_id,
                            key,
                            f"{key}-{count}",
                            json.dumps(
                                {"season_id": season, "task_snapshot": snapshot}
                            ),
                        ),
                    )
        result = await _send(runtime, adapter, "advance", "晋升境界")
        assert result.code == expected, result
        await runtime.close()

    asyncio.run(run())
