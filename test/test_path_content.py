from __future__ import annotations

import asyncio
import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle, ContentError
from nonebot_plugin_xiuxian_3.xiuxian.player.path_rules import (
    path_records,
    resolve_path,
    resolve_subprofession,
    reward_items,
)


ROOT = Path(__file__).parents[1]
ADAPTERS = ("qq.official", "onebot.v11")


def _context(adapter: str, user: str, request: str, *, operation_id: str = "") -> CommandContext:
    return CommandContext(
        adapter=adapter,
        user_id=user,
        request_id=request,
        operation_id=operation_id,
    )


def _copy_data(tmp_path: Path) -> Path:
    data_root = tmp_path / "data"
    shutil.copytree(ROOT / "data", data_root)
    return data_root


def _write_paths(data_root: Path, document: dict) -> None:
    (data_root / "道途" / "道途.json").write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _path_document(data_root: Path) -> dict:
    return json.loads((data_root / "道途" / "道途.json").read_text(encoding="utf-8"))


async def _prepare_seeker(runtime, adapter: str, user: str) -> None:
    commands = (
        "开始修仙",
        "寻仙问道",
        "完成引导 阅读",
        "前往近郊",
        "完成引导 采集",
        "完成引导 布阵",
    )
    for index, command in enumerate(commands):
        result = await runtime.adapters.dispatch(
            adapter,
            _context(adapter, user, f"setup-{index}"),
            command,
        )
        assert result.ok, (command, result.code, result.message)


def test_path_content_resolves_names_aliases_and_stable_rewards(tmp_path: Path) -> None:
    data_root = _copy_data(tmp_path)
    document = _path_document(data_root)
    support = next(row for row in document["records"] if row["key"] == "support")
    support.update(name="百艺道", aliases=["百艺"])
    subprofession = next(
        row for row in support["subprofessions"] if row["key"] == "formation"
    )
    subprofession.update(name="阵道", aliases=["阵法"])
    _write_paths(data_root, document)

    bundle = ContentBundle.load(data_root)
    assert resolve_path("百艺", bundle) == "support"
    assert resolve_path("support", bundle) == "support"
    assert resolve_subprofession("阵法", "support", bundle) == "formation"
    assert reward_items("support", "formation", bundle) == (
        ("item.manual.basic_qi", 1),
        ("skill.support.quick_assessment", 1),
        ("item.mat.array_sand", 3),
    )


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_path_content_drives_both_adapters_and_replay(tmp_path: Path, adapter: str) -> None:
    async def run(data_root: Path) -> None:
        document = _path_document(data_root)
        support = next(row for row in document["records"] if row["key"] == "support")
        support.update(name="百艺道", aliases=["百艺"])
        subprofession = next(
            row for row in support["subprofessions"] if row["key"] == "formation"
        )
        subprofession.update(name="阵道", aliases=["阵法"])
        _write_paths(data_root, document)

        runtime = create_runtime(data_dir=data_root, adapters=(adapter,))
        user = f"path-content-{adapter}"
        operation_id = f"path-enter-{adapter}"
        await _prepare_seeker(runtime, adapter, user)
        entered = await runtime.adapters.dispatch(
            adapter,
            _context(adapter, user, "enter", operation_id=operation_id),
            "选择道途 百艺 阵法",
        )
        assert entered.code == "CULTIVATION_ENTERED"
        assert "百艺道" in entered.message
        assert "阵道" in entered.message
        assert entered.data["path_key"] == "support"
        assert entered.data["subprofession_key"] == "formation"
        assert entered.data["inventory"]["item.mat.array_sand"] == 3

        profile = await runtime.adapters.dispatch(
            adapter,
            _context(adapter, user, "profile"),
            "我的状态",
        )
        assert "百艺道·阵道" in profile.message
        with sqlite3.connect(runtime.settings.database_path) as connection:
            player = connection.execute(
                "SELECT path_key, subprofession_key, inventory_json FROM players "
                "WHERE platform=? AND platform_user_id=?",
                (adapter, user),
            ).fetchone()
            operation_count = connection.execute(
                "SELECT COUNT(*) FROM operations WHERE operation_id=?", (operation_id,)
            ).fetchone()[0]
        assert player[0:2] == ("support", "formation")
        assert json.loads(player[2])["item.mat.array_sand"] == 3
        assert operation_count == 1
        await runtime.close()

        support.update(name="百艺新篇", aliases=[])
        subprofession.update(name="阵门", aliases=[])
        _write_paths(data_root, document)
        recovered = create_runtime(data_dir=data_root, adapters=(adapter,))
        try:
            replay = await recovered.adapters.dispatch(
                adapter,
                _context(adapter, user, "enter-replay", operation_id=operation_id),
                "选择道途 support formation",
            )
            assert replay.code == "CULTIVATION_ENTERED"
            assert replay.data["idempotent_replay"] is True
            assert "百艺新篇" in replay.message
            assert "阵门" in replay.message
            assert replay.data["inventory"]["item.mat.array_sand"] == 3

            renamed_text = await recovered.adapters.dispatch(
                adapter,
                _context(adapter, user, "enter-old-text", operation_id=f"{operation_id}-old-text"),
                "选择道途 百艺 阵法",
            )
            assert renamed_text.code == "INVALID_PATH"
            with sqlite3.connect(recovered.settings.database_path) as connection:
                assert connection.execute(
                    "SELECT COUNT(*) FROM operations WHERE operation_id=?", (operation_id,)
                ).fetchone()[0] == 1
        finally:
            await recovered.close()

    asyncio.run(run(_copy_data(tmp_path)))


def test_path_content_rejects_locked_ambiguous_and_broken_records(tmp_path: Path) -> None:
    data_root = _copy_data(tmp_path)
    document = _path_document(data_root)
    body = next(row for row in document["records"] if row["key"] == "body")
    body["status"] = "locked"
    _write_paths(data_root, document)
    bundle = ContentBundle.load(data_root)
    assert resolve_path("体修", bundle) is None
    assert all(record["key"] != "body" for record in path_records(bundle))

    body["status"] = "active"
    body["aliases"] = ["辅修"]
    _write_paths(data_root, document)
    with pytest.raises(ContentError, match="ambiguous path selector"):
        path_records(ContentBundle.load(data_root))

    document = _path_document(data_root)
    body = next(row for row in document["records"] if row["key"] == "body")
    body["aliases"] = []
    support = next(row for row in document["records"] if row["key"] == "support")
    original_subprofessions = support["subprofessions"]
    support.pop("subprofessions")
    _write_paths(data_root, document)
    with pytest.raises(ContentError, match="subprofessions"):
        path_records(ContentBundle.load(data_root))

    document = _path_document(data_root)
    support = next(row for row in document["records"] if row["key"] == "support")
    support["subprofessions"] = original_subprofessions
    support["subprofessions"][1]["aliases"] = [
        support["subprofessions"][0]["name"]
    ]
    _write_paths(data_root, document)
    with pytest.raises(ContentError, match="ambiguous sub-profession"):
        path_records(ContentBundle.load(data_root))

    document = _path_document(data_root)
    support = next(row for row in document["records"] if row["key"] == "support")
    support["subprofessions"][1]["aliases"] = []
    support["subprofessions"][0]["entry_item_rewards"][0]["item_key"] = "item.missing"
    _write_paths(data_root, document)
    with pytest.raises(ContentError, match="unavailable item"):
        path_records(ContentBundle.load(data_root))


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_path_selection_rejects_invalid_content_without_writes(
    tmp_path: Path, adapter: str
) -> None:
    async def run(data_root: Path) -> None:
        document = _path_document(data_root)
        body = next(row for row in document["records"] if row["key"] == "body")
        body["status"] = "locked"
        _write_paths(data_root, document)

        runtime = create_runtime(data_dir=data_root, adapters=(adapter,))
        user = f"path-invalid-{adapter}"
        await _prepare_seeker(runtime, adapter, user)
        result = await runtime.adapters.dispatch(
            adapter,
            _context(adapter, user, "locked", operation_id="path-invalid-locked"),
            "选择道途 体修",
        )
        assert result.code == "INVALID_PATH"
        with sqlite3.connect(runtime.settings.database_path) as connection:
            before = connection.execute(
                "SELECT path_key, subprofession_key, spirit_stones, inventory_json "
                "FROM players WHERE platform=? AND platform_user_id=?",
                (adapter, user),
            ).fetchone()
            assert connection.execute(
                "SELECT COUNT(*) FROM operations WHERE operation_id=?",
                ("path-invalid-locked",),
            ).fetchone()[0] == 0
        await runtime.close()

        body["status"] = "active"
        body["aliases"] = ["辅修"]
        _write_paths(data_root, document)
        runtime = create_runtime(data_dir=data_root, adapters=(adapter,))
        try:
            result = await runtime.adapters.dispatch(
                adapter,
                _context(adapter, user, "ambiguous", operation_id="path-invalid-ambiguous"),
                "选择道途 体修",
            )
            assert result.code == "INVALID_PATH"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                after = connection.execute(
                    "SELECT path_key, subprofession_key, spirit_stones, inventory_json "
                    "FROM players WHERE platform=? AND platform_user_id=?",
                    (adapter, user),
                ).fetchone()
                assert after == before
                assert connection.execute(
                    "SELECT COUNT(*) FROM operations WHERE operation_id=?",
                    ("path-invalid-ambiguous",),
                ).fetchone()[0] == 0
        finally:
            await runtime.close()

    asyncio.run(run(_copy_data(tmp_path)))


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_path_selection_rolls_back_and_retries_original_operation(
    tmp_path: Path, adapter: str
) -> None:
    async def run(data_root: Path) -> None:
        runtime = create_runtime(data_dir=data_root, adapters=(adapter,))
        user = f"path-recovery-{adapter}"
        operation_id = f"path-recovery-enter-{adapter}"
        await _prepare_seeker(runtime, adapter, user)
        with sqlite3.connect(runtime.settings.database_path) as connection:
            before = connection.execute(
                "SELECT path_key, subprofession_key, spirit_stones, inventory_json "
                "FROM players WHERE platform=? AND platform_user_id=?",
                (adapter, user),
            ).fetchone()
            connection.execute(
                "CREATE TRIGGER reject_path_operation BEFORE INSERT ON operations "
                "WHEN NEW.operation_name='player.enter_cultivation' "
                "BEGIN SELECT RAISE(ABORT, 'injected path operation failure'); END"
            )

        failed = await runtime.adapters.dispatch(
            adapter,
            _context(adapter, user, "enter-failed", operation_id=operation_id),
            "选择道途 辅修 布阵",
        )
        assert failed.code == "PERSISTENCE_ERROR"
        with sqlite3.connect(runtime.settings.database_path) as connection:
            after = connection.execute(
                "SELECT path_key, subprofession_key, spirit_stones, inventory_json "
                "FROM players WHERE platform=? AND platform_user_id=?",
                (adapter, user),
            ).fetchone()
            assert after == before
            assert connection.execute(
                "SELECT COUNT(*) FROM operations WHERE operation_id=?", (operation_id,)
            ).fetchone()[0] == 0
            connection.execute("DROP TRIGGER reject_path_operation")

        retried = await runtime.adapters.dispatch(
            adapter,
            _context(adapter, user, "enter-retry", operation_id=operation_id),
            "选择道途 辅修 布阵",
        )
        assert retried.code == "CULTIVATION_ENTERED"
        assert retried.data["idempotent_replay"] is False
        replay = await runtime.adapters.dispatch(
            adapter,
            _context(adapter, user, "enter-replay", operation_id=operation_id),
            "选择道途 辅修 布阵",
        )
        assert replay.code == "CULTIVATION_ENTERED"
        assert replay.data["idempotent_replay"] is True
        conflict = await runtime.adapters.dispatch(
            adapter,
            _context(adapter, user, "enter-conflict", operation_id=operation_id),
            "选择道途 体修",
        )
        assert conflict.code == "OPERATION_CONFLICT"
        with sqlite3.connect(runtime.settings.database_path) as connection:
            assert connection.execute(
                "SELECT COUNT(*) FROM operations WHERE operation_id=?", (operation_id,)
            ).fetchone()[0] == 1
        await runtime.close()

    asyncio.run(run(_copy_data(tmp_path)))
