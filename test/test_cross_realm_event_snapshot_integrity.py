from __future__ import annotations

import asyncio
import json
import shutil
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from test_cross_realm_events import _configure_beast_event, _create_player


ADAPTERS = ("qq.official", "onebot.v11")


class _Clock:
    def __init__(self) -> None:
        self.value = datetime(2026, 9, 21, 12, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.value

    def advance(self, **kwargs: int) -> None:
        self.value += timedelta(**kwargs)


def _context(adapter: str, user: str, operation_id: str) -> CommandContext:
    return CommandContext(
        adapter=adapter,
        user_id=user,
        request_id=f"cross-realm-integrity:{operation_id}",
        operation_id=operation_id,
    )


def _copy_content(data_dir: Path) -> None:
    shutil.copytree(Path(__file__).parents[1] / "data", data_dir)


def _append_duplicate(raw: str, key: str, value: object) -> str:
    text = raw.rstrip()
    assert text.endswith("}")
    return f'{text[:-1]},"{key}":{json.dumps(value, ensure_ascii=False)}}}'


def _corrupt_round_result(raw: str, corruption: str) -> str:
    if corruption == "malformed":
        return "{"
    if corruption == "duplicate":
        return _append_duplicate(raw, "success", True)
    payload = json.loads(raw)
    if corruption == "wrong_type":
        payload["success"] = {"settled": True}
    elif corruption == "reward_mismatch":
        payload["configuration"]["reward"]["assets"]["item.mat.array_sand"] = 9999
    else:
        raise AssertionError(f"unknown corruption: {corruption}")
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _corrupt_operation_result(raw: str, corruption: str) -> str:
    if corruption == "malformed":
        return "{"
    if corruption == "duplicate":
        return _append_duplicate(raw, "reward", {})
    if corruption == "wrong_reward":
        payload = json.loads(raw)
        payload["reward"]["item.mat.array_sand"] = 9999
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)
    if corruption == "foreign_player":
        payload = json.loads(raw)
        payload["player"]["id"] = "foreign-player"
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)
    raise AssertionError(f"unknown corruption: {corruption}")


async def _seed_settled_round(runtime, adapter: str, user: str, clock: _Clock) -> tuple[str, int, str]:
    player_id = await _create_player(runtime, adapter, user)
    status = await runtime.adapters.dispatch(
        adapter,
        _context(adapter, user, f"{user}:status"),
        "妖界贸易事件",
    )
    assert status.code == "EVENT_STATUS"
    round_id = str(status.data["round_id"])
    contributed = await runtime.adapters.dispatch(
        adapter,
        _context(adapter, user, f"{user}:contribute"),
        "贡献妖界贸易 妖血",
    )
    assert contributed.code == "EVENT_CONTRIBUTION_RECORDED"
    assert contributed.data["player_contribution"] == 5
    clock.advance(days=7, minutes=1)
    settled = await runtime.adapters.dispatch(
        adapter,
        _context(adapter, user, f"{user}:settle"),
        f"妖界贸易事件 {round_id}",
    )
    assert settled.code == "EVENT_STATUS"
    assert settled.data["status"] == "settled"
    with sqlite3.connect(runtime.settings.database_path) as connection:
        result_json = connection.execute(
            "SELECT result_json FROM world_event_rounds WHERE round_id=?", (round_id,)
        ).fetchone()[0]
    return round_id, player_id, str(result_json)


def _asset_state(runtime, player_id: int, operation_id: str) -> tuple[tuple[object, ...], tuple[int, int, int]]:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        player = connection.execute(
            "SELECT inventory_json, faction_reputation_json FROM players WHERE id=?", (player_id,)
        ).fetchone()
        counts = connection.execute(
            "SELECT "
            "(SELECT COUNT(*) FROM world_event_claims WHERE operation_id=?), "
            "(SELECT COUNT(*) FROM operations WHERE operation_id=?), "
            "(SELECT COUNT(*) FROM activity_events WHERE source_operation_id=?)",
            (operation_id, operation_id, operation_id),
        ).fetchone()
    assert player is not None
    return tuple(player), tuple(int(value) for value in counts)


@pytest.mark.parametrize("adapter", ADAPTERS)
@pytest.mark.parametrize(
    "corruption",
    [
        "duplicate",
        "malformed",
        "wrong_type",
        "reward_mismatch",
        "round_target",
        "round_location",
        "round_hash",
    ],
)
def test_corrupt_beast_trade_round_snapshot_is_read_only_until_repaired(
    tmp_path: Path, adapter: str, corruption: str
) -> None:
    async def run() -> None:
        clock = _Clock()
        data_dir = tmp_path / adapter.replace(".", "-") / corruption / "data"
        _copy_content(data_dir)
        _configure_beast_event(data_dir, target=5, quantity=5, threshold=5, reward=10)
        runtime = create_runtime(data_dir=data_dir, adapters=(adapter,), clock=clock)
        user = f"beast-snapshot-{adapter}-{corruption}"
        claim_operation = f"{user}:claim"
        try:
            round_id, player_id, original = await _seed_settled_round(runtime, adapter, user, clock)
            with sqlite3.connect(runtime.settings.database_path) as connection:
                original_round = connection.execute(
                    "SELECT target_quantity, location_key, configuration_hash "
                    "FROM world_event_rounds WHERE round_id=?",
                    (round_id,),
                ).fetchone()
                assert original_round is not None
                if corruption == "round_target":
                    connection.execute(
                        "UPDATE world_event_rounds SET target_quantity=? WHERE round_id=?",
                        (int(original_round[0]) + 1, round_id),
                    )
                elif corruption == "round_location":
                    connection.execute(
                        "UPDATE world_event_rounds SET location_key=? WHERE round_id=?",
                        ("beast.ten_thousand_hills", round_id),
                    )
                elif corruption == "round_hash":
                    connection.execute(
                        "UPDATE world_event_rounds SET configuration_hash=? WHERE round_id=?",
                        ("corrupted-configuration-hash", round_id),
                    )
                else:
                    connection.execute(
                        "UPDATE world_event_rounds SET result_json=? WHERE round_id=?",
                        (_corrupt_round_result(original, corruption), round_id),
                    )
            before = _asset_state(runtime, player_id, claim_operation)

            refused = await runtime.adapters.dispatch(
                adapter,
                _context(adapter, user, claim_operation),
                f"领取妖界贸易奖励 {round_id}",
            )
            assert refused.code == "PERSISTENCE_ERROR"
            assert _asset_state(runtime, player_id, claim_operation) == before

            with sqlite3.connect(runtime.settings.database_path) as connection:
                if corruption == "round_target":
                    assert connection.execute(
                        "SELECT target_quantity FROM world_event_rounds WHERE round_id=?", (round_id,)
                    ).fetchone()[0] != original_round[0]
                    connection.execute(
                        "UPDATE world_event_rounds SET target_quantity=? WHERE round_id=?",
                        (original_round[0], round_id),
                    )
                elif corruption == "round_location":
                    assert connection.execute(
                        "SELECT location_key FROM world_event_rounds WHERE round_id=?", (round_id,)
                    ).fetchone()[0] != original_round[1]
                    connection.execute(
                        "UPDATE world_event_rounds SET location_key=? WHERE round_id=?",
                        (original_round[1], round_id),
                    )
                elif corruption == "round_hash":
                    assert connection.execute(
                        "SELECT configuration_hash FROM world_event_rounds WHERE round_id=?", (round_id,)
                    ).fetchone()[0] != original_round[2]
                    connection.execute(
                        "UPDATE world_event_rounds SET configuration_hash=? WHERE round_id=?",
                        (original_round[2], round_id),
                    )
                else:
                    assert connection.execute(
                        "SELECT result_json FROM world_event_rounds WHERE round_id=?", (round_id,)
                    ).fetchone()[0] != original
                    connection.execute(
                        "UPDATE world_event_rounds SET result_json=? WHERE round_id=?", (original, round_id)
                    )

            claimed = await runtime.adapters.dispatch(
                adapter,
                _context(adapter, user, claim_operation),
                f"领取妖界贸易奖励 {round_id}",
            )
            assert claimed.code == "EVENT_REWARD_CLAIMED"
            assert claimed.data["reward"] == {
                "faction_reputation.beast": 10,
                "item.mat.array_sand": 10,
            }
            await runtime.close()
            runtime = create_runtime(data_dir=data_dir, adapters=(adapter,), clock=clock)
            replay = await runtime.adapters.dispatch(
                adapter,
                _context(adapter, user, claim_operation),
                f"领取妖界贸易奖励 {round_id}",
            )
            assert replay.code == "EVENT_REWARD_CLAIMED"
            assert replay.data["idempotent_replay"] is True
            with sqlite3.connect(runtime.settings.database_path) as connection:
                inventory, reputation = connection.execute(
                    "SELECT inventory_json, faction_reputation_json FROM players WHERE id=?", (player_id,)
                ).fetchone()
            assert json.loads(inventory) == {"item.mat.array_sand": 10}
            assert json.loads(reputation)["beast"] == 210
        finally:
            await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("adapter", ADAPTERS)
@pytest.mark.parametrize("corruption", ["duplicate", "malformed", "wrong_reward", "foreign_player"])
def test_corrupt_beast_trade_claim_operation_rejects_replay_until_repaired(
    tmp_path: Path, adapter: str, corruption: str
) -> None:
    async def run() -> None:
        clock = _Clock()
        data_dir = tmp_path / adapter.replace(".", "-") / "operation" / corruption / "data"
        _copy_content(data_dir)
        _configure_beast_event(data_dir, target=5, quantity=5, threshold=5, reward=10)
        runtime = create_runtime(data_dir=data_dir, adapters=(adapter,), clock=clock)
        user = f"beast-operation-{adapter}-{corruption}"
        claim_operation = f"{user}:claim"
        try:
            round_id, player_id, _ = await _seed_settled_round(runtime, adapter, user, clock)
            claimed = await runtime.adapters.dispatch(
                adapter,
                _context(adapter, user, claim_operation),
                f"领取妖界贸易奖励 {round_id}",
            )
            assert claimed.code == "EVENT_REWARD_CLAIMED"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                original = connection.execute(
                    "SELECT result_json FROM operations WHERE operation_id=?", (claim_operation,)
                ).fetchone()[0]
                connection.execute(
                    "UPDATE operations SET result_json=? WHERE operation_id=?",
                    (_corrupt_operation_result(str(original), corruption), claim_operation),
                )
            before = _asset_state(runtime, player_id, claim_operation)
            await runtime.close()
            runtime = create_runtime(data_dir=data_dir, adapters=(adapter,), clock=clock)

            refused = await runtime.adapters.dispatch(
                adapter,
                _context(adapter, user, claim_operation),
                f"领取妖界贸易奖励 {round_id}",
            )
            assert refused.code == "PERSISTENCE_ERROR"
            assert _asset_state(runtime, player_id, claim_operation) == before

            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE operations SET result_json=? WHERE operation_id=?", (original, claim_operation)
                )
            replay = await runtime.adapters.dispatch(
                adapter,
                _context(adapter, user, claim_operation),
                f"领取妖界贸易奖励 {round_id}",
            )
            assert replay.code == "EVENT_REWARD_CLAIMED"
            assert replay.data["idempotent_replay"] is True
            with sqlite3.connect(runtime.settings.database_path) as connection:
                inventory, reputation = connection.execute(
                    "SELECT inventory_json, faction_reputation_json FROM players WHERE id=?", (player_id,)
                ).fetchone()
            assert json.loads(inventory) == {"item.mat.array_sand": 10}
            assert json.loads(reputation)["beast"] == 210
        finally:
            await runtime.close()

    asyncio.run(run())
