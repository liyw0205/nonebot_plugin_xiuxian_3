from __future__ import annotations

import asyncio
import json
import shutil
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime


ADAPTERS = ("qq.official", "onebot.v11")
POOL_KEY = "reward.gacha.fate.dao_echo"


def _context(adapter: str, user: str, operation_id: str) -> CommandContext:
    return CommandContext(adapter=adapter, user_id=user, operation_id=operation_id)


def _copy_data(tmp_path: Path) -> Path:
    target = tmp_path / "data"
    shutil.copytree(Path(__file__).parents[1] / "data", target)
    return target


def _update_pool(data_dir: Path, **changes: object) -> None:
    path = data_dir / "奖励" / "奖励.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    next(row for row in document["records"] if row["key"] == POOL_KEY).update(changes)
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _set_dao_union(runtime, adapter: str, user: str, stones: int = 10_000) -> None:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE players SET stage='cultivator', realm_key='dao_union', realm_layer=1, spirit_stones=? "
            "WHERE platform=? AND platform_user_id=?",
            (stones, adapter, user),
        )


def test_dao_echo_requires_he_dao_and_uses_one_shared_adapter_path() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            for adapter in ADAPTERS:
                user = f"dao-echo-{adapter}"
                assert (await runtime.adapters.dispatch(
                    adapter, _context(adapter, user, f"{user}:create"), "开始修仙"
                )).ok
                assert (await runtime.adapters.dispatch(
                    adapter, _context(adapter, user, f"{user}:seek"), "寻仙问道"
                )).ok
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    before = connection.execute(
                        "SELECT spirit_stones FROM players WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    ).fetchone()[0]
                refused = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, f"{user}:refused"),
                    "机缘寻宝 道统回响 单抽",
                )
                assert refused.code == "FATE_POOL_REQUIREMENT_MISSING"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    after = connection.execute(
                        "SELECT spirit_stones, COUNT(fate_rolls.id) FROM players "
                        "LEFT JOIN fate_rolls ON fate_rolls.player_id=players.id "
                        "WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    ).fetchone()
                assert after == (before, 0)

                _set_dao_union(runtime, adapter, user)
                rolled = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, f"{user}:roll"),
                    "机缘寻宝 道统回响 单抽",
                )
                assert rolled.code == "FATE_POOL_ROLLED"
                assert rolled.data["pool_key"] == "gacha.fate.dao_echo"
                assert rolled.data["cost_quantity"] == 800
                assert rolled.data["pity_after"] < 20
            await runtime.close()

    asyncio.run(run())


def test_dao_echo_replays_frozen_result_after_content_closes(tmp_path: Path) -> None:
    async def run() -> None:
        data_dir = _copy_data(tmp_path)
        runtime = create_runtime(data_dir=data_dir)
        adapter, user, operation_id = "onebot.v11", "dao-echo-snapshot", "dao-echo-snapshot:roll"
        assert (await runtime.adapters.dispatch(
            adapter, _context(adapter, user, f"{user}:create"), "开始修仙"
        )).ok
        assert (await runtime.adapters.dispatch(
            adapter, _context(adapter, user, f"{user}:seek"), "寻仙问道"
        )).ok
        _set_dao_union(runtime, adapter, user)
        first = await runtime.adapters.dispatch(
            adapter, _context(adapter, user, operation_id), "机缘寻宝 道统回响 单抽"
        )
        assert first.ok and first.data["cost_quantity"] == 800
        await runtime.close()

        _update_pool(
            data_dir,
            name="道统残响",
            aliases=["道统机缘", "道统回响池"],
            status="locked",
            draw_costs={"single": {"spirit_stones": 9_999}, "ten": {"spirit_stones": 8_888}},
        )
        recovered = create_runtime(data_dir=data_dir)
        replay = await recovered.adapters.dispatch(
            adapter, _context(adapter, user, operation_id), "机缘寻宝 道统回响 单抽"
        )
        assert replay.ok and replay.data["idempotent_replay"] is True
        assert replay.data["cost_quantity"] == 800
        assert replay.data["reward"] == first.data["reward"]
        assert "道统回响" in replay.message
        await recovered.close()

    asyncio.run(run())


def test_dao_echo_rejects_malformed_operation_without_charging(tmp_path: Path) -> None:
    async def run() -> None:
        data_dir = _copy_data(tmp_path)
        runtime = create_runtime(data_dir=data_dir)
        adapter, user, operation_id = "qq.official", "dao-echo-malformed", "dao-echo-malformed:roll"
        assert (await runtime.adapters.dispatch(
            adapter, _context(adapter, user, f"{user}:create"), "开始修仙"
        )).ok
        assert (await runtime.adapters.dispatch(
            adapter, _context(adapter, user, f"{user}:seek"), "寻仙问道"
        )).ok
        _set_dao_union(runtime, adapter, user)
        first = await runtime.adapters.dispatch(
            adapter, _context(adapter, user, operation_id), "机缘寻宝 道统回响 单抽"
        )
        assert first.ok
        with sqlite3.connect(runtime.settings.database_path) as connection:
            connection.execute(
                "UPDATE operations SET result_json=? WHERE operation_id=?",
                ("[]", operation_id),
            )
            charged = connection.execute(
                "SELECT spirit_stones FROM players WHERE platform=? AND platform_user_id=?",
                (adapter, user),
            ).fetchone()[0]
        replay = await runtime.adapters.dispatch(
            adapter, _context(adapter, user, operation_id), "机缘寻宝 道统回响 单抽"
        )
        assert replay.code == "PERSISTENCE_ERROR"
        with sqlite3.connect(runtime.settings.database_path) as connection:
            assert connection.execute(
                "SELECT spirit_stones FROM players WHERE platform=? AND platform_user_id=?",
                (adapter, user),
            ).fetchone()[0] == charged
            assert connection.execute(
                "SELECT COUNT(*) FROM fate_rolls WHERE operation_id=?", (operation_id,)
            ).fetchone()[0] == 1
        await runtime.close()

    asyncio.run(run())
