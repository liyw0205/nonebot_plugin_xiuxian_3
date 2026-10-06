from __future__ import annotations

import asyncio
import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle, ContentError
from nonebot_plugin_xiuxian_3.xiuxian.events.rules import final_heaven_season_window
from nonebot_plugin_xiuxian_3.xiuxian.quests.rules import dao_origin_codex_entry_key


class FixedClock:
    def __init__(self) -> None:
        self.value = datetime(2026, 9, 24, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.value


def _context(adapter: str, user: str, operation: str) -> CommandContext:
    return CommandContext(adapter=adapter, user_id=user, operation_id=operation)


def _copy_content(root: Path, target: Path) -> None:
    shutil.copytree(root / "data", target)


async def _prepare_player(runtime, adapter: str, user: str) -> int:
    assert (await runtime.dispatch(_context(adapter, user, "create"), "开始修仙")).ok
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE players SET stage='cultivator', realm_key='dao_union', realm_layer=1, endgame_status='dao_union' "
            "WHERE platform=? AND platform_user_id=?",
            (adapter, user),
        )
        player_id = connection.execute(
            "SELECT id FROM players WHERE platform=? AND platform_user_id=?",
            (adapter, user),
        ).fetchone()[0]
        for index in range(3):
            project_id = f"build-evidence-{adapter}-{index}"
            created_at = "2026-09-24T00:00:00+00:00"
            connection.execute(
                "INSERT INTO livelihood_projects(project_id, project_key, business_week, status, target_points, "
                "contribution_points, requirements_json, progress_json, effect_key, snapshot_json, result_json, "
                "created_at, updated_at) VALUES (?, 'project.town_well', ?, 'active', 10, 10, '{}', '{}', 'test', '{}', '{}', ?, ?)",
                (project_id, f"2026-09-{22 + index:02d}-{adapter}", created_at, created_at),
            )
            connection.execute(
                "INSERT INTO livelihood_project_rewards(project_id, player_id, operation_id, eligible, reward_json, created_at) "
                "VALUES (?, ?, ?, 1, '{}', ?)",
                (project_id, player_id, f"project-reward-{adapter}-{index}", created_at),
            )
    return int(player_id)


def test_dao_origin_build_records_service_codex_only_on_third_evidence_for_both_adapters() -> None:
    async def run() -> None:
        for adapter in ("qq.official", "onebot.v11"):
            with TemporaryDirectory() as temp_dir:
                content_dir = Path(temp_dir) / "content"
                _copy_content(Path(__file__).parents[1], content_dir)
                runtime = create_runtime(data_dir=content_dir, adapters=(adapter,), clock=FixedClock())
                user = f"dao-build-{adapter}"
                player_id = await _prepare_player(runtime, adapter, user)
                operations: list[str] = []
                for index in range(3):
                    operation = f"{user}:build:{index}"
                    operations.append(operation)
                    result = await runtime.dispatch(_context(adapter, user, operation), "完成道源任务 建设")
                    assert result.code == "DAO_ORIGIN_TASK_RECORDED"
                    assert "task.dao_origin.build" not in result.message
                    assert "道源行历" in result.message
                    assert result.data["progress"]["completed"] == index + 1
                    assert result.data["discovery"] == (
                        {}
                        if index < 2
                        else {
                            "entry_key": "codex.dao.service_settlement",
                            "task_key": "task.dao_origin.build",
                            "task_operation_id": operation,
                            "source_operation_id": f"project-reward-{adapter}-{index}",
                            "source_kind": "livelihood_project_rewards",
                            "evidence_id": f"build-evidence-{adapter}-{index}",
                            "season_id": final_heaven_season_window(datetime(2026, 9, 24, tzinfo=timezone.utc))[0],
                            "occurred_at": "2026-09-24T00:00:00+00:00",
                            "source_key": "project.town_well",
                            "label": "道统服务结算",
                        }
                    )
                    with sqlite3.connect(runtime.settings.database_path) as connection:
                        assert connection.execute(
                            "SELECT COUNT(*) FROM codex_entries WHERE player_id=? AND entry_key=?",
                            (player_id, "codex.dao.service_settlement"),
                        ).fetchone()[0] == (1 if index == 2 else 0)

                replay = await runtime.dispatch(_context(adapter, user, operations[-1]), "完成道源任务 建设")
                assert replay.code == "DAO_ORIGIN_TASK_RECORDED"
                assert replay.data["idempotent_replay"] is True
                assert replay.data["discovery"]["entry_key"] == "codex.dao.service_settlement"
                conflict = await runtime.dispatch(_context(adapter, user, operations[-1]), "完成道源任务 守界")
                assert conflict.code == "OPERATION_CONFLICT"
                await runtime.close()

                entries_path = content_dir / "图鉴" / "条目.json"
                entries = json.loads(entries_path.read_text(encoding="utf-8"))
                entry = next(item for item in entries["records"] if item["key"] == "codex.dao.service_settlement")
                entry["name"] = "改名后的道统服务结算"
                entry["status"] = "closed"
                entries_path.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
                tasks_path = content_dir / "任务" / "任务.json"
                tasks = json.loads(tasks_path.read_text(encoding="utf-8"))
                task = next(item for item in tasks["records"] if item["key"] == "task.dao_origin.build")
                task["name"] = "改名后的留界建设"
                task["status"] = "closed"
                tasks_path.write_text(json.dumps(tasks, ensure_ascii=False, indent=2), encoding="utf-8")
                recovered = create_runtime(data_dir=content_dir, adapters=(adapter,))
                replay_after_change = await recovered.dispatch(
                    _context(adapter, user, operations[-1]), "完成道源任务 建设"
                )
                assert replay_after_change.data["idempotent_replay"] is True
                assert "留界建设" in replay_after_change.message
                assert "改名后的留界建设" not in replay_after_change.message
                overview = await recovered.dispatch(
                    _context(adapter, user, f"{user}:codex"), "我的图鉴 服务"
                )
                assert any(
                    item["entry_key"] == "codex.dao.service_settlement"
                    and item["label"] == "道统服务结算"
                    for item in overview.data["entries"]
                )
                await recovered.close()

    asyncio.run(run())


def test_dao_origin_build_codex_failure_rolls_back_and_retries() -> None:
    async def run() -> None:
        with TemporaryDirectory() as temp_dir:
            runtime = create_runtime(data_dir=temp_dir, adapters=("qq.official",), clock=FixedClock())
            adapter, user = "qq.official", "dao-build-retry"
            player_id = await _prepare_player(runtime, adapter, user)
            for index in range(2):
                assert (
                    await runtime.dispatch(
                        _context(adapter, user, f"{user}:build:{index}"), "完成道源任务 建设"
                    )
                ).ok
            operation = f"{user}:build:2"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "CREATE TRIGGER fail_dao_build_codex BEFORE INSERT ON codex_entries "
                    "WHEN NEW.entry_key='codex.dao.service_settlement' BEGIN "
                    "SELECT RAISE(ABORT, 'injected dao build codex failure'); END"
                )
            failed = await runtime.dispatch(_context(adapter, user, operation), "完成道源任务 建设")
            assert failed.code == "PERSISTENCE_ERROR"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute(
                    "SELECT dao_fruit_progress, ascension_merit FROM players WHERE id=?", (player_id,)
                ).fetchone() == (0, 0)
                assert connection.execute(
                    "SELECT COUNT(*) FROM quest_events WHERE player_id=? AND quest_key='task.dao_origin.build'",
                    (player_id,),
                ).fetchone()[0] == 2
                assert connection.execute(
                    "SELECT COUNT(*) FROM codex_entries WHERE player_id=? AND entry_key=?",
                    (player_id, "codex.dao.service_settlement"),
                ).fetchone()[0] == 0
                assert connection.execute(
                    "SELECT COUNT(*) FROM operations WHERE operation_id=?", (operation,)
                ).fetchone()[0] == 0
                connection.execute("DROP TRIGGER fail_dao_build_codex")
            retried = await runtime.dispatch(_context(adapter, user, operation), "完成道源任务 建设")
            assert retried.code == "DAO_ORIGIN_TASK_RECORDED"
            assert retried.data["discovery"]["entry_key"] == "codex.dao.service_settlement"
            await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("damage", ["missing", "wrong_category", "not_active"])
def test_dao_origin_build_requires_active_service_codex_reference(tmp_path: Path, damage: str) -> None:
    content_dir = tmp_path / "content"
    _copy_content(Path(__file__).parents[1], content_dir)
    task_path = content_dir / "任务" / "任务.json"
    document = json.loads(task_path.read_text(encoding="utf-8"))
    task = next(item for item in document["records"] if item["key"] == "task.dao_origin.build")
    entries_path = content_dir / "图鉴" / "条目.json"
    if damage == "missing":
        task["codex_entry_key"] = "codex.missing.service"
    elif damage == "wrong_category":
        task["codex_entry_key"] = "codex.dao.service_public_works"
        entries = json.loads(entries_path.read_text(encoding="utf-8"))
        next(item for item in entries["records"] if item["key"] == task["codex_entry_key"])["category"] = "story"
        entries_path.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        entries = json.loads(entries_path.read_text(encoding="utf-8"))
        next(
            item for item in entries["records"] if item["key"] == "codex.dao.service_settlement"
        )["status"] = "open"
        entries_path.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
    task_path.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
    with pytest.raises(ContentError, match="service codex entry"):
        dao_origin_codex_entry_key("task.dao_origin.build", ContentBundle.load(content_dir))
