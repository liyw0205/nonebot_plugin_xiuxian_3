from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.specials.dispatch_rules import DISPATCHES, choose_outcome

MID_HIGH = (
    "dispatch.foundation.patrol",
    "dispatch.foundation.escort",
    "dispatch.golden_core.vein_survey",
    "dispatch.golden_core.pill_run",
    "dispatch.nascent.ruins_watch",
    "dispatch.nascent.beast_census",
    "dispatch.soul.domain_relay",
    "dispatch.soul.abyss_manifest",
    "dispatch.void.garden_tending",
    "dispatch.void.route_courier",
)


class MutableClock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value

    def advance(self, **kwargs: int) -> None:
        self.value += timedelta(**kwargs)


def _context(adapter: str, user: str, operation_id: str) -> CommandContext:
    return CommandContext(adapter=adapter, user_id=user, operation_id=operation_id)


async def _send(runtime, adapter: str, user: str, operation_id: str, text: str):
    return await runtime.adapters.dispatch(
        adapter, _context(adapter, user, operation_id), text
    )


async def _create_and_promote(runtime, adapter: str, user: str) -> None:
    assert (await _send(runtime, adapter, user, f"{user}-create", "开始修仙")).ok
    assert (await _send(runtime, adapter, user, f"{user}-seek", "寻仙问道")).ok
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE players SET stage = 'cultivator', realm_key = 'void_refining', "
            "realm_layer = 10, stamina = 500, stamina_max = 500, energy = 500, "
            "energy_max = 500 WHERE platform = ? AND platform_user_id = ?",
            (adapter, user),
        )


def _forced_dispatch_seed(dispatch_key: str, outcome: str) -> str:
    definition = DISPATCHES[dispatch_key]
    return next(
        seed
        for index in range(10000)
        if (seed := f"forced-{dispatch_key}-{index}")
        and choose_outcome(definition, seed) == outcome
    )


def _force_uuid(seed: str, assignment: str):
    return patch(
        "nonebot_plugin_xiuxian_3.xiuxian.specials.dispatch_repository.uuid4",
        side_effect=[SimpleNamespace(hex=seed), SimpleNamespace(hex=assignment)],
    )


def _player_state(runtime, adapter: str, user: str) -> dict[str, int]:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        row = connection.execute(
            "SELECT id, stamina, energy, spirit_stones FROM players "
            "WHERE platform = ? AND platform_user_id = ?",
            (adapter, user),
        ).fetchone()
    assert row is not None
    return {
        "id": int(row[0]),
        "stamina": int(row[1]),
        "energy": int(row[2]),
        "spirit_stones": int(row[3]),
    }


def _assignment_snapshot(runtime, assignment_id: str) -> dict[str, object]:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        row = connection.execute(
            "SELECT snapshot_json FROM dispatch_assignments WHERE assignment_id = ?",
            (assignment_id,),
        ).fetchone()
    assert row is not None
    return json.loads(row[0])


def test_all_ten_mid_high_dispatches_accept_settle_and_replay() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 10, 1, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            adapter, user = "qq.official", "dispatch-runtime-ten"
            try:
                await _create_and_promote(runtime, adapter, user)
                for index, key in enumerate(MID_HIGH):
                    definition = DISPATCHES[key]
                    costs = dict(definition.costs)
                    success = dict(dict(definition.rewards)["success"])
                    before = _player_state(runtime, adapter, user)

                    seed = _forced_dispatch_seed(key, "success")
                    with _force_uuid(seed, f"assignment-{index}"):
                        accepted = await _send(
                            runtime,
                            adapter,
                            user,
                            f"accept-{key}",
                            f"接受派遣 {definition.label}",
                        )
                    assert accepted.code == "DISPATCH_ACCEPTED", (key, accepted.message)
                    assert accepted.data["outcome"] == "success"
                    after_accept = _player_state(runtime, adapter, user)
                    assert before["stamina"] - after_accept["stamina"] == costs.get("stamina", 0)
                    assert before["energy"] - after_accept["energy"] == costs.get("energy", 0)

                    snapshot = _assignment_snapshot(runtime, accepted.data["assignment_id"])
                    assert snapshot["dispatch_key"] == key
                    assert snapshot["outcome"] == "success"
                    assert sum(dict(snapshot["risk_weights"]).values()) == 10000
                    assert set(dict(snapshot["failure_refunds"])) <= set(costs)
                    assert dict(snapshot["reward"])["spirit_stones"] == success["spirit_stones"]

                    clock.value = datetime.fromisoformat(accepted.data["ends_at"])
                    settled = await _send(
                        runtime, adapter, user, f"settle-{key}", "结算派遣"
                    )
                    assert settled.code == "DISPATCH_SETTLED", (key, settled.message)
                    assert settled.data["outcome"] == "success"
                    assert settled.data["reward"]["spirit_stones"] == success["spirit_stones"]
                    for reward_key, value in success.items():
                        if reward_key.startswith("item."):
                            assert (
                                value[0]
                                <= settled.data["reward"][reward_key]
                                <= value[1]
                            )
                        elif reward_key.startswith("local."):
                            assert settled.data["reward"][reward_key] == value
                    assert settled.data["refunded"] == {}

                    replay = await _send(
                        runtime, adapter, user, f"settle-{key}", "结算派遣"
                    )
                    assert replay.data["idempotent_replay"] is True
                    assert replay.data["reward"] == settled.data["reward"]
                    assert _player_state(runtime, adapter, user)["spirit_stones"] == (
                        before["spirit_stones"]
                        + settled.data["reward"].get("spirit_stones", 0)
                    )
            finally:
                await runtime.close()

    asyncio.run(run())


def test_mid_high_dispatch_daily_limit_failure_refund_and_restart() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 10, 2, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            adapter, user = "onebot.v11", "dispatch-runtime-limits"

            async def accept_and_settle(key: str, tag: str):
                definition = DISPATCHES[key]
                seed = _forced_dispatch_seed(key, "success")
                with _force_uuid(seed, f"limit-{tag}"):
                    accepted = await _send(
                        runtime, adapter, user, f"accept-{tag}", f"接受派遣 {key}"
                    )
                assert accepted.code == "DISPATCH_ACCEPTED", (tag, accepted.message)
                clock.value = datetime.fromisoformat(accepted.data["ends_at"])
                settled = await _send(runtime, adapter, user, f"settle-{tag}", "结算派遣")
                assert settled.code == "DISPATCH_SETTLED", (tag, settled.message)
                return settled

            try:
                await _create_and_promote(runtime, adapter, user)
                await accept_and_settle("dispatch.foundation.patrol", "patrol-1")
                await accept_and_settle("dispatch.foundation.patrol", "patrol-2")
                await accept_and_settle("dispatch.foundation.patrol", "patrol-3")
                blocked = await _send(
                    runtime,
                    adapter,
                    user,
                    "patrol-4",
                    "接受派遣 dispatch.foundation.patrol",
                )
                assert blocked.code == "DISPATCH_DAILY_LIMIT"

                key = "dispatch.void.route_courier"
                definition = DISPATCHES[key]
                costs = dict(definition.costs)
                refunds = dict(definition.failure_refunds)
                before = _player_state(runtime, adapter, user)
                failed_seed = _forced_dispatch_seed(key, "failed")
                with _force_uuid(failed_seed, "courier-failed"):
                    failed_accept = await _send(
                        runtime, adapter, user, "courier-failed-accept", f"接受派遣 {key}"
                    )
                assert failed_accept.code == "DISPATCH_ACCEPTED"
                assert failed_accept.data["outcome"] == "failed"
                clock.value = datetime.fromisoformat(failed_accept.data["ends_at"])
                failed = await _send(
                    runtime, adapter, user, "courier-failed-settle", "结算派遣"
                )
                assert failed.code == "DISPATCH_SETTLED"
                assert failed.data["reward"] == {}
                assert failed.data["refunded"] == refunds
                after = _player_state(runtime, adapter, user)
                assert before["stamina"] - after["stamina"] == (
                    costs.get("stamina", 0) - refunds.get("stamina", 0)
                )
                assert before["energy"] - after["energy"] == (
                    costs.get("energy", 0) - refunds.get("energy", 0)
                )

                key = "dispatch.soul.domain_relay"
                seed = _forced_dispatch_seed(key, "success")
                with _force_uuid(seed, "relay-restart"):
                    accepted = await _send(
                        runtime, adapter, user, "relay-restart-accept", f"接受派遣 {key}"
                    )
                assert accepted.code == "DISPATCH_ACCEPTED"
                assignment_id = accepted.data["assignment_id"]
                ends_at = accepted.data["ends_at"]
                await runtime.close()

                runtime = create_runtime(data_dir=data_dir, clock=clock)
                clock.value = datetime.fromisoformat(ends_at)
                settled = await _send(
                    runtime, adapter, user, "relay-restart-settle", "结算派遣"
                )
                assert settled.code == "DISPATCH_SETTLED", settled.message
                assert settled.code == "DISPATCH_SETTLED"
                assert settled.data["outcome"] == "success"
                assert settled.data["reward"]["spirit_stones"] == 180
                assert _assignment_snapshot(runtime, assignment_id)["dispatch_key"] == key
            finally:
                await runtime.close()

    asyncio.run(run())
