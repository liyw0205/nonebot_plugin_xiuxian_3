from __future__ import annotations

import asyncio
import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime

ROOT = Path(__file__).parents[1]
ADAPTERS = ("qq.official", "onebot.v11")
ENTRY_COMMAND = "选择道途 百艺 阵法"


def _copy_data(tmp_path: Path) -> Path:
    data_root = tmp_path / "data"
    shutil.copytree(ROOT / "data", data_root)
    return data_root


def _write_path_content(data_root: Path, document: dict) -> None:
    (data_root / "道途" / "道途.json").write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _context(
    adapter: str, user: str, request_id: str, operation_id: str
) -> CommandContext:
    return CommandContext(
        adapter=adapter,
        user_id=user,
        request_id=request_id,
        operation_id=operation_id,
    )


async def _dispatch(
    runtime, adapter: str, user: str, request_id: str, operation_id: str, text: str
):
    return await runtime.adapters.dispatch(
        adapter,
        _context(adapter, user, request_id, operation_id),
        text,
    )


async def _prepare_seeker(runtime, adapter: str, user: str) -> None:
    for index, command in enumerate(
        (
            "开始修仙",
            "寻仙问道",
            "完成引导 阅读",
            "前往近郊",
            "完成引导 采集",
            "完成引导 布阵",
        )
    ):
        result = await _dispatch(
            runtime, adapter, user, f"setup-{index}", f"{user}-setup-{index}", command
        )
        assert result.ok, (command, result.code, result.message)


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_path_alias_entry_replays_after_alias_removal(
    tmp_path: Path, adapter: str
) -> None:
    async def run() -> None:
        data_root = _copy_data(tmp_path)
        path_file = data_root / "道途" / "道途.json"
        document = json.loads(path_file.read_text(encoding="utf-8"))
        support = next(row for row in document["records"] if row["key"] == "support")
        support.update(name="百艺道", aliases=["百艺"])
        formation = next(
            row for row in support["subprofessions"] if row["key"] == "formation"
        )
        formation.update(name="阵道", aliases=["阵法"])
        _write_path_content(data_root, document)

        user = f"path-alias-{adapter}"
        operation_id = f"path-alias-entry-{adapter}"
        runtime = create_runtime(
            data_dir=data_root,
            adapters=("qq.official", "onebot.v11"),
        )
        await _prepare_seeker(runtime, adapter, user)
        entered = await _dispatch(
            runtime, adapter, user, "enter", operation_id, ENTRY_COMMAND
        )
        assert entered.code == "CULTIVATION_ENTERED"
        assert entered.data["idempotent_replay"] is False
        assert entered.data["inventory"]["item.mat.array_sand"] == 3
        assert "百艺道" in entered.message
        assert "阵道" in entered.message
        await runtime.close()

        support["aliases"] = []
        formation["aliases"] = []
        _write_path_content(data_root, document)
        recovered = create_runtime(
            data_dir=data_root,
            adapters=("qq.official", "onebot.v11"),
        )
        try:
            replay = await _dispatch(
                recovered,
                adapter,
                user,
                "enter-retry",
                operation_id,
                ENTRY_COMMAND,
            )
            assert replay.code == "CULTIVATION_ENTERED"
            assert replay.data["idempotent_replay"] is True
            assert replay.message == entered.message
            assert {**replay.data, "idempotent_replay": False} == entered.data

            conflict = await _dispatch(
                recovered,
                adapter,
                user,
                "enter-conflict",
                operation_id,
                "选择道途 失传方向",
            )
            assert conflict.code == "OPERATION_CONFLICT"

            new_operation = await _dispatch(
                recovered,
                adapter,
                user,
                "enter-new-operation",
                f"{operation_id}-new",
                ENTRY_COMMAND,
            )
            assert new_operation.code == "INVALID_PATH"

            with sqlite3.connect(recovered.settings.database_path) as connection:
                player = connection.execute(
                    "SELECT id, path_key, subprofession_key, spirit_stones, inventory_json "
                    "FROM players WHERE platform=? AND platform_user_id=?",
                    (adapter, user),
                ).fetchone()
                assert player is not None
                assert player[1:4] == (
                    "support",
                    "formation",
                    entered.data["spirit_stones"],
                )
                assert json.loads(player[4]) == entered.data["inventory"]
                assert (
                    connection.execute(
                        "SELECT COUNT(*) FROM operations WHERE operation_id=?",
                        (operation_id,),
                    ).fetchone()[0]
                    == 1
                )
                assert (
                    connection.execute(
                        "SELECT COUNT(*) FROM operations WHERE operation_id=?",
                        (f"{operation_id}-new",),
                    ).fetchone()[0]
                    == 0
                )
                assert (
                    connection.execute(
                        "SELECT COUNT(*) FROM codex_entries WHERE player_id=? "
                        "AND first_seen_operation_id=?",
                        (player[0], operation_id),
                    ).fetchone()[0]
                    == 2
                )
        finally:
            await recovered.close()

    asyncio.run(run())
