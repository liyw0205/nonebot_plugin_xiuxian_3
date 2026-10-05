from __future__ import annotations

import asyncio
import json
import shutil
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle, ContentError
from nonebot_plugin_xiuxian_3.xiuxian.progression.rules import (
    CULTIVATION_GUIDANCE,
    cultivation_definitions,
    cultivation_gain,
)


def _context(adapter: str, user: str, request: str, *, operation_id: str = "") -> CommandContext:
    return CommandContext(adapter=adapter, user_id=user, request_id=request, operation_id=operation_id)


async def _enter_cultivator(runtime, adapter: str, user: str) -> None:
    for index, command in enumerate(
        ("开始修仙", "寻仙问道", "完成引导 阅读", "前往近郊", "完成引导 采集", "完成引导 炼丹", "选择道途 体修")
    ):
        result = await runtime.adapters.dispatch(adapter, _context(adapter, user, f"setup-{index}"), command)
        assert result.ok, (command, result.code, result.message)


def _copy_data(tmp_path: Path) -> Path:
    data_root = tmp_path / "data"
    shutil.copytree(Path(__file__).parents[1] / "data", data_root)
    return data_root


def _cultivation_document(data_root: Path) -> tuple[Path, dict]:
    path = data_root / "养成" / "修炼.json"
    return path, json.loads(path.read_text(encoding="utf-8"))


def test_cultivation_content_keeps_only_rule_inputs() -> None:
    path = Path(__file__).parents[1] / "data" / "养成" / "修炼.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    assert all("desc" not in row for row in document["records"])
    assert set(CULTIVATION_GUIDANCE) == {row["key"] for row in document["records"]}
    assert all(CULTIVATION_GUIDANCE[key] for key in CULTIVATION_GUIDANCE)
    assert set(cultivation_definitions()) == set(CULTIVATION_GUIDANCE)


def _write_document(path: Path, document: dict) -> None:
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")


def test_cultivation_parameters_and_history_are_frozen_across_content_change(tmp_path: Path) -> None:
    async def run(data_root: Path) -> None:
        path, document = _cultivation_document(data_root)
        breathing = next(row for row in document["records"] if row["key"] == "cultivate.breathing")
        breathing.update({"stamina_cost": 4, "duration_seconds": 1200, "base_cultivation": 123})
        _write_document(path, document)

        runtime = create_runtime(data_dir=data_root)
        user = "content-freeze"
        await _enter_cultivator(runtime, "qq.official", user)
        started = await runtime.adapters.dispatch(
            "qq.official",
            _context("qq.official", user, "start", operation_id="cultivation-start"),
            "开始修炼 调息",
        )
        assert started.code == "CULTIVATION_STARTED"
        assert started.data["stamina_cost"] == 4
        assert started.data["ends_at"]
        with sqlite3.connect(runtime.settings.database_path) as connection:
            snapshot = json.loads(
                connection.execute(
                    "SELECT snapshot_json FROM cultivation_sessions WHERE session_id = ?",
                    (started.data["session_id"],),
                ).fetchone()[0]
            )
            connection.execute(
                "UPDATE cultivation_sessions SET ends_at = ? WHERE session_id = ?",
                ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(), started.data["session_id"]),
            )

        path, document = _cultivation_document(data_root)
        breathing = next(row for row in document["records"] if row["key"] == "cultivate.breathing")
        breathing.update({"name": "静息吐纳", "aliases": [], "stamina_cost": 9, "duration_seconds": 60, "base_cultivation": 9999})
        _write_document(path, document)
        await runtime.close()
        runtime = create_runtime(data_dir=data_root)
        replay = await runtime.adapters.dispatch(
            "qq.official",
            _context("qq.official", user, "start-replay", operation_id="cultivation-start"),
            "开始修炼 调息",
        )
        assert replay.ok
        assert replay.data["idempotent_replay"] is True
        assert replay.data["mode_label"] == "调息修炼"

        settled = await runtime.adapters.dispatch(
            "qq.official",
            _context("qq.official", user, "settle", operation_id="cultivation-settle"),
            "结算修炼",
        )
        assert settled.code == "CULTIVATION_SETTLED"
        assert settled.data["mode_key"] == "cultivate.breathing"
        assert settled.data["cultivation_gain"] == cultivation_gain(
            snapshot["base_cultivation"],
            snapshot["qualification"],
            environment_bp=snapshot["environment_bp"],
            state_bp=snapshot["state_bp"],
            manual_bonus_bp=snapshot["manual_cultivation_gain_bp"],
        )
        await runtime.close()

    with TemporaryDirectory() as directory:
        asyncio.run(run(_copy_data(Path(directory))))


def test_closed_cultivation_mode_rejects_new_session_without_changing_state(tmp_path: Path) -> None:
    async def run(data_root: Path) -> None:
        path, document = _cultivation_document(data_root)
        next(row for row in document["records"] if row["key"] == "cultivate.spirit_spring")["status"] = "closed"
        _write_document(path, document)
        runtime = create_runtime(data_dir=data_root)
        user = "closed-cultivation"
        await _enter_cultivator(runtime, "onebot.v11", user)
        with sqlite3.connect(runtime.settings.database_path) as connection:
            before = connection.execute(
                "SELECT stamina, energy FROM players WHERE platform = ? AND platform_user_id = ?",
                ("onebot.v11", user),
            ).fetchone()
        result = await runtime.adapters.dispatch(
            "onebot.v11", _context("onebot.v11", user, "closed"), "开始修炼 灵泉"
        )
        assert result.code == "INVALID_CULTIVATION_MODE"
        with sqlite3.connect(runtime.settings.database_path) as connection:
            assert connection.execute(
                "SELECT stamina, energy FROM players WHERE platform = ? AND platform_user_id = ?",
                ("onebot.v11", user),
            ).fetchone() == before
            assert connection.execute("SELECT COUNT(*) FROM cultivation_sessions").fetchone()[0] == 0
        await runtime.close()

    asyncio.run(run(_copy_data(tmp_path)))


def test_cultivation_location_copy_uses_current_content_names(tmp_path: Path) -> None:
    async def run(data_root: Path) -> None:
        mode_path, mode_document = _cultivation_document(data_root)
        spring = next(row for row in mode_document["records"] if row["key"] == "cultivate.spirit_spring")
        spring.update({"name": "清心泉修炼", "aliases": ["清心泉"]})
        _write_document(mode_path, mode_document)
        location_path = data_root / "地图" / "地点.json"
        location_document = json.loads(location_path.read_text(encoding="utf-8"))
        next(row for row in location_document["records"] if row["key"] == "xuantian.spirit_field")["name"] = "清心泉谷"
        _write_document(location_path, location_document)

        runtime = create_runtime(data_dir=data_root)
        user = "dynamic-cultivation-copy"
        await _enter_cultivator(runtime, "qq.official", user)
        result = await runtime.adapters.dispatch(
            "qq.official", _context("qq.official", user, "location-copy"), "开始修炼 清心泉"
        )
        assert result.code == "LOCATION_REQUIRED"
        assert "清心泉修炼" in result.message
        assert "清心泉谷" in result.message
        await runtime.close()

    asyncio.run(run(_copy_data(tmp_path)))


@pytest.mark.parametrize("adapter", ("qq.official", "onebot.v11"))
def test_cultivation_operation_bad_json_is_read_only_and_both_adapters_share_flow(tmp_path: Path, adapter: str) -> None:
    async def run(data_root: Path) -> None:
        runtime = create_runtime(data_dir=data_root)
        user = f"bad-operation-{adapter}"
        await _enter_cultivator(runtime, adapter, user)
        operation_id = f"bad-start-{adapter}"
        started = await runtime.adapters.dispatch(
            adapter, _context(adapter, user, "start", operation_id=operation_id), "开始修炼"
        )
        assert started.ok
        with sqlite3.connect(runtime.settings.database_path) as connection:
            before = connection.execute(
                "SELECT stamina, energy FROM players WHERE platform = ? AND platform_user_id = ?",
                (adapter, user),
            ).fetchone()
            connection.execute("UPDATE operations SET result_json = ? WHERE operation_id = ?", ("{", operation_id))
        replay = await runtime.adapters.dispatch(
            adapter, _context(adapter, user, "start-replay", operation_id=operation_id), "开始修炼"
        )
        assert replay.code == "PERSISTENCE_ERROR"
        with sqlite3.connect(runtime.settings.database_path) as connection:
            assert connection.execute(
                "SELECT stamina, energy FROM players WHERE platform = ? AND platform_user_id = ?",
                (adapter, user),
            ).fetchone() == before
            assert connection.execute("SELECT COUNT(*) FROM cultivation_sessions").fetchone()[0] == 1
        await runtime.close()

    asyncio.run(run(_copy_data(tmp_path)))


def test_cultivation_content_rejects_duplicate_player_references(tmp_path: Path) -> None:
    data_root = _copy_data(tmp_path)
    path, document = _cultivation_document(data_root)
    next(row for row in document["records"] if row["key"] == "cultivate.seclusion")["aliases"] = ["调息"]
    _write_document(path, document)
    with pytest.raises(ContentError, match="duplicate cultivation name or alias"):
        cultivation_definitions(ContentBundle.load(data_root))
