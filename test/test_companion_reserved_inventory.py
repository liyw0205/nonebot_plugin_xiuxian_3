from __future__ import annotations

import asyncio
import json
from tempfile import TemporaryDirectory

import pytest

from nonebot_plugin_xiuxian_3.runtime import create_runtime
from test_companions import _context, _prepare


@pytest.mark.parametrize(
    ("adapter", "user"),
    (("qq.official", "qq-seller"), ("onebot.v11", "ob-seller")),
)
def test_companion_feed_preserves_reserved_inventory_and_retries_same_operation(
    adapter: str, user: str
) -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, adapters=(adapter,))
            await _prepare(runtime, adapter=adapter, user=user)
            with runtime.repository._connect() as connection:
                connection.execute(
                    "UPDATE players SET inventory_json = ?, spirit_stones = 1000 "
                    "WHERE platform = ? AND platform_user_id = ?",
                    (json.dumps({"item.food.coarse_spirit_rice": 1}), adapter, user),
                )

            bonded = await runtime.dispatch(
                _context(adapter, user, f"{user}:bond", "bond"),
                "结缘灵兽 beast.wood_rat",
            )
            assert bonded.code == "COMPANION_BONDED"

            listing = await runtime.dispatch(
                _context(adapter, user, f"{user}:listing", "listing"),
                "发布摆摊 item.food.coarse_spirit_rice 1 100",
            )
            assert listing.code == "MARKET_ORDER_CREATED"

            with runtime.repository._connect() as connection:
                database_before_feed = tuple(connection.iterdump())
                player_id = connection.execute(
                    "SELECT id FROM players WHERE platform = ? AND platform_user_id = ?",
                    (adapter, user),
                ).fetchone()["id"]
                experience_before = connection.execute(
                    "SELECT experience FROM companion_instances WHERE instance_id = ?",
                    (bonded.data["instance_id"],),
                ).fetchone()["experience"]

            feed_context = _context(adapter, user, "feed", "feed")
            rejected = await runtime.dispatch(
                feed_context,
                f"喂养灵兽 {bonded.data['instance_id']}",
            )
            assert rejected.code == "COMPANION_FEED_INSUFFICIENT"

            with runtime.repository._connect() as connection:
                assert tuple(connection.iterdump()) == database_before_feed
                assert connection.execute(
                    "SELECT COUNT(*) FROM operations WHERE operation_id = 'feed'"
                ).fetchone()[0] == 0
                assert connection.execute(
                    "SELECT experience FROM companion_instances WHERE instance_id = ?",
                    (bonded.data["instance_id"],),
                ).fetchone()["experience"] == experience_before
                assert json.loads(
                    connection.execute(
                        "SELECT inventory_json FROM players WHERE id = ?", (player_id,)
                    ).fetchone()["inventory_json"]
                ) == {"item.food.coarse_spirit_rice": 1}
                assert tuple(
                    connection.execute(
                        "SELECT status, remaining_quantity FROM market_orders WHERE order_id = ?",
                        (listing.data["order_id"],),
                    ).fetchone()
                ) == ("listed", 1)
                assert connection.execute(
                    "SELECT quantity FROM market_item_locks WHERE order_id = ?",
                    (listing.data["order_id"],),
                ).fetchone()["quantity"] == 1

            cancelled = await runtime.dispatch(
                _context(adapter, user, f"{user}:cancel", "cancel"),
                f"取消摆摊 {listing.data['order_id']}",
            )
            assert cancelled.code == "MARKET_ORDER_CANCELLED"

            with runtime.repository._connect() as connection:
                assert connection.execute(
                    "SELECT COUNT(*) FROM market_item_locks WHERE order_id = ?",
                    (listing.data["order_id"],),
                ).fetchone()[0] == 0

            fed = await runtime.dispatch(
                feed_context,
                f"喂养灵兽 {bonded.data['instance_id']}",
            )
            replay = await runtime.dispatch(
                _context(adapter, user, "feed", "feed-retry"),
                f"喂养灵兽 {bonded.data['instance_id']}",
            )
            assert fed.code == "COMPANION_FED"
            assert fed.data["idempotent_replay"] is False
            assert replay.code == "COMPANION_FED"
            assert replay.data["idempotent_replay"] is True

            with runtime.repository._connect() as connection:
                assert json.loads(
                    connection.execute(
                        "SELECT inventory_json FROM players WHERE id = ?", (player_id,)
                    ).fetchone()["inventory_json"]
                ) == {}
                assert connection.execute(
                    "SELECT experience FROM companion_instances WHERE instance_id = ?",
                    (bonded.data["instance_id"],),
                ).fetchone()["experience"] == experience_before + 10
                assert connection.execute(
                    "SELECT COUNT(*) FROM operations WHERE operation_id = 'feed'"
                ).fetchone()[0] == 1
                assert tuple(
                    connection.execute(
                        "SELECT status, remaining_quantity FROM market_orders WHERE order_id = ?",
                        (listing.data["order_id"],),
                    ).fetchone()
                ) == ("cancelled", 1)
                assert connection.execute(
                    "SELECT COUNT(*) FROM market_item_locks WHERE order_id = ?",
                    (listing.data["order_id"],),
                ).fetchone()[0] == 0
                state_before_restart = tuple(
                    connection.execute(
                        "SELECT spirit_stones, inventory_json, experience FROM players "
                        "JOIN companion_instances ON companion_instances.player_id = players.id "
                        "WHERE companion_instances.instance_id = ?",
                        (bonded.data["instance_id"],),
                    ).fetchone()
                )
                order_before_restart = tuple(
                    connection.execute(
                        "SELECT status, remaining_quantity FROM market_orders WHERE order_id = ?",
                        (listing.data["order_id"],),
                    ).fetchone()
                )

            await runtime.close()
            runtime = create_runtime(data_dir=data_dir, adapters=(adapter,))
            restored_replay = await runtime.dispatch(
                _context(adapter, user, "feed", "feed-after-restart"),
                f"喂养灵兽 {bonded.data['instance_id']}",
            )
            assert restored_replay.code == "COMPANION_FED"
            assert restored_replay.data["idempotent_replay"] is True
            with runtime.repository._connect() as connection:
                assert tuple(
                    connection.execute(
                        "SELECT spirit_stones, inventory_json, experience FROM players "
                        "JOIN companion_instances ON companion_instances.player_id = players.id "
                        "WHERE companion_instances.instance_id = ?",
                        (bonded.data["instance_id"],),
                    ).fetchone()
                ) == state_before_restart
                assert tuple(
                    connection.execute(
                        "SELECT status, remaining_quantity FROM market_orders WHERE order_id = ?",
                        (listing.data["order_id"],),
                    ).fetchone()
                ) == order_before_restart
                assert connection.execute(
                    "SELECT COUNT(*) FROM operations WHERE operation_id = 'feed'"
                ).fetchone()[0] == 1
            await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize(
    ("adapter", "user"),
    (("qq.official", "qq-evolve"), ("onebot.v11", "ob-evolve")),
)
def test_companion_evolution_preserves_reserved_assets_and_retries_same_operation(
    adapter: str, user: str
) -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, adapters=(adapter,))
            await _prepare(runtime, adapter=adapter, user=user)
            with runtime.repository._connect() as connection:
                connection.execute(
                    "UPDATE players SET inventory_json = ?, spirit_stones = 1000 "
                    "WHERE platform = ? AND platform_user_id = ?",
                    (json.dumps({"item.ancient_fruit": 3}), adapter, user),
                )

            bonded = await runtime.dispatch(
                _context(adapter, user, f"{user}:bond", "bond"),
                "结缘灵兽 beast.wood_rat",
            )
            assert bonded.code == "COMPANION_BONDED"
            instance_id = bonded.data["instance_id"]
            with runtime.repository._connect() as connection:
                connection.execute(
                    "UPDATE companion_instances SET level = 10, affinity = 40 "
                    "WHERE instance_id = ?",
                    (instance_id,),
                )

            listing = await runtime.dispatch(
                _context(adapter, user, f"{user}:listing", "listing"),
                "发布摆摊 item.ancient_fruit 3 100",
            )
            assert listing.code == "MARKET_ORDER_CREATED"

            with runtime.repository._connect() as connection:
                database_before_evolution = tuple(connection.iterdump())
                before = connection.execute(
                    "SELECT spirit_stones, inventory_json, companion_key, evolution_stage, level, affinity "
                    "FROM players JOIN companion_instances ON companion_instances.player_id = players.id "
                    "WHERE companion_instances.instance_id = ?",
                    (instance_id,),
                ).fetchone()

            evolve_context = _context(adapter, user, "evolve", "evolve")
            rejected = await runtime.dispatch(
                evolve_context,
                f"蜕变灵兽 {instance_id}",
            )
            assert rejected.code == "COMPANION_EVOLUTION_INSUFFICIENT"

            with runtime.repository._connect() as connection:
                assert tuple(connection.iterdump()) == database_before_evolution
                assert connection.execute(
                    "SELECT COUNT(*) FROM operations WHERE operation_id = 'evolve'"
                ).fetchone()[0] == 0
                after = connection.execute(
                    "SELECT spirit_stones, inventory_json, companion_key, evolution_stage, level, affinity "
                    "FROM players JOIN companion_instances ON companion_instances.player_id = players.id "
                    "WHERE companion_instances.instance_id = ?",
                    (instance_id,),
                ).fetchone()
                assert tuple(after) == tuple(before)
                assert tuple(
                    connection.execute(
                        "SELECT status, remaining_quantity FROM market_orders WHERE order_id = ?",
                        (listing.data["order_id"],),
                    ).fetchone()
                ) == ("listed", 3)
                assert connection.execute(
                    "SELECT quantity FROM market_item_locks WHERE order_id = ?",
                    (listing.data["order_id"],),
                ).fetchone()["quantity"] == 3

            cancelled = await runtime.dispatch(
                _context(adapter, user, f"{user}:cancel", "cancel"),
                f"取消摆摊 {listing.data['order_id']}",
            )
            assert cancelled.code == "MARKET_ORDER_CANCELLED"

            with runtime.repository._connect() as connection:
                assert connection.execute(
                    "SELECT COUNT(*) FROM market_item_locks WHERE order_id = ?",
                    (listing.data["order_id"],),
                ).fetchone()[0] == 0

            evolved = await runtime.dispatch(
                evolve_context,
                f"蜕变灵兽 {instance_id}",
            )
            replay = await runtime.dispatch(
                _context(adapter, user, "evolve", "evolve-retry"),
                f"蜕变灵兽 {instance_id}",
            )
            assert evolved.code == "COMPANION_EVOLVED"
            assert evolved.data["idempotent_replay"] is False
            assert evolved.data["spent"] == {
                "item.ancient_fruit": 3,
                "currency.spirit_stone": 300,
            }
            assert replay.code == "COMPANION_EVOLVED"
            assert replay.data["idempotent_replay"] is True

            with runtime.repository._connect() as connection:
                after_replay = connection.execute(
                    "SELECT spirit_stones, inventory_json, companion_key, evolution_stage, level, affinity "
                    "FROM players JOIN companion_instances ON companion_instances.player_id = players.id "
                    "WHERE companion_instances.instance_id = ?",
                    (instance_id,),
                ).fetchone()
                assert tuple(after_replay) == (
                    before["spirit_stones"] - 300,
                    "{}",
                    "beast.iron_rat",
                    "evolved",
                    10,
                    40,
                )
                assert connection.execute(
                    "SELECT COUNT(*) FROM operations WHERE operation_id = 'evolve'"
                ).fetchone()[0] == 1
                assert tuple(
                    connection.execute(
                        "SELECT status, remaining_quantity FROM market_orders WHERE order_id = ?",
                        (listing.data["order_id"],),
                    ).fetchone()
                ) == ("cancelled", 3)
                assert connection.execute(
                    "SELECT COUNT(*) FROM market_item_locks WHERE order_id = ?",
                    (listing.data["order_id"],),
                ).fetchone()[0] == 0
                state_before_restart = tuple(after_replay)

            await runtime.close()
            runtime = create_runtime(data_dir=data_dir, adapters=(adapter,))
            restored_replay = await runtime.dispatch(
                _context(adapter, user, "evolve", "evolve-after-restart"),
                f"蜕变灵兽 {instance_id}",
            )
            assert restored_replay.code == "COMPANION_EVOLVED"
            assert restored_replay.data["idempotent_replay"] is True
            with runtime.repository._connect() as connection:
                after_restart = connection.execute(
                    "SELECT spirit_stones, inventory_json, companion_key, evolution_stage, level, affinity "
                    "FROM players JOIN companion_instances ON companion_instances.player_id = players.id "
                    "WHERE companion_instances.instance_id = ?",
                    (instance_id,),
                ).fetchone()
                assert tuple(after_restart) == state_before_restart
                assert tuple(
                    connection.execute(
                        "SELECT status, remaining_quantity FROM market_orders WHERE order_id = ?",
                        (listing.data["order_id"],),
                    ).fetchone()
                ) == ("cancelled", 3)
                assert connection.execute(
                    "SELECT COUNT(*) FROM market_item_locks WHERE order_id = ?",
                    (listing.data["order_id"],),
                ).fetchone()[0] == 0
                assert connection.execute(
                    "SELECT COUNT(*) FROM operations WHERE operation_id = 'evolve'"
                ).fetchone()[0] == 1
            await runtime.close()

    asyncio.run(run())
