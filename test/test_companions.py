from __future__ import annotations

import asyncio
import json
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.companions.rules import mount_transport_injury_roll_bp


def _context(adapter: str, user: str, operation: str, message: str) -> CommandContext:
    return CommandContext(
        adapter=adapter,
        user_id=user,
        scene_id="private",
        message_id=message,
        operation_id=operation,
    )


async def _prepare(runtime, *, adapter: str, user: str) -> None:
    created = await runtime.dispatch(_context(adapter, user, f"{adapter}:create", "create"), "开始修仙")
    assert created.ok
    await runtime.repository.initialize()
    with runtime.repository._connect() as connection:
        connection.execute(
            "UPDATE players SET location_key = ?, inventory_json = ? WHERE platform = ? AND platform_user_id = ?",
            (
                "xuantian.outskirts",
                json.dumps({"item.food.coarse_spirit_rice": 2, "beast.gear.sack_small": 1}),
                adapter,
                user,
            ),
        )


def test_companion_flow_is_shared_by_qq_and_onebot_and_survives_restart() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            await _prepare(runtime, adapter="qq.official", user="qq-user")
            await _prepare(runtime, adapter="onebot.v11", user="ob-user")

            qq_bond = await runtime.dispatch(
                _context("qq.official", "qq-user", "qq:bond", "bond"),
                "结缘灵兽 beast.wood_rat",
            )
            ob_bond = await runtime.dispatch(
                _context("onebot.v11", "ob-user", "ob:bond", "bond"),
                "结缘灵兽 beast.wood_rat",
            )
            assert qq_bond.code == "COMPANION_BONDED"
            assert ob_bond.code == "COMPANION_BONDED"

            qq_feed_context = _context("qq.official", "qq-user", "qq:feed", "feed")
            first = await runtime.dispatch(qq_feed_context, f"喂养灵兽 {qq_bond.data['instance_id']}")
            replay = await runtime.dispatch(
                _context("qq.official", "qq-user", "qq:feed", "feed-retry"),
                f"喂养灵兽 {qq_bond.data['instance_id']}",
            )
            assert first.code == "COMPANION_FED"
            assert first.data["experience"] == 10
            assert replay.data["experience"] == 10
            assert replay.data["idempotent_replay"] is True

            gear = await runtime.dispatch(
                _context("onebot.v11", "ob-user", "ob:gear", "gear"),
                f"装备灵具 {ob_bond.data['instance_id']} beast.gear.sack_small",
            )
            assert gear.code == "COMPANION_GEAR_EQUIPPED"

            await runtime.close()
            runtime = create_runtime(data_dir=data_dir)
            restored = await runtime.dispatch(
                _context("onebot.v11", "ob-user", "ob:status", "status"), "灵兽状态"
            )
            assert restored.code == "COMPANION_STATUS"
            assert restored.data["companions"][0]["companion_key"] == "beast.wood_rat"
            assert restored.data["companions"][0]["gear"][0]["gear_key"] == "beast.gear.sack_small"
            await runtime.close()

    asyncio.run(run())


def test_companion_battle_snapshot_is_detached_and_read_only() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            await _prepare(runtime, adapter="onebot.v11", user="u")
            bonded = await runtime.dispatch(
                _context("onebot.v11", "u", "bond", "bond"), "结缘灵兽 beast.wood_rat"
            )
            await runtime.repository.initialize()
            with runtime.repository._connect() as connection:
                player = connection.execute(
                    "SELECT id FROM players WHERE platform = ? AND platform_user_id = ?",
                    ("onebot.v11", "u"),
                ).fetchone()
                snapshot = runtime.repository.companion_battle_snapshot(connection, player["id"])
                snapshot.companions[0]["effect"]["value"] = 9999
            status = await runtime.dispatch(
                _context("onebot.v11", "u", "status", "status"), "灵兽状态"
            )
            assert status.data["companions"][0]["level"] == 1
            assert bonded.data["instance_id"] == status.data["companions"][0]["instance_id"]
            await runtime.close()

    asyncio.run(run())


def test_companion_evolution_is_atomic_idempotent_and_shared_by_adapters() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            await _prepare(runtime, adapter="qq.official", user="evolve-qq")
            await _prepare(runtime, adapter="onebot.v11", user="evolve-ob")
            for adapter, user in (("qq.official", "evolve-qq"), ("onebot.v11", "evolve-ob")):
                with runtime.repository._connect() as connection:
                    connection.execute(
                        "UPDATE players SET spirit_stones=500, inventory_json=? WHERE platform=? AND platform_user_id=?",
                        (json.dumps({"item.ancient_fruit": 3}), adapter, user),
                    )
            bonded = await runtime.dispatch(
                _context("qq.official", "evolve-qq", "evolve-bond", "bond"),
                "结缘灵兽 beast.wood_rat",
            )
            instance_id = bonded.data["instance_id"]
            with runtime.repository._connect() as connection:
                connection.execute(
                    "UPDATE companion_instances SET level=10, affinity=40 WHERE instance_id=?",
                    (instance_id,),
                )
            evolved = await runtime.dispatch(
                _context("qq.official", "evolve-qq", "evolve-op", "evolve"),
                f"蜕变灵兽 {instance_id}",
            )
            assert evolved.code == "COMPANION_EVOLVED"
            assert evolved.data["companion_key"] == "beast.iron_rat"
            replay = await runtime.dispatch(
                _context("qq.official", "evolve-qq", "evolve-op", "evolve-retry"),
                f"蜕变灵兽 {instance_id}",
            )
            assert replay.code == "COMPANION_EVOLVED"
            assert replay.data["idempotent_replay"] is True
            with runtime.repository._connect() as connection:
                stored = connection.execute(
                    "SELECT spirit_stones, inventory_json, companion_key, evolution_stage, skill_slots FROM players JOIN companion_instances ON companion_instances.player_id=players.id WHERE companion_instances.instance_id=?",
                    (instance_id,),
                ).fetchone()
            assert stored[0] == 200
            assert json.loads(stored[1]) == {}
            assert tuple(stored[2:]) == ("beast.iron_rat", "evolved", 1)
            conflict = await runtime.dispatch(
                _context("qq.official", "evolve-qq", "evolve-op", "evolve-conflict"),
                "蜕变灵兽 missing-companion",
            )
            assert conflict.code == "OPERATION_CONFLICT"
            ob_bond = await runtime.dispatch(
                _context("onebot.v11", "evolve-ob", "ob-bond", "bond"),
                "结缘灵兽 beast.wood_rat",
            )
            with runtime.repository._connect() as connection:
                connection.execute(
                    "UPDATE companion_instances SET level=10, affinity=40 WHERE instance_id=?",
                    (ob_bond.data["instance_id"],),
                )
            ob_evolved = await runtime.dispatch(
                _context("onebot.v11", "evolve-ob", "ob-evolve", "evolve"),
                f"灵兽蜕变 {ob_bond.data['instance_id']}",
            )
            assert ob_evolved.code == "COMPANION_EVOLVED"
            await runtime.close()
            runtime = create_runtime(data_dir=data_dir)
            restored = await runtime.dispatch(
                _context("onebot.v11", "evolve-ob", "ob-status", "status"), "灵兽状态"
            )
            assert restored.code == "COMPANION_STATUS"
            assert restored.data["companions"][0]["companion_key"] == "beast.iron_rat"
            await runtime.close()

    asyncio.run(run())


def test_companion_evolution_rejects_missing_assets_without_partial_changes() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            await _prepare(runtime, adapter="qq.official", user="evolve-poor")
            bonded = await runtime.dispatch(
                _context("qq.official", "evolve-poor", "poor-bond", "bond"),
                "结缘灵兽 beast.wood_rat",
            )
            instance_id = bonded.data["instance_id"]
            with runtime.repository._connect() as connection:
                connection.execute(
                    "UPDATE companion_instances SET level=10, affinity=40 WHERE instance_id=?",
                    (instance_id,),
                )
                before = connection.execute(
                    "SELECT spirit_stones, inventory_json, companion_key FROM players JOIN companion_instances ON companion_instances.player_id=players.id WHERE companion_instances.instance_id=?",
                    (instance_id,),
                ).fetchone()
            result = await runtime.dispatch(
                _context("qq.official", "evolve-poor", "poor-evolve", "evolve"),
                f"蜕变灵兽 {instance_id}",
            )
            assert result.code == "COMPANION_EVOLUTION_INSUFFICIENT"
            with runtime.repository._connect() as connection:
                after = connection.execute(
                    "SELECT spirit_stones, inventory_json, companion_key FROM players JOIN companion_instances ON companion_instances.player_id=players.id WHERE companion_instances.instance_id=?",
                    (instance_id,),
                ).fetchone()
            assert tuple(after) == tuple(before)
            await runtime.close()

    asyncio.run(run())


def test_mount_transport_lifecycle_is_atomic_idempotent_and_recovers_across_adapters() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            users = (("qq.official", "mount-qq"), ("onebot.v11", "mount-ob"))
            mount_ids: dict[str, str] = {}
            for adapter, user in users:
                await _prepare(runtime, adapter=adapter, user=user)
                seeking = await runtime.dispatch(
                    _context(adapter, user, f"{user}:seek", "seek"),
                    "寻仙问道",
                )
                assert seeking.ok
                with runtime.repository._connect() as connection:
                    player = connection.execute(
                        "SELECT id FROM players WHERE platform = ? AND platform_user_id = ?",
                        (adapter, user),
                    ).fetchone()
                    connection.execute(
                        "UPDATE players SET location_key = 'xuantian.new_town', inventory_json = ? WHERE id = ?",
                        (json.dumps({"item.herb.blood_grass": 2, "mount.tack.bamboo_saddle": 1}), player["id"]),
                    )
                    connection.execute(
                        "INSERT INTO activity_events(player_id, event_key, source_operation_id, occurred_at) VALUES (?, ?, ?, ?)",
                        (player["id"], "story.mainline.xuantian", f"seed-{user}", "2026-01-01T00:00:00+00:00"),
                    )
                bonded = await runtime.dispatch(
                    _context(adapter, user, f"{user}:bond", "bond"),
                    "结缘灵骑 mount.bamboo_deer",
                )
                assert bonded.code == "COMPANION_BONDED"
                mount_ids[user] = str(bonded.data["instance_id"])
                equipped = await runtime.dispatch(
                    _context(adapter, user, f"{user}:gear", "gear"),
                    f"装备灵具 {mount_ids[user]} mount.tack.bamboo_saddle",
                )
                assert equipped.code == "COMPANION_GEAR_EQUIPPED"
                preview = await runtime.dispatch(
                    _context(adapter, user, f"{user}:preview", "preview"),
                    f"运输预览 止血草 1 {mount_ids[user]}",
                )
                assert preview.code == "ROUTE_PREVIEW"
                assert preview.data["mount_stamina_cost"] == 1
                assert preview.data["duration_seconds"] < 600

            operation_id = "mount-route-start"
            while mount_transport_injury_roll_bp(operation_id) < 1000:
                operation_id += "-retry"
            started = await runtime.dispatch(
                _context("qq.official", "mount-qq", operation_id, "start"),
                f"开始运输 止血草 1 {mount_ids['mount-qq']}",
            )
            assert started.code == "ROUTE_STARTED"
            replay = await runtime.dispatch(
                _context("qq.official", "mount-qq", operation_id, "start-retry"),
                f"开始运输 止血草 1 {mount_ids['mount-qq']}",
            )
            assert replay.data["idempotent_replay"] is True
            conflict = await runtime.dispatch(
                _context("qq.official", "mount-qq", operation_id, "start-conflict"),
                f"开始运输 止血草 2 {mount_ids['mount-qq']}",
            )
            assert conflict.code == "OPERATION_CONFLICT"
            with runtime.repository._connect() as connection:
                mid = connection.execute(
                    "SELECT status, stamina FROM companion_instances WHERE instance_id = ?",
                    (mount_ids["mount-qq"],),
                ).fetchone()
                assert tuple(mid) == ("travelling", 19)
                connection.execute(
                    "UPDATE livelihood_trade_routes SET arrives_at = '2000-01-01T00:00:00+00:00' WHERE route_id = ?",
                    (started.data["route_id"],),
                )
            await runtime.close()
            runtime = create_runtime(data_dir=data_dir)
            settled = await runtime.dispatch(
                _context("qq.official", "mount-qq", "mount-route-settle", "settle"),
                f"结算运输 {started.data['route_id']}",
            )
            assert settled.code == "ROUTE_SETTLED"
            assert settled.data["mount_experience"] == 5
            replay_settled = await runtime.dispatch(
                _context("qq.official", "mount-qq", "mount-route-settle", "settle-retry"),
                f"结算运输 {started.data['route_id']}",
            )
            assert replay_settled.data["idempotent_replay"] is True
            with runtime.repository._connect() as connection:
                final = connection.execute(
                    "SELECT status, stamina, experience, level FROM companion_instances WHERE instance_id = ?",
                    (mount_ids["mount-qq"],),
                ).fetchone()
            assert tuple(final) == ("available", 19, 5, 1)
            injury_operation = "mount-injury"
            while mount_transport_injury_roll_bp(injury_operation) >= 1000:
                injury_operation += "-retry"
            injured_start = await runtime.dispatch(
                _context("onebot.v11", "mount-ob", injury_operation, "injury-start"),
                f"开始运输 止血草 1 {mount_ids['mount-ob']}",
            )
            assert injured_start.code == "ROUTE_STARTED"
            with runtime.repository._connect() as connection:
                connection.execute(
                    "UPDATE livelihood_trade_routes SET arrives_at = '2000-01-01T00:00:00+00:00' WHERE route_id = ?",
                    (injured_start.data["route_id"],),
                )
            injured_settlement = await runtime.dispatch(
                _context("onebot.v11", "mount-ob", "mount-injury-settle", "injury-settle"),
                f"结算运输 {injured_start.data['route_id']}",
            )
            assert injured_settlement.code == "ROUTE_SETTLED"
            assert injured_settlement.data["mount_name"] == "竹鹿"
            with runtime.repository._connect() as connection:
                connection.execute(
                    "UPDATE companion_instances SET injury_until = '2000-01-01T00:00:00+00:00' WHERE instance_id = ?",
                    (mount_ids["mount-ob"],),
                )
            rested = await runtime.dispatch(
                _context("onebot.v11", "mount-ob", "mount-injury-rest", "injury-rest"),
                f"休养灵兽 {mount_ids['mount-ob']}",
            )
            assert rested.code == "COMPANION_RESTED"
            await runtime.close()

    asyncio.run(run())
