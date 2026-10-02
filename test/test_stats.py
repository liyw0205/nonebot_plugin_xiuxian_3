from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.stats.rules import build_stat_preview


async def _send(runtime, adapter: str, user: str, operation_id: str, text: str):
    return await runtime.adapters.dispatch(
        adapter,
        CommandContext(adapter=adapter, user_id=user, operation_id=operation_id),
        text,
    )


def test_stats_preview_freeze_and_replay_work_for_both_adapters() -> None:
    async def scenario() -> None:
        with TemporaryDirectory() as temp:
            data_dir = Path(temp) / "data"
            shutil.copytree(Path("data"), data_dir)
            runtime = create_runtime(data_dir=data_dir, adapters=("qq.official", "onebot.v11"))
            await runtime.initialize()
            try:
                for adapter in ("qq.official", "onebot.v11"):
                    user = f"stats-{adapter}"
                    assert (await _send(runtime, adapter, user, f"{user}-create", "开始修仙")).ok
                    assert (await _send(runtime, adapter, user, f"{user}-seek", "寻仙问道")).ok
                    preview = await _send(runtime, adapter, user, f"{user}-preview", "我的属性")
                    assert preview.code == "STATS_PREVIEW"
                    base = preview.data["base_stats"]
                    derived = preview.data["derived_stats"]
                    assert derived["max_hp"] == 100 + 8 * base["body"] + 5 * base["root"]
                    assert derived["max_mp"] == 60 + 10 * base["spirit"] + 4 * base["insight"]
                    explanation = await _send(runtime, adapter, user, f"{user}-explain", "属性说明 气血上限")
                    assert explanation.code == "STAT_EXPLAINED"
                    profile = await _send(runtime, adapter, user, f"{user}-profile", "我的状态")
                    assert profile.data["stats"]["derived_stats"] == preview.data["derived_stats"]
                    frozen = await runtime.repository.freeze_stats(
                        platform=adapter,
                        platform_user_id=user,
                        purpose="battle",
                        operation_id=f"{user}-freeze",
                    )
                    replay = await runtime.repository.freeze_stats(
                        platform=adapter,
                        platform_user_id=user,
                        purpose="battle",
                        operation_id=f"{user}-freeze",
                    )
                    assert replay.payload() == frozen.payload()
                    assert frozen.already_completed is False
                    assert replay.already_completed is True
                    try:
                        await runtime.repository.freeze_stats(
                            platform=adapter,
                            platform_user_id=user,
                            purpose="exploration",
                            operation_id=f"{user}-freeze",
                        )
                    except Exception as exc:
                        assert exc.__class__.__name__ == "OperationConflictError"
                    else:
                        raise AssertionError("reusing a freeze operation with another purpose must conflict")
                    with runtime.repository._connect() as connection:
                        count = connection.execute(
                            "SELECT COUNT(*) FROM stat_snapshots WHERE player_id=?",
                            (frozen.player_id,),
                        ).fetchone()[0]
                    assert count == 1
            finally:
                await runtime.close()
            recovered = create_runtime(data_dir=data_dir, adapters=("qq.official",))
            await recovered.initialize()
            try:
                replay = await recovered.repository.freeze_stats(
                    platform="qq.official",
                    platform_user_id="stats-qq.official",
                    purpose="battle",
                    operation_id="stats-qq.official-freeze",
                )
                assert replay.snapshot_id.startswith("stats-")
            finally:
                await recovered.close()

    asyncio.run(scenario())


def test_stats_formula_changes_with_content_without_runtime_constants() -> None:
    async def scenario() -> None:
        with TemporaryDirectory() as temp:
            data_dir = Path(temp) / "data"
            shutil.copytree(Path("data"), data_dir)
            rules_path = data_dir / "养成" / "规则.json"
            document = json.loads(rules_path.read_text(encoding="utf-8"))
            record = next(item for item in document["records"] if item["key"] == "stats.formula")
            record["formulas"]["max_hp_body"] = 9
            rules_path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            runtime = create_runtime(data_dir=data_dir, adapters=("qq.official",))
            await runtime.initialize()
            try:
                user = "stats-content-change"
                assert (await _send(runtime, "qq.official", user, "create", "开始修仙")).ok
                assert (await _send(runtime, "qq.official", user, "seek", "寻仙问道")).ok
                preview = await _send(runtime, "qq.official", user, "preview", "我的属性")
                base = preview.data["base_stats"]
                assert preview.data["derived_stats"]["max_hp"] == 100 + 9 * base["body"] + 5 * base["root"]
            finally:
                await runtime.close()

    asyncio.run(scenario())


def test_stats_preview_uses_shared_player_projection_for_json_rows() -> None:
    preview = build_stat_preview(
        {
            "qualification_json": json.dumps(
                {"body": 10, "spirit": 10, "insight": 10, "root": 10, "agility": 10, "fortune": 10}
            ),
            "realm_key": "mortal",
            "realm_layer": 0,
            "path_key": None,
        }
    )

    assert preview["base_stats"] == {
        "body": 10,
        "spirit": 10,
        "insight": 10,
        "root": 10,
        "agility": 10,
        "fortune": 10,
    }
    assert preview["derived_stats"]["initiative"] == 20
