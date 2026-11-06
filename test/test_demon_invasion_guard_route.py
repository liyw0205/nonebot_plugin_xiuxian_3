from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime


class MutableClock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value


def _context(adapter: str, user: str, request: str, operation: str = "") -> CommandContext:
    return CommandContext(
        adapter=adapter,
        user_id=user,
        request_id=request,
        operation_id=operation,
        can_write_assets=True,
    )


async def _prepare_player(runtime, adapter: str, user: str) -> int:
    created = await runtime.adapters.dispatch(
        adapter, _context(adapter, user, "create"), "开始修仙"
    )
    assert created.ok, created.message
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE players SET stage='cultivator', realm_key='nascent_soul', realm_layer=1 "
            "WHERE platform=? AND platform_user_id=?",
            (adapter, user),
        )
        return int(
            connection.execute(
                "SELECT id FROM players WHERE platform=? AND platform_user_id=?",
                (adapter, user),
            ).fetchone()[0]
        )


def _join_route_sect(
    database_path,
    now: datetime,
    player_id: int,
    route_key: str | None,
    *,
    sect_id: str,
    sect_name: str,
) -> None:
    now_text = now.isoformat()
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "INSERT INTO sects(sect_id, name, name_key, leader_id, status, level, "
            "max_members, warehouse_capacity, construction, spirit_stones, "
            "sect_merit, warehouse_json, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, 'active', 6, 80, 100, 0, 0, 1000, '{}', ?, ?)",
            (sect_id, sect_name, f"{sect_id}:name", player_id, now_text, now_text),
        )
        connection.execute(
            "INSERT INTO sect_members(sect_id, player_id, role, status, contribution, "
            "joined_at, last_action_at, created_at, updated_at) "
            "VALUES (?, ?, 'leader', 'active', 0, ?, ?, ?, ?)",
            (sect_id, player_id, now_text, now_text, now_text, now_text),
        )
        if route_key is not None:
            connection.execute(
                "INSERT INTO dao_route_state(sect_id, route_key, cycle_id, locked_until, "
                "updated_at) VALUES (?, ?, 'route:test', ?, ?)",
                (
                    sect_id,
                    route_key,
                    (now + timedelta(days=7)).isoformat(),
                    now_text,
                ),
            )


def _insert_transport_sources(runtime, adapter: str, user: str, count: int) -> list[str]:
    now = datetime(2026, 9, 23, 20, 5, tzinfo=timezone.utc).isoformat()
    with sqlite3.connect(runtime.settings.database_path) as connection:
        player_id = connection.execute(
            "SELECT id FROM players WHERE platform=? AND platform_user_id=?",
            (adapter, user),
        ).fetchone()[0]
        source_ids = []
        for index in range(count):
            source_id = f"transport-source-{adapter}-{user}-{index}"
            source_ids.append(source_id)
            connection.execute(
                """
                INSERT INTO livelihood_trade_routes(
                    route_id, player_id, operation_id, route_key, business_date, status,
                    source_location, destination_location, cargo_json, cargo_value,
                    starts_at, arrives_at, settled_at, stamina_cost, reward_stones,
                    snapshot_json, result_json, created_at, updated_at
                ) VALUES (?, ?, ?, 'route.new_town_outskirts', '2026-09-23', 'settled',
                    'xuantian.new_town', 'xuantian.outskirts', '{}', 10,
                    ?, ?, ?, 0, 0, '{}', '{}', ?, ?)
                """,
                (f"route-{source_id}", player_id, source_id, now, now, now, now, now),
            )
    return source_ids


def test_guard_route_bonus_applies_to_demon_invasion_contributions() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            clock = MutableClock(datetime(2026, 9, 23, 20, 5, tzinfo=timezone.utc))
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            adapter, user = "onebot.v11", "guard-route-bonus"
            player_id = await _prepare_player(runtime, adapter, user)
            _join_route_sect(
                runtime.settings.database_path,
                clock.value,
                player_id,
                "route.dao_settlement.guard_world",
                sect_id="sect-guard",
                sect_name="守界宗",
            )
            sources = _insert_transport_sources(runtime, adapter, user, 5)
            status = await runtime.adapters.dispatch(
                adapter, _context(adapter, user, "status"), "魔界入侵"
            )
            assert status.code == "EVENT_STATUS", status.message
            round_id = status.data["round_id"]

            contributed = await runtime.adapters.dispatch(
                adapter,
                _context(adapter, user, "contribute-0", "guard-contribute-0"),
                f"贡献魔界战场 运输 {sources[0]}",
            )
            assert contributed.code == "EVENT_CONTRIBUTION_RECORDED", contributed.message
            assert contributed.data["base_contribution"] == 10
            assert contributed.data["route_bonus_bp"] == 1000
            assert contributed.data["applied_contribution"] == 11
            assert contributed.data["player_contribution"] == 11
            assert "10 + 守界路线 10% = 11" in contributed.message
            with sqlite3.connect(runtime.settings.database_path) as connection:
                quantity, applied = connection.execute(
                    "SELECT quantity, applied_quantity FROM world_event_contribution_events "
                    "WHERE round_id=? AND player_id=? AND source_operation_id=?",
                    (round_id, player_id, sources[0]),
                ).fetchone()
            assert (quantity, applied) == (10, 11)

            for index, source in enumerate(sources[1:], start=1):
                contributed = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, f"contribute-{index}", f"guard-contribute-{index}"),
                    f"贡献魔界战场 运输 {source}",
                )
                assert contributed.data["applied_contribution"] == 11
                assert contributed.data["player_contribution"] == 11 * (index + 1)

            replay = await runtime.adapters.dispatch(
                adapter,
                _context(adapter, user, "contribute-replay", "guard-contribute-0"),
                f"贡献魔界战场 运输 {sources[0]}",
            )
            assert replay.code == "EVENT_CONTRIBUTION_RECORDED", replay.message
            assert replay.data["idempotent_replay"] is True
            assert replay.data["base_contribution"] == 10
            assert replay.data["route_bonus_bp"] == 1000
            assert replay.data["applied_contribution"] == 11
            assert replay.data["player_contribution"] == 11
            assert "10 + 守界路线 10% = 11" in replay.message
            with sqlite3.connect(runtime.settings.database_path) as connection:
                total = connection.execute(
                    "SELECT contribution FROM world_event_contributions "
                    "WHERE round_id=? AND player_id=?",
                    (round_id, player_id),
                ).fetchone()[0]
            assert total == 55

            clock.value = datetime(2026, 9, 23, 23, 6, tzinfo=timezone.utc)
            runtime.repository._clock = clock
            settled = await runtime.adapters.dispatch(
                adapter, _context(adapter, user, "settled"), f"魔界入侵 {round_id}"
            )
            assert settled.data["status"] == "settled"
            claim = await runtime.adapters.dispatch(
                adapter,
                _context(adapter, user, "claim", "guard-route-claim"),
                f"领取魔界入侵奖励 {round_id}",
            )
            assert claim.code == "EVENT_REWARD_CLAIMED", claim.message
            assert claim.data["reward"] == {
                "faction_reputation.demon": 20,
                "world_merit": 50,
            }
            await runtime.close()

            restarted = create_runtime(data_dir=data_dir, clock=clock)
            try:
                replay_after_restart = await restarted.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "contribute-restart", "guard-contribute-0"),
                    f"贡献魔界战场 运输 {sources[0]}",
                )
                assert replay_after_restart.data["idempotent_replay"] is True
                assert replay_after_restart.data["base_contribution"] == 10
                assert replay_after_restart.data["route_bonus_bp"] == 1000
                assert replay_after_restart.data["applied_contribution"] == 11
                assert replay_after_restart.data["player_contribution"] == 11
                status_after_restart = await restarted.adapters.dispatch(
                    adapter, _context(adapter, user, "status-after"), "魔界入侵"
                )
                assert status_after_restart.data["player_contribution"] == 55
            finally:
                await restarted.close()

    asyncio.run(run())


def test_guard_route_bonus_requires_an_active_sect_on_the_guard_world_route() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            clock = MutableClock(datetime(2026, 9, 23, 20, 5, tzinfo=timezone.utc))
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            adapter = "qq.official"
            scenarios = (
                ("guard-none", None, None),
                ("guard-no-route", "sect-no-route", None),
                ("guard-ascend", "sect-ascend", "route.dao_settlement.ascend"),
                ("guard-remain", "sect-remain", "route.dao_settlement.remain"),
            )
            for user, sect_id, route_key in scenarios:
                player_id = await _prepare_player(runtime, adapter, user)
                if sect_id is not None:
                    _join_route_sect(
                        runtime.settings.database_path,
                        clock.value,
                        player_id,
                        route_key,
                        sect_id=sect_id,
                        sect_name=f"{sect_id}-宗",
                    )
                source = _insert_transport_sources(runtime, adapter, user, 1)[0]
                await runtime.adapters.dispatch(
                    adapter, _context(adapter, user, f"{user}-status"), "魔界入侵"
                )
                contributed = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, f"{user}-contribute", f"{user}-contribute"),
                    f"贡献魔界战场 运输 {source}",
                )
                assert contributed.code == "EVENT_CONTRIBUTION_RECORDED", contributed.message
                assert contributed.data["base_contribution"] == 10, user
                assert contributed.data["route_bonus_bp"] == 0, user
                assert contributed.data["applied_contribution"] == 10, user
                assert contributed.data["player_contribution"] == 10, user
                assert "守界路线" not in contributed.message, user
            await runtime.close()

    asyncio.run(run())


def test_legacy_contribution_payload_replays_without_bonus_fields() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            clock = MutableClock(datetime(2026, 9, 23, 20, 5, tzinfo=timezone.utc))
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            adapter, user = "onebot.v11", "guard-legacy"
            player_id = await _prepare_player(runtime, adapter, user)
            _join_route_sect(
                runtime.settings.database_path,
                clock.value,
                player_id,
                "route.dao_settlement.guard_world",
                sect_id="sect-legacy",
                sect_name="旧案宗",
            )
            source = _insert_transport_sources(runtime, adapter, user, 1)[0]
            await runtime.adapters.dispatch(
                adapter, _context(adapter, user, "status"), "魔界入侵"
            )
            contributed = await runtime.adapters.dispatch(
                adapter,
                _context(adapter, user, "legacy-contribute", "guard-legacy-contribute"),
                f"贡献魔界战场 运输 {source}",
            )
            assert contributed.code == "EVENT_CONTRIBUTION_RECORDED", contributed.message
            with sqlite3.connect(runtime.settings.database_path) as connection:
                payload = json.loads(
                    connection.execute(
                        "SELECT result_json FROM operations WHERE operation_id=?",
                        ("guard-legacy-contribute",),
                    ).fetchone()[0]
                )
                payload.pop("base_contribution")
                payload.pop("route_bonus_bp")
                payload.pop("applied_contribution")
                connection.execute(
                    "UPDATE operations SET result_json=? WHERE operation_id=?",
                    (
                        json.dumps(payload, ensure_ascii=False, sort_keys=True),
                        "guard-legacy-contribute",
                    ),
                )
            replay = await runtime.adapters.dispatch(
                adapter,
                _context(adapter, user, "legacy-replay", "guard-legacy-contribute"),
                f"贡献魔界战场 运输 {source}",
            )
            assert replay.code == "EVENT_CONTRIBUTION_RECORDED", replay.message
            assert replay.data["idempotent_replay"] is True
            assert replay.data["base_contribution"] == 0
            assert replay.data["route_bonus_bp"] == 0
            assert replay.data["applied_contribution"] == 0
            assert replay.data["player_contribution"] == 11
            assert "守界路线" not in replay.message
            with sqlite3.connect(runtime.settings.database_path) as connection:
                applied = connection.execute(
                    "SELECT applied_quantity FROM world_event_contribution_events "
                    "WHERE player_id=? AND source_operation_id=?",
                    (player_id, source),
                ).fetchone()[0]
            assert applied == 11
            await runtime.close()

    asyncio.run(run())
