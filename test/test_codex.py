from __future__ import annotations

import asyncio
import json
import shutil
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from combat_fixtures import BALANCED_QUALIFICATION, equip_damage_weapon

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.content import bundled_content
from nonebot_plugin_xiuxian_3.xiuxian.exploration.rules import battle_roll_bp
from nonebot_plugin_xiuxian_3.xiuxian.specials.codex_migration import ensure_codex_schema
from nonebot_plugin_xiuxian_3.xiuxian.specials.codex_projection import record_codex_discovery


class MutableClock:
    def __init__(self, value: datetime):
        self.value = value

    def __call__(self) -> datetime:
        return self.value

    def advance(self, **kwargs: int) -> None:
        self.value += timedelta(**kwargs)


async def _send(runtime, adapter: str, user: str, operation_id: str, text: str):
    context = CommandContext(adapter=adapter, user_id=user, operation_id=operation_id)
    return await runtime.adapters.dispatch(adapter, context, text)


def _seed_codex_entries(runtime, adapter: str, user: str, operation_prefix: str, keys: tuple[str, ...]) -> None:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        player = connection.execute(
            "SELECT id FROM players WHERE platform=? AND platform_user_id=?", (adapter, user)
        ).fetchone()
        assert player is not None
        connection.execute("BEGIN IMMEDIATE")
        for index, key in enumerate(keys):
            record_codex_discovery(
                connection,
                player_id=int(player[0]),
                entry_key=key,
                operation_id=f"{operation_prefix}-{index}",
                occurred_at="2026-09-27T00:00:00+00:00",
                snapshot={"instance_key": "instance.example"},
            )
        connection.execute("COMMIT")


async def _enter_path(runtime, adapter: str, user: str, prefix: str, path: str) -> None:
    for index, command in enumerate(
        (
            "开始修仙",
            "寻仙问道",
            "完成引导 阅读",
            "前往近郊",
            "完成引导 采集",
            "完成引导 炼丹",
            f"选择道途 {path}",
        )
    ):
        result = await _send(runtime, adapter, user, f"{prefix}-{index}", command)
        assert result.ok, (command, result.code, result.message)


async def _advance_to_qi_sensing_l2(runtime, clock: MutableClock, adapter: str, user: str, prefix: str) -> None:
    for index in range(4):
        started = await _send(runtime, adapter, user, f"{prefix}-cultivate-{index}", "开始修炼")
        assert started.code == "CULTIVATION_STARTED"
        clock.advance(minutes=10)
        settled = await _send(runtime, adapter, user, f"{prefix}-settle-{index}", "结算修炼")
        assert settled.code == "CULTIVATION_SETTLED"
        if settled.data["cultivation"] >= 80:
            promoted = await _send(runtime, adapter, user, f"{prefix}-promote", "晋升境界")
            assert promoted.code == "REALM_LAYER_ADVANCED"
            return
    raise AssertionError("normal cultivation did not reach qi sensing layer 2")


def _prepare_cloud_city_player(runtime, adapter: str, user: str) -> None:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            """
            UPDATE players SET stage='cultivator', realm_key='golden_core', realm_layer=1,
                location_key='xuantian.new_town', stamina=100, stamina_max=100,
                energy=30, energy_max=30, subprofession_key='mining', max_hp=50000,
                initiative=50000, qualification_json=?
            WHERE platform=? AND platform_user_id=?
            """,
            (
                json.dumps(BALANCED_QUALIFICATION),
                adapter,
                user,
            ),
        )
    equip_damage_weapon(runtime, adapter, user, 500)


def _set_local_reputation(runtime, adapter: str, user: str, local_json: str) -> None:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        player = connection.execute(
            "SELECT id FROM players WHERE platform=? AND platform_user_id=?", (adapter, user)
        ).fetchone()
        assert player is not None
        connection.execute(
            """
            INSERT INTO player_reputations(player_id, local_json, service_reputation, updated_at)
            VALUES (?, ?, 0, '2026-09-27T00:00:00+00:00')
            ON CONFLICT(player_id) DO UPDATE SET local_json=excluded.local_json
            """,
            (int(player[0]), local_json),
        )


def test_cloud_city_codex_unlocks_and_settles_guild_order_on_both_adapters() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 27, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            for adapter, user in (("qq.official", "codex-cloud-qq"), ("onebot.v11", "codex-cloud-ob")):
                prefix = adapter.replace(".", "-")
                created = await _send(runtime, adapter, user, f"{prefix}-create", "开始修仙")
                assert created.code == "PLAYER_CREATED"
                _prepare_cloud_city_player(runtime, adapter, user)

                for index, (destination, duration) in enumerate((("云城", 3), ("云铁矿区", 2))):
                    started = await _send(
                        runtime, adapter, user, f"{prefix}-travel-{index}", f"前往 {destination}"
                    )
                    assert started.code == "TRAVEL_STARTED"
                    clock.advance(minutes=duration)
                    arrived = await _send(
                        runtime, adapter, user, f"{prefix}-arrive-{index}", "结算移动"
                    )
                    assert arrived.code == "TRAVEL_COMPLETED"
                    if index == 0:
                        not_ready = await _send(
                            runtime,
                            adapter,
                            user,
                            f"{prefix}-codex-incomplete",
                            "领取图鉴里程碑 codex.cloud_city.discovery_3",
                        )
                        assert not_ready.code == "CODEX_MILESTONE_NOT_READY"

                hidden = await _send(
                    runtime, adapter, user, f"{prefix}-guild-hidden", "接取委托 云铁供应"
                )
                assert hidden.code == "LIVELIHOOD_CONTENT_CLOSED"
                encounter = next(
                    f"{prefix}-cloud-mine-{index}"
                    for index in range(1000)
                    if battle_roll_bp(f"{prefix}-cloud-mine-{index}:battle") < 3000
                )
                started = await _send(
                    runtime,
                    adapter,
                    user,
                    encounter,
                    "开始探索 云铁矿区采集",
                )
                assert started.code == "EXPLORATION_STARTED"
                clock.advance(minutes=2)
                settled = await _send(
                    runtime, adapter, user, f"{prefix}-mine-settle", "结算探索"
                )
                assert settled.code == "EXPLORATION_SETTLED"
                assert settled.data["battle_outcome"] == "won"
                assert settled.data["result"]["item.material.cloud_iron"] >= 1

                overview = await _send(runtime, adapter, user, f"{prefix}-codex", "我的图鉴")
                discovered = {item["entry_key"] for item in overview.data["entries"]}
                assert {
                    "codex.place.cloud_city",
                    "codex.material.cloud_iron",
                    "codex.creature.cloud_beast",
                } <= discovered
                claim_context = CommandContext(
                    adapter=adapter,
                    user_id=user,
                    operation_id=f"{prefix}-cloud-codex-claim",
                )
                claimed = await runtime.adapters.dispatch(
                    adapter,
                    claim_context,
                    "领取图鉴里程碑 codex.cloud_city.discovery_3",
                )
                replayed = await runtime.adapters.dispatch(
                    adapter,
                    claim_context,
                    "领取图鉴里程碑 codex.cloud_city.discovery_3",
                )
                assert claimed.code == "CODEX_MILESTONE_CLAIMED"
                assert claimed.data["reward"] == {"local.xuantian.cloud_city": 8}
                assert claimed.data["unlocks"] == ["commission.cloud_city.extra_order"]
                assert "云城名望 +8" in claimed.message
                assert "local.xuantian.cloud_city" not in claimed.message
                assert replayed.data["idempotent_replay"] is True

                offers = await _send(runtime, adapter, user, f"{prefix}-guild-list", "城镇委托")
                guild_order = next(
                    item for item in offers.data["commissions"]
                    if item["commission_key"] == "guild.cloud_iron_supply"
                )
                assert guild_order["stock_total"] == 80
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    player = connection.execute(
                        "SELECT id, inventory_json FROM players WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    ).fetchone()
                    inventory = json.loads(player[1])
                    inventory["item.material.cloud_iron"] = 5
                    connection.execute(
                        "UPDATE players SET inventory_json=? WHERE id=?",
                        (json.dumps(inventory, ensure_ascii=False), player[0]),
                    )
                accepted = await _send(
                    runtime, adapter, user, f"{prefix}-guild-accept", "接取委托 云铁供应"
                )
                assert accepted.code == "COMMISSION_ACCEPTED"
                delivered = await _send(
                    runtime, adapter, user, f"{prefix}-guild-deliver", "交付委托 云铁供应"
                )
                replay = await _send(
                    runtime, adapter, user, f"{prefix}-guild-deliver", "交付委托 云铁供应"
                )
                assert delivered.code == "COMMISSION_DELIVERED"
                assert delivered.data["reward_stones"] == 180
                assert delivered.data["local_reputation"] == 6
                assert replay.data["idempotent_replay"] is True
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    local_json, service_reputation = connection.execute(
                        "SELECT local_json, service_reputation FROM player_reputations WHERE player_id=?",
                        (player[0],),
                    ).fetchone()
                assert json.loads(local_json)["local.xuantian.cloud_city"] == 14
                assert service_reputation == 2
            await runtime.close()

    asyncio.run(run())


def test_codex_place_milestone_claim_unlocks_extra_commission_on_both_adapters() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 27, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            for adapter, user in (("qq.official", "codex-qq"), ("onebot.v11", "codex-onebot")):
                prefix = adapter.replace(".", "-")
                await _enter_path(runtime, adapter, user, prefix, "体修")
                before = await _send(runtime, adapter, user, f"{prefix}-codex-before", "我的图鉴 地点")
                assert before.code == "CODEX_OVERVIEW"
                assert {item["entry_key"] for item in before.data["entries"]} == {
                    "codex.place.new_town",
                    "codex.place.outskirts",
                }
                not_ready = await _send(
                    runtime,
                    adapter,
                    user,
                    f"{prefix}-claim-before",
                    "领取图鉴里程碑 1",
                )
                assert not_ready.code == "CODEX_MILESTONE_NOT_READY"

                await _advance_to_qi_sensing_l2(runtime, clock, adapter, user, prefix)
                spirit_field = await _send(runtime, adapter, user, f"{prefix}-spirit-field", "前往灵泉谷")
                assert spirit_field.code == "TRAVEL_COMPLETED"
                overview = await _send(runtime, adapter, user, f"{prefix}-codex-ready", "我的图鉴 地点")
                assert {item["entry_key"] for item in overview.data["entries"]} == {
                    "codex.place.new_town",
                    "codex.place.outskirts",
                    "codex.place.spirit_field",
                }
                honors = await _send(runtime, adapter, user, f"{prefix}-honors", "功业录")
                assert honors.code == "HONOR_STATUS", (honors.code, honors.message, honors.data)
                codex_achievement = next(
                    item
                    for item in honors.data["achievements"]
                    if item["achievement_key"] == "achievement.codex_5"
                )
                assert codex_achievement["state"] == "claimable"
                achievement_context = CommandContext(
                    adapter=adapter, user_id=user, operation_id=f"{prefix}-claim-codex-achievement"
                )
                achievement = await runtime.adapters.dispatch(adapter, achievement_context, "领取功业 4")
                achievement_replay = await runtime.adapters.dispatch(
                    adapter, achievement_context, "领取功业 4"
                )
                assert achievement.code == "ACHIEVEMENT_CLAIMED"
                assert achievement.data["achievement_key"] == "achievement.codex_5"
                assert achievement_replay.data["idempotent_replay"] is True
                offers_before = await _send(runtime, adapter, user, f"{prefix}-offers-before", "城镇委托")
                assert len(offers_before.data["commissions"]) == 3
                assert all(
                    item["commission_key"] != "town_commission.spirit_leaf"
                    for item in offers_before.data["commissions"]
                )
                locked_offer = await _send(
                    runtime,
                    adapter,
                    user,
                    f"{prefix}-extra-offer-locked",
                    "接取委托 灵泉谷灵叶收集",
                )
                assert locked_offer.code == "LIVELIHOOD_CONTENT_CLOSED"

                claim_context = CommandContext(
                    adapter=adapter, user_id=user, operation_id=f"{prefix}-claim-place"
                )
                claimed = await runtime.adapters.dispatch(adapter, claim_context, "领取图鉴里程碑 1")
                replayed = await runtime.adapters.dispatch(adapter, claim_context, "领取图鉴里程碑 1")
                assert claimed.code == "CODEX_MILESTONE_CLAIMED"
                assert claimed.data["reward"] == {"local.xuantian.new_town": 5}
                assert replayed.data["idempotent_replay"] is True
                duplicate = await _send(
                    runtime,
                    adapter,
                    user,
                    f"{prefix}-claim-place-again",
                    "领取图鉴里程碑 1",
                )
                assert duplicate.code == "CODEX_MILESTONE_ALREADY_CLAIMED"

                offers_after = await _send(runtime, adapter, user, f"{prefix}-offers-after", "城镇委托")
                assert len(offers_after.data["commissions"]) == 4
                assert any(
                    item["commission_key"] == "town_commission.spirit_leaf"
                    for item in offers_after.data["commissions"]
                )
                accepted_offer = await _send(
                    runtime,
                    adapter,
                    user,
                    f"{prefix}-extra-offer-accept",
                    "接取委托 灵泉谷灵叶收集",
                )
                assert accepted_offer.code == "COMMISSION_ACCEPTED"
            await runtime.close()

    asyncio.run(run())


def test_arena_match_records_both_publicly_observed_paths_in_codex() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 27, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            await _enter_path(runtime, "qq.official", "codex-observer", "observer", "体修")
            await _enter_path(runtime, "onebot.v11", "codex-opponent", "opponent", "法修")
            published = await _send(
                runtime, "onebot.v11", "codex-opponent", "opponent-publish", "发布竞技场快照"
            )
            assert published.code == "ARENA_SNAPSHOT_PUBLISHED"
            clock.advance(minutes=31)
            match = await _send(
                runtime,
                "qq.official",
                "codex-observer",
                "observer-challenge",
                f"挑战竞技场 {published.data['snapshot_id']}",
            )
            assert match.code == "ARENA_MATCH_SETTLED"

            observer_codex = await _send(
                runtime, "qq.official", "codex-observer", "observer-codex", "我的图鉴 道途"
            )
            opponent_codex = await _send(
                runtime, "onebot.v11", "codex-opponent", "opponent-codex", "我的图鉴 道途"
            )
            observer_paths = {item["entry_key"] for item in observer_codex.data["entries"]}
            opponent_paths = {item["entry_key"] for item in opponent_codex.data["entries"]}
            assert {"codex.path.body", "codex.path.spell"} <= observer_paths
            assert {"codex.path.body", "codex.path.spell"} <= opponent_paths
            await runtime.close()

    asyncio.run(run())


def test_place_codex_keys_come_from_location_content_on_both_adapters() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 27, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            destinations = (
                ("demon.abyss_market", "demon.fallen_ruins", "魔渊集市", "codex.place.demon_market"),
                ("beast.ten_thousand_hills", "xuantian.floating_boat", "万兽山", "codex.place.beast_hills"),
            )
            for adapter in ("qq.official", "onebot.v11"):
                user = f"codex-{adapter}"
                await _send(runtime, adapter, user, f"{adapter}-create", "开始修仙")
                for index, (destination, source, label, entry_key) in enumerate(destinations):
                    with sqlite3.connect(runtime.settings.database_path) as connection:
                        connection.execute(
                            """
                            UPDATE players SET stage='cultivator', realm_key='nascent_soul', realm_layer=1,
                                location_key=?, stamina=100, stamina_max=100, spirit_stones=10000,
                                faction_reputation_json=?
                            WHERE platform=? AND platform_user_id=?
                            """,
                            (source, json.dumps({"demon": 200, "beast": 200}), adapter, user),
                        )
                    prefix = f"{adapter}-place-{index}"
                    started = await _send(runtime, adapter, user, f"{prefix}-start", f"前往 {label}")
                    assert started.code == "TRAVEL_STARTED"
                    clock.advance(minutes=5)
                    arrived = await _send(runtime, adapter, user, f"{prefix}-arrive", "结算移动")
                    assert arrived.code == "TRAVEL_COMPLETED"
                    with sqlite3.connect(runtime.settings.database_path) as connection:
                        entry = connection.execute(
                            "SELECT category, first_seen_operation_id FROM codex_entries WHERE entry_key=? "
                            "AND player_id=(SELECT id FROM players WHERE platform=? AND platform_user_id=?)",
                            (entry_key, adapter, user),
                        ).fetchone()
                    assert entry == ("place", f"{prefix}-arrive")
            await runtime.close()

    asyncio.run(run())


def test_domain_codex_entries_are_configured_and_confirmed_on_both_adapters() -> None:
    async def run() -> None:
        content = bundled_content()
        paths = content.list("path", include_locked=False)
        assert len(paths) == 6
        for path in paths:
            entry_key = path.get("codex_entry_key")
            assert isinstance(entry_key, str)
            assert content.get("codex_entry", entry_key, include_locked=False) is not None

        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            for adapter in ("qq.official", "onebot.v11"):
                user = f"domain-codex-{adapter}"
                await _send(runtime, adapter, user, f"{adapter}-create", "开始修仙")
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE players SET realm_key='soul_transformation', realm_layer=3, "
                        "path_key='body', domain_level=5, spirit_stones=12000, inventory_json=? "
                        "WHERE platform=? AND platform_user_id=?",
                        (json.dumps({"item.domain_core": 1}), adapter, user),
                    )
                selected = await _send(
                    runtime, adapter, user, f"{adapter}-choose-domain", "选择领域 体修"
                )
                assert selected.code == "DOMAIN_SELECTION_PENDING"
                confirmed = await _send(
                    runtime, adapter, user, f"{adapter}-confirm-domain", "确认领域"
                )
                replay = await _send(
                    runtime, adapter, user, f"{adapter}-confirm-domain", "确认领域"
                )
                assert confirmed.code == "DOMAIN_SELECTED"
                assert replay.data["idempotent_replay"] is True
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    entry = connection.execute(
                        "SELECT entry_key, first_seen_operation_id FROM codex_entries "
                        "WHERE player_id=(SELECT id FROM players WHERE platform=? AND platform_user_id=?)",
                        (adapter, user),
                    ).fetchone()
                assert entry == ("codex.domain.mountain_body", f"{adapter}-confirm-domain")
            await runtime.close()

    asyncio.run(run())


def test_domain_survey_codex_reward_uses_json_and_replays_after_restart_on_both_adapters() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            keys = (
                "codex.domain.ancient_domain",
                "codex.domain.ancestral_hall",
                "codex.domain.frontline",
            )
            for adapter in ("qq.official", "onebot.v11"):
                user = f"domain-survey-{adapter}"
                prefix = adapter.replace(".", "-")
                created = await _send(runtime, adapter, user, f"{prefix}-create", "开始修仙")
                assert created.code == "PLAYER_CREATED"
                _seed_codex_entries(runtime, adapter, user, prefix, keys[:2])

                before = await _send(runtime, adapter, user, f"{prefix}-before", "我的图鉴")
                milestone = next(
                    item
                    for item in before.data["milestones"]
                    if item["milestone_key"] == "codex.domain.frontier_records_3"
                )
                assert (milestone["discovered_count"], milestone["required_count"]) == (2, 3)
                assert milestone["ready"] is False
                not_ready = await _send(
                    runtime,
                    adapter,
                    user,
                    f"{prefix}-not-ready",
                    "领取图鉴里程碑 codex.domain.frontier_records_3",
                )
                assert not_ready.code == "CODEX_MILESTONE_NOT_READY"

                _seed_codex_entries(runtime, adapter, user, f"{prefix}-final", keys[2:])
                ready = await _send(runtime, adapter, user, f"{prefix}-ready", "我的图鉴")
                milestone = next(
                    item
                    for item in ready.data["milestones"]
                    if item["milestone_key"] == "codex.domain.frontier_records_3"
                )
                assert milestone["ready"] is True
                claim = await _send(
                    runtime,
                    adapter,
                    user,
                    f"{prefix}-claim",
                    "领取图鉴里程碑 codex.domain.frontier_records_3",
                )
                assert claim.code == "CODEX_MILESTONE_CLAIMED"
                assert claim.data["reward"] == {}
                assert claim.data["unlocks"] == [
                    "encyclopedia.domain_tactics",
                    "display.domain_observatory",
                ]
                assert "六域战策" in claim.message
                assert "观域居所陈设" in claim.message
                assert "版本" not in claim.message
                conflict = await _send(
                    runtime,
                    adapter,
                    user,
                    f"{prefix}-claim",
                    "领取图鉴里程碑 codex.xuantian.place_3",
                )
                assert conflict.code == "OPERATION_CONFLICT"
                duplicate = await _send(
                    runtime,
                    adapter,
                    user,
                    f"{prefix}-claim-again",
                    "领取图鉴里程碑 codex.domain.frontier_records_3",
                )
                assert duplicate.code == "CODEX_MILESTONE_ALREADY_CLAIMED"

                with sqlite3.connect(runtime.settings.database_path) as connection:
                    entry_columns = {
                        row[1] for row in connection.execute("PRAGMA table_info(codex_entries)")
                    }
                    claim_columns = {
                        row[1]
                        for row in connection.execute("PRAGMA table_info(codex_milestone_claims)")
                    }
                    payload = connection.execute(
                        "SELECT payload_json FROM codex_entries WHERE entry_key=? AND player_id=("
                        "SELECT id FROM players WHERE platform=? AND platform_user_id=?)",
                        (keys[0], adapter, user),
                    ).fetchone()[0]
                    assert "version" not in payload
                    assert connection.execute(
                        "SELECT COUNT(*) FROM codex_milestone_claims WHERE milestone_key=? AND player_id=("
                        "SELECT id FROM players WHERE platform=? AND platform_user_id=?)",
                        ("codex.domain.frontier_records_3", adapter, user),
                    ).fetchone()[0] == 1
            await runtime.close()

            runtime = create_runtime(data_dir=data_dir)
            for adapter in ("qq.official", "onebot.v11"):
                user = f"domain-survey-{adapter}"
                prefix = adapter.replace(".", "-")
                replay = await _send(
                    runtime,
                    adapter,
                    user,
                    f"{prefix}-claim",
                    "领取图鉴里程碑 codex.domain.frontier_records_3",
                )
                assert replay.code == "CODEX_MILESTONE_CLAIMED"
                assert replay.data["idempotent_replay"] is True
                overview = await _send(runtime, adapter, user, f"{prefix}-after-restart", "我的图鉴")
                milestone = next(
                    item
                    for item in overview.data["milestones"]
                    if item["milestone_key"] == "codex.domain.frontier_records_3"
                )
                assert milestone["claimed"] is True
            await runtime.close()

    asyncio.run(run())


def test_codex_schema_uses_current_tables_without_version_columns() -> None:
    with sqlite3.connect(":memory:") as connection:
        connection.execute("CREATE TABLE players(id INTEGER PRIMARY KEY)")
        connection.execute(
            """CREATE TABLE codex_entries(
                id INTEGER PRIMARY KEY, player_id INTEGER NOT NULL, entry_key TEXT NOT NULL,
                category TEXT NOT NULL, first_seen_operation_id TEXT NOT NULL,
                first_seen_at TEXT NOT NULL, payload_json TEXT NOT NULL,
                last_seen_at TEXT NOT NULL, UNIQUE(player_id, entry_key))"""
        )
        ensure_codex_schema(connection)
        ensure_codex_schema(connection)

        entry_columns = {row[1] for row in connection.execute("PRAGMA table_info(codex_entries)")}
        claim_columns = {row[1] for row in connection.execute("PRAGMA table_info(codex_milestone_claims)")}
        assert connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='index' AND name='idx_codex_milestone_claims_player'"
        ).fetchone()


def test_codex_collection_requirements_and_names_follow_custom_content_json() -> None:
    async def run() -> None:
        with TemporaryDirectory() as temp_dir:
            source_data = Path(__file__).parents[1] / "data"
            content_dir = Path(temp_dir) / "data"
            shutil.copytree(source_data, content_dir)

            milestones_path = content_dir / "图鉴" / "里程碑.json"
            milestones = json.loads(milestones_path.read_text(encoding="utf-8"))
            target = next(
                row
                for row in milestones["records"]
                if row["key"] == "codex.domain.frontier_records_3"
            )
            target["entry_keys"] = ["codex.domain.frontline"]
            milestones_path.write_text(
                json.dumps(milestones, ensure_ascii=False, indent=2), encoding="utf-8"
            )

            unlocks_path = content_dir / "图鉴" / "解锁.json"
            unlocks = json.loads(unlocks_path.read_text(encoding="utf-8"))
            next(row for row in unlocks["records"] if row["key"] == "encyclopedia.domain_tactics")[
                "name"
            ] = "山河战策"
            unlocks_path.write_text(json.dumps(unlocks, ensure_ascii=False, indent=2), encoding="utf-8")

            runtime = create_runtime(data_dir=content_dir)
            adapter = "qq.official"
            user = "codex-custom-content"
            await _send(runtime, adapter, user, "custom-create", "开始修仙")
            _seed_codex_entries(
                runtime,
                adapter,
                user,
                "custom-discovery",
                ("codex.domain.frontline",),
            )
            overview = await _send(runtime, adapter, user, "custom-overview", "我的图鉴")
            milestone = next(
                item
                for item in overview.data["milestones"]
                if item["milestone_key"] == "codex.domain.frontier_records_3"
            )
            assert milestone["ready"] is True
            assert milestone["required_count"] == 1
            claimed = await _send(
                runtime,
                adapter,
                user,
                "custom-claim",
                "领取图鉴里程碑 codex.domain.frontier_records_3",
            )
            assert claimed.code == "CODEX_MILESTONE_CLAIMED"
            assert "山河战策" in claimed.message
            await runtime.close()

    asyncio.run(run())


def test_codex_reputation_reward_uses_location_cap_and_replays_after_content_closes() -> None:
    async def run() -> None:
        with TemporaryDirectory() as temp_dir:
            content_dir = Path(temp_dir) / "data"
            shutil.copytree(Path(__file__).parents[1] / "data", content_dir)
            milestones_path = content_dir / "图鉴" / "里程碑.json"
            milestones = json.loads(milestones_path.read_text(encoding="utf-8"))
            target = next(row for row in milestones["records"] if row["key"] == "codex.xuantian.place_3")
            target["name"] = "新镇三则"
            target["reward"]["amount"] = 20
            milestones_path.write_text(
                json.dumps(milestones, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            locations_path = content_dir / "地图" / "地点.json"
            locations = json.loads(locations_path.read_text(encoding="utf-8"))
            next(row for row in locations["records"] if row["key"] == "xuantian.new_town")[
                "local_reputation_maximum"
            ] = 50
            locations_path.write_text(
                json.dumps(locations, ensure_ascii=False, indent=2), encoding="utf-8"
            )

            runtime = create_runtime(data_dir=content_dir)
            entries = (
                "codex.place.new_town",
                "codex.place.outskirts",
                "codex.place.spirit_field",
            )
            for adapter in ("qq.official", "onebot.v11"):
                user = f"codex-cap-{adapter}"
                prefix = adapter.replace(".", "-")
                await _send(runtime, adapter, user, f"{prefix}-create", "开始修仙")
                _seed_codex_entries(runtime, adapter, user, prefix, entries)
                _set_local_reputation(runtime, adapter, user, '{"local.xuantian.new_town":48}')
                claim = await _send(
                    runtime,
                    adapter,
                    user,
                    f"{prefix}-claim",
                    "领取图鉴里程碑 codex.xuantian.place_3",
                )
                assert claim.code == "CODEX_MILESTONE_CLAIMED", claim
                assert claim.data["reward"] == {"local.xuantian.new_town": 2}
                assert "新镇三则" in claim.message
                assert "青石镇名望 +2" in claim.message
                assert "城镇委托额外展示条目" in claim.message
                overview = await _send(runtime, adapter, user, f"{prefix}-claimed-overview", "我的图鉴")
                claimed_milestone = next(
                    item
                    for item in overview.data["milestones"]
                    if item["milestone_key"] == "codex.xuantian.place_3"
                )
                assert claimed_milestone["reward"] == {"local.xuantian.new_town": 2}
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    player_id = connection.execute(
                        "SELECT id FROM players WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    ).fetchone()[0]
                    local_json = connection.execute(
                        "SELECT local_json FROM player_reputations WHERE player_id=?", (player_id,)
                    ).fetchone()[0]
                    assert json.loads(local_json)["local.xuantian.new_town"] == 50
                    claim_reward = connection.execute(
                        "SELECT reward_json FROM codex_milestone_claims WHERE player_id=?",
                        (player_id,),
                    ).fetchone()[0]
                    operation_payload = connection.execute(
                        "SELECT result_json FROM operations WHERE operation_id=?",
                        (f"{prefix}-claim",),
                    ).fetchone()[0]
                assert json.loads(claim_reward) == claim.data["reward"]
                assert json.loads(operation_payload)["reward"] == claim.data["reward"]
            await runtime.close()

            milestones = json.loads(milestones_path.read_text(encoding="utf-8"))
            target = next(row for row in milestones["records"] if row["key"] == "codex.xuantian.place_3")
            target["status"] = "inactive"
            target["name"] = "后来改写的见闻"
            milestones_path.write_text(
                json.dumps(milestones, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            unlocks_path = content_dir / "图鉴" / "解锁.json"
            unlocks = json.loads(unlocks_path.read_text(encoding="utf-8"))
            next(row for row in unlocks["records"] if row["key"] == "commission.town.extra_offer")[
                "name"
            ] = "后来改写的委托"
            unlocks_path.write_text(
                json.dumps(unlocks, ensure_ascii=False, indent=2), encoding="utf-8"
            )

            runtime = create_runtime(data_dir=content_dir)
            for adapter in ("qq.official", "onebot.v11"):
                prefix = adapter.replace(".", "-")
                replay = await _send(
                    runtime,
                    adapter,
                    f"codex-cap-{adapter}",
                    f"{prefix}-claim",
                    "领取图鉴里程碑 codex.xuantian.place_3",
                )
                assert replay.code == "CODEX_MILESTONE_CLAIMED", replay
                assert replay.data["idempotent_replay"] is True
                assert replay.data["reward"] == {"local.xuantian.new_town": 2}
                assert "新镇三则" in replay.message
                assert "后来改写" not in replay.message
                assert "城镇委托额外展示条目" in replay.message
            await runtime.close()

    asyncio.run(run())


def test_codex_reputation_bad_json_and_operation_failure_roll_back_for_retry() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            entries = (
                "codex.material.blood_grass",
                "codex.material.spirit_leaf",
                "codex.material.ironstone",
                "codex.material.wood",
                "codex.material.array_sand",
            )
            for adapter in ("qq.official", "onebot.v11"):
                prefix = adapter.replace(".", "-")
                bad_json_user = f"codex-bad-json-{adapter}"
                await _send(runtime, adapter, bad_json_user, f"{prefix}-json-create", "开始修仙")
                _seed_codex_entries(runtime, adapter, bad_json_user, f"{prefix}-json", entries)
                _set_local_reputation(runtime, adapter, bad_json_user, "{broken")
                bad_json = await _send(
                    runtime,
                    adapter,
                    bad_json_user,
                    f"{prefix}-json-claim",
                    "领取图鉴里程碑 codex.xuantian.materials_5",
                )
                assert bad_json.code == "PERSISTENCE_ERROR", bad_json
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    player_id = connection.execute(
                        "SELECT id FROM players WHERE platform=? AND platform_user_id=?",
                        (adapter, bad_json_user),
                    ).fetchone()[0]
                    assert connection.execute(
                        "SELECT COUNT(*) FROM codex_milestone_claims WHERE player_id=?", (player_id,)
                    ).fetchone()[0] == 0
                    assert connection.execute(
                        "SELECT COUNT(*) FROM operations WHERE operation_id=?",
                        (f"{prefix}-json-claim",),
                    ).fetchone()[0] == 0
                _set_local_reputation(
                    runtime, adapter, bad_json_user, '{"local.xuantian.new_town":10}'
                )
                retried_json = await _send(
                    runtime,
                    adapter,
                    bad_json_user,
                    f"{prefix}-json-claim",
                    "领取图鉴里程碑 codex.xuantian.materials_5",
                )
                assert retried_json.code == "CODEX_MILESTONE_CLAIMED", retried_json
                assert retried_json.data["reward"] == {"local.xuantian.new_town": 5}

                operation_user = f"codex-op-failure-{adapter}"
                await _send(runtime, adapter, operation_user, f"{prefix}-op-create", "开始修仙")
                _seed_codex_entries(runtime, adapter, operation_user, f"{prefix}-op", entries)
                _set_local_reputation(
                    runtime, adapter, operation_user, '{"local.xuantian.new_town":9}'
                )
                with runtime.repository._connect() as connection:
                    connection.executescript(
                        """
                        CREATE TRIGGER fail_codex_claim_operation BEFORE INSERT ON operations
                        WHEN NEW.operation_name = 'specials.claim_codex_milestone'
                        BEGIN SELECT RAISE(ABORT, 'injected codex operation failure'); END;
                        """
                    )
                operation_id = f"{prefix}-operation-claim"
                failed = await _send(
                    runtime,
                    adapter,
                    operation_user,
                    operation_id,
                    "领取图鉴里程碑 codex.xuantian.materials_5",
                )
                assert failed.code == "PERSISTENCE_ERROR", failed
                with runtime.repository._connect() as connection:
                    connection.execute("DROP TRIGGER fail_codex_claim_operation")
                    player_id = connection.execute(
                        "SELECT id FROM players WHERE platform=? AND platform_user_id=?",
                        (adapter, operation_user),
                    ).fetchone()[0]
                    local_json = connection.execute(
                        "SELECT local_json FROM player_reputations WHERE player_id=?", (player_id,)
                    ).fetchone()[0]
                    assert json.loads(local_json)["local.xuantian.new_town"] == 9
                    assert connection.execute(
                        "SELECT COUNT(*) FROM codex_milestone_claims WHERE player_id=?", (player_id,)
                    ).fetchone()[0] == 0
                    assert connection.execute(
                        "SELECT COUNT(*) FROM operations WHERE operation_id=?", (operation_id,)
                    ).fetchone()[0] == 0
                retried_operation = await _send(
                    runtime,
                    adapter,
                    operation_user,
                    operation_id,
                    "领取图鉴里程碑 codex.xuantian.materials_5",
                )
                assert retried_operation.code == "CODEX_MILESTONE_CLAIMED", retried_operation
                assert retried_operation.data["reward"] == {"local.xuantian.new_town": 5}
            await runtime.close()

    asyncio.run(run())
