from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.exploration.rules import battle_roll_bp


def _context(adapter: str, user: str, request_id: str, *, operation_id: str = "") -> CommandContext:
    return CommandContext(
        adapter=adapter,
        user_id=user,
        request_id=request_id,
        operation_id=operation_id,
    )


def _set_player(runtime, adapter: str, user: str, **values: object) -> None:
    assignments = ", ".join(f"{key} = ?" for key in values)
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            f"UPDATE players SET {assignments} WHERE platform = ? AND platform_user_id = ?",
            (*values.values(), adapter, user),
        )


def _inventory(runtime, adapter: str, user: str, **changes: int) -> dict[str, int]:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        row = connection.execute(
            "SELECT inventory_json FROM players WHERE platform = ? AND platform_user_id = ?",
            (adapter, user),
        ).fetchone()
        inventory = json.loads(row[0])
        for key, quantity in changes.items():
            inventory[key] = int(inventory.get(key, 0)) + quantity
        connection.execute(
            "UPDATE players SET inventory_json = ? WHERE platform = ? AND platform_user_id = ?",
            (json.dumps(inventory, ensure_ascii=False, sort_keys=True), adapter, user),
        )
        return inventory


def _expire_exploration(runtime, exploration_id: str) -> None:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE exploration_sessions SET ends_at = ? WHERE exploration_id = ?",
            ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(), exploration_id),
        )


def test_cloud_mine_bounty_qq_and_onebot_full_claim_flow() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            cases = (
                # L4 is a direct gate and does not require a permit.
                ("qq.official", "cloud-bounty-qq", "foundation", 4, {}),
                # L1 is allowed through a persisted mining permit.
                ("onebot.v11", "cloud-bounty-ob", "foundation", 1, {"item.permit.cloud_mine": 1}),
            )
            for adapter, user, realm_key, realm_layer, starting_inventory in cases:
                created = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "create"),
                    "开始修仙",
                )
                assert created.code == "PLAYER_CREATED"
                _set_player(
                    runtime,
                    adapter,
                    user,
                    stage="cultivator",
                    realm_key=realm_key,
                    realm_layer=realm_layer,
                    spirit_stones=50,
                    inventory_json=json.dumps(starting_inventory, ensure_ascii=False, sort_keys=True),
                )

                board = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "board"),
                    "悬赏榜",
                )
                cloud_offer = next(item for item in board.data["offers"] if item["bounty_key"] == "bounty.cloud_mine")
                assert cloud_offer["status"] == "available"
                assert cloud_offer["target"] == 3

                accepted = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "accept", operation_id=f"{adapter}:cloud-accept"),
                    "接取悬赏 云铁矿区悬赏",
                )
                assert accepted.code == "BOUNTY_ACCEPTED"
                assert accepted.data["bounty_key"] == "bounty.cloud_mine"

                _inventory(runtime, adapter, user, **{"item.material.cloud_iron": 3})
                claimed = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "claim", operation_id=f"{adapter}:cloud-claim"),
                    "领取悬赏",
                )
                assert claimed.code == "BOUNTY_CLAIMED"
                assert claimed.data["rewards"] == {"spirit_stones": 120, "local_reputation": 8}

                replay = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "claim-replay", operation_id=f"{adapter}:cloud-claim"),
                    "领取悬赏",
                )
                assert replay.code == "BOUNTY_CLAIMED"
                assert replay.data["idempotent_replay"] is True
                assert replay.data["rewards"] == claimed.data["rewards"]

                with sqlite3.connect(runtime.settings.database_path) as connection:
                    stones, local_json, offer_count = connection.execute(
                        "SELECT p.spirit_stones, r.local_json, COUNT(o.id) "
                        "FROM players p "
                        "JOIN player_reputations r ON r.player_id = p.id "
                        "LEFT JOIN bounty_offers o ON o.player_id = p.id "
                        "WHERE p.platform = ? AND p.platform_user_id = ? "
                        "GROUP BY p.id, r.local_json",
                        (adapter, user),
                    ).fetchone()
                local = json.loads(local_json)
                assert stones == 170
                assert local["local.xuantian.cloud_city"] == 8
                assert "local.xuantian.new_town" not in local
                assert offer_count == 1
            await runtime.close()

    asyncio.run(run())


def test_cloud_mine_bounty_requires_access_and_expiry_does_not_reward() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            adapter, user = "onebot.v11", "cloud-bounty-guards"
            created = await runtime.adapters.dispatch(
                adapter,
                _context(adapter, user, "create"),
                "开始修仙",
            )
            assert created.code == "PLAYER_CREATED"
            _set_player(
                runtime,
                adapter,
                user,
                stage="cultivator",
                realm_key="foundation",
                realm_layer=1,
                spirit_stones=50,
                inventory_json=json.dumps({}, sort_keys=True),
            )
            denied = await runtime.adapters.dispatch(
                adapter,
                _context(adapter, user, "denied"),
                "接取悬赏 云铁矿区悬赏",
            )
            assert denied.code == "BOUNTY_REQUIREMENT_MISSING"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute(
                    "SELECT COUNT(*) FROM bounty_offers WHERE player_id = "
                    "(SELECT id FROM players WHERE platform = ? AND platform_user_id = ?)",
                    (adapter, user),
                ).fetchone()[0] == 0

            _set_player(
                runtime,
                adapter,
                user,
                inventory_json=json.dumps({"item.permit.cloud_mine": 1}, sort_keys=True),
            )
            accepted = await runtime.adapters.dispatch(
                adapter,
                _context(adapter, user, "accept", operation_id="cloud-expiry-accept"),
                "接取悬赏 云铁悬赏",
            )
            assert accepted.code == "BOUNTY_ACCEPTED"
            _inventory(runtime, adapter, user, **{"item.material.cloud_iron": 3})
            with sqlite3.connect(runtime.settings.database_path) as connection:
                expired_at = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
                connection.execute(
                    "UPDATE bounty_offers SET expires_at = ? WHERE operation_id = ?",
                    (expired_at, "cloud-expiry-accept"),
                )
            expired = await runtime.adapters.dispatch(
                adapter,
                _context(adapter, user, "claim-expired", operation_id="cloud-expiry-claim"),
                "领取悬赏",
            )
            assert expired.code == "BOUNTY_EXPIRED"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                stones, local_json, status = connection.execute(
                    "SELECT p.spirit_stones, r.local_json, o.status "
                    "FROM players p "
                    "LEFT JOIN player_reputations r ON r.player_id = p.id "
                    "JOIN bounty_offers o ON o.player_id = p.id "
                    "WHERE p.platform = ? AND p.platform_user_id = ?",
                    (adapter, user),
                ).fetchone()
            assert stones == 50
            assert json.loads(local_json or "{}") == {}
            assert status == "expired"
            await runtime.close()

    asyncio.run(run())


def test_elite_bounty_grants_advanced_cave_pass_after_exploration_win() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            for adapter, user in (("qq.official", "elite-bounty-qq"), ("onebot.v11", "elite-bounty-ob")):
                created = await runtime.adapters.dispatch(adapter, _context(adapter, user, "create"), "开始修仙")
                assert created.code == "PLAYER_CREATED"
                _set_player(
                    runtime,
                    adapter,
                    user,
                    stage="cultivator",
                    realm_key="golden_core",
                    realm_layer=1,
                    location_key="cave.mist_grotto_2",
                    stamina=30,
                    max_hp=10000,
                    initiative=100,
                    qualification_json=json.dumps({"body": 10000, "agility": 10000}),
                    inventory_json=json.dumps({}),
                )
                accepted = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "accept", operation_id=f"{adapter}:elite-accept"),
                    "接取悬赏 洞天精英悬赏",
                )
                assert accepted.code == "BOUNTY_ACCEPTED"
                operation = next(
                    f"{adapter}:elite-explore:{index}"
                    for index in range(1000)
                    if battle_roll_bp(f"{adapter}:elite-explore:{index}:battle") < 4000
                )
                started = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "start", operation_id=operation),
                    "开始探索 洞天二层探索",
                )
                assert started.code == "EXPLORATION_STARTED"
                _expire_exploration(runtime, started.data["exploration_id"])
                settled = await runtime.adapters.dispatch(adapter, _context(adapter, user, "settle"), "结算探索")
                assert settled.code == "EXPLORATION_SETTLED"
                assert settled.data["battle_outcome"] == "won"
                claimed = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "claim", operation_id=f"{adapter}:elite-claim"),
                    "领取悬赏",
                )
                assert claimed.code == "BOUNTY_CLAIMED"
                assert claimed.data["rewards"] == {"item.cave_pass_advanced": 1, "local_reputation": 12}
                replay = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "claim-replay", operation_id=f"{adapter}:elite-claim"),
                    "领取悬赏",
                )
                assert replay.data["idempotent_replay"] is True
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    inventory = connection.execute(
                        "SELECT inventory_json FROM players WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    ).fetchone()[0]
                assert json.loads(inventory)["item.cave_pass_advanced"] == 1
            await runtime.close()

    asyncio.run(run())
