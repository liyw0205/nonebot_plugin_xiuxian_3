from __future__ import annotations

import asyncio
import json
import shutil
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


def _update_record(path: Path, key: str, update) -> None:
    document = json.loads(path.read_text(encoding="utf-8"))
    update(next(record for record in document["records"] if record["key"] == key))
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _configure_beast_event(data_dir: Path, *, target: int, quantity: int, threshold: int, reward: int) -> None:
    _update_record(
        data_dir / "事件" / "事件.json",
        "event.beast_trade",
        lambda event: event["public_event"].update(
            {
                "target_quantity": target,
                "contributions": {
                    **event["public_event"]["contributions"],
                    "trade": {
                        "source": "completed_cross_realm_trade",
                        "quantity": quantity,
                        "trade_keys": ["trade.xuantian_to_beast"],
                    },
                },
                "claim": {"min_contribution": threshold, "reward_key": "reward.event.beast_trade"},
            }
        ),
    )

    def change_reward(record) -> None:
        for entry in record["entries"]:
            if entry["kind"] in {"item", "reputation"}:
                entry["quantity"] = reward

    _update_record(data_dir / "奖励" / "奖励.json", "reward.event.beast_trade", change_reward)


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
                assert "reward_snapshot" not in status.data
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
                assert claim.data["reward"] == {"faction_reputation.beast": 50, "item.mat.array_sand": 10}
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
                assert json.loads(inventory) == {"item.mat.array_sand": 10}
                assert json.loads(faction)["beast"] == 250
                await runtime.close()

    asyncio.run(run())


def test_beast_blood_contributions_use_operation_id_as_the_consumption_source() -> None:
    async def run() -> None:
        for adapter in ("qq.official", "onebot.v11"):
            clock = MutableClock(datetime(2026, 9, 21, 12, tzinfo=timezone.utc))
            with TemporaryDirectory() as data_dir:
                runtime = create_runtime(data_dir=Path(data_dir), clock=clock)
                user = f"beast-blood-{adapter}"
                player_id = await _create_player(runtime, adapter, user)
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE players SET inventory_json=? WHERE id=?",
                        (json.dumps({"item.beast_blood": 2}), player_id),
                    )

                first = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "blood-first", f"{adapter}-blood-first"),
                    "贡献妖界贸易 妖血",
                )
                replay = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "blood-first-replay", f"{adapter}-blood-first"),
                    "贡献妖界贸易 妖血",
                )
                second = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "blood-second", f"{adapter}-blood-second"),
                    "贡献妖界贸易 妖血",
                )

                assert first.data["player_contribution"] == 5
                assert replay.data["idempotent_replay"] is True
                assert second.data["player_contribution"] == 10
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    inventory = connection.execute(
                        "SELECT inventory_json FROM players WHERE id=?", (player_id,)
                    ).fetchone()[0]
                    sources = connection.execute(
                        "SELECT source_operation_id FROM world_event_contribution_events "
                        "WHERE round_id=? ORDER BY id",
                        (first.data["round_id"],),
                    ).fetchall()
                assert json.loads(inventory) == {}
                assert [row[0] for row in sources] == [
                    f"{adapter}-blood-first",
                    f"{adapter}-blood-second",
                ]
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
                    "INSERT INTO parties(party_id, party_type, status, leader_id, location_key, confirmation_deadline, distribution_key, created_at, updated_at) VALUES ('boundary-event-party', 'boundary_realm', 'ready', ?, 'cave.boundary_realm', ?, 'contribution', ?, ?)",
                    (player_id, now, now, now),
                )
                connection.execute(
                    "INSERT INTO party_battle_sessions(battle_id, party_id, start_operation_id, battle_type, enemy_key, location_key, status, round_no, action_sequence, starts_at, turn_deadline, snapshot_json, state_json, result_json, created_at, updated_at) VALUES ('boundary-event-battle', 'boundary-event-party', 'boundary-source-operation', 'pve.party', 'enemy.boundary_watcher', 'cave.boundary_realm', 'settled', 3, 3, ?, ?, '{}', '{}', ?, ?, ?)",
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
                    "INSERT INTO parties(party_id, party_type, status, leader_id, location_key, confirmation_deadline, distribution_key, created_at, updated_at) VALUES ('boundary-event-party-ob', 'boundary_realm', 'ready', ?, 'cave.boundary_realm', ?, 'contribution', ?, ?)",
                    (player_id, now, now, now),
                )
                connection.execute(
                    "INSERT INTO party_battle_sessions(battle_id, party_id, start_operation_id, battle_type, enemy_key, location_key, status, round_no, action_sequence, starts_at, turn_deadline, snapshot_json, state_json, result_json, created_at, updated_at) VALUES ('boundary-event-battle-ob', 'boundary-event-party-ob', 'boundary-source-operation-ob', 'pve.party', 'enemy.boundary_watcher', 'cave.boundary_realm', 'settled', 3, 3, ?, ?, '{}', '{}', ?, ?, ?)",
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


def test_beast_event_freezes_config_across_restart_and_reads_new_config_for_next_round() -> None:
    async def run() -> None:
        for adapter in ("qq.official", "onebot.v11"):
            with TemporaryDirectory() as temp:
                data_dir = Path(temp) / "data"
                shutil.copytree(Path(__file__).parents[1] / "data", data_dir)
                _configure_beast_event(data_dir, target=10, quantity=10, threshold=10, reward=7)
                clock = MutableClock(datetime(2026, 9, 21, 12, tzinfo=timezone.utc))
                runtime = create_runtime(data_dir=data_dir, adapters=(adapter,), clock=clock)
                user = f"beast-freeze-{adapter}"
                player_id = await _create_player(runtime, adapter, user)
                source_id = _insert_trade_sources(runtime, player_id, adapter, count=1)[0]
                status = await runtime.adapters.dispatch(adapter, _context(adapter, user, "status"), "妖界贸易事件")
                round_id = status.data["round_id"]
                await runtime.close()

                _configure_beast_event(data_dir, target=900, quantity=90, threshold=90, reward=70)
                recovered = create_runtime(data_dir=data_dir, adapters=(adapter,), clock=clock)
                try:
                    recovered_status = await recovered.adapters.dispatch(
                        adapter, _context(adapter, user, "recovered-status"), f"妖界贸易事件 {round_id}"
                    )
                    assert recovered_status.data["target_quantity"] == 10
                    assert recovered_status.data["minimum_contribution"] == 10
                    contributed = await recovered.adapters.dispatch(
                        adapter,
                        _context(adapter, user, "contribute", f"{adapter}-frozen-contribution"),
                        f"贡献妖界贸易 贸易 {source_id}",
                    )
                    assert contributed.data["player_contribution"] == 10
                    clock.advance(days=7, minutes=1)
                    settled = await recovered.adapters.dispatch(
                        adapter, _context(adapter, user, "settled"), f"妖界贸易事件 {round_id}"
                    )
                    assert settled.data["status"] == "settled"
                    claimed = await recovered.adapters.dispatch(
                        adapter,
                        _context(adapter, user, "claim", f"{adapter}-frozen-claim"),
                        f"领取妖界贸易奖励 {round_id}",
                    )
                    assert claimed.data["reward"] == {
                        "faction_reputation.beast": 7,
                        "item.mat.array_sand": 7,
                    }
                    next_round = await recovered.adapters.dispatch(
                        adapter, _context(adapter, user, "next-round"), "妖界贸易事件"
                    )
                    assert next_round.data["round_id"] != round_id
                    assert next_round.data["target_quantity"] == 900
                    assert next_round.data["minimum_contribution"] == 90
                    with sqlite3.connect(recovered.settings.database_path) as connection:
                        inventory, reputation = connection.execute(
                            "SELECT inventory_json, faction_reputation_json FROM players WHERE id=?", (player_id,)
                        ).fetchone()
                    assert json.loads(inventory) == {"item.beast_blood": 1, "item.mat.array_sand": 7}
                    assert json.loads(reputation)["beast"] == 207
                finally:
                    await recovered.close()

    asyncio.run(run())


def test_invalid_public_event_reward_reference_rolls_back_round_creation() -> None:
    async def run() -> None:
        for adapter in ("qq.official", "onebot.v11"):
            with TemporaryDirectory() as temp:
                data_dir = Path(temp) / "data"
                shutil.copytree(Path(__file__).parents[1] / "data", data_dir)

                def break_reward(record) -> None:
                    next(entry for entry in record["entries"] if entry["kind"] == "item")["item_key"] = "item.missing_event_reward"

                _update_record(data_dir / "奖励" / "奖励.json", "reward.event.beast_trade", break_reward)
                runtime = create_runtime(
                    data_dir=data_dir,
                    adapters=(adapter,),
                    clock=lambda: datetime(2026, 9, 21, 12, tzinfo=timezone.utc),
                )
                user = f"beast-invalid-reward-{adapter}"
                player_id = await _create_player(runtime, adapter, user)
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    before = connection.execute(
                        "SELECT spirit_stones, inventory_json, faction_reputation_json FROM players WHERE id=?",
                        (player_id,),
                    ).fetchone()
                rejected = await runtime.adapters.dispatch(
                    adapter, _context(adapter, user, "invalid-status"), "妖界贸易事件"
                )
                assert rejected.code == "PERSISTENCE_ERROR"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    after = connection.execute(
                        "SELECT spirit_stones, inventory_json, faction_reputation_json FROM players WHERE id=?",
                        (player_id,),
                    ).fetchone()
                    assert connection.execute("SELECT COUNT(*) FROM world_event_rounds").fetchone()[0] == 0
                    assert connection.execute("SELECT COUNT(*) FROM world_event_contributions").fetchone()[0] == 0
                    assert connection.execute("SELECT COUNT(*) FROM world_event_claims").fetchone()[0] == 0
                assert after == before
                await runtime.close()

    asyncio.run(run())


def test_unregistered_trade_source_rolls_back_public_event_round_creation() -> None:
    async def run() -> None:
        for adapter in ("qq.official", "onebot.v11"):
            with TemporaryDirectory() as temp:
                data_dir = Path(temp) / "data"
                shutil.copytree(Path(__file__).parents[1] / "data", data_dir)

                def add_unknown_trade(record) -> None:
                    record["public_event"]["contributions"]["trade"]["trade_keys"].append(
                        "trade.not_open_at_any_location"
                    )

                _update_record(data_dir / "事件" / "事件.json", "event.beast_trade", add_unknown_trade)
                runtime = create_runtime(
                    data_dir=data_dir,
                    adapters=(adapter,),
                    clock=lambda: datetime(2026, 9, 21, 12, tzinfo=timezone.utc),
                )
                user = f"beast-invalid-trade-{adapter}"
                await _create_player(runtime, adapter, user)
                rejected = await runtime.adapters.dispatch(
                    adapter, _context(adapter, user, "invalid-trade-status"), "妖界贸易事件"
                )
                assert rejected.code == "PERSISTENCE_ERROR"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    assert connection.execute("SELECT COUNT(*) FROM world_event_rounds").fetchone()[0] == 0
                    assert connection.execute("SELECT COUNT(*) FROM world_event_contributions").fetchone()[0] == 0
                await runtime.close()

    asyncio.run(run())
