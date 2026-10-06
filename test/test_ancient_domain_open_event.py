from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime


class MutableClock:
    def __init__(self, value: datetime):
        self.value = value

    def __call__(self) -> datetime:
        return self.value

    def advance(self, **kwargs: int) -> None:
        self.value += timedelta(**kwargs)


def _context(adapter: str, user: str, request: str, operation: str = "") -> CommandContext:
    return CommandContext(
        adapter=adapter,
        user_id=user,
        request_id=request,
        operation_id=operation,
        can_write_assets=True,
    )


async def _create_player(runtime, adapter: str, user: str) -> int:
    result = await runtime.adapters.dispatch(
        adapter, _context(adapter, user, f"create-{user}"), "开始修仙"
    )
    assert result.ok
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE players SET stage='cultivator', realm_key='soul_transformation', realm_layer=1, "
            "location_key='xuantian.domain_front' WHERE platform=? AND platform_user_id=?",
            (adapter, user),
        )
        return int(
            connection.execute(
                "SELECT id FROM players WHERE platform=? AND platform_user_id=?",
                (adapter, user),
            ).fetchone()[0]
        )


def _insert_ancient_domain_sources(runtime, player_id: int, now: str, prefix: str) -> list[str]:
    source_ids: list[str] = []
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "INSERT INTO parties(party_id,party_type,status,leader_id,location_key,confirmation_deadline,distribution_key,created_at,updated_at) "
            "VALUES(?, 'secret_realm_ancient', 'ready', ?, 'cave.ancient_domain', ?, 'contribution', ?, ?)",
            (f"party-{prefix}", player_id, now, now, now),
        )
        for index in range(5):
            run_id = f"run-{prefix}-{index}"
            source_id = f"ancient-settle-{prefix}-{index}"
            source_ids.append(source_id)
            connection.execute(
                "INSERT INTO ancient_domain_runs(run_id,party_id,status,node_index,battle_id,quota_key,starts_at,expires_at,snapshot_json,result_json,entry_operation_id,created_at,updated_at) "
                "VALUES(?, ?, 'settled', 8, NULL, ?, ?, ?, '{}', ?, ?, ?, ?)",
                (
                    run_id,
                    f"party-{prefix}",
                    f"quota-{prefix}-{index}",
                    now,
                    now,
                    json.dumps({"outcome": "won", "rewards": {str(player_id): {"item.ancient_fruit": 1}}}),
                    f"ancient-enter-{prefix}-{index}",
                    now,
                    now,
                ),
            )
            connection.execute(
                "INSERT INTO ancient_domain_members(run_id,player_id,quota_key,member_order,first_clear,status,reward_json,created_at,updated_at) "
                "VALUES(?, ?, ?, 0, 0, 'cleared', ?, ?, ?)",
                (
                    run_id,
                    player_id,
                    f"quota-{prefix}-{index}",
                    json.dumps({"item.ancient_fruit": 1}),
                    now,
                    now,
                ),
            )
            connection.execute(
                "INSERT INTO operations(operation_id,operation_name,player_id,request_hash,result_json,created_at) "
                "VALUES(?, 'ancient_domain.settle', ?, ?, ?, ?)",
                (
                    source_id,
                    player_id,
                    f"hash-{source_id}",
                    json.dumps({"run_id": run_id, "outcome": "won"}),
                    now,
                ),
            )
    return source_ids


def test_ancient_domain_open_event_replays_and_recovers_on_both_adapters() -> None:
    async def run() -> None:
        for adapter in ("qq.official", "onebot.v11"):
            clock = MutableClock(datetime(2026, 9, 25, 12, tzinfo=timezone.utc))
            with TemporaryDirectory() as data_dir:
                runtime = create_runtime(data_dir=Path(data_dir), clock=clock)
                user = f"ancient-event-{adapter}"
                player_id = await _create_player(runtime, adapter, user)
                sources = _insert_ancient_domain_sources(
                    runtime, player_id, clock.value.isoformat(), adapter
                )

                status = await runtime.adapters.dispatch(
                    adapter, _context(adapter, user, "status"), "远古洞天事件"
                )
                assert status.ok
                round_id = status.data["round_id"]
                for index, source_id in enumerate(sources):
                    contribution = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, user, f"contribute-{index}", f"contribution-{index}"),
                        f"贡献远古洞天 {source_id}",
                    )
                    assert contribution.code == "EVENT_CONTRIBUTION_RECORDED"
                replay = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "replay", "contribution-0"),
                    f"贡献远古洞天 {sources[0]}",
                )
                assert replay.data["idempotent_replay"] is True
                await runtime.close()

                clock.advance(hours=13)
                runtime = create_runtime(data_dir=Path(data_dir), clock=clock)
                settled = await runtime.adapters.dispatch(
                    adapter, _context(adapter, user, "settled"), f"远古洞天事件 {round_id}"
                )
                assert settled.data["status"] == "settled"
                claimed = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "claim", f"claim-{adapter}"),
                    f"领取远古洞天奖励 {round_id}",
                )
                assert claimed.data["reward"] == {"item.domain_core_fragment": 10}
                claim_replay = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "claim-replay", f"claim-{adapter}"),
                    f"领取远古洞天奖励 {round_id}",
                )
                assert claim_replay.data["idempotent_replay"] is True
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    inventory = connection.execute(
                        "SELECT inventory_json FROM players WHERE id=?", (player_id,)
                    ).fetchone()[0]
                    contribution_count = connection.execute(
                        "SELECT COUNT(*) FROM world_event_contribution_events WHERE round_id=? AND player_id=?",
                        (round_id, player_id),
                    ).fetchone()[0]
                assert json.loads(inventory) == {"item.domain_core_fragment": 10}
                assert contribution_count == 5
                await runtime.close()

    asyncio.run(run())


def test_ancient_domain_open_event_rejects_wrong_realm_and_unrelated_sources() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 25, 12, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=Path(data_dir), clock=clock)
            adapter, user = "qq.official", "ancient-event-denied"
            player_id = await _create_player(runtime, adapter, user)
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE players SET realm_key='nascent_soul', realm_layer=1 WHERE id=?",
                    (player_id,),
                )
                connection.execute(
                    "INSERT INTO operations(operation_id,operation_name,player_id,request_hash,result_json,created_at) VALUES('unrelated', 'party.settle', ?, '', '{}', ?)",
                    (player_id, clock.value.isoformat()),
                )
            denied = await runtime.adapters.dispatch(
                adapter,
                _context(adapter, user, "denied", "denied-contribution"),
                "贡献远古洞天 unrelated",
            )
            assert denied.code == "EVENT_CONTRIBUTION_SOURCE_INVALID"
            await runtime.close()

    asyncio.run(run())
