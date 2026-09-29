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
from nonebot_plugin_xiuxian_3.xiuxian.content import bundled_content
from nonebot_plugin_xiuxian_3.xiuxian.adventures.rules import (
    _reward_outcomes,
    bounty_definition,
    meets_realm,
    reward_map,
)


def _context(user_id: str, request_id: str, *, operation_id: str = "") -> CommandContext:
    return CommandContext(
        adapter="web",
        user_id=user_id,
        request_id=request_id,
        operation_id=operation_id,
    )


async def _enter_mortal(runtime, user_id: str) -> None:
    assert (await runtime.dispatch(_context(user_id, "create"), "开始修仙")).ok
    assert (await runtime.dispatch(_context(user_id, "seek"), "寻仙问道")).ok


async def _enter_alchemy(runtime, user_id: str) -> None:
    commands = (
        "开始修仙",
        "寻仙问道",
        "完成引导 阅读",
        "前往近郊",
        "完成引导 采集",
        "完成引导 炼丹",
        "选择道途 辅修 炼丹",
    )
    for index, command in enumerate(commands):
        result = await runtime.dispatch(_context(user_id, f"setup-{index}"), command)
        assert result.ok, (command, result.code, result.message)


def _inventory(runtime, user_id: str, **changes: int) -> None:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        row = connection.execute(
            "SELECT inventory_json FROM players WHERE platform_user_id = ?",
            (user_id,),
        ).fetchone()
        inventory = json.loads(row[0])
        for key, quantity in changes.items():
            inventory[key] = int(inventory.get(key, 0)) + quantity
        connection.execute(
            "UPDATE players SET inventory_json = ? WHERE platform_user_id = ?",
            (json.dumps(inventory, ensure_ascii=False, sort_keys=True), user_id),
        )


def _finish_order(runtime, order_id: str) -> None:
    old = datetime.now(timezone.utc) - timedelta(seconds=1)
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE production_orders SET starts_at = ?, ends_at = ? WHERE order_id = ?",
            ((old - timedelta(seconds=30)).isoformat(), old.isoformat(), order_id),
        )


def test_bounty_reward_pools_can_select_new_gear_and_manual_content() -> None:
    void = bounty_definition("bounty.void_anchoring")
    void_rewards = [reward_map(void, seed=f"void:{seed}") for seed in range(500)]
    assert any("item.manual.dao_union_mysteries" in reward for reward in void_rewards)
    assert any("item.weapon.primal_creation_sword" in reward for reward in void_rewards)
    assert any("item.armor.chaos_immortal_raiment" in reward for reward in void_rewards)


def test_accessory_reward_pools_cover_all_paths_and_open_realms() -> None:
    content = bundled_content()
    sources = (
        ("foundation", "reward_pool.bounty.cloud_mine"),
        ("golden_core", "reward_pool.bounty.elite_hunt"),
        ("nascent_soul", "reward_pool.bounty.elite_hunt"),
        ("soul_transformation", "reward_pool.bounty.elite_hunt"),
        ("void_refining", "reward_pool.bounty.void_anchoring"),
        ("dao_union", "reward_pool.bounty.void_anchoring"),
        ("tribulation", "reward_pool.bounty.void_anchoring"),
    )
    for path_key in ("body", "spell", "device", "demonic", "beast", "support"):
        for realm_key, pool_key in sources:
            outcomes = _reward_outcomes(
                content,
                pool_key,
                path_key=path_key,
                realm_key=realm_key,
                realm_layer=1,
            )
            accessory_keys = {
                key
                for outcome in outcomes
                for key in outcome["rewards"]
                if key.startswith("item.accessory.")
            }
            assert accessory_keys, (path_key, realm_key, pool_key)
            for item_key in accessory_keys:
                item = content.require("item", item_key, include_locked=False)
                assert item["path_key"] == path_key
                requirement = next(row for row in item["requirements"] if row["type"] == "realm")
                assert meets_realm(
                    realm_key,
                    1,
                    requirement["realm_key"],
                    requirement["min_layer"],
                    content,
                )


def test_equipment_quality_rewards_select_path_and_realm_eligible_gear() -> None:
    content = bundled_content()
    for path_key in ("body", "spell", "device", "demonic", "beast", "support"):
        for realm_key, pool_key in (
            ("foundation", "reward_pool.bounty.cloud_mine"),
            ("golden_core", "reward_pool.bounty.elite_hunt"),
            ("nascent_soul", "reward_pool.bounty.elite_hunt"),
            ("soul_transformation", "reward_pool.bounty.elite_hunt"),
            ("void_refining", "reward_pool.bounty.void_anchoring"),
            ("dao_union", "reward_pool.bounty.void_anchoring"),
            ("tribulation", "reward_pool.bounty.void_anchoring"),
        ):
            outcomes = _reward_outcomes(
                content,
                pool_key,
                path_key=path_key,
                realm_key=realm_key,
                realm_layer=1,
            )
            gear = {
                key
                for outcome in outcomes
                for key in outcome["rewards"]
                if key.startswith(("item.weapon.", "item.armor."))
            }
            weapons = {key for key in gear if key.startswith("item.weapon.")}
            armors = {key for key in gear if key.startswith("item.armor.")}
            assert weapons, ("weapon", path_key, realm_key, pool_key)
            assert armors, ("armor", path_key, realm_key, pool_key)
            assert any(content.require("item", key).get("path_key") == path_key for key in weapons)
            assert any(content.require("item", key).get("path_key") == path_key for key in armors)
            for item_key in gear:
                item = content.require("item", item_key, include_locked=False)
                assert item.get("path_key") in {None, path_key}
                requirement = next(
                    (row for row in item["requirements"] if row["type"] == "realm"),
                    None,
                )
                assert requirement is None or meets_realm(
                    realm_key,
                    1,
                    requirement["realm_key"],
                    requirement["min_layer"],
                    content,
                )


def test_equipment_rewards_follow_path_and_realm_and_create_instances() -> None:
    async def run(data_dir: Path) -> None:
        reward_path = data_dir / "奖励" / "奖励.json"
        rewards = json.loads(reward_path.read_text(encoding="utf-8"))
        pool = next(
            record
            for record in rewards["records"]
            if record.get("key") == "reward_pool.bounty.herb_supply"
        )
        pool["equipment_reward_qualities"] = {}
        pool["outcomes"] = [
            {
                "weight": 1,
                "rewards": {
                    "item.accessory.body.stone_pulse_bracer": 1,
                    "item.weapon.body.pulse_edge": 1,
                    "item.armor.body.stoneheart_guard": 1,
                },
            }
        ]
        reward_path.write_text(json.dumps(rewards, ensure_ascii=False, indent=2), encoding="utf-8")

        runtime = create_runtime(data_dir=data_dir)
        user = "bounty-accessory-instance"
        await _enter_mortal(runtime, user)
        with sqlite3.connect(runtime.settings.database_path) as connection:
            connection.execute(
                "UPDATE players SET stage='cultivator', realm_key='qi_sensing', realm_layer=1, path_key='body' "
                "WHERE platform='web' AND platform_user_id=?",
                (user,),
            )
        accepted = await runtime.dispatch(_context(user, "accept"), "接取悬赏 草药补给")
        assert accepted.code == "BOUNTY_ACCEPTED"
        _inventory(runtime, user, **{"item.herb.blood_grass": 5})
        claimed = await runtime.dispatch(_context(user, "claim"), "领取悬赏")
        assert claimed.code == "BOUNTY_CLAIMED"
        assert claimed.data["rewards"] == {
            "item.accessory.body.stone_pulse_bracer": 1,
            "item.weapon.body.pulse_edge": 1,
            "item.armor.body.stoneheart_guard": 1,
        }
        with sqlite3.connect(runtime.settings.database_path) as connection:
            items = connection.execute(
                "SELECT item_key, slot FROM equipment_instances "
                "WHERE player_id=(SELECT id FROM players WHERE platform='web' AND platform_user_id=?) "
                "ORDER BY item_key",
                (user,),
            ).fetchall()
        assert items == [
            ("item.accessory.body.stone_pulse_bracer", "accessory"),
            ("item.armor.body.stoneheart_guard", "armor"),
            ("item.weapon.body.pulse_edge", "weapon"),
        ]

        started = await runtime.dispatch(_context(user, "equipment-combat"), "开始训练战")
        assert started.code == "BATTLE_SETTLED"
        replay = await runtime.dispatch(_context(user, "equipment-combat-replay"), "战斗回放")
        snapshot = replay.data["snapshot"]["player"]
        equipment_keys = {item["item_key"] for item in snapshot["equipment"]}
        assert {
            "item.accessory.body.stone_pulse_bracer",
            "item.armor.body.stoneheart_guard",
            "item.weapon.body.pulse_edge",
        } <= equipment_keys
        assert snapshot["stats"]["accuracy_bp"] >= 190
        assert snapshot["stats"]["damage_reduction_bp"] >= 110
        await runtime.close()

    with TemporaryDirectory() as directory:
        data_dir = Path(directory) / "data"
        shutil.copytree(Path(__file__).parents[1] / "data", data_dir)
        asyncio.run(run(data_dir))


def test_bounty_board_herb_claim_replay_and_reputation() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            user = "bounty-herb"
            await _enter_mortal(runtime, user)

            board = await runtime.dispatch(_context(user, "board"), "悬赏榜")
            assert board.code == "BOUNTY_BOARD"
            assert "草药补给" in board.message
            assert "前置不足" in board.message
            assert board.data["offers"][0]["status"] == "available"

            accepted = await runtime.dispatch(
                _context(user, "accept", operation_id="bounty-accept-1"),
                "接取悬赏 草药补给",
            )
            assert accepted.code == "BOUNTY_ACCEPTED"
            assert accepted.data["progress"] == 0
            _inventory(runtime, user, **{"item.herb.blood_grass": 5})

            claimed = await runtime.dispatch(
                _context(user, "claim", operation_id="bounty-claim-1"),
                "领取悬赏",
            )
            assert claimed.code == "BOUNTY_CLAIMED"
            assert claimed.data["rewards"] in (
                {"spirit_stones": 30, "local_reputation": 2},
                {"spirit_stones": 45, "local_reputation": 1},
            )
            replay = await runtime.dispatch(
                _context(user, "claim-replay", operation_id="bounty-claim-1"),
                "领取悬赏",
            )
            assert replay.data["idempotent_replay"] is True
            assert replay.data["rewards"] == claimed.data["rewards"]
            duplicate = await runtime.dispatch(_context(user, "claim-again"), "领取悬赏")
            assert duplicate.code == "BOUNTY_REWARD_ALREADY_CLAIMED"

            with sqlite3.connect(runtime.settings.database_path) as connection:
                reputation = connection.execute(
                    "SELECT local_json, service_reputation FROM player_reputations WHERE player_id = (SELECT id FROM players WHERE platform_user_id = ?)",
                    (user,),
                ).fetchone()
                assert json.loads(reputation[0])["local.xuantian.new_town"] == claimed.data["rewards"]["local_reputation"]
                assert reputation[1] == 0
            await runtime.close()

    asyncio.run(run())


def test_bounty_progress_guards_expiry_and_operation_conflict() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            user = "bounty-guards"
            await _enter_mortal(runtime, user)
            accepted = await runtime.dispatch(
                _context(user, "accept", operation_id="bounty-op"),
                "接取悬赏 草药补给",
            )
            assert accepted.code == "BOUNTY_ACCEPTED"
            incomplete = await runtime.dispatch(_context(user, "claim-incomplete"), "领取悬赏")
            assert incomplete.code == "BOUNTY_NOT_COMPLETE"
            conflict = await runtime.dispatch(
                _context(user, "accept-conflict", operation_id="bounty-op"),
                "接取悬赏 生产订单",
            )
            assert conflict.code == "OPERATION_CONFLICT"

            with sqlite3.connect(runtime.settings.database_path) as connection:
                old = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
                connection.execute(
                    "UPDATE bounty_offers SET expires_at = ? WHERE player_id = (SELECT id FROM players WHERE platform_user_id = ?)",
                    (old, user),
                )
            expired = await runtime.dispatch(_context(user, "claim-expired"), "领取悬赏")
            assert expired.code == "BOUNTY_EXPIRED"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                status = connection.execute(
                    "SELECT status FROM bounty_offers WHERE player_id = (SELECT id FROM players WHERE platform_user_id = ?)",
                    (user,),
                ).fetchone()[0]
            assert status == "expired"

            limited = await runtime.dispatch(_context(user, "accept-second"), "接取悬赏 草药补给")
            assert limited.code == "BOUNTY_DAILY_LIMIT"
            await runtime.close()

    asyncio.run(run())


def test_production_bounty_tracks_completed_order() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            user = "bounty-production"
            await _enter_alchemy(runtime, user)
            accepted = await runtime.dispatch(_context(user, "accept"), "接取悬赏 生产订单")
            assert accepted.code == "BOUNTY_ACCEPTED"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE players SET energy = 10 WHERE platform_user_id = ?",
                    (user,),
                )
            started = await runtime.dispatch(_context(user, "production"), "开始生产 疗伤丹")
            assert started.code == "PRODUCTION_STARTED"
            _finish_order(runtime, started.data["order_id"])
            completed = await runtime.dispatch(_context(user, "complete"), "领取生产")
            assert completed.code == "PRODUCTION_COMPLETED"
            claimed = await runtime.dispatch(
                _context(user, "claim", operation_id="bounty-claim-production"),
                "领取悬赏",
            )
            assert claimed.code == "BOUNTY_CLAIMED"
            assert claimed.data["rewards"] == {"energy": 10, "service_reputation": 2}
            with sqlite3.connect(runtime.settings.database_path) as connection:
                energy = connection.execute(
                    "SELECT energy FROM players WHERE platform_user_id = ?",
                    (user,),
                ).fetchone()[0]
                reputation = connection.execute(
                    "SELECT service_reputation FROM player_reputations WHERE player_id = (SELECT id FROM players WHERE platform_user_id = ?)",
                    (user,),
                ).fetchone()[0]
            assert energy == 16
            assert reputation == 2

            await runtime.close()

    asyncio.run(run())
