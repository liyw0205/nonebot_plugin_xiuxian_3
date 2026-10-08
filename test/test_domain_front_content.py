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
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle, ContentError
from nonebot_plugin_xiuxian_3.xiuxian.events.domain_front_rules import (
    activity_window,
    domain_front_definition,
    domain_front_definition_from_snapshot,
    domain_war_season_definition,
    domain_war_season_definition_from_snapshot,
)


ROOT = Path(__file__).parents[1]
ADAPTERS = ("qq.official", "onebot.v11")


class MutableClock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value

    def advance(self, **kwargs: int) -> None:
        self.value += timedelta(**kwargs)


def _copy_data(tmp_path: Path) -> Path:
    target = tmp_path / "data"
    shutil.copytree(ROOT / "data", target)
    return target


def _update_record(data_dir: Path, relative_path: str, key: str, **changes: object) -> None:
    path = data_dir / relative_path
    document = json.loads(path.read_text(encoding="utf-8"))
    record = next(item for item in document["records"] if item["key"] == key)
    record.update(changes)
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _update_domain_event(data_dir: Path, **changes: object) -> None:
    _update_record(data_dir, "事件/事件.json", "event.domain_front", **changes)


def _update_season(data_dir: Path, **changes: object) -> None:
    _update_record(data_dir, "事件/赛季.json", "season.domain_war", **changes)


def _insert_production_order(
    connection: sqlite3.Connection,
    *,
    player_id: int,
    order_id: str,
    recipe_key: str,
    realm_key: str,
    occurred_at: str,
) -> None:
    connection.execute(
        "INSERT INTO production_orders(order_id,player_id,operation_id,recipe_key,status,starts_at,ends_at,snapshot_json,created_at,updated_at) "
        "VALUES (?, ?, ?, ?, 'completed', ?, ?, ?, ?, ?)",
        (
            order_id,
            player_id,
            f"{order_id}:operation",
            recipe_key,
            occurred_at,
            occurred_at,
            json.dumps({"realm_key": realm_key}),
            occurred_at,
            occurred_at,
        ),
    )


def _update_reward(data_dir: Path, key: str, **changes: object) -> None:
    _update_record(data_dir, "奖励/奖励.json", key, **changes)


def _context(adapter: str, user: str, operation_id: str) -> CommandContext:
    return CommandContext(adapter=adapter, user_id=user, operation_id=operation_id)


async def _send(runtime, adapter: str, user: str, operation_id: str, command: str):
    return await runtime.adapters.dispatch(adapter, _context(adapter, user, operation_id), command)


async def _prepare_player(runtime, adapter: str, user: str, sect_id: str) -> int:
    created = await _send(runtime, adapter, user, f"{user}:create", "开始修仙")
    assert created.ok, (created.code, created.message)
    now = runtime.repository._now().isoformat()
    with sqlite3.connect(runtime.settings.database_path) as connection:
        player_id = int(
            connection.execute(
                "SELECT id FROM players WHERE platform=? AND platform_user_id=?",
                (adapter, user),
            ).fetchone()[0]
        )
        connection.execute(
            "UPDATE players SET stage='cultivator', realm_key='soul_transformation', realm_layer=1, "
            "domain_key='domain.fire', location_key='xuantian.domain_front', stamina=100, "
            "max_hp=100000, initiative=1000 WHERE id=?",
            (player_id,),
        )
        connection.execute(
            "INSERT INTO sects(sect_id,name,name_key,motto,leader_id,status,level,max_members,"
            "warehouse_capacity,construction,spirit_stones,sect_merit,warehouse_json,created_at,updated_at) "
            "VALUES (?, ?, ?, '', ?, 'active', 4, 20, 100, 0, 0, 0, '{}', ?, ?)",
            (sect_id, f"宗门{sect_id}", sect_id, player_id, now, now),
        )
        connection.execute(
            "INSERT INTO sect_members(sect_id,player_id,role,status,contribution,joined_at,last_action_at,created_at,updated_at) "
            "VALUES (?, ?, 'leader', 'active', 0, ?, ?, ?, ?)",
            (sect_id, player_id, now, now, now, now),
        )
    return player_id


def _reward_entries(item_quantity: int, merit_quantity: int) -> list[dict[str, object]]:
    return [
        {"kind": "item", "item_key": "item.domain_core_fragment", "quantity": item_quantity},
        {"kind": "resource", "resource_key": "world_merit", "quantity": merit_quantity},
    ]


def test_domain_front_point_content_and_operation_replay_on_both_adapters(tmp_path: Path) -> None:
    async def run() -> None:
        data_dir = _copy_data(tmp_path)
        _update_domain_event(
            data_dir,
            contribution={"battle": 100, "point_per_minute": 7, "point_minutes_min": 1, "point_minutes_max": 5},
            global_goal=10,
            personal_claim_threshold=10,
        )
        clock = MutableClock(datetime(2026, 9, 25, 12, 5, tzinfo=timezone.utc))
        runtime = create_runtime(data_dir=data_dir, clock=clock, adapters=ADAPTERS)
        try:
            for adapter in ADAPTERS:
                user = f"domain-point-{adapter}"
                await _prepare_player(runtime, adapter, user, f"sect-point-{adapter}")
                status = await _send(runtime, adapter, user, f"{user}:status", "领域前线")
                assert status.code == "DOMAIN_EVENT_STATUS"
                joined = await _send(runtime, adapter, user, f"{user}:join", "加入领域前线")
                assert joined.code == "DOMAIN_EVENT_JOINED"

                point = await _send(runtime, adapter, user, f"{user}:point", "占点领域前线 3")
                assert point.code == "DOMAIN_POINT_SETTLED"
                assert point.data["minutes"] == 3
                assert point.data["contribution"] == 21
                point_replay = await _send(runtime, adapter, user, f"{user}:point", "占点领域前线 3")
                assert point_replay.code == "DOMAIN_POINT_SETTLED"
                assert point_replay.data["idempotent_replay"] is True
                assert point_replay.data["point_id"] == point.data["point_id"]

                contributed = await _send(
                    runtime,
                    adapter,
                    user,
                    f"{user}:contribute",
                    f"贡献领域前线 占点 {user}:point",
                )
                assert contributed.code == "DOMAIN_EVENT_CONTRIBUTION_RECORDED"
                assert contributed.data["quantity"] == 21
                assert contributed.data["player_contribution"] == 21
                contribution_replay = await _send(
                    runtime,
                    adapter,
                    user,
                    f"{user}:contribute",
                    f"贡献领域前线 占点 {user}:point",
                )
                assert contribution_replay.data["idempotent_replay"] is True
                assert contribution_replay.data["player_contribution"] == 21
                reused_source = await _send(
                    runtime,
                    adapter,
                    user,
                    f"{user}:contribute-reused-source",
                    f"贡献领域前线 占点 {user}:point",
                )
                assert reused_source.code == "EVENT_CONTRIBUTION_SOURCE_INVALID"

                with sqlite3.connect(runtime.settings.database_path) as connection:
                    assert connection.execute(
                        "SELECT COUNT(*) FROM domain_front_point_operations WHERE player_id=?",
                        (_player_id(runtime, adapter, user),),
                    ).fetchone()[0] == 1
                    assert connection.execute(
                        "SELECT COUNT(*) FROM domain_front_contributions WHERE player_id=?",
                        (_player_id(runtime, adapter, user),),
                    ).fetchone()[0] == 1
                    assert connection.execute(
                        "SELECT stamina FROM players WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    ).fetchone()[0] == 80
        finally:
            await runtime.close()

    asyncio.run(run())


def test_domain_front_rule_snapshots_round_trip_and_respect_activity_anchor(tmp_path: Path) -> None:
    data_dir = _copy_data(tmp_path)
    _update_domain_event(
        data_dir,
        schedule={"activity_hours": 4, "anchor_hour": 3, "round_minutes": 30, "claim_days": 1},
    )
    bundle = ContentBundle.load(data_dir)
    event = domain_front_definition(bundle)
    season = domain_war_season_definition(bundle)

    assert domain_front_definition_from_snapshot(event.snapshot()).snapshot() == event.snapshot()
    assert domain_war_season_definition_from_snapshot(season.snapshot()).snapshot() == season.snapshot()
    _, starts_at, ends_at = activity_window(datetime(2026, 9, 25, 2, 30, tzinfo=timezone.utc), event)
    assert starts_at == datetime(2026, 9, 24, 23, 0, tzinfo=timezone.utc)
    assert ends_at == datetime(2026, 9, 25, 3, 0, tzinfo=timezone.utc)


def _player_id(runtime, adapter: str, user: str) -> int:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        return int(
            connection.execute(
                "SELECT id FROM players WHERE platform=? AND platform_user_id=?",
                (adapter, user),
            ).fetchone()[0]
        )


def test_domain_front_round_snapshot_survives_content_change_and_close(tmp_path: Path) -> None:
    async def run() -> None:
        data_dir = _copy_data(tmp_path)
        _update_domain_event(
            data_dir,
            contribution={"battle": 100, "point_per_minute": 10, "point_minutes_min": 1, "point_minutes_max": 3},
            global_goal=10,
            personal_claim_threshold=10,
        )
        _update_reward(data_dir, "reward.event.domain_front", entries=_reward_entries(3, 7))
        clock = MutableClock(datetime(2026, 9, 25, 12, 5, tzinfo=timezone.utc))
        runtime = create_runtime(data_dir=data_dir, clock=clock, adapters=ADAPTERS)
        try:
            for adapter in ADAPTERS:
                user = f"domain-round-freeze-{adapter}"
                await _prepare_player(runtime, adapter, user, f"sect-round-freeze-{adapter}")
                old_status = await _send(runtime, adapter, user, f"{user}:status-old", "领域前线")
                old_round = str(old_status.data["round_id"])
                assert (await _send(runtime, adapter, user, f"{user}:join-old", "加入领域前线")).ok
                assert (await _send(runtime, adapter, user, f"{user}:point-old", "占点领域前线 1")).ok
                assert (
                    await _send(
                        runtime,
                        adapter,
                        user,
                        f"{user}:contribute-old",
                        f"贡献领域前线 占点 {user}:point-old",
                    )
                ).ok

            _update_domain_event(
                data_dir,
                contribution={"battle": 100, "point_per_minute": 99, "point_minutes_min": 2, "point_minutes_max": 4},
                participation={"participant_cap": 20, "join_stamina_cost": 20, "sect_level_min": 5},
                global_goal=999,
                personal_claim_threshold=999,
            )
            _update_reward(data_dir, "reward.event.domain_front", entries=_reward_entries(9, 77))
            await runtime.close()
            runtime = create_runtime(data_dir=data_dir, clock=clock, adapters=ADAPTERS)

            for adapter in ADAPTERS:
                user = f"domain-round-freeze-{adapter}"
                old_point = await _send(runtime, adapter, user, f"{user}:point-old-replay", "占点领域前线 1")
                assert old_point.code == "DOMAIN_POINT_SETTLED"
                assert old_point.data["contribution"] == 10

            clock.advance(hours=4)

            for adapter in ADAPTERS:
                user = f"domain-round-freeze-{adapter}"
                new_status = await _send(runtime, adapter, user, f"{user}:status-new", "领域前线")
                new_round = str(new_status.data["round_id"])
                assert new_round != old_round
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    rows = connection.execute(
                        "SELECT round_id,target_quantity,rules_snapshot_json FROM domain_front_rounds "
                        "WHERE round_id IN (?, ?) ORDER BY round_id",
                        (old_round, new_round),
                    ).fetchall()
                assert len(rows) == 2
                snapshots = {str(row[0]): (int(row[1]), json.loads(row[2])) for row in rows}
                assert snapshots[old_round][0] == 10
                assert snapshots[new_round][0] == 999
                assert snapshots[old_round][1]["point_contribution_per_minute"] == 10
                assert snapshots[new_round][1]["point_contribution_per_minute"] == 99
                assert snapshots[new_round][1]["point_minutes_min"] == 2
                assert snapshots[old_round][1]["personal_claim_threshold"] == 10
                assert snapshots[new_round][1]["personal_claim_threshold"] == 999
                assert snapshots[old_round][1]["sect_level_min"] == 4
                assert snapshots[new_round][1]["sect_level_min"] == 5

                user = f"domain-round-freeze-{adapter}"
                denied_new_join = await _send(runtime, adapter, user, f"{user}:join-new-denied", "加入领域前线")
                assert denied_new_join.code == "DOMAIN_EVENT_REQUIREMENT_MISSING"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    assert connection.execute("SELECT stamina FROM players WHERE platform=? AND platform_user_id=?", (adapter, user)).fetchone()[0] == 80
                    assert connection.execute("SELECT COUNT(*) FROM domain_front_participants WHERE round_id=? AND player_id=?", (new_round, _player_id(runtime, adapter, user))).fetchone()[0] == 0
                    connection.execute("UPDATE sects SET level=5 WHERE sect_id=?", (f"sect-round-freeze-{adapter}",))
                joined_new = await _send(runtime, adapter, user, f"{user}:join-new-allowed", "加入领域前线")
                assert joined_new.code == "DOMAIN_EVENT_JOINED"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    assert connection.execute("SELECT stamina FROM players WHERE platform=? AND platform_user_id=?", (adapter, user)).fetchone()[0] == 60

            _update_domain_event(data_dir, status="closed")
            await runtime.close()
            runtime = create_runtime(data_dir=data_dir, clock=clock, adapters=ADAPTERS)
            for adapter in ADAPTERS:
                user = f"domain-round-freeze-{adapter}"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    before = (
                        int(connection.execute("SELECT stamina FROM players WHERE platform=? AND platform_user_id=?", (adapter, user)).fetchone()[0]),
                        int(connection.execute("SELECT COUNT(*) FROM domain_front_rounds").fetchone()[0]),
                        int(connection.execute("SELECT COUNT(*) FROM domain_front_participants").fetchone()[0]),
                        int(connection.execute("SELECT COUNT(*) FROM operations WHERE operation_name LIKE 'event.domain_front.%'").fetchone()[0]),
                    )
                denied = await _send(runtime, adapter, user, f"{user}:join-new", "加入领域前线")
                assert not denied.ok
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    after = (
                        int(connection.execute("SELECT stamina FROM players WHERE platform=? AND platform_user_id=?", (adapter, user)).fetchone()[0]),
                        int(connection.execute("SELECT COUNT(*) FROM domain_front_rounds").fetchone()[0]),
                        int(connection.execute("SELECT COUNT(*) FROM domain_front_participants").fetchone()[0]),
                        int(connection.execute("SELECT COUNT(*) FROM operations WHERE operation_name LIKE 'event.domain_front.%'").fetchone()[0]),
                    )
                assert after == before

                claimed = await _send(
                    runtime,
                    adapter,
                    user,
                    f"{user}:claim-old",
                    f"领取领域前线奖励 {old_round}",
                )
                assert claimed.code == "DOMAIN_EVENT_REWARD_CLAIMED"
                assert claimed.data["reward"] == {"item.domain_core_fragment": 3, "world_merit": 7}
                replay = await _send(
                    runtime,
                    adapter,
                    user,
                    f"{user}:claim-old",
                    f"领取领域前线奖励 {old_round}",
                )
                assert replay.data["idempotent_replay"] is True
                await runtime.close()
                runtime = create_runtime(data_dir=data_dir, clock=clock, adapters=ADAPTERS)
                recovered_replay = await _send(
                    runtime,
                    adapter,
                    user,
                    f"{user}:claim-old",
                    f"领取领域前线奖励 {old_round}",
                )
                assert recovered_replay.data["idempotent_replay"] is True
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    assert connection.execute("SELECT COUNT(*) FROM domain_front_claims WHERE round_id=? AND player_id=?", (old_round, _player_id(runtime, adapter, user))).fetchone()[0] == 1
                    assert connection.execute("SELECT world_merit FROM players WHERE platform=? AND platform_user_id=?", (adapter, user)).fetchone()[0] == 7
                    inventory = json.loads(connection.execute("SELECT inventory_json FROM players WHERE platform=? AND platform_user_id=?", (adapter, user)).fetchone()[0])
                assert inventory["item.domain_core_fragment"] == 3
        finally:
            await runtime.close()

    asyncio.run(run())


def test_domain_war_season_snapshot_survives_restart_and_content_change(tmp_path: Path) -> None:
    async def run() -> None:
        for adapter in ADAPTERS:
            data_dir = _copy_data(tmp_path / adapter)
            _update_reward(data_dir, "reward.season.domain_war.rank_1", entries=_reward_entries(13, 0)[:1])
            clock = MutableClock(datetime(2026, 9, 25, 12, 5, tzinfo=timezone.utc))
            runtime = create_runtime(data_dir=data_dir, clock=clock, adapters=(adapter,))
            try:
                user = f"domain-season-freeze-{adapter}"
                player_id = await _prepare_player(runtime, adapter, user, f"sect-season-freeze-{adapter}")
                season = await _send(runtime, adapter, user, f"{user}:season", "领域赛季")
                assert season.code == "DOMAIN_SEASON_RANKING"
                season_id = str(season.data["season_id"])
                season_ends_at = str(season.data["ends_at"])
                now = clock.value.isoformat()
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "INSERT INTO sect_contribution_events(sect_id,player_id,source_operation_id,quantity,occurred_at) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (f"sect-season-freeze-{adapter}", player_id, f"{user}:sect-source", 1, now),
                    )
                    _insert_production_order(
                        connection,
                        player_id=player_id,
                        order_id=f"{user}:recipe-source",
                        recipe_key="recipe.domain.test",
                        realm_key="qi_condensation",
                        occurred_at=now,
                    )
                    _insert_production_order(
                        connection,
                        player_id=player_id,
                        order_id=f"{user}:realm-source",
                        recipe_key="recipe.other.test",
                        realm_key="soul_transformation",
                        occurred_at=now,
                    )
                    _insert_production_order(
                        connection,
                        player_id=player_id,
                        order_id=f"{user}:unmatched-source",
                        recipe_key="recipe.other.unmatched",
                        realm_key="qi_condensation",
                        occurred_at=now,
                    )

                _update_season(
                    data_dir,
                    score_sources={
                        "domain_contribution": {"multiplier": 8},
                        "sect_contribution": {"multiplier": 9},
                        "soul_transformation_production": {
                            "multiplier": 11,
                            "recipe_key_prefix": "recipe.unrelated.",
                            "snapshot_realm_key": "qi_condensation",
                        },
                    },
                )
                _update_reward(data_dir, "reward.season.domain_war.rank_1", entries=_reward_entries(91, 0)[:1])
                await runtime.close()
                clock.value = datetime.fromisoformat(season_ends_at) + timedelta(minutes=5)
                runtime = create_runtime(data_dir=data_dir, clock=clock, adapters=(adapter,))

                frozen = await _send(runtime, adapter, user, f"{user}:freeze", f"领域赛季 {season_id}")
                assert frozen.code == "DOMAIN_SEASON_RANKING"
                assert frozen.data["status"] == "frozen"
                assert frozen.data["personal"]["score"] == 12
                assert frozen.data["personal"]["reward"] == {"item.domain_core_fragment": 13}
                claimed = await _send(
                    runtime,
                    adapter,
                    user,
                    f"{user}:claim",
                    f"领取领域赛季奖励 {season_id}",
                )
                assert claimed.code == "DOMAIN_SEASON_REWARD_CLAIMED"
                assert claimed.data["reward"] == {"item.domain_core_fragment": 13}
                assert claimed.data["reward_name"] == "领域战赛季第一名"
                replay = await _send(
                    runtime,
                    adapter,
                    user,
                    f"{user}:claim",
                    f"领取领域赛季奖励 {season_id}",
                )
                assert replay.data["idempotent_replay"] is True
                assert replay.data["reward_name"] == claimed.data["reward_name"]
                await runtime.close()
                runtime = create_runtime(data_dir=data_dir, clock=clock, adapters=(adapter,))
                recovered_replay = await _send(
                    runtime,
                    adapter,
                    user,
                    f"{user}:claim",
                    f"领取领域赛季奖励 {season_id}",
                )
                assert recovered_replay.data["idempotent_replay"] is True
                assert recovered_replay.data["reward_name"] == claimed.data["reward_name"]
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    row = connection.execute(
                        "SELECT rules_snapshot_json,snapshot_json FROM domain_war_seasons WHERE season_id=?",
                        (season_id,),
                    ).fetchone()
                    inventory = json.loads(connection.execute("SELECT inventory_json FROM players WHERE id=?", (player_id,)).fetchone()[0])
                    assert connection.execute("SELECT COUNT(*) FROM domain_war_claims WHERE season_id=? AND player_id=?", (season_id, player_id)).fetchone()[0] == 1
                assert inventory["item.domain_core_fragment"] == 13
                rules_snapshot = json.loads(row[0])
                frozen_snapshot = json.loads(row[1])
                assert rules_snapshot["score_sources"]["sect_contribution"]["multiplier"] == 2
                assert frozen_snapshot["rules"]["rank_rewards"][0]["reward"]["assets"]["item.domain_core_fragment"] == 13
            finally:
                await runtime.close()

    asyncio.run(run())


def test_domain_front_bad_reward_reference_fails_without_round_or_operation_writes(tmp_path: Path) -> None:
    async def run() -> None:
        data_dir = _copy_data(tmp_path)
        _update_domain_event(data_dir, reward_key="reward.event.domain_front.missing")
        bundle = ContentBundle.load(data_dir)
        with pytest.raises(ContentError):
            domain_front_definition(bundle)

        runtime = create_runtime(data_dir=data_dir, adapters=ADAPTERS)
        try:
            for adapter in ADAPTERS:
                user = f"domain-bad-reward-{adapter}"
                await _prepare_player(runtime, adapter, user, f"sect-bad-reward-{adapter}")
                result = await _send(runtime, adapter, user, f"{user}:status", "领域前线")
                assert not result.ok
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute("SELECT COUNT(*) FROM domain_front_rounds").fetchone()[0] == 0
                assert connection.execute("SELECT COUNT(*) FROM domain_front_participants").fetchone()[0] == 0
                assert connection.execute(
                    "SELECT COUNT(*) FROM operations WHERE operation_name LIKE 'event.domain_front.%'"
                ).fetchone()[0] == 0
        finally:
            await runtime.close()

    asyncio.run(run())
