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
    return CommandContext(adapter=adapter, user_id=user, request_id=request, operation_id=operation, can_write_assets=True)


async def _create_player(runtime, adapter: str, user: str) -> int:
    created = await runtime.adapters.dispatch(adapter, _context(adapter, user, f"create-{user}"), "开始修仙")
    assert created.ok
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE players SET stage='cultivator', realm_key='nascent_soul', realm_layer=1, location_key='beast.three_realms_trade_port', inventory_json=?, faction_reputation_json=? WHERE platform=? AND platform_user_id=?",
            (json.dumps({"item.beast_blood": 1}), json.dumps({"beast": 200}), adapter, user),
        )
        return int(connection.execute("SELECT id FROM players WHERE platform=? AND platform_user_id=?", (adapter, user)).fetchone()[0])


def _insert_trade_sources(runtime, player_id: int, prefix: str, count: int = 3) -> list[str]:
    now = "2026-09-21T12:00:00+00:00"
    with sqlite3.connect(runtime.settings.database_path) as connection:
        source_ids = []
        for index in range(count):
            source_id = f"{prefix}-trade-{index}"
            source_ids.append(source_id)
            connection.execute(
                "INSERT INTO cross_realm_trades(trade_id, player_id, trade_key, week_start, location_key, status, input_json, currency_cost, output_json, binding_expires_at, snapshot_json, operation_id, created_at, updated_at) VALUES (?, ?, 'trade.xuantian_to_beast', '2026-09-21', 'beast.ten_thousand_hills', 'completed', '{}', 0, '{}', ?, '{}', ?, ?, ?)",
                (f"trade-{source_id}", player_id, now, source_id, now, now),
            )
    return source_ids


def test_beast_trade_event_projects_sources_and_claims_on_both_adapters() -> None:
    async def run() -> None:
        for adapter in ("qq.official", "onebot.v11"):
            clock = MutableClock(datetime(2026, 9, 21, 12, tzinfo=timezone.utc))
            with TemporaryDirectory() as data_dir:
                runtime = create_runtime(data_dir=Path(data_dir), clock=clock)
                user = f"beast-event-{adapter}"
                player_id = await _create_player(runtime, adapter, user)
                sources = _insert_trade_sources(runtime, player_id, adapter)
                status = await runtime.adapters.dispatch(adapter, _context(adapter, user, "status"), "妖界贸易事件")
                assert status.code == "EVENT_STATUS"
                round_id = status.data["round_id"]
                for index, source_id in enumerate(sources):
                    result = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, user, f"trade-{index}", f"{adapter}-trade-{index}"),
                        f"贡献妖界贸易 贸易 {source_id}",
                    )
                    assert result.code == "EVENT_CONTRIBUTION_RECORDED"
                replay = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "trade-replay", f"{adapter}-trade-0"),
                    f"贡献妖界贸易 贸易 {sources[0]}",
                )
                assert replay.data["idempotent_replay"] is True
                blood = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "blood", f"{adapter}-blood"),
                    "贡献妖界贸易 妖血",
                )
                assert blood.data["player_contribution"] == 35
                clock.advance(days=7, hours=1)
                settled = await runtime.adapters.dispatch(adapter, _context(adapter, user, "settled"), f"妖界贸易事件 {round_id}")
                assert settled.data["status"] == "settled"
                claim = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "claim", f"{adapter}-claim"),
                    f"领取妖界贸易奖励 {round_id}",
                )
                assert claim.data["reward"] == {"faction_reputation.beast": 50, "item.material.array_sand": 10}
                claim_replay = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "claim-replay", f"{adapter}-claim"),
                    f"领取妖界贸易奖励 {round_id}",
                )
                assert claim_replay.data["idempotent_replay"] is True
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    inventory, faction = connection.execute(
                        "SELECT inventory_json, faction_reputation_json FROM players WHERE id=?", (player_id,)
                    ).fetchone()
                assert json.loads(inventory) == {"item.material.array_sand": 10}
                assert json.loads(faction)["beast"] == 250
                await runtime.close()

    asyncio.run(run())


def test_boundary_rift_event_recovers_round_and_claims_settled_party_source() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 21, 12, 30, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=Path(data_dir), clock=clock)
            adapter, user = "qq.official", "boundary-event"
            player_id = await _create_player(runtime, adapter, user)
            now = clock.value.isoformat()
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "INSERT INTO parties(party_id, party_type, status, leader_id, location_key, confirmation_deadline, distribution_key, content_version, rule_version, created_at, updated_at) VALUES ('boundary-event-party', 'boundary_realm', 'ready', ?, 'cave.boundary_realm', ?, 'contribution', 'content-0.3', 'social-0.3.0', ?, ?)",
                    (player_id, now, now, now),
                )
                connection.execute(
                    "INSERT INTO party_battle_sessions(battle_id, party_id, start_operation_id, battle_type, enemy_key, location_key, status, round_no, action_sequence, starts_at, turn_deadline, snapshot_json, state_json, result_json, content_version, rule_version, created_at, updated_at) VALUES ('boundary-event-battle', 'boundary-event-party', 'boundary-source-operation', 'pve.party', 'enemy.boundary_watcher', 'cave.boundary_realm', 'settled', 3, 3, ?, ?, '{}', '{}', ?, 'content-0.3', 'combat-0.3.0', ?, ?)",
                    (now, now, json.dumps({"outcome": "won"}), now, now),
                )
                connection.execute(
                    "INSERT INTO party_battle_members(battle_id, party_id, player_id, role, asset_lock_status, snapshot_json, created_at, updated_at) VALUES ('boundary-event-battle', 'boundary-event-party', ?, 'leader', 'released', '{}', ?, ?)",
                    (player_id, now, now),
                )
            status = await runtime.adapters.dispatch(adapter, _context(adapter, user, "status"), "界隙裂痕")
            assert status.code == "EVENT_STATUS"
            round_id = status.data["round_id"]
            contribution = await runtime.adapters.dispatch(
                adapter,
                _context(adapter, user, "contribute", "boundary-contribution"),
                "贡献界隙裂痕 boundary-source-operation",
            )
            assert contribution.code == "EVENT_CONTRIBUTION_RECORDED"
            assert contribution.data["player_contribution"] == 50
            # The event is recovered and settled by a later read, without a scheduler process.
            clock.advance(hours=2, minutes=1)
            settled = await runtime.adapters.dispatch(adapter, _context(adapter, user, "settled"), f"界隙裂痕 {round_id}")
            assert settled.data["status"] == "settled"
            claimed = await runtime.adapters.dispatch(
                adapter,
                _context(adapter, user, "claim", "boundary-claim"),
                f"领取界隙裂痕奖励 {round_id}",
            )
            assert claimed.data["reward"] == {"item.soul_crystal": 2, "world_merit": 30}
            await runtime.close()

    asyncio.run(run())


def test_boundary_rift_event_claims_on_onebot_v11() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 21, 12, 30, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=Path(data_dir), clock=clock)
            adapter, user = "onebot.v11", "boundary-event-onebot"
            player_id = await _create_player(runtime, adapter, user)
            now = clock.value.isoformat()
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "INSERT INTO parties(party_id, party_type, status, leader_id, location_key, confirmation_deadline, distribution_key, content_version, rule_version, created_at, updated_at) VALUES ('boundary-event-party-ob', 'boundary_realm', 'ready', ?, 'cave.boundary_realm', ?, 'contribution', 'content-0.3', 'social-0.3.0', ?, ?)",
                    (player_id, now, now, now),
                )
                connection.execute(
                    "INSERT INTO party_battle_sessions(battle_id, party_id, start_operation_id, battle_type, enemy_key, location_key, status, round_no, action_sequence, starts_at, turn_deadline, snapshot_json, state_json, result_json, content_version, rule_version, created_at, updated_at) VALUES ('boundary-event-battle-ob', 'boundary-event-party-ob', 'boundary-source-operation-ob', 'pve.party', 'enemy.boundary_watcher', 'cave.boundary_realm', 'settled', 3, 3, ?, ?, '{}', '{}', ?, 'content-0.3', 'combat-0.3.0', ?, ?)",
                    (now, now, json.dumps({"outcome": "won"}), now, now),
                )
                connection.execute(
                    "INSERT INTO party_battle_members(battle_id, party_id, player_id, role, asset_lock_status, snapshot_json, created_at, updated_at) VALUES ('boundary-event-battle-ob', 'boundary-event-party-ob', ?, 'leader', 'released', '{}', ?, ?)",
                    (player_id, now, now),
                )
            status = await runtime.adapters.dispatch(adapter, _context(adapter, user, "status"), "界隙事件")
            round_id = status.data["round_id"]
            recorded = await runtime.adapters.dispatch(
                adapter,
                _context(adapter, user, "contribute", "boundary-onebot-contribution"),
                "贡献界隙裂痕 boundary-source-operation-ob",
            )
            assert recorded.code == "EVENT_CONTRIBUTION_RECORDED"
            clock.advance(hours=2, minutes=1)
            claimed = await runtime.adapters.dispatch(
                adapter,
                _context(adapter, user, "claim", "boundary-onebot-claim"),
                f"领取界隙裂痕奖励 {round_id}",
            )
            assert claimed.code == "EVENT_REWARD_CLAIMED"
            await runtime.close()

    asyncio.run(run())
