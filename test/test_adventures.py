from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime


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


def test_bounty_board_herb_claim_replay_and_reputation() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            user = "bounty-herb"
            await _enter_mortal(runtime, user)

            board = await runtime.dispatch(_context(user, "board"), "悬赏榜")
            assert board.code == "BOUNTY_BOARD"
            assert "草药补给" in board.message
            assert "训练傀儡" in board.message
            assert "战斗功能未开放" in board.message
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
            assert claimed.data["rewards"] == {"spirit_stones": 30, "local_reputation": 2}
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
                assert json.loads(reputation[0])["local.xuantian.new_town"] == 2
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


def test_production_bounty_tracks_completed_order_and_battle_bounty_stays_locked() -> None:
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

            locked = await runtime.dispatch(_context(user, "locked"), "接取悬赏 训练傀儡")
            assert locked.code == "CONTENT_CLOSED"
            await runtime.close()

    asyncio.run(run())
