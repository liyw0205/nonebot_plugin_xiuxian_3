"""Focused contract for the cross-realm trade milestone `codex.place.markets_two`.

The milestone is pure data over two shipped place codex entries; this file pins
its contract, proves both entries and the reputation ceiling resolve, that no
other milestone already groups the same pair, and that a player who has really
discovered both markets can claim it once (with idempotent replay and the usual
not-ready / already-claimed rejections).
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle
from nonebot_plugin_xiuxian_3.xiuxian.rewards.rules import local_reputation_maximum
from nonebot_plugin_xiuxian_3.xiuxian.specials.codex_projection import record_codex_discovery

DATA = Path(__file__).parents[1] / "data"

MILESTONE = "codex.place.markets_two"
ENTRIES = ("codex.place.demon_market", "codex.place.trade_port")
REPUTATION = "local.demon.abyss_market"


def _context(adapter: str, user: str, operation_id: str) -> CommandContext:
    return CommandContext(adapter=adapter, user_id=user, operation_id=operation_id)


def _seed_entries(runtime, adapter: str, user: str, prefix: str, keys: tuple[str, ...]) -> None:
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
                operation_id=f"{prefix}-{index}",
                occurred_at="2026-11-08T00:00:00+00:00",
                snapshot={"instance_key": "instance.example"},
            )
        connection.execute("COMMIT")


def test_market_milestone_contract_uses_two_existing_place_entries() -> None:
    bundle = ContentBundle.load(DATA)
    record = bundle.require("codex_milestone", MILESTONE)
    assert record["entry_keys"] == list(ENTRIES)
    assert record["status"] == "active"
    assert record["unlocks"] == []
    reward = record["reward"]
    assert reward["type"] == "local_reputation"
    assert reward["reputation_key"] == REPUTATION
    assert reward["amount"] == 6
    assert isinstance(reward["name"], str) and reward["name"].strip()

    for entry in ENTRIES:
        entry_record = bundle.get("codex_entry", entry, include_locked=False)
        assert entry_record is not None, entry
        assert entry_record["category"] == "place", entry
    # The reward reputation key resolves to a real positive ceiling.
    assert local_reputation_maximum(REPUTATION, bundle) > 0


def test_market_milestone_is_the_only_group_over_that_entry_pair() -> None:
    bundle = ContentBundle.load(DATA)
    signature = tuple(sorted(ENTRIES))
    grouped = [
        row["key"]
        for row in bundle.list("codex_milestone")
        if tuple(sorted(row["entry_keys"])) == signature
    ]
    assert grouped == [MILESTONE], grouped
    assert len({tuple(sorted(row["entry_keys"])) for row in bundle.list("codex_milestone")}) == len(
        bundle.list("codex_milestone")
    )


def test_market_milestone_claims_after_both_markets_are_discovered() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, adapters=("onebot.v11",))
            adapter, user = "onebot.v11", "ob-market-milestone"
            try:
                assert (await runtime.dispatch(_context(adapter, user, "create"), "开始修仙")).ok

                # One market alone is below threshold; the claim is refused.
                _seed_entries(runtime, adapter, user, "seed-one", ENTRIES[:1])
                status = await runtime.dispatch(_context(adapter, user, "codex"), "我的图鉴")
                milestone = next(
                    item for item in status.data["milestones"] if item["milestone_key"] == MILESTONE
                )
                assert (milestone["discovered_count"], milestone["required_count"]) == (1, 2)
                assert milestone["ready"] is False
                not_ready = await runtime.dispatch(
                    _context(adapter, user, "not-ready"), f"领取图鉴里程碑 {MILESTONE}"
                )
                assert not_ready.code == "CODEX_MILESTONE_NOT_READY", not_ready

                # Discovering the second market makes it claimable.
                _seed_entries(runtime, adapter, user, "seed-two", ENTRIES[1:])
                claimed = await runtime.dispatch(
                    _context(adapter, user, "claim"), f"领取图鉴里程碑 {MILESTONE}"
                )
                assert claimed.code == "CODEX_MILESTONE_CLAIMED", claimed
                assert claimed.data["milestone_key"] == MILESTONE
                assert claimed.data["reward"] == {REPUTATION: 6}, claimed.data["reward"]
                assert claimed.data["unlocks"] == []
                assert "双市通商" in claimed.message

                # The same operation replays the frozen payload without a second grant.
                replay = await runtime.dispatch(
                    _context(adapter, user, "claim"), f"领取图鉴里程碑 {MILESTONE}"
                )
                assert replay.code == "CODEX_MILESTONE_CLAIMED", replay
                assert replay.data["reward"] == {REPUTATION: 6}, replay.data["reward"]

                again = await runtime.dispatch(
                    _context(adapter, user, "claim-again"), f"领取图鉴里程碑 {MILESTONE}"
                )
                assert again.code == "CODEX_MILESTONE_ALREADY_CLAIMED", again
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    claims = connection.execute(
                        "SELECT COUNT(*) FROM codex_milestone_claims WHERE milestone_key=?",
                        (MILESTONE,),
                    ).fetchone()[0]
                    local_json = connection.execute(
                        "SELECT local_json FROM player_reputations WHERE player_id="
                        "(SELECT id FROM players WHERE platform=? AND platform_user_id=?)",
                        (adapter, user),
                    ).fetchone()[0]
                assert claims == 1, claims
                assert json.loads(local_json)[REPUTATION] == 6, local_json
            finally:
                await runtime.close()

    asyncio.run(run())
