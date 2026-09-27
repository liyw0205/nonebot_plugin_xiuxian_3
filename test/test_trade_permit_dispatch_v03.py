from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.specials.dispatch_rules import (
    BEAST_RELOCATION,
    DEMON_RELIEF,
    DISPATCHES,
    choose_outcome,
)


class MutableClock:
    def __init__(self, value: datetime):
        self.value = value

    def __call__(self) -> datetime:
        return self.value

    def advance(self, **kwargs: int) -> None:
        self.value += timedelta(**kwargs)


async def _send(runtime, adapter: str, user: str, operation: str, text: str):
    context = CommandContext(adapter=adapter, user_id=user, operation_id=operation)
    return await runtime.adapters.dispatch(adapter, context, text)


def _force_uuid(seed: str, assignment: str):
    return patch(
        "nonebot_plugin_xiuxian_3.xiuxian.specials.dispatch_repository.uuid4",
        side_effect=[SimpleNamespace(hex=seed), SimpleNamespace(hex=assignment)],
    )


def _seed_for(dispatch_key: str, outcome: str) -> str:
    definition = DISPATCHES[dispatch_key]
    return next(
        seed
        for index in range(10000)
        if (seed := f"trade-v03-{dispatch_key}-{index}")
        and choose_outcome(definition, seed) == outcome
    )


def _grant_trade_prerequisites(runtime, adapter: str, user: str) -> None:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        row = connection.execute(
            "SELECT intro_json FROM players WHERE platform=? AND platform_user_id=?",
            (adapter, user),
        ).fetchone()
        intro = json.loads(row[0])
        flags = set(intro.get("flags", []))
        flags.update({"quest.demon_intro", "quest.beast_intro"})
        intro["flags"] = sorted(flags)
        connection.execute(
            "UPDATE players SET intro_json=?, faction_reputation_json=?, spirit_stones=2000 "
            "WHERE platform=? AND platform_user_id=?",
            (json.dumps(intro, sort_keys=True), json.dumps({"demon": 80, "beast": 80}), adapter, user),
        )


def _grant_dispatch_materials(runtime, adapter: str, user: str) -> None:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        row = connection.execute(
            "SELECT inventory_json FROM players WHERE platform=? AND platform_user_id=?",
            (adapter, user),
        ).fetchone()
        inventory = json.loads(row[0])
        inventory.update(
            {
                "item.food.coarse_spirit_rice": 12,
                "item.herb.blood_grass": 4,
                "item.herb.spirit_leaf": 6,
            }
        )
        connection.execute(
            "UPDATE players SET inventory_json=? WHERE platform=? AND platform_user_id=?",
            (json.dumps(inventory, sort_keys=True), adapter, user),
        )


@pytest.mark.parametrize("adapter", ["qq.official", "onebot.v11"])
def test_trade_permits_dispatches_and_beast_bounty_close_on_both_adapters(adapter: str) -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 28, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            user = f"trade-chain-{adapter}"
            assert (await _send(runtime, adapter, user, "create", "开始修仙")).code == "PLAYER_CREATED"
            assert (await _send(runtime, adapter, user, "seeking", "寻仙问道")).ok
            _grant_trade_prerequisites(runtime, adapter, user)
            _grant_dispatch_materials(runtime, adapter, user)

            preview = await _send(runtime, adapter, user, "dispatch-locked", "派遣预览 dispatch.beast_relocation")
            assert preview.data["dispatches"][0]["ready"] is False
            assert "permit.beast_trade" in " ".join(preview.data["dispatches"][0]["missing"])

            demon_permit = await _send(runtime, adapter, user, "demon-permit", "申请贸易许可 魔界")
            beast_permit = await _send(runtime, adapter, user, "beast-permit", "申请贸易许可 妖界")
            assert demon_permit.code == "TRADE_PERMIT_ISSUED"
            assert beast_permit.code == "TRADE_PERMIT_ISSUED"
            assert beast_permit.data["permit_key"] == "permit.beast_trade"
            assert datetime.fromisoformat(beast_permit.data["expires_at"]) - datetime.fromisoformat(
                beast_permit.data["issued_at"]
            ) == timedelta(days=7)
            replay = await _send(runtime, adapter, user, "beast-permit", "申请贸易许可 妖界")
            assert replay.data["idempotent_replay"] is True
            active = await _send(runtime, adapter, user, "beast-permit-again", "申请贸易许可 妖界")
            assert active.code == "TRADE_PERMIT_ACTIVE"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                stones = connection.execute(
                    "SELECT spirit_stones FROM players WHERE platform=? AND platform_user_id=?",
                    (adapter, user),
                ).fetchone()[0]
            assert stones == 1000

            board = await _send(runtime, adapter, user, "bounty-board", "悬赏榜")
            offer = next(item for item in board.data["offers"] if item["bounty_key"] == "bounty.beast_habitat")
            assert offer["status"] == "available"
            prior_seed = _seed_for(BEAST_RELOCATION, "success")
            with _force_uuid(prior_seed, f"beast-relocation-prior-{adapter}"):
                prior_dispatch = await _send(
                    runtime,
                    adapter,
                    user,
                    "beast-accept-prior",
                    "接受派遣 dispatch.beast_relocation",
                )
            assert prior_dispatch.code == "DISPATCH_ACCEPTED"
            accepted_bounty = await _send(runtime, adapter, user, "bounty-accept", "接取悬赏 妖界栖地保护")
            assert accepted_bounty.code == "BOUNTY_ACCEPTED"
            clock.value = datetime.fromisoformat(prior_dispatch.data["ends_at"])
            prior_settled = await _send(runtime, adapter, user, "beast-settle-prior", "结算派遣")
            assert prior_settled.code == "DISPATCH_SETTLED"
            prior_board = await _send(runtime, adapter, user, "bounty-prior-board", "悬赏榜")
            prior_offer = next(item for item in prior_board.data["offers"] if item["bounty_key"] == "bounty.beast_habitat")
            assert prior_offer["progress"] == 0

            for index in range(2):
                seed = _seed_for(BEAST_RELOCATION, "success")
                with _force_uuid(seed, f"beast-relocation-{adapter}-{index}"):
                    dispatch = await _send(
                        runtime,
                        adapter,
                        user,
                        f"beast-accept-{index}",
                        "接受派遣 dispatch.beast_relocation",
                    )
                assert dispatch.code == "DISPATCH_ACCEPTED"
                assert dispatch.data["outcome"] == "success"
                clock.value = datetime.fromisoformat(dispatch.data["ends_at"])
                settled = await _send(runtime, adapter, user, f"beast-settle-{index}", "结算派遣")
                assert settled.code == "DISPATCH_SETTLED"
                assert settled.data["reward"] == {
                    "codex.story.dispatch_beast_relocation": 1,
                    "local.beast.trade_post": 6,
                }

            completed = await _send(runtime, adapter, user, "bounty-completed", "悬赏榜")
            offer = next(item for item in completed.data["offers"] if item["bounty_key"] == "bounty.beast_habitat")
            assert offer["status"] == "completed"
            assert offer["progress"] == 2
            claimed = await _send(runtime, adapter, user, "bounty-claim", "领取悬赏")
            assert claimed.code == "BOUNTY_CLAIMED"
            assert claimed.data["rewards"] == {
                "codex.story.beast_habitat": 1,
                "faction_reputation.beast": 10,
            }
            replay_claim = await _send(runtime, adapter, user, "bounty-claim", "领取悬赏")
            assert replay_claim.data["idempotent_replay"] is True

            failed_seed = _seed_for(DEMON_RELIEF, "failed")
            with _force_uuid(failed_seed, f"demon-failed-{adapter}"):
                failed_dispatch = await _send(
                    runtime, adapter, user, "demon-failed-accept", "接受派遣 dispatch.demon_relief"
                )
            assert failed_dispatch.code == "DISPATCH_ACCEPTED"
            clock.value = datetime.fromisoformat(failed_dispatch.data["ends_at"])
            failed = await _send(runtime, adapter, user, "demon-failed-settle", "结算派遣")
            assert failed.data["outcome"] == "failed"
            assert failed.data["refunded"] == {
                "item.food.coarse_spirit_rice": 1,
                "item.herb.blood_grass": 1,
            }

            success_seed = _seed_for(DEMON_RELIEF, "success")
            with _force_uuid(success_seed, f"demon-success-{adapter}"):
                demon_dispatch = await _send(
                    runtime, adapter, user, "demon-success-accept", "接受派遣 dispatch.demon_relief"
                )
            assert demon_dispatch.code == "DISPATCH_ACCEPTED"
            clock.value = datetime.fromisoformat(demon_dispatch.data["ends_at"])
            demon_settled = await _send(runtime, adapter, user, "demon-success-settle", "结算派遣")
            assert demon_settled.data["reward"] == {
                "codex.story.dispatch_demon_relief": 1,
                "local.demon.trade_post": 6,
            }

            with sqlite3.connect(runtime.settings.database_path) as connection:
                reputation = connection.execute(
                    "SELECT faction_reputation_json FROM players WHERE platform=? AND platform_user_id=?",
                    (adapter, user),
                ).fetchone()[0]
                codex_count = connection.execute(
                    "SELECT COUNT(*) FROM codex_entries WHERE player_id=(SELECT id FROM players WHERE platform=? AND platform_user_id=?) AND entry_key IN (?, ?, ?)",
                    (
                        adapter,
                        user,
                        "codex.story.beast_habitat",
                        "codex.story.dispatch_beast_relocation",
                        "codex.story.dispatch_demon_relief",
                    ),
                ).fetchone()[0]
                source_count = connection.execute(
                    "SELECT COUNT(*) FROM activity_events WHERE player_id=(SELECT id FROM players WHERE platform=? AND platform_user_id=?) AND event_key='specials.dispatch.settled'",
                    (adapter, user),
                ).fetchone()[0]
            assert json.loads(reputation)["beast"] == 90
            assert codex_count == 3
            assert source_count == 5
            await runtime.close()

    asyncio.run(run())


def test_trade_permit_requirements_expiry_and_no_debit_on_rejection() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 28, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            adapter, user = "onebot.v11", "trade-permit-gate"
            await _send(runtime, adapter, user, "create", "开始修仙")
            await _send(runtime, adapter, user, "seeking", "寻仙问道")
            denied = await _send(runtime, adapter, user, "denied", "申请贸易许可 魔界")
            assert denied.code == "TRADE_PERMIT_REQUIREMENT_MISSING"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute("SELECT spirit_stones FROM players WHERE platform_user_id=?", (user,)).fetchone()[0] == 100
                assert connection.execute("SELECT COUNT(*) FROM trade_permits").fetchone()[0] == 0
            _grant_trade_prerequisites(runtime, adapter, user)
            issued = await _send(runtime, adapter, user, "issued", "申请贸易许可 妖界")
            assert issued.ok
            bounty = await _send(runtime, adapter, user, "long-bounty", "接取悬赏 妖界栖地保护")
            assert bounty.code == "BOUNTY_ACCEPTED"
            clock.advance(days=1)
            board = await _send(runtime, adapter, user, "long-bounty-board", "悬赏榜")
            beast_offer = next(item for item in board.data["offers"] if item["bounty_key"] == "bounty.beast_habitat")
            assert beast_offer["status"] == "accepted"
            overlapping = await _send(runtime, adapter, user, "overlapping-bounty", "接取悬赏 妖界栖地保护")
            assert overlapping.code == "BOUNTY_DAILY_LIMIT"
            clock.advance(days=8)
            expired_dispatch = await _send(
                runtime, adapter, user, "expired-dispatch", "派遣预览 dispatch.beast_relocation"
            )
            assert expired_dispatch.data["dispatches"][0]["ready"] is False
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute("SELECT COUNT(*) FROM trade_permits").fetchone()[0] == 1
            await runtime.close()

    asyncio.run(run())
