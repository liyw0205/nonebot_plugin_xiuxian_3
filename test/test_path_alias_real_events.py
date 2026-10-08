from __future__ import annotations

import asyncio
import json
import shutil
from dataclasses import replace
from pathlib import Path

import pytest
from test_adapter_simulation import _onebot_group_event, _qq_group_event

from nonebot_plugin_xiuxian_3.adapters.onebot import (
    normalize_event as normalize_onebot_event,
)
from nonebot_plugin_xiuxian_3.adapters.qq import normalize_event as normalize_qq_event
from nonebot_plugin_xiuxian_3.runtime import create_runtime

ROOT = Path(__file__).parents[1]
ADAPTERS = ("qq.official", "onebot.v11")
ENTRY_COMMAND = "选择道途 百艺 阵法"


def _normalized_event(adapter: str, message_id: str | int):
    if adapter == "qq.official":
        event = _qq_group_event(ENTRY_COMMAND, message_id=str(message_id))
        return normalize_qq_event(event)
    event = _onebot_group_event(ENTRY_COMMAND, message_id=int(message_id))
    return normalize_onebot_event(event)


def _remove_path_aliases(data_root: Path) -> None:
    path_file = data_root / "道途" / "道途.json"
    document = json.loads(path_file.read_text(encoding="utf-8"))
    support = next(row for row in document["records"] if row["key"] == "support")
    support["aliases"] = []
    formation = next(
        row for row in support["subprofessions"] if row["key"] == "formation"
    )
    formation["aliases"] = []
    path_file.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_real_adapter_event_replays_path_alias_after_alias_removal(
    tmp_path: Path, adapter: str
) -> None:
    async def run() -> None:
        data_root = tmp_path / "data"
        shutil.copytree(ROOT / "data", data_root)
        path_file = data_root / "道途" / "道途.json"
        document = json.loads(path_file.read_text(encoding="utf-8"))
        support = next(row for row in document["records"] if row["key"] == "support")
        support.update(name="百艺道", aliases=["百艺"])
        formation = next(
            row for row in support["subprofessions"] if row["key"] == "formation"
        )
        formation.update(name="阵道", aliases=["阵法"])
        path_file.write_text(
            json.dumps(document, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        message_id: str | int = (
            f"path-alias-{adapter}" if adapter == "qq.official" else 41001
        )
        normalized = _normalized_event(adapter, message_id)
        assert normalized.text == ENTRY_COMMAND
        assert normalized.context.adapter == adapter
        runtime = create_runtime(data_dir=data_root, adapters=(adapter,))
        setup_commands = (
            "开始修仙",
            "寻仙问道",
            "完成引导 阅读",
            "前往近郊",
            "完成引导 采集",
            "完成引导 布阵",
        )
        for index, command in enumerate(setup_commands):
            setup_context = replace(
                normalized.context,
                operation_id=f"{adapter}:path-alias-setup:{index}",
            )
            result = await runtime.adapters.dispatch(adapter, setup_context, command)
            assert result.ok, (command, result.code, result.message)

        entered = await runtime.adapters.dispatch(
            adapter, normalized.context, normalized.text
        )
        assert entered.code == "CULTIVATION_ENTERED"
        assert entered.data["idempotent_replay"] is False
        assert entered.data["path_key"] == "support"
        assert entered.data["subprofession_key"] == "formation"
        assert "百艺道" in entered.message
        assert "阵道" in entered.message
        await runtime.close()

        _remove_path_aliases(data_root)
        recovered = create_runtime(data_dir=data_root, adapters=(adapter,))
        try:
            retried_event = _normalized_event(adapter, message_id)
            assert retried_event.context.operation_id == normalized.context.operation_id
            replay = await recovered.adapters.dispatch(
                adapter, retried_event.context, retried_event.text
            )
            assert replay.code == "CULTIVATION_ENTERED"
            assert replay.data["idempotent_replay"] is True
            assert replay.data["path_key"] == "support"
            assert replay.data["subprofession_key"] == "formation"
            assert replay.message == entered.message
            assert {**replay.data, "idempotent_replay": False} == entered.data
        finally:
            await recovered.close()

    asyncio.run(run())
