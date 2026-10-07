from __future__ import annotations

import asyncio
import json
import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from nonebot_plugin_xiuxian_3.runtime import create_runtime
from test_events import _adapter_contexts, _create_player


class _Clock:
    def __init__(self) -> None:
        self.value = datetime(2026, 9, 23, 20, 5, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.value

    def advance(self, **kwargs: int) -> None:
        self.value += timedelta(**kwargs)


def _append_duplicate(raw: str, key: str, value: object) -> str:
    text = raw.rstrip()
    assert text.endswith("}")
    return f'{text[:-1]},"{key}":{json.dumps(value, ensure_ascii=False)}}}'


def _adapter_case(kind: str):
    qq, onebot = _adapter_contexts()
    return ("qq.official", qq) if kind == "qq" else ("onebot.v11", onebot)


async def _seed_round(runtime, adapter: str, context, clock, prefix: str) -> str:
    await _create_player(runtime, context, context.user_id, prefix)
    status = await runtime.adapters.dispatch(
        adapter, replace(context, operation_id=f"{prefix}-status"), "灵泉事件"
    )
    assert status.code == "EVENT_STATUS"
    round_id = status.data["round_id"]
    with sqlite3.connect(runtime.settings.database_path) as connection:
        player_id = connection.execute(
            "SELECT id FROM players WHERE platform=? AND platform_user_id=?",
            (adapter, context.user_id),
        ).fetchone()[0]
        connection.execute(
            "INSERT INTO world_event_contributions(round_id, player_id, contribution, updated_at) "
            "VALUES (?, ?, 10, ?)",
            (round_id, player_id, clock.value.isoformat()),
        )
    clock.advance(minutes=31)
    settled = await runtime.adapters.dispatch(
        adapter, replace(context, operation_id=f"{prefix}-settled"), "灵泉事件"
    )
    assert settled.code == "EVENT_STATUS"
    assert settled.data["status"] == "settled"
    assert settled.data["success"] is False
    return round_id


def _player_state(runtime, adapter: str, user_id: str) -> tuple:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        return connection.execute(
            "SELECT spirit_stones, cultivation, faction_reputation_json "
            "FROM players WHERE platform=? AND platform_user_id=?",
            (adapter, user_id),
        ).fetchone()


@pytest.mark.parametrize("kind", ["qq", "onebot"])
@pytest.mark.parametrize("corruption", ["duplicate", "malformed", "wrong_success"])
def test_spirit_spring_round_snapshot_rejects_corruption_and_retries(
    tmp_path: Path, kind: str, corruption: str,
) -> None:
    async def run() -> None:
        clock = _Clock()
        adapter, context = _adapter_case(kind)
        with TemporaryDirectory(dir=tmp_path) as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock, adapters=(adapter,))
            try:
                round_id = await _seed_round(runtime, adapter, context, clock, f"{kind}-{corruption}")
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    raw = connection.execute(
                        "SELECT result_json FROM world_event_rounds WHERE round_id=?", (round_id,)
                    ).fetchone()[0]
                    if corruption == "malformed":
                        bad = "{"
                    elif corruption == "duplicate":
                        bad = _append_duplicate(raw, "success", True)
                    else:
                        valid = json.loads(raw)
                        valid["success"] = True
                        bad = json.dumps(valid, ensure_ascii=False, sort_keys=True)
                    connection.execute(
                        "UPDATE world_event_rounds SET result_json=? WHERE round_id=?",
                        (bad, round_id),
                    )
                before = _player_state(runtime, adapter, context.user_id)
                refused = await runtime.adapters.dispatch(
                    adapter,
                    replace(context, operation_id=f"{kind}-{corruption}-claim"),
                    f"领取灵泉事件奖励 {round_id}",
                )
                assert refused.code == "PERSISTENCE_ERROR"
                assert _player_state(runtime, adapter, context.user_id) == before
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    player_id = connection.execute(
                        "SELECT id FROM players WHERE platform=? AND platform_user_id=?",
                        (adapter, context.user_id),
                    ).fetchone()[0]
                    assert connection.execute(
                        "SELECT COUNT(*) FROM world_event_claims WHERE round_id=? AND player_id=?",
                        (round_id, player_id),
                    ).fetchone()[0] == 0
                    assert connection.execute(
                        "SELECT COUNT(*) FROM operations WHERE operation_id=?",
                        (f"{kind}-{corruption}-claim",),
                    ).fetchone()[0] == 0
                    assert connection.execute(
                        "SELECT COUNT(*) FROM activity_events WHERE source_operation_id=?",
                        (f"{kind}-{corruption}-claim",),
                    ).fetchone()[0] == 0
                    connection.execute(
                        "UPDATE world_event_rounds SET result_json=? WHERE round_id=?",
                        (raw, round_id),
                    )
                claimed = await runtime.adapters.dispatch(
                    adapter,
                    replace(context, operation_id=f"{kind}-{corruption}-claim"),
                    f"领取灵泉事件奖励 {round_id}",
                )
                assert claimed.code == "EVENT_REWARD_CLAIMED"
                assert claimed.data["reward"] == {"cultivation": 150, "spirit_stones": 100}
                replay = await runtime.adapters.dispatch(
                    adapter,
                    replace(context, operation_id=f"{kind}-{corruption}-claim"),
                    f"领取灵泉事件奖励 {round_id}",
                )
                assert replay.data["idempotent_replay"] is True
            finally:
                await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("kind", ["qq", "onebot"])
@pytest.mark.parametrize("corruption", ["duplicate", "malformed", "wrong_reward"])
def test_spirit_spring_operation_replay_rejects_bad_result_and_recovers(
    tmp_path: Path, kind: str, corruption: str,
) -> None:
    async def run() -> None:
        clock = _Clock()
        adapter, context = _adapter_case(kind)
        with TemporaryDirectory(dir=tmp_path) as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock, adapters=(adapter,))
            try:
                round_id = await _seed_round(runtime, adapter, context, clock, f"replay-{kind}-{corruption}")
                operation_id = f"{kind}-{corruption}-claim"
                claimed = await runtime.adapters.dispatch(
                    adapter, replace(context, operation_id=operation_id), f"领取灵泉事件奖励 {round_id}"
                )
                assert claimed.code == "EVENT_REWARD_CLAIMED"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    raw = connection.execute(
                        "SELECT result_json FROM operations WHERE operation_id=?", (operation_id,)
                    ).fetchone()[0]
                    if corruption == "malformed":
                        bad = "{"
                    elif corruption == "duplicate":
                        bad = _append_duplicate(raw, "reward", {})
                    else:
                        valid = json.loads(raw)
                        valid["reward"]["spirit_stones"] = 999
                        bad = json.dumps(valid, ensure_ascii=False, sort_keys=True)
                    connection.execute(
                        "UPDATE operations SET result_json=? WHERE operation_id=?",
                        (bad, operation_id),
                    )
                before = _player_state(runtime, adapter, context.user_id)
                refused = await runtime.adapters.dispatch(
                    adapter, replace(context, operation_id=operation_id), f"领取灵泉事件奖励 {round_id}"
                )
                assert refused.code == "PERSISTENCE_ERROR"
                assert _player_state(runtime, adapter, context.user_id) == before
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE operations SET result_json=? WHERE operation_id=?", (raw, operation_id)
                    )
                replay = await runtime.adapters.dispatch(
                    adapter, replace(context, operation_id=operation_id), f"领取灵泉事件奖励 {round_id}"
                )
                assert replay.code == "EVENT_REWARD_CLAIMED"
                assert replay.data["idempotent_replay"] is True
            finally:
                await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("kind", ["qq", "onebot"])
def test_spirit_spring_claim_rolls_back_assets_and_retries_after_operation_failure(
    tmp_path: Path, kind: str,
) -> None:
    async def run() -> None:
        clock = _Clock()
        adapter, context = _adapter_case(kind)
        with TemporaryDirectory(dir=tmp_path) as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock, adapters=(adapter,))
            try:
                round_id = await _seed_round(runtime, adapter, context, clock, f"failure-{kind}")
                operation_id = f"{kind}-failure-claim"
                before = _player_state(runtime, adapter, context.user_id)
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "CREATE TRIGGER fail_spirit_spring_operation "
                        "BEFORE INSERT ON operations "
                        "WHEN NEW.operation_name='event.claim_reward' "
                        "BEGIN SELECT RAISE(ABORT, 'injected event failure'); END"
                    )
                failed = await runtime.adapters.dispatch(
                    adapter, replace(context, operation_id=operation_id), f"领取灵泉事件奖励 {round_id}"
                )
                assert failed.code == "PERSISTENCE_ERROR"
                assert _player_state(runtime, adapter, context.user_id) == before
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    player_id = connection.execute(
                        "SELECT id FROM players WHERE platform=? AND platform_user_id=?",
                        (adapter, context.user_id),
                    ).fetchone()[0]
                    assert connection.execute(
                        "SELECT COUNT(*) FROM world_event_claims WHERE round_id=? AND player_id=?",
                        (round_id, player_id),
                    ).fetchone()[0] == 0
                    assert connection.execute(
                        "SELECT COUNT(*) FROM operations WHERE operation_id=?", (operation_id,)
                    ).fetchone()[0] == 0
                    assert connection.execute(
                        "SELECT COUNT(*) FROM activity_events WHERE source_operation_id=?", (operation_id,)
                    ).fetchone()[0] == 0
                    connection.execute("DROP TRIGGER fail_spirit_spring_operation")
                retried = await runtime.adapters.dispatch(
                    adapter, replace(context, operation_id=operation_id), f"领取灵泉事件奖励 {round_id}"
                )
                assert retried.code == "EVENT_REWARD_CLAIMED"
                assert retried.data["idempotent_replay"] is False
            finally:
                await runtime.close()

    asyncio.run(run())
