from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime


def _context(adapter: str, user: str, request: str, operation: str = "") -> CommandContext:
    return CommandContext(adapter=adapter, user_id=user, request_id=request, operation_id=operation, can_write_assets=True)


def _insert_transport_sources(runtime, adapter: str, user: str, count: int) -> list[str]:
    now = datetime(2026, 9, 23, 20, 5, tzinfo=timezone.utc).isoformat()
    with sqlite3.connect(runtime.settings.database_path) as connection:
        player_id = connection.execute(
            "SELECT id FROM players WHERE platform=? AND platform_user_id=?", (adapter, user)
        ).fetchone()[0]
        source_ids = []
        for index in range(count):
            source_id = f"transport-source-{adapter}-{index}"
            source_ids.append(source_id)
            connection.execute(
                """
                INSERT INTO livelihood_trade_routes(
                    route_id, player_id, operation_id, route_key, business_date, status,
                    source_location, destination_location, cargo_json, cargo_value,
                    starts_at, arrives_at, settled_at, stamina_cost, reward_stones,
                    snapshot_json, result_json, created_at, updated_at
                ) VALUES (?, ?, ?, 'route.town.v0.1', '2026-09-23', 'settled',
                    'xuantian.new_town', 'xuantian.outskirts', '{}', 10,
                    ?, ?, ?, 0, 0, '{}', '{}', ?, ?)
                """,
                (f"route-{source_id}", player_id, source_id, now, now, now, now, now),
            )
    return source_ids


def test_demon_invasion_projects_settled_sources_and_claims_on_qq_and_onebot() -> None:
    async def run() -> None:
        for adapter in ("qq.official", "onebot.v11"):
            with TemporaryDirectory() as data_dir:
                runtime = create_runtime(
                    data_dir=Path(data_dir) / adapter,
                    clock=lambda: datetime(2026, 9, 23, 20, 5, tzinfo=timezone.utc),
                )
                user = f"demon-event-{adapter}"
                created = await runtime.adapters.dispatch(
                    adapter, _context(adapter, user, "create"), "开始修仙"
                )
                assert created.ok
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE players SET stage='cultivator', realm_key='nascent_soul', realm_layer=1 WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    )
                sources = _insert_transport_sources(runtime, adapter, user, 5)

                status = await runtime.adapters.dispatch(
                    adapter, _context(adapter, user, "status"), "魔界入侵"
                )
                assert status.code == "EVENT_STATUS"
                assert status.data["event_key"] == "event.demon_invasion"
                round_id = status.data["round_id"]

                for index, source_id in enumerate(sources):
                    contributed = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, user, f"contribute-{index}", f"demon-contribute-{index}"),
                        f"贡献魔界战场 运输 {source_id}",
                    )
                    assert contributed.code == "EVENT_CONTRIBUTION_RECORDED"
                    assert contributed.data["player_contribution"] == (index + 1) * 10
                duplicate_source = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "duplicate-source", "demon-contribute-duplicate"),
                    f"贡献魔界战场 运输 {sources[0]}",
                )
                assert duplicate_source.code == "EVENT_CONTRIBUTION_SOURCE_INVALID"

                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE players SET world_merit=0, faction_reputation_json='{}' WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    )
                clock = datetime(2026, 9, 23, 23, 6, tzinfo=timezone.utc)
                runtime.repository._clock = lambda: clock
                settled = await runtime.adapters.dispatch(
                    adapter, _context(adapter, user, "settled"), f"魔界入侵 {round_id}"
                )
                assert settled.data["status"] == "settled"
                claim = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "claim", "demon-event-claim"),
                    f"领取魔界入侵奖励 {round_id}",
                )
                assert claim.code == "EVENT_REWARD_CLAIMED"
                assert claim.data["reward"] == {"faction_reputation.demon": 20, "world_merit": 50}
                replay = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "claim-replay", "demon-event-claim"),
                    f"领取魔界入侵奖励 {round_id}",
                )
                assert replay.data["idempotent_replay"] is True
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    merit, reputation = connection.execute(
                        "SELECT world_merit, faction_reputation_json FROM players WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    ).fetchone()
                assert merit == 50
                assert json.loads(reputation)["demon"] == 20
                await runtime.close()

    asyncio.run(run())


def test_demon_invasion_rejects_invalid_sources_and_enforces_claim_boundaries() -> None:
    async def run() -> None:
        for adapter in ("qq.official", "onebot.v11"):
            with TemporaryDirectory() as data_dir:
                runtime = create_runtime(
                    data_dir=Path(data_dir) / adapter,
                    clock=lambda: datetime(2026, 9, 23, 20, 5, tzinfo=timezone.utc),
                )
                user = f"demon-boundary-{adapter}"
                created = await runtime.adapters.dispatch(
                    adapter, _context(adapter, user, "create"), "开始修仙"
                )
                assert created.ok
                sources = _insert_transport_sources(runtime, adapter, user, 3)

                # A mortal cannot enter the event, even when a settled source exists.
                denied = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "realm-denied", "demon-boundary-denied"),
                    f"贡献魔界战场 运输 {sources[0]}",
                )
                assert denied.code == "EVENT_CONTRIBUTION_SOURCE_INVALID"

                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE players SET stage='cultivator', realm_key='nascent_soul', realm_layer=1 WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    )

                missing = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "missing-source", "demon-boundary-missing"),
                    "贡献魔界战场 运输 does-not-exist",
                )
                assert missing.code == "EVENT_CONTRIBUTION_SOURCE_INVALID"
                first = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "first-source", "demon-boundary-first"),
                    f"贡献魔界战场 运输 {sources[0]}",
                )
                assert first.code == "EVENT_CONTRIBUTION_RECORDED"
                implicit_source = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "implicit-source", "demon-boundary-implicit"),
                    "贡献魔界战场 运输",
                )
                assert implicit_source.code == "EVENT_CONTRIBUTION_RECORDED"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    player_id = connection.execute(
                        "SELECT id FROM players WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    ).fetchone()[0]
                    connection.execute(
                        "INSERT INTO production_facility_slots(slot_key, location_key, facility_kind, slot_index, owner_type, owner_id, status, created_at, updated_at) VALUES (?, 'cave.mist_grotto_2', 'alchemy', 99, 'personal', ?, 'active', ?, ?)",
                        (f"demon-maintenance-{adapter}", str(player_id), "2026-09-23T20:05:00+00:00", "2026-09-23T20:05:00+00:00"),
                    )
                    slot_id = connection.execute(
                        "SELECT id FROM production_facility_slots WHERE slot_key=?",
                        (f"demon-maintenance-{adapter}",),
                    ).fetchone()[0]
                    connection.execute(
                        "INSERT INTO production_facility_maintenance(slot_id, business_date, owner_type, owner_id, fee, paid, status, operation_id, created_at) VALUES (?, '2026-09-23', 'personal', ?, 100, 1, 'inactive', ?, ?)",
                        (slot_id, str(player_id), f"demon-maintenance-source-{adapter}", "2026-09-23T20:05:00+00:00"),
                    )
                inactive_maintenance = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "inactive-maintenance", "demon-boundary-inactive-maintenance"),
                    f"贡献魔界战场 维修 demon-maintenance-source-{adapter}",
                )
                assert inactive_maintenance.code == "EVENT_CONTRIBUTION_SOURCE_INVALID"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE production_facility_maintenance SET status='active' WHERE operation_id=?",
                        (f"demon-maintenance-source-{adapter}",),
                    )
                active_maintenance = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "active-maintenance", "demon-boundary-active-maintenance"),
                    f"贡献魔界战场 维修 demon-maintenance-source-{adapter}",
                )
                assert active_maintenance.code == "EVENT_CONTRIBUTION_RECORDED"
                conflicting = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "conflicting-source", "demon-boundary-first"),
                    f"贡献魔界战场 运输 {sources[1]}",
                )
                assert conflicting.code == "OPERATION_CONFLICT"
                duplicate = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "duplicate-source", "demon-boundary-duplicate"),
                    f"贡献魔界战场 运输 {sources[0]}",
                )
                assert duplicate.code == "EVENT_CONTRIBUTION_SOURCE_INVALID"

                status = await runtime.adapters.dispatch(
                    adapter, _context(adapter, user, "status"), "魔界入侵"
                )
                round_id = status.data["round_id"]
                runtime.repository._clock = lambda: datetime(
                    2026, 9, 23, 23, 6, tzinfo=timezone.utc
                )
                settled = await runtime.adapters.dispatch(
                    adapter, _context(adapter, user, "settled"), f"魔界入侵 {round_id}"
                )
                assert settled.data["status"] == "settled"
                insufficient = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "insufficient-claim", "demon-boundary-insufficient"),
                    f"领取魔界入侵奖励 {round_id}",
                )
                assert insufficient.code == "EVENT_CONTRIBUTION_INSUFFICIENT"

                with sqlite3.connect(runtime.settings.database_path) as connection:
                    player_id = connection.execute(
                        "SELECT id FROM players WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    ).fetchone()[0]
                    connection.execute(
                        "UPDATE world_event_contributions SET contribution=50 WHERE round_id=? AND player_id=?",
                        (round_id, player_id),
                    )
                    connection.execute(
                        "UPDATE world_event_rounds SET total_contribution=50 WHERE round_id=?",
                        (round_id,),
                    )
                claimed = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "claim", "demon-boundary-claim"),
                    f"领取魔界入侵奖励 {round_id}",
                )
                assert claimed.code == "EVENT_REWARD_CLAIMED"
                duplicate_claim = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "duplicate-claim", "demon-boundary-claim-2"),
                    f"领取魔界入侵奖励 {round_id}",
                )
                assert duplicate_claim.code == "EVENT_REWARD_ALREADY_CLAIMED"

                expired_user = f"demon-expired-{adapter}"
                assert (
                    await runtime.adapters.dispatch(
                        adapter, _context(adapter, expired_user, "expired-create"), "开始修仙"
                    )
                ).ok
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    expired_player_id = connection.execute(
                        "SELECT id FROM players WHERE platform=? AND platform_user_id=?",
                        (adapter, expired_user),
                    ).fetchone()[0]
                    connection.execute(
                        "INSERT INTO world_event_contributions(round_id, player_id, contribution, updated_at) VALUES (?, ?, 50, ?)",
                        (round_id, expired_player_id, datetime(2026, 9, 23, 23, 6, tzinfo=timezone.utc).isoformat()),
                    )
                runtime.repository._clock = lambda: datetime(
                    2026, 9, 25, 0, 0, tzinfo=timezone.utc
                )
                expired = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, expired_user, "expired-claim", "demon-boundary-expired"),
                    f"领取魔界入侵奖励 {round_id}",
                )
                assert expired.code == "EVENT_REWARD_EXPIRED"
                await runtime.close()

    asyncio.run(run())


def test_personal_facility_maintenance_is_player_scoped_and_idempotent_on_qq_and_onebot() -> None:
    async def run() -> None:
        for adapter in ("qq.official", "onebot.v11"):
            with TemporaryDirectory() as data_dir:
                runtime = create_runtime(
                    data_dir=Path(data_dir) / adapter,
                    clock=lambda: datetime(2026, 9, 23, 20, 5, tzinfo=timezone.utc),
                )
                user = f"facility-maintenance-{adapter}"
                created = await runtime.adapters.dispatch(adapter, _context(adapter, user, "create"), "开始修仙")
                assert created.ok
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE players SET stage='cultivator', realm_key='golden_core', realm_layer=1, location_key='cave.mist_grotto_2', spirit_stones=250 WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    )

                claimed = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "claim", "facility-claim"),
                    "认领设施槽位 炼丹房",
                )
                assert claimed.code == "FACILITY_SLOT_CLAIMED"
                maintained = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "maintain", "facility-maintain"),
                    "维护设施",
                )
                assert maintained.code == "FACILITY_MAINTENANCE_SETTLED"
                assert maintained.data["paid_count"] == 1
                source_id = maintained.data["records"][0]["maintenance_operation_id"]
                replay = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "maintain-replay", "facility-maintain"),
                    "维护设施",
                )
                assert replay.data["idempotent_replay"] is True
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    stones = connection.execute(
                        "SELECT spirit_stones FROM players WHERE platform=? AND platform_user_id=?", (adapter, user)
                    ).fetchone()[0]
                assert stones == 150

                runtime.repository._clock = lambda: datetime(2026, 9, 24, 20, 5, tzinfo=timezone.utc)
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE players SET spirit_stones=0 WHERE platform=? AND platform_user_id=?", (adapter, user)
                    )
                unpaid = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "maintain-unpaid", "facility-maintain-next"),
                    "维护设施",
                )
                assert unpaid.code == "FACILITY_MAINTENANCE_SETTLED"
                assert unpaid.data["inactive_count"] == 1
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    status = connection.execute(
                        "SELECT status FROM production_facility_maintenance WHERE operation_id=?", (source_id,)
                    ).fetchone()[0]
                    slot_status = connection.execute(
                        "SELECT status FROM production_facility_slots WHERE slot_key='facility.alchemy_room.1'"
                    ).fetchone()[0]
                assert status == "active"
                assert slot_status == "inactive"
                await runtime.close()

    asyncio.run(run())
