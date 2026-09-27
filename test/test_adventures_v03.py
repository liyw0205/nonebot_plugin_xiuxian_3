from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime


def _context(adapter: str, user: str, request_id: str, *, operation_id: str = "") -> CommandContext:
    return CommandContext(
        adapter=adapter,
        user_id=user,
        request_id=request_id,
        operation_id=operation_id,
    )


def _set_inventory(runtime, adapter: str, user: str, item_key: str, quantity: int) -> None:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        row = connection.execute(
            "SELECT inventory_json FROM players WHERE platform=? AND platform_user_id=?",
            (adapter, user),
        ).fetchone()
        inventory = json.loads(row[0])
        inventory[item_key] = int(inventory.get(item_key, 0)) + quantity
        connection.execute(
            "UPDATE players SET inventory_json=? WHERE platform=? AND platform_user_id=?",
            (json.dumps(inventory, ensure_ascii=False, sort_keys=True), adapter, user),
        )


def _grant_demon_permit(runtime, adapter: str, user: str, rice: int = 0) -> None:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        row = connection.execute(
            "SELECT intro_json, inventory_json FROM players WHERE platform=? AND platform_user_id=?",
            (adapter, user),
        ).fetchone()
        intro = json.loads(row[0])
        intro.setdefault("flags", []).append("access.demon_abyss_gate")
        inventory = json.loads(row[1])
        if rice:
            inventory["item.food.coarse_spirit_rice"] = rice
        connection.execute(
            "UPDATE players SET intro_json=?, inventory_json=?, spirit_stones=50 "
            "WHERE platform=? AND platform_user_id=?",
            (json.dumps(intro, sort_keys=True), json.dumps(inventory, sort_keys=True), adapter, user),
        )


def test_demon_relief_bounty_qq_and_onebot_debits_supply_and_rewards_faction_reputation() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            for adapter, user in (
                ("qq.official", "demon-relief-qq"),
                ("onebot.v11", "demon-relief-onebot"),
            ):
                created = await runtime.adapters.dispatch(
                    adapter, _context(adapter, user, "create"), "开始修仙"
                )
                assert created.code == "PLAYER_CREATED"
                sought = await runtime.adapters.dispatch(
                    adapter, _context(adapter, user, "seeking"), "寻仙问道"
                )
                assert sought.ok
                _grant_demon_permit(runtime, adapter, user, rice=2)

                board = await runtime.adapters.dispatch(
                    adapter, _context(adapter, user, "board"), "悬赏榜"
                )
                offer = next(item for item in board.data["offers"] if item["bounty_key"] == "bounty.demon_relief")
                assert offer["status"] == "available"
                assert offer["reward"] == {"faction_reputation.demon": 10, "spirit_stones": 240}

                accepted = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "accept", operation_id=f"{adapter}:demon-accept"),
                    "接取悬赏 魔界救援",
                )
                assert accepted.code == "BOUNTY_ACCEPTED"
                assert accepted.data["bounty_key"] == "bounty.demon_relief"
                _set_inventory(runtime, adapter, user, "item.food.coarse_spirit_rice", 3)

                completed_board = await runtime.adapters.dispatch(
                    adapter, _context(adapter, user, "completed-board"), "悬赏榜"
                )
                offer = next(item for item in completed_board.data["offers"] if item["bounty_key"] == "bounty.demon_relief")
                assert offer["status"] == "completed"
                assert offer["progress"] == 3

                claimed = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "claim", operation_id=f"{adapter}:demon-claim"),
                    "领取悬赏",
                )
                assert claimed.code == "BOUNTY_CLAIMED"
                assert claimed.data["rewards"] == {
                    "faction_reputation.demon": 10,
                    "spirit_stones": 240,
                }
                assert "魔界声望 +10" in claimed.message

                replay = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "claim-replay", operation_id=f"{adapter}:demon-claim"),
                    "领取悬赏",
                )
                assert replay.code == "BOUNTY_CLAIMED"
                assert replay.data["idempotent_replay"] is True
                assert replay.data["rewards"] == claimed.data["rewards"]

                with sqlite3.connect(runtime.settings.database_path) as connection:
                    stones, inventory_json, faction_json, offer_count = connection.execute(
                        "SELECT spirit_stones, inventory_json, faction_reputation_json, "
                        "(SELECT COUNT(*) FROM bounty_offers WHERE player_id=players.id) "
                        "FROM players WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    ).fetchone()
                assert stones == 290
                assert json.loads(inventory_json)["item.food.coarse_spirit_rice"] == 2
                assert json.loads(faction_json)["demon"] == 10
                assert offer_count == 1
            await runtime.close()

    asyncio.run(run())


def test_demon_relief_requires_permit_and_expiry_does_not_debit_supply() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            adapter, user = "onebot.v11", "demon-relief-guards"
            created = await runtime.adapters.dispatch(
                adapter, _context(adapter, user, "create"), "开始修仙"
            )
            assert created.code == "PLAYER_CREATED"
            await runtime.adapters.dispatch(adapter, _context(adapter, user, "seeking"), "寻仙问道")
            board = await runtime.adapters.dispatch(
                adapter, _context(adapter, user, "locked-board"), "悬赏榜"
            )
            offer = next(item for item in board.data["offers"] if item["bounty_key"] == "bounty.demon_relief")
            assert offer["status"] == "requirement"
            denied = await runtime.adapters.dispatch(
                adapter, _context(adapter, user, "denied"), "接取悬赏 魔界救援"
            )
            assert denied.code == "BOUNTY_REQUIREMENT_MISSING"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute("SELECT COUNT(*) FROM bounty_offers").fetchone()[0] == 0

            _grant_demon_permit(runtime, adapter, user, rice=1)
            accepted = await runtime.adapters.dispatch(
                adapter,
                _context(adapter, user, "accept", operation_id="demon-expiry-accept"),
                "接取悬赏 魔界救援",
            )
            assert accepted.code == "BOUNTY_ACCEPTED"
            _set_inventory(runtime, adapter, user, "item.food.coarse_spirit_rice", 3)
            with sqlite3.connect(runtime.settings.database_path) as connection:
                expired_at = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
                connection.execute(
                    "UPDATE bounty_offers SET expires_at=? WHERE operation_id=?",
                    (expired_at, "demon-expiry-accept"),
                )
            expired = await runtime.adapters.dispatch(
                adapter, _context(adapter, user, "expired-claim"), "领取悬赏"
            )
            assert expired.code == "BOUNTY_EXPIRED"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                stones, inventory_json, faction_json, status = connection.execute(
                    "SELECT p.spirit_stones, p.inventory_json, p.faction_reputation_json, o.status "
                    "FROM players p JOIN bounty_offers o ON o.player_id=p.id "
                    "WHERE p.platform=? AND p.platform_user_id=?",
                    (adapter, user),
                ).fetchone()
            assert stones == 50
            assert json.loads(inventory_json)["item.food.coarse_spirit_rice"] == 4
            assert json.loads(faction_json) == {}
            assert status == "expired"
            await runtime.close()

    asyncio.run(run())
