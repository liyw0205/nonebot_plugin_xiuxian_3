from __future__ import annotations

import asyncio
import json
import shutil
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime


class MutableClock:
    def __init__(self, value: datetime):
        self.value = value

    def __call__(self) -> datetime:
        return self.value

    def advance(self, **kwargs: int) -> None:
        self.value += timedelta(**kwargs)


def _context(user: str, operation_id: str = "") -> CommandContext:
    return CommandContext(adapter="web", user_id=user, operation_id=operation_id)


def test_blood_grass_plot_is_idempotent_and_does_not_change_cultivation() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            user = "livelihood-user"
            context = _context(user)
            assert (await runtime.dispatch(context, "开始修仙")).ok
            assert (await runtime.dispatch(context, "寻仙问道")).ok
            leased = await runtime.dispatch(_context(user, "lease"), "租住居所")
            assert leased.code == "RESIDENCE_LEASED"
            planted = await runtime.dispatch(_context(user, "plant"), "灵田播种 止血草")
            assert planted.code == "FIELD_PLOT_PLANTED"
            replayed = await runtime.dispatch(_context(user, "plant"), "灵田播种 止血草")
            assert replayed.code == planted.code
            assert replayed.data["plot_id"] == planted.data["plot_id"]
            assert replayed.data["idempotent_replay"] is True

            busy = await runtime.dispatch(_context(user, "plant-2"), "灵田播种")
            assert busy.code == "FIELD_PLOT_BUSY"
            maintained = await runtime.dispatch(_context(user, "maintain"), "灵田维护")
            assert maintained.code == "FIELD_PLOT_MAINTAINED"
            clock.advance(hours=4)
            harvested = await runtime.dispatch(_context(user, "harvest"), "灵田收获")
            assert harvested.code == "FIELD_PLOT_HARVESTED"
            assert harvested.data["harvest"] == {"item.herb.blood_grass": 3}
            assert harvested.data["local_reputation_delta"] == 1
            harvest_replay = await runtime.dispatch(_context(user, "harvest"), "灵田收获")
            assert harvest_replay.data["harvest"] == harvested.data["harvest"]
            assert harvest_replay.data["idempotent_replay"] is True
            second = await runtime.dispatch(_context(user, "plant-3"), "灵田播种")
            assert second.code == "FIELD_PLOT_PLANTED"
            clock.advance(hours=4)
            unmaintained = await runtime.dispatch(_context(user, "harvest-2"), "灵田收获")
            assert unmaintained.data["harvest"] == {"item.herb.blood_grass": 1}
            daily_limit = await runtime.dispatch(_context(user, "plant-4"), "灵田播种")
            assert daily_limit.code == "CROP_DAILY_LIMIT"

            with sqlite3.connect(runtime.settings.database_path) as connection:
                player = connection.execute(
                    "SELECT cultivation, total_cultivation, energy, inventory_json FROM players WHERE platform_user_id = ?",
                    (user,),
                ).fetchone()
                assert player[0:2] == (0, 0)
                assert player[2] == 27
                inventory = json.loads(player[3])
                assert inventory["item.herb.blood_grass"] == 5
                reputation = connection.execute(
                    "SELECT local_json FROM player_reputations WHERE player_id = (SELECT id FROM players WHERE platform_user_id = ?)",
                    (user,),
                ).fetchone()
                assert json.loads(reputation[0])["local.xuantian.new_town"] == 2
            await runtime.close()

    asyncio.run(run())


def test_blood_grass_harvest_uses_location_cap_and_recovers_after_reward_failure() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
        with TemporaryDirectory() as temp:
            data_dir = Path(temp) / "data"
            shutil.copytree(Path(__file__).parents[1] / "data", data_dir)
            location_file = data_dir / "地图" / "地点.json"
            locations = json.loads(location_file.read_text(encoding="utf-8"))
            new_town = next(
                item for item in locations["records"] if item["key"] == "xuantian.new_town"
            )
            new_town["local_reputation_maximum"] = 41
            location_file.write_text(
                json.dumps(locations, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

            runtime = create_runtime(data_dir=data_dir, clock=clock)
            user = "livelihood-reputation-cap"
            assert (await runtime.dispatch(_context(user), "开始修仙")).ok
            assert (await runtime.dispatch(_context(user), "寻仙问道")).ok
            with sqlite3.connect(runtime.settings.database_path) as connection:
                player_id = connection.execute(
                    "SELECT id FROM players WHERE platform='web' AND platform_user_id=?",
                    (user,),
                ).fetchone()[0]
                connection.execute(
                    "INSERT INTO player_reputations(player_id, local_json, updated_at) "
                    "VALUES (?, ?, ?) ON CONFLICT(player_id) DO UPDATE SET local_json=excluded.local_json",
                    (player_id, json.dumps({"local.xuantian.new_town": 40}), clock.value.isoformat()),
                )
            assert (await runtime.dispatch(_context(user, "lease"), "租住居所")).ok
            planted = await runtime.dispatch(_context(user, "plant"), "灵田播种 止血草")
            assert planted.code == "FIELD_PLOT_PLANTED"
            assert (await runtime.dispatch(_context(user, "maintain"), "灵田维护")).ok
            clock.advance(hours=4)
            with sqlite3.connect(runtime.settings.database_path) as connection:
                inventory_before_harvest = json.loads(
                    connection.execute(
                        "SELECT inventory_json FROM players WHERE id=?", (player_id,)
                    ).fetchone()[0]
                )

            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    f"CREATE TRIGGER fail_reputation_insert BEFORE INSERT ON player_reputations "
                    f"WHEN NEW.player_id={player_id} BEGIN "
                    "SELECT RAISE(ABORT, 'injected reputation failure'); END"
                )
            with pytest.raises(sqlite3.IntegrityError, match="injected reputation failure"):
                await runtime.repository.harvest_plot(
                    platform="web",
                    platform_user_id=user,
                    operation_id="harvest-retry",
                )
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute(
                    "SELECT status FROM field_plots WHERE plot_id=?", (planted.data["plot_id"],)
                ).fetchone()[0] == "growing"
                inventory_raw, reputation_raw, operation_count = connection.execute(
                    "SELECT p.inventory_json, r.local_json, "
                    "(SELECT COUNT(*) FROM operations WHERE operation_id='harvest-retry') "
                    "FROM players p JOIN player_reputations r ON r.player_id=p.id WHERE p.id=?",
                    (player_id,),
                ).fetchone()
                assert json.loads(inventory_raw) == inventory_before_harvest
                assert json.loads(reputation_raw)["local.xuantian.new_town"] == 40
                assert operation_count == 0
                connection.execute("DROP TRIGGER fail_reputation_insert")

            harvested = await runtime.dispatch(
                _context(user, "harvest-retry"), "灵田收获"
            )
            assert harvested.code == "FIELD_PLOT_HARVESTED"
            assert harvested.data["local_reputation_delta"] == 1
            replay = await runtime.dispatch(
                _context(user, "harvest-retry"), "灵田收获"
            )
            assert replay.data["idempotent_replay"] is True
            with sqlite3.connect(runtime.settings.database_path) as connection:
                inventory_raw, reputation_raw, operation_count = connection.execute(
                    "SELECT p.inventory_json, r.local_json, "
                    "(SELECT COUNT(*) FROM operations WHERE operation_id='harvest-retry') "
                    "FROM players p JOIN player_reputations r ON r.player_id=p.id WHERE p.id=?",
                    (player_id,),
                ).fetchone()
            assert json.loads(inventory_raw)["item.herb.blood_grass"] == (
                inventory_before_harvest.get("item.herb.blood_grass", 0) + 3
            )
            assert json.loads(reputation_raw)["local.xuantian.new_town"] == 41
            assert operation_count == 1
            await runtime.close()

    asyncio.run(run())


def test_plot_expiry_marks_withered_without_refunding_assets() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            user = "withered-user"
            context = _context(user)
            await runtime.dispatch(context, "开始修仙")
            await runtime.dispatch(context, "寻仙问道")
            await runtime.dispatch(_context(user, "lease"), "租住居所")
            await runtime.dispatch(_context(user, "plant"), "灵田播种")
            clock.advance(hours=29)
            result = await runtime.dispatch(_context(user, "harvest"), "灵田收获")
            assert result.code == "PLOT_WITHERED"
            profile = await runtime.dispatch(_context(user), "我的灵田")
            assert profile.data["status"] == "withered"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                row = connection.execute(
                    "SELECT energy, inventory_json FROM players WHERE platform_user_id = ?", (user,)
                ).fetchone()
                assert row[0] == 29
                assert json.loads(row[1])["item.herb.blood_grass"] == 2
            await runtime.close()

    asyncio.run(run())


def test_spirit_leaf_requires_courtyard_and_freezes_array_sand_roll() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            user = "spirit-leaf-user"
            context = _context(user)
            await runtime.dispatch(context, "开始修仙")
            await runtime.dispatch(context, "寻仙问道")
            with sqlite3.connect(runtime.settings.database_path) as connection:
                player_id = connection.execute(
                    "SELECT id FROM players WHERE platform_user_id = ?", (user,)
                ).fetchone()[0]
                connection.execute(
                    "UPDATE players SET inventory_json = ?, spirit_stones = 100 WHERE id = ?",
                    (json.dumps({"item.herb.spirit_leaf": 2}), player_id),
                )
                connection.execute(
                    """
                    INSERT INTO player_reputations(player_id, local_json, service_reputation, updated_at)
                    VALUES (?, ?, 0, ?)
                    ON CONFLICT(player_id) DO UPDATE SET local_json = excluded.local_json
                    """,
                    (player_id, json.dumps({"local.xuantian.new_town": 40}), clock.value.isoformat()),
                )

            leased = await runtime.dispatch(_context(user, "spirit-lease"), "租住居所 小院")
            assert leased.code == "RESIDENCE_LEASED"
            planted = await runtime.dispatch(
                _context(user, "spirit-plant"), "灵田播种 灵叶"
            )
            assert planted.code == "FIELD_PLOT_PLANTED"
            assert planted.data["crop_key"] == "crop.spirit_leaf"
            assert planted.data["required_maintenance"] == 2
            assert (await runtime.dispatch(_context(user, "spirit-maintain-1"), "灵田维护")).ok
            assert (await runtime.dispatch(_context(user, "spirit-maintain-2"), "灵田维护")).ok
            clock.advance(hours=8)
            harvested = await runtime.dispatch(_context(user, "spirit-harvest"), "灵田收获")
            assert harvested.code == "FIELD_PLOT_HARVESTED"
            assert harvested.data["harvest"]["item.herb.spirit_leaf"] == 3
            assert harvested.data["harvest"]["item.mat.array_sand"] == 1
            codex = await runtime.dispatch(_context(user, "spirit-codex"), "我的图鉴 材料")
            assert any(
                item["entry_key"] == "codex.material.array_sand"
                for item in codex.data["entries"]
            )
            replay = await runtime.dispatch(_context(user, "spirit-harvest"), "灵田收获")
            assert replay.data["harvest"] == harvested.data["harvest"]
            assert replay.data["idempotent_replay"] is True

            with sqlite3.connect(runtime.settings.database_path) as connection:
                snapshot = connection.execute(
                    "SELECT snapshot_json FROM field_plots WHERE plot_id = ?", (planted.data["plot_id"],)
                ).fetchone()[0]
                payload = json.loads(snapshot)
                assert payload["random_pool"] == "livelihood.harvest"
                assert payload["random_seed"] == "spirit-plant"
                assert payload["array_sand_roll"] in {0, 1}
            await runtime.close()

    asyncio.run(run())


def test_town_commission_defers_materials_until_delivery_and_settles_once() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            user = "commission-user"
            context = _context(user)
            await runtime.dispatch(context, "开始修仙")
            await runtime.dispatch(context, "寻仙问道")
            listed = await runtime.dispatch(_context(user), "城镇委托")
            assert listed.code == "COMMISSION_LIST"
            assert len(listed.data["commissions"]) == 3
            accepted = await runtime.dispatch(
                _context(user, "accept-herb"), "接取委托 止血草供应"
            )
            assert accepted.code == "COMMISSION_ACCEPTED"
            assert accepted.data["claim_id"] != accepted.data["commission_id"]
            with sqlite3.connect(runtime.settings.database_path) as connection:
                before = connection.execute(
                    "SELECT spirit_stones, cultivation, total_cultivation, inventory_json FROM players WHERE platform_user_id = ?",
                    (user,),
                ).fetchone()
            inventory_before = json.loads(before[3])
            assert inventory_before["item.herb.blood_grass"] == 3
            assert before[:3] == (100, 0, 0)

            delivered = await runtime.dispatch(
                _context(user, "deliver-herb"), "交付委托 止血草供应"
            )
            assert delivered.code == "COMMISSION_DELIVERED"
            assert delivered.data["reward_stones"] == 18
            replay = await runtime.dispatch(
                _context(user, "deliver-herb"), "交付委托 止血草供应"
            )
            assert replay.code == delivered.code
            assert replay.data["idempotent_replay"] is True
            with sqlite3.connect(runtime.settings.database_path) as connection:
                after = connection.execute(
                    "SELECT spirit_stones, cultivation, total_cultivation, inventory_json FROM players WHERE platform_user_id = ?",
                    (user,),
                ).fetchone()
                reputation = connection.execute(
                    "SELECT local_json, service_reputation FROM player_reputations WHERE player_id = (SELECT id FROM players WHERE platform_user_id = ?)",
                    (user,),
                ).fetchone()
            assert after[:3] == (118, 0, 0)
            assert json.loads(after[3]).get("item.herb.blood_grass", 0) == 0
            assert json.loads(reputation[0])["local.xuantian.new_town"] == 3
            assert reputation[1] == 1
            await runtime.close()

    asyncio.run(run())


def test_town_commission_quota_material_failure_and_global_stock_are_atomic() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)

            async def create_user(user: str) -> None:
                context = _context(user)
                await runtime.dispatch(context, "开始修仙")
                await runtime.dispatch(context, "寻仙问道")

            await create_user("quota-user")
            assert (await runtime.dispatch(_context("quota-user", "q1"), "接取委托 止血草供应")).ok
            assert (await runtime.dispatch(_context("quota-user", "q2"), "接取委托 工具修缮")).ok
            quota = await runtime.dispatch(_context("quota-user", "q3"), "接取委托 灵米饭供应")
            assert quota.code == "COMMISSION_QUOTA_EXHAUSTED"
            missing = await runtime.dispatch(_context("quota-user", "missing"), "交付委托 工具修缮")
            assert missing.code == "RESOURCE_INSUFFICIENT"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                wallet = connection.execute(
                    "SELECT spirit_stones, cultivation, total_cultivation FROM players WHERE platform_user_id = ?",
                    ("quota-user",),
                ).fetchone()
            assert wallet == (100, 0, 0)

            await create_user("stock-a")
            await create_user("stock-b")
            await runtime.dispatch(_context("stock-a"), "城镇委托")
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE town_commissions SET stock_remaining = 1 WHERE commission_key = ? AND business_date = ?",
                    ("town_commission.meal_service", "2026-09-22"),
                )
            results = await asyncio.gather(
                runtime.dispatch(_context("stock-a", "stock-a-op"), "接取委托 灵米饭供应"),
                runtime.dispatch(_context("stock-b", "stock-b-op"), "接取委托 灵米饭供应"),
            )
            assert {result.code for result in results} == {"COMMISSION_ACCEPTED", "COMMISSION_STOCK_EXHAUSTED"}
            await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("failure_stage", ["reputation", "claim", "operation"])
def test_town_commission_shared_reward_transaction_caps_and_recovers(failure_stage: str) -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
        with TemporaryDirectory() as temp:
            data_dir = Path(temp) / "data"
            shutil.copytree(Path(__file__).parents[1] / "data", data_dir)
            location_file = data_dir / "地图" / "地点.json"
            locations = json.loads(location_file.read_text(encoding="utf-8"))
            new_town = next(
                item for item in locations["records"] if item["key"] == "xuantian.new_town"
            )
            new_town["local_reputation_maximum"] = 4
            location_file.write_text(
                json.dumps(locations, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

            runtime = create_runtime(data_dir=data_dir, clock=clock)
            user = "commission-reward-transaction"
            assert (await runtime.dispatch(_context(user), "开始修仙")).ok
            assert (await runtime.dispatch(_context(user), "寻仙问道")).ok
            with sqlite3.connect(runtime.settings.database_path) as connection:
                player_id = connection.execute(
                    "SELECT id FROM players WHERE platform='web' AND platform_user_id=?",
                    (user,),
                ).fetchone()[0]
                connection.execute(
                    "UPDATE players SET inventory_json=? WHERE id=?",
                    (json.dumps({"item.herb.blood_grass": 3}), player_id),
                )
                connection.execute(
                    "INSERT INTO player_reputations(player_id, local_json, service_reputation, updated_at) "
                    "VALUES (?, ?, 99, ?) ON CONFLICT(player_id) DO UPDATE SET "
                    "local_json=excluded.local_json, service_reputation=excluded.service_reputation",
                    (player_id, json.dumps({"local.xuantian.new_town": 3}), clock.value.isoformat()),
                )
            assert (await runtime.dispatch(_context(user, "commission-list"), "城镇委托")).ok
            assert (
                await runtime.dispatch(
                    _context(user, "commission-accept"), "接取委托 止血草供应"
                )
            ).code == "COMMISSION_ACCEPTED"

            with sqlite3.connect(runtime.settings.database_path) as connection:
                table, timing, action = {
                    "reputation": ("player_reputations", "BEFORE", "INSERT"),
                    "claim": ("town_commission_claims", "AFTER", "UPDATE"),
                    "operation": ("operations", "AFTER", "INSERT"),
                }[failure_stage]
                connection.execute(
                    f"CREATE TRIGGER fail_commission_write {timing} {action} ON {table} "
                    f"WHEN NEW.player_id={player_id} BEGIN "
                    "SELECT RAISE(ABORT, 'injected commission failure'); END"
                )
            with pytest.raises(sqlite3.IntegrityError, match="injected commission failure"):
                await runtime.repository.deliver_commission(
                    platform="web",
                    platform_user_id=user,
                    commission_key="town_commission.herb_supply",
                    operation_id="commission-retry",
                )
            with sqlite3.connect(runtime.settings.database_path) as connection:
                state = connection.execute(
                    "SELECT p.spirit_stones, p.inventory_json, r.local_json, r.service_reputation, "
                    "c.status, (SELECT COUNT(*) FROM operations WHERE operation_id='commission-retry') "
                    "FROM players p JOIN player_reputations r ON r.player_id=p.id "
                    "JOIN town_commission_claims c ON c.player_id=p.id "
                    "WHERE p.id=? ORDER BY c.id DESC LIMIT 1",
                    (player_id,),
                ).fetchone()
                connection.execute("DROP TRIGGER fail_commission_write")
            assert state[0] == 100
            assert json.loads(state[1]) == {"item.herb.blood_grass": 3}
            assert json.loads(state[2])["local.xuantian.new_town"] == 3
            assert state[3] == 99
            assert state[4] == "accepted"
            assert state[5] == 0

            settled = await runtime.dispatch(
                _context(user, "commission-retry"), "交付委托 止血草供应"
            )
            assert settled.code == "COMMISSION_DELIVERED"
            assert settled.data["local_reputation"] == 1
            assert settled.data["service_reputation"] == 1
            replay = await runtime.dispatch(
                _context(user, "commission-retry"), "交付委托 止血草供应"
            )
            assert replay.data["idempotent_replay"] is True
            conflict = await runtime.dispatch(
                _context(user, "commission-retry"), "交付委托 工具修缮"
            )
            assert conflict.code == "OPERATION_CONFLICT"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                wallet, inventory, local_json, service = connection.execute(
                    "SELECT p.spirit_stones, p.inventory_json, r.local_json, r.service_reputation "
                    "FROM players p JOIN player_reputations r ON r.player_id=p.id WHERE p.id=?",
                    (player_id,),
                ).fetchone()
            assert wallet == 118
            assert json.loads(inventory) == {}
            assert json.loads(local_json)["local.xuantian.new_town"] == 4
            assert service == 100
            await runtime.close()

    asyncio.run(run())


def test_service_order_success_locks_both_players_and_preserves_cultivation() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)

            async def create_user(user: str) -> None:
                context = _context(user)
                await runtime.dispatch(context, "开始修仙")
                await runtime.dispatch(context, "寻仙问道")

            await create_user("service-publisher")
            await create_user("service-provider")
            with sqlite3.connect(runtime.settings.database_path) as connection:
                provider_id = connection.execute(
                    "SELECT id FROM players WHERE platform_user_id = ?", ("service-provider",)
                ).fetchone()[0]
                connection.execute(
                    """
                    INSERT INTO player_reputations(player_id, service_reputation, updated_at)
                    VALUES (?, 10, ?)
                    ON CONFLICT(player_id) DO UPDATE SET service_reputation = 10, updated_at = excluded.updated_at
                    """,
                    (provider_id, clock.value.isoformat()),
                )

            published = await runtime.dispatch(
                _context("service-publisher", "service-publish"), "发布服务 教学采集协助"
            )
            assert published.code == "SERVICE_PUBLISHED"
            order_id = published.data["order_id"]
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute(
                    "SELECT spirit_stones FROM players WHERE platform_user_id = ?",
                    ("service-publisher",),
                ).fetchone()[0] == 85
            accepted = await runtime.dispatch(
                _context("service-provider", "service-accept"), f"接取服务 {order_id}"
            )
            assert accepted.code == "SERVICE_ACCEPTED"
            settled = await runtime.dispatch(
                _context("service-provider", "service-settle"), f"结算服务 {order_id}"
            )
            assert settled.code == "SERVICE_SETTLED"
            assert settled.data["provider_payment"] == 14
            assert settled.data["outputs"] == {"item.herb.blood_grass": 1}

            replay = await runtime.dispatch(
                _context("service-provider", "service-settle"), f"结算服务 {order_id}"
            )
            assert replay.code == settled.code
            assert replay.data["idempotent_replay"] is True
            with sqlite3.connect(runtime.settings.database_path) as connection:
                rows = connection.execute(
                    """
                    SELECT platform_user_id, spirit_stones, stamina, cultivation,
                           total_cultivation, inventory_json
                    FROM players ORDER BY platform_user_id
                    """
                ).fetchall()
            publisher = next(row for row in rows if row[0] == "service-publisher")
            provider = next(row for row in rows if row[0] == "service-provider")
            assert publisher[1:5] == (85, 30, 0, 0)
            assert json.loads(publisher[5])["item.herb.blood_grass"] == 4
            assert provider[1:5] == (114, 27, 0, 0)
            await runtime.close()

    asyncio.run(run())


def test_service_publisher_can_cancel_and_refund_locked_reward() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            for user in ("cancel-publisher", "cancel-provider"):
                context = _context(user)
                await runtime.dispatch(context, "开始修仙")
                await runtime.dispatch(context, "寻仙问道")
            published = await runtime.dispatch(
                _context("cancel-publisher", "cancel-publish"), "发布服务 烹饪服务 30"
            )
            assert published.code == "SERVICE_PUBLISHED"
            order_id = published.data["order_id"]
            cancelled = await runtime.dispatch(
                _context("cancel-publisher", "cancel-order"), f"取消服务 {order_id}"
            )
            assert cancelled.code == "SERVICE_CANCELLED"
            assert cancelled.data["refund_stones"] == 30
            replay = await runtime.dispatch(
                _context("cancel-publisher", "cancel-order"), f"取消服务 {order_id}"
            )
            assert replay.data["idempotent_replay"] is True
            accepted = await runtime.dispatch(
                _context("cancel-provider", "cancel-accept"), f"接取服务 {order_id}"
            )
            assert accepted.code == "SERVICE_ORDER_CONFLICT"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                wallet = connection.execute(
                    "SELECT spirit_stones FROM players WHERE platform_user_id = ?",
                    ("cancel-publisher",),
                ).fetchone()[0]
                status = connection.execute(
                    "SELECT status FROM livelihood_service_orders WHERE order_id = ?", (order_id,)
                ).fetchone()[0]
            assert wallet == 100
            assert status == "cancelled"
            await runtime.close()

    asyncio.run(run())


def test_unaccepted_service_expiry_releases_publisher_escrow() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            for user in ("unaccepted-expiry", "unaccepted-expiry-provider"):
                context = _context(user)
                await runtime.dispatch(context, "开始修仙")
                await runtime.dispatch(context, "寻仙问道")
            published = await runtime.dispatch(
                _context("unaccepted-expiry", "unaccepted-publish"), "发布服务 教学采集协助"
            )
            order_id = published.data["order_id"]
            clock.advance(hours=25)
            expired = await runtime.dispatch(
                _context("unaccepted-expiry-provider", "unaccepted-accept"), f"接取服务 {order_id}"
            )
            assert expired.code == "SERVICE_EXPIRED"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                wallet = connection.execute(
                    "SELECT spirit_stones FROM players WHERE platform_user_id = ?",
                    ("unaccepted-expiry",),
                ).fetchone()[0]
                status = connection.execute(
                    "SELECT status FROM livelihood_service_orders WHERE order_id = ?", (order_id,)
                ).fetchone()[0]
            assert wallet == 100
            assert status == "expired"
            await runtime.close()

    asyncio.run(run())


def test_service_failure_refunds_snapshot_and_expiry_does_not_double_settle() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)

            async def create_user(user: str) -> None:
                context = _context(user)
                await runtime.dispatch(context, "开始修仙")
                await runtime.dispatch(context, "寻仙问道")

            await create_user("failure-publisher")
            await create_user("failure-provider")
            with sqlite3.connect(runtime.settings.database_path) as connection:
                provider_id = connection.execute(
                    "SELECT id FROM players WHERE platform_user_id = ?", ("failure-provider",)
                ).fetchone()[0]
                connection.execute(
                    "INSERT INTO player_reputations(player_id, service_reputation, updated_at) VALUES (?, 10, ?)",
                    (provider_id, clock.value.isoformat()),
                )
            published = await runtime.dispatch(
                _context("failure-publisher", "failure-publish"), "发布服务 教学采集协助"
            )
            order_id = published.data["order_id"]
            assert (await runtime.dispatch(_context("failure-provider", "failure-accept"), f"接取服务 {order_id}")).ok
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE players SET location_key = 'xuantian.outskirts' WHERE platform_user_id = ?",
                    ("failure-provider",),
                )
            failed = await runtime.dispatch(
                _context("failure-provider", "failure-settle"), f"结算服务 {order_id}"
            )
            assert failed.code == "SERVICE_FAILED"
            assert failed.data["publisher_refund"] == 12
            assert failed.data["stamina_refund"] == 1
            replay = await runtime.dispatch(
                _context("failure-provider", "failure-settle"), f"结算服务 {order_id}"
            )
            assert replay.data["idempotent_replay"] is True
            with sqlite3.connect(runtime.settings.database_path) as connection:
                wallet = connection.execute(
                    "SELECT spirit_stones, stamina, cultivation, total_cultivation FROM players WHERE platform_user_id = ?",
                    ("failure-publisher",),
                ).fetchone()
                provider = connection.execute(
                    "SELECT spirit_stones, stamina, cultivation, total_cultivation FROM players WHERE platform_user_id = ?",
                    ("failure-provider",),
                ).fetchone()
                order_status = connection.execute(
                    "SELECT status FROM livelihood_service_orders WHERE order_id = ?", (order_id,)
                ).fetchone()[0]
            assert wallet == (97, 30, 0, 0)
            assert provider == (100, 28, 0, 0)
            assert order_status == "failed"
            await runtime.close()

    asyncio.run(run())


def test_cook_service_transfers_cooked_meal_and_is_atomic() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            for user in ("cook-publisher", "cook-provider"):
                context = _context(user)
                await runtime.dispatch(context, "开始修仙")
                await runtime.dispatch(context, "寻仙问道")
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE players SET intro_json = ?, selected_service = ? WHERE platform_user_id = ?",
                    (json.dumps({"flags": ["guide.choose_service"]}), "cooking", "cook-provider"),
                )
            published = await runtime.dispatch(
                _context("cook-publisher", "cook-publish"), "发布服务 烹饪服务"
            )
            order_id = published.data["order_id"]
            accepted = await runtime.dispatch(
                _context("cook-provider", "cook-accept"), f"接取服务 {order_id}"
            )
            assert accepted.code == "SERVICE_ACCEPTED"
            settled = await runtime.dispatch(
                _context("cook-provider", "cook-settle"), f"结算服务 {order_id}"
            )
            assert settled.code == "SERVICE_SETTLED"
            assert settled.data["outputs"] == {"item.food.spirit_rice": 2}
            with sqlite3.connect(runtime.settings.database_path) as connection:
                publisher = connection.execute(
                    "SELECT spirit_stones, energy, cultivation, total_cultivation, inventory_json FROM players WHERE platform_user_id = ?",
                    ("cook-publisher",),
                ).fetchone()
                provider = connection.execute(
                    "SELECT spirit_stones, energy, cultivation, total_cultivation, inventory_json FROM players WHERE platform_user_id = ?",
                    ("cook-provider",),
                ).fetchone()
            assert publisher[:4] == (80, 30, 0, 0)
            assert json.loads(publisher[4])["item.food.spirit_rice"] == 2
            assert provider[:4] == (119, 28, 0, 0)
            assert json.loads(provider[4])["item.food.coarse_spirit_rice"] == 1
            await runtime.close()

    asyncio.run(run())


def test_service_expiry_releases_all_locked_resources_once() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            for user in ("expiry-publisher", "expiry-provider"):
                context = _context(user)
                await runtime.dispatch(context, "开始修仙")
                await runtime.dispatch(context, "寻仙问道")
            with sqlite3.connect(runtime.settings.database_path) as connection:
                provider_id = connection.execute(
                    "SELECT id FROM players WHERE platform_user_id = ?", ("expiry-provider",)
                ).fetchone()[0]
                connection.execute(
                    "UPDATE players SET intro_json = ?, selected_service = ? WHERE id = ?",
                    (json.dumps({"flags": ["guide.choose_service"]}), "cooking", provider_id),
                )
            published = await runtime.dispatch(
                _context("expiry-publisher", "expiry-publish"), "发布服务 烹饪服务"
            )
            order_id = published.data["order_id"]
            accepted = await runtime.dispatch(
                _context("expiry-provider", "expiry-accept"), f"接取服务 {order_id}"
            )
            assert accepted.code == "SERVICE_ACCEPTED"
            clock.advance(hours=25)
            expired = await runtime.dispatch(
                _context("expiry-provider", "expiry-settle"), f"结算服务 {order_id}"
            )
            assert expired.code == "SERVICE_EXPIRED"
            assert expired.data["publisher_refund"] == 16
            assert expired.data["provider_refunds"] == {"item.food.coarse_spirit_rice": 2}
            assert expired.data["stamina_refund"] == 0
            replay = await runtime.dispatch(
                _context("expiry-provider", "expiry-settle"), f"结算服务 {order_id}"
            )
            assert replay.data["idempotent_replay"] is True
            with sqlite3.connect(runtime.settings.database_path) as connection:
                publisher = connection.execute(
                    "SELECT spirit_stones, cultivation, total_cultivation, inventory_json FROM players WHERE platform_user_id = ?",
                    ("expiry-publisher",),
                ).fetchone()
                provider = connection.execute(
                    "SELECT spirit_stones, energy, cultivation, total_cultivation, inventory_json FROM players WHERE platform_user_id = ?",
                    ("expiry-provider",),
                ).fetchone()
            assert publisher[:3] == (96, 0, 0)
            assert json.loads(publisher[3]).get("item.food.spirit_rice", 0) == 0
            assert provider[:4] == (100, 30, 0, 0)
            assert json.loads(provider[4])["item.food.coarse_spirit_rice"] == 3
            await runtime.close()

    asyncio.run(run())


def test_service_accept_concurrency_allows_only_one_provider() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            for user in ("race-publisher", "race-a", "race-b"):
                context = _context(user)
                await runtime.dispatch(context, "开始修仙")
                await runtime.dispatch(context, "寻仙问道")
            with sqlite3.connect(runtime.settings.database_path) as connection:
                for user in ("race-a", "race-b"):
                    provider_id = connection.execute(
                        "SELECT id FROM players WHERE platform_user_id = ?", (user,)
                    ).fetchone()[0]
                    connection.execute(
                        "INSERT INTO player_reputations(player_id, service_reputation, updated_at) VALUES (?, 10, ?)",
                        (provider_id, clock.value.isoformat()),
                    )
            published = await runtime.dispatch(
                _context("race-publisher", "race-publish"), "发布服务 教学采集协助"
            )
            order_id = published.data["order_id"]
            results = await asyncio.gather(
                runtime.dispatch(_context("race-a", "race-a-accept"), f"接取服务 {order_id}"),
                runtime.dispatch(_context("race-b", "race-b-accept"), f"接取服务 {order_id}"),
            )
            assert {result.code for result in results} == {"SERVICE_ACCEPTED", "SERVICE_ORDER_CONFLICT"}
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute(
                    "SELECT COUNT(*) FROM livelihood_service_orders WHERE order_id = ? AND status = 'accepted'",
                    (order_id,),
                ).fetchone()[0] == 1
            await runtime.close()

    asyncio.run(run())


def test_short_route_locks_cargo_settles_once_and_preserves_cultivation() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            user = "route-user"
            await runtime.dispatch(_context(user), "开始修仙")
            await runtime.dispatch(_context(user), "寻仙问道")
            preview = await runtime.dispatch(_context(user, "route-preview"), "运输预览 止血草 1")
            assert preview.code == "ROUTE_PREVIEW"
            assert preview.data["ready"] is True
            with sqlite3.connect(runtime.settings.database_path) as connection:
                before = connection.execute(
                    "SELECT spirit_stones, stamina, cultivation, total_cultivation, location_key, inventory_json FROM players WHERE platform_user_id = ?",
                    (user,),
                ).fetchone()
            assert before[:5] == (100, 30, 0, 0, "xuantian.new_town")
            assert json.loads(before[5])["item.herb.blood_grass"] == 3

            started = await runtime.dispatch(_context(user, "route-start"), "开始运输 止血草 1")
            assert started.code == "ROUTE_STARTED"
            route_id = started.data["route_id"]
            replay = await runtime.dispatch(_context(user, "route-start"), "开始运输 止血草 1")
            assert replay.data["idempotent_replay"] is True
            not_ready = await runtime.dispatch(_context(user, "route-settle-early"), f"结算运输 {route_id}")
            assert not_ready.code == "ROUTE_NOT_READY"
            clock.advance(minutes=20)
            settled = await runtime.dispatch(_context(user, "route-settle"), f"结算运输 {route_id}")
            assert settled.code == "ROUTE_SETTLED"
            assert settled.data["reward_stones"] == 12
            assert settled.data["local_reputation_delta"] == 2
            settled_replay = await runtime.dispatch(_context(user, "route-settle"), f"结算运输 {route_id}")
            assert settled_replay.data["idempotent_replay"] is True
            with sqlite3.connect(runtime.settings.database_path) as connection:
                after = connection.execute(
                    "SELECT spirit_stones, stamina, cultivation, total_cultivation, location_key, inventory_json FROM players WHERE platform_user_id = ?",
                    (user,),
                ).fetchone()
                reputation = connection.execute(
                    "SELECT local_json FROM player_reputations WHERE player_id = (SELECT id FROM players WHERE platform_user_id = ?)",
                    (user,),
                ).fetchone()
                status = connection.execute(
                    "SELECT status, cargo_json FROM livelihood_trade_routes WHERE route_id = ?", (route_id,)
                ).fetchone()
            assert after[:5] == (112, 28, 0, 0, "xuantian.outskirts")
            assert json.loads(after[5]).get("item.herb.blood_grass", 0) == 2
            assert json.loads(reputation[0])["local.xuantian.new_town"] == 2
            assert status[0] == "settled"
            assert json.loads(status[1]) == {"item.herb.blood_grass": 1}
            await runtime.close()

    asyncio.run(run())


def test_short_route_cargo_limit_and_concurrent_lock_are_atomic() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            user = "route-atomic"
            await runtime.dispatch(_context(user), "开始修仙")
            await runtime.dispatch(_context(user), "寻仙问道")
            too_valuable = await runtime.dispatch(_context(user, "route-too-valuable"), "开始运输 止血草 11")
            assert too_valuable.code == "ROUTE_CARGO_LOCKED"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                before = connection.execute(
                    "SELECT spirit_stones, stamina, inventory_json FROM players WHERE platform_user_id = ?", (user,)
                ).fetchone()
            assert before[:2] == (100, 30)
            assert json.loads(before[2])["item.herb.blood_grass"] == 3
            results = await asyncio.gather(
                runtime.dispatch(_context(user, "route-race-a"), "开始运输 止血草 1"),
                runtime.dispatch(_context(user, "route-race-b"), "开始运输 止血草 1"),
            )
            assert {result.code for result in results} == {"ROUTE_STARTED", "ROUTE_BUSY"}
            with sqlite3.connect(runtime.settings.database_path) as connection:
                route_count = connection.execute(
                    "SELECT COUNT(*) FROM livelihood_trade_routes WHERE player_id = (SELECT id FROM players WHERE platform_user_id = ?) AND status = 'in_transit'",
                    (user,),
                ).fetchone()[0]
                after = connection.execute(
                    "SELECT stamina, inventory_json, cultivation, total_cultivation FROM players WHERE platform_user_id = ?",
                    (user,),
                ).fetchone()
            assert route_count == 1
            assert after[0] == 28
            assert json.loads(after[1])["item.herb.blood_grass"] == 2
            assert after[2:4] == (0, 0)
            await runtime.close()

    asyncio.run(run())


def _onebot_event(content: str, message_id: int, *, user_id: int = 1001, group_id: int = 2002):
    from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message
    from nonebot.adapters.onebot.v11.event import Sender

    return GroupMessageEvent(
        time=1_735_689_600,
        self_id=9001,
        post_type="message",
        sub_type="normal",
        user_id=user_id,
        message_type="group",
        message_id=message_id,
        message=Message(content),
        original_message=Message(content),
        raw_message=content,
        font=0,
        sender=Sender(user_id=user_id, nickname="OneBot道友"),
        group_id=group_id,
    )


def _qq_event(
    content: str,
    message_id: str,
    *,
    member_openid: str = "qq-user-1",
    group_openid: str = "qq-group-1",
):
    from nonebot.adapters.qq.event import GroupMessageCreateEvent
    from nonebot.adapters.qq.models.qq import GroupMemberAuthor

    return GroupMessageCreateEvent(
        id=message_id,
        content=content,
        timestamp="2026-01-01T00:00:00+00:00",
        author=GroupMemberAuthor(
            id="qq-user-raw",
            bot=False,
            member_openid=member_openid,
            member_role="member",
            username="QQ道友",
        ),
        group_id="qq-group-raw",
        group_openid=group_openid,
    )


@pytest.mark.parametrize("kind", ["onebot", "qq"])
def test_real_adapters_reach_livelihood_application(kind: str) -> None:
    pytest.importorskip("nonebot")
    from nonebot_plugin_xiuxian_3.adapters.onebot import normalize_event
    from nonebot_plugin_xiuxian_3.adapters.qq import normalize_event as normalize_qq_event

    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            clock = MutableClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            texts = [
                "开始修仙",
                "寻仙问道",
                "城镇委托",
                "接取委托 止血草供应",
                "交付委托 止血草供应",
            ]
            for index, text in enumerate(texts):
                event = _onebot_event(text, 4000 + index) if kind == "onebot" else _qq_event(text, f"qq-{index}")
                normalized = normalize_event(event) if kind == "onebot" else normalize_qq_event(event)
                result = await runtime.dispatch(normalized.context, normalized.text)
                assert result.ok, result
            delivery_event = (
                _onebot_event("交付委托 止血草供应", 4004)
                if kind == "onebot"
                else _qq_event("交付委托 止血草供应", "qq-4")
            )
            delivery_replay = normalize_event(delivery_event) if kind == "onebot" else normalize_qq_event(delivery_event)
            replay = await runtime.dispatch(delivery_replay.context, delivery_replay.text)
            assert replay.code == "COMMISSION_DELIVERED"
            assert replay.data["idempotent_replay"] is True
            platform = "onebot.v11" if kind == "onebot" else "qq.official"
            user_id = "1001" if kind == "onebot" else "qq-user-1"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                player_id, spirit_stones, inventory, local_json, service = connection.execute(
                    "SELECT p.id, p.spirit_stones, p.inventory_json, r.local_json, r.service_reputation "
                    "FROM players p JOIN player_reputations r ON r.player_id=p.id "
                    "WHERE p.platform=? AND p.platform_user_id=?",
                    (platform, user_id),
                ).fetchone()
                operation_count = connection.execute(
                    "SELECT COUNT(*) FROM operations WHERE operation_id=?",
                    (delivery_replay.context.operation_id,),
                ).fetchone()[0]
            assert spirit_stones == 118
            assert json.loads(inventory) == {"item.food.coarse_spirit_rice": 3}
            assert json.loads(local_json)["local.xuantian.new_town"] == 3
            assert service == 1
            assert operation_count == 1
            await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("kind", ["onebot", "qq"])
def test_real_adapters_reach_cross_player_service_order(kind: str) -> None:
    pytest.importorskip("nonebot")
    from nonebot_plugin_xiuxian_3.adapters.onebot import normalize_event
    from nonebot_plugin_xiuxian_3.adapters.qq import normalize_event as normalize_qq_event

    def event(text: str, message_id: int, user: str):
        if kind == "onebot":
            return _onebot_event(text, message_id, user_id=3001 if user == "publisher" else 3002)
        return _qq_event(
            text,
            f"service-qq-{message_id}",
            member_openid="qq-publisher" if user == "publisher" else "qq-provider",
        )

    def normalize(raw):
        return normalize_event(raw) if kind == "onebot" else normalize_qq_event(raw)

    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)

            async def dispatch(text: str, message_id: int, user: str):
                normalized = normalize(event(text, message_id, user))
                return await runtime.dispatch(normalized.context, normalized.text)

            assert (await dispatch("开始修仙", 5000, "publisher")).ok
            assert (await dispatch("寻仙问道", 5001, "publisher")).ok
            assert (await dispatch("开始修仙", 5002, "provider")).ok
            assert (await dispatch("寻仙问道", 5003, "provider")).ok
            platform = "onebot.v11" if kind == "onebot" else "qq.official"
            provider_id = "3002" if kind == "onebot" else "qq-provider"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                player_id = connection.execute(
                    "SELECT id FROM players WHERE platform = ? AND platform_user_id = ?",
                    (platform, provider_id),
                ).fetchone()[0]
                connection.execute(
                    "INSERT INTO player_reputations(player_id, service_reputation, updated_at) VALUES (?, 10, ?)",
                    (player_id, "2026-09-22T00:00:00+00:00"),
                )
            published = await dispatch("发布服务 教学采集协助", 5004, "publisher")
            assert published.code == "SERVICE_PUBLISHED"
            order_id = published.data["order_id"]
            accepted = await dispatch(f"接取服务 {order_id}", 5005, "provider")
            assert accepted.code == "SERVICE_ACCEPTED"
            settled = await dispatch(f"结算服务 {order_id}", 5006, "provider")
            assert settled.code == "SERVICE_SETTLED"
            assert settled.data["outputs"] == {"item.herb.blood_grass": 1}
            await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("kind", ["onebot", "qq"])
def test_real_adapters_reach_short_route(kind: str) -> None:
    pytest.importorskip("nonebot")
    from nonebot_plugin_xiuxian_3.adapters.onebot import normalize_event
    from nonebot_plugin_xiuxian_3.adapters.qq import normalize_event as normalize_qq_event

    clock = MutableClock(datetime(2026, 9, 22, tzinfo=timezone.utc))

    def event(text: str, message_id: int):
        if kind == "onebot":
            return _onebot_event(text, message_id, user_id=4001, group_id=4002)
        return _qq_event(text, f"route-qq-{message_id}", member_openid="qq-route-user", group_openid="qq-route-group")

    def normalize(raw):
        return normalize_event(raw) if kind == "onebot" else normalize_qq_event(raw)

    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)

            async def dispatch(text: str, message_id: int):
                normalized = normalize(event(text, message_id))
                return await runtime.dispatch(normalized.context, normalized.text)

            assert (await dispatch("开始修仙", 7000)).ok
            assert (await dispatch("寻仙问道", 7001)).ok
            preview = await dispatch("运输预览 止血草 1", 7002)
            assert preview.code == "ROUTE_PREVIEW"
            started = await dispatch("开始运输 止血草 1", 7003)
            assert started.code == "ROUTE_STARTED"
            clock.advance(minutes=20)
            settled = await dispatch(f"结算运输 {started.data['route_id']}", 7004)
            assert settled.code == "ROUTE_SETTLED"
            assert settled.data["reward_stones"] == 12
            platform = "onebot.v11" if kind == "onebot" else "qq.official"
            user_id = "4001" if kind == "onebot" else "qq-route-user"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                row = connection.execute(
                    "SELECT platform, platform_user_id, location_key FROM players WHERE platform = ? AND platform_user_id = ?",
                    (platform, user_id),
                ).fetchone()
            assert row == (platform, user_id, "xuantian.outskirts")
            await runtime.close()

    asyncio.run(run())
