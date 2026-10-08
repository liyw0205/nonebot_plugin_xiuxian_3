from __future__ import annotations

import asyncio
import json
import sqlite3
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime


ROOT = Path(__file__).resolve().parents[1]


def _context(adapter: str, user: str, request: str, operation: str = "") -> CommandContext:
    return CommandContext(
        adapter=adapter,
        user_id=user,
        request_id=request,
        operation_id=operation,
        can_write_assets=True,
    )


def _prepare_demon(runtime, adapter: str, user: str) -> None:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE players SET stage='cultivator', realm_key='foundation', realm_layer=1, "
            "location_key='xuantian.cloud_city', spirit_stones=1000, stamina=30, stamina_max=30 "
            "WHERE platform=? AND platform_user_id=?",
            (adapter, user),
        )


async def _arrive_demon(runtime, adapter: str, user: str) -> None:
    started = await runtime.dispatch(_context(adapter, user, f"board-{user}", f"board-{user}"), "登上云舟 魔界引导")
    assert started.code == "CLOUD_BOAT_STARTED"
    with sqlite3.connect(runtime.settings.database_path) as connection:
        ends_at = datetime.fromisoformat(
            connection.execute(
                "SELECT ends_at FROM cloud_boat_sessions WHERE session_id=?",
                (started.data["session_id"],),
            ).fetchone()[0]
        )
    runtime.repository._clock = lambda ends_at=ends_at: ends_at + timedelta(seconds=1)
    settled = await runtime.dispatch(_context(adapter, user, f"settle-{user}", f"settle-{user}"), "结算云舟")
    assert settled.code == "CLOUD_BOAT_ARRIVED"


def _edit_content(data_dir: Path, *, cost: int, reputation: int) -> None:
    quest_path = data_dir / "任务" / "任务.json"
    quest = json.loads(quest_path.read_text(encoding="utf-8"))
    for row in quest["records"]:
        if row.get("key") == "quest.demon_intro":
            row["introduction"]["costs"]["currency.spirit_stone"] = cost
    quest_path.write_text(json.dumps(quest, ensure_ascii=False, indent=2), encoding="utf-8")

    reward_path = data_dir / "奖励" / "奖励.json"
    rewards = json.loads(reward_path.read_text(encoding="utf-8"))
    for row in rewards["records"]:
        if row.get("key") == "reward.world.demon_intro":
            row["entries"][0]["quantity"] = reputation
    reward_path.write_text(json.dumps(rewards, ensure_ascii=False, indent=2), encoding="utf-8")


def test_world_intro_content_snapshot_and_replay_on_both_adapters() -> None:
    async def run() -> None:
        for adapter in ("qq.official", "onebot.v11"):
            with TemporaryDirectory() as temporary:
                data_dir = Path(temporary) / "data"
                shutil.copytree(ROOT / "data", data_dir)
                runtime = create_runtime(data_dir=data_dir, adapters=(adapter,))
                user = f"intro-old-{adapter}"
                await runtime.dispatch(_context(adapter, user, "create"), "开始修仙")
                await runtime.dispatch(_context(adapter, user, "seek"), "寻仙问道")
                _prepare_demon(runtime, adapter, user)
                await _arrive_demon(runtime, adapter, user)
                accepted = await runtime.dispatch(
                    _context(adapter, user, "accept", "intro-old"), "接受魔界引导"
                )
                assert accepted.code == "DEMON_INTRO_ACCEPTED"
                _edit_content(data_dir, cost=40, reputation=7)
                await runtime.close()

                recovered = create_runtime(data_dir=data_dir, adapters=(adapter,))
                replay = await recovered.dispatch(
                    _context(adapter, user, "accept-replay", "intro-old"), "接受魔界引导"
                )
                assert replay.code == "DEMON_INTRO_ACCEPTED"
                assert replay.data["reward"] == {"faction_reputation.demon": 20}

                new_user = f"intro-new-{adapter}"
                await recovered.dispatch(_context(adapter, new_user, "create"), "开始修仙")
                await recovered.dispatch(_context(adapter, new_user, "seek"), "寻仙问道")
                _prepare_demon(recovered, adapter, new_user)
                await _arrive_demon(recovered, adapter, new_user)
                changed = await recovered.dispatch(
                    _context(adapter, new_user, "accept-new", "intro-new"), "接受魔界引导"
                )
                assert changed.code == "DEMON_INTRO_ACCEPTED"
                assert changed.data["reward"] == {"faction_reputation.demon": 7}
                with sqlite3.connect(recovered.settings.database_path) as connection:
                    state = connection.execute(
                        "SELECT spirit_stones, faction_reputation_json FROM players "
                        "WHERE platform=? AND platform_user_id=?",
                        (adapter, new_user),
                    ).fetchone()
                assert state == (460, '{"demon": 7}')
                await recovered.close()

    asyncio.run(run())


def test_world_intro_bad_ledger_and_operation_insert_failure_are_retryable() -> None:
    async def run() -> None:
        for adapter in ("qq.official", "onebot.v11"):
            with TemporaryDirectory() as temporary:
                runtime = create_runtime(data_dir=Path(temporary) / "data", adapters=(adapter,))
                user = f"intro-failure-{adapter}"
                await runtime.dispatch(_context(adapter, user, "create"), "开始修仙")
                await runtime.dispatch(_context(adapter, user, "seek"), "寻仙问道")
                _prepare_demon(runtime, adapter, user)
                await _arrive_demon(runtime, adapter, user)
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "CREATE TRIGGER fail_world_intro BEFORE INSERT ON operations "
                        "WHEN NEW.operation_name='world.accept_demon_intro' "
                        "BEGIN SELECT RAISE(ABORT, 'injected'); END"
                    )
                failed = await runtime.dispatch(
                    _context(adapter, user, "accept-failed", "intro-failed"), "接受魔界引导"
                )
                assert failed.code == "PERSISTENCE_ERROR"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    unchanged = connection.execute(
                        "SELECT spirit_stones, faction_reputation_json, intro_json FROM players "
                        "WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    ).fetchone()
                    connection.execute("DROP TRIGGER fail_world_intro")
                assert unchanged == (500, "{}", "{}")
                retried = await runtime.dispatch(
                    _context(adapter, user, "accept-retry", "intro-failed"), "接受魔界引导"
                )
                assert retried.code == "DEMON_INTRO_ACCEPTED"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    original = connection.execute(
                        "SELECT result_json FROM operations WHERE operation_id='intro-failed'"
                    ).fetchone()[0]
                    malformed_reward = json.loads(original)
                    malformed_reward["reward_snapshot"] = {}
                    connection.execute(
                        "UPDATE operations SET result_json=? WHERE operation_id='intro-failed'",
                        (json.dumps(malformed_reward, ensure_ascii=False, sort_keys=True),),
                    )
                malformed = await runtime.dispatch(
                    _context(adapter, user, "accept-malformed", "intro-failed"), "接受魔界引导"
                )
                assert malformed.code == "PERSISTENCE_ERROR"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE operations SET result_json=? WHERE operation_id='intro-failed'",
                        (original,),
                    )
                replay = await runtime.dispatch(
                    _context(adapter, user, "accept-replay", "intro-failed"), "接受魔界引导"
                )
                assert replay.code == "DEMON_INTRO_ACCEPTED"
                assert replay.data["idempotent_replay"] is True
                await runtime.close()

    asyncio.run(run())
