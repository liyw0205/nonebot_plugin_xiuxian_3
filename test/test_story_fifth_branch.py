"""Focused contract for the fifth xuantian-road story branch (闲居 / sojourner).

The branch introduces a NEW source kind `idle_claims`: readiness comes from the
player's really settled idle assignments, counted through the existing
`specials.claim_idle` claims. This file pins the content contract, proves the
readiness gate against real claimed idle assignments (not injected state),
exercises choose + claim + replay, checks the below-threshold rejection, and
confirms the other branches' evidence is untouched.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle
from nonebot_plugin_xiuxian_3.xiuxian.specials.story_rules import (
    resolve_branch,
    story_definition,
)

DATA = Path(__file__).parents[1] / "data"

BRANCH = "sojourner"
LABEL = "闲居"
CODEX = "codex.story.xuantian.road.sojourner"
REQUIRED = 2


class Clock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value

    def advance(self, **kwargs: int) -> None:
        self.value += timedelta(**kwargs)


def _context(user: str, request: str, operation_id: str = "") -> CommandContext:
    return CommandContext(
        adapter="onebot.v11", user_id=user, request_id=request, operation_id=operation_id
    )


async def _claim_idle(runtime, clock: Clock, user: str, tag: str, route: str, hours: int = 2):
    started = await runtime.dispatch(_context(user, f"{tag}-start"), f"开始挂机 {route}")
    assert started.code == "IDLE_STARTED", started
    clock.advance(hours=hours)
    claimed = await runtime.dispatch(_context(user, f"{tag}-claim"), "领取挂机")
    assert claimed.code == "IDLE_CLAIMED", claimed
    return claimed


def test_fifth_branch_is_content_backed_and_resolves() -> None:
    bundle = ContentBundle.load(DATA)
    definition = story_definition(bundle)
    keys = [branch.key for branch in definition.branches]
    assert len(keys) == 5
    assert keys.count(BRANCH) == 1
    branch = next(item for item in definition.branches if item.key == BRANCH)
    assert branch.required_source_count == REQUIRED
    assert branch.source_kind == "idle_claims"
    assert branch.ending_key == "ending.sojourner"
    assert branch.flag_key == "flag.road.sojourner"
    assert branch.appearance_key == "appearance.home.sojourner"
    assert branch.codex_entry_key == CODEX
    assert len(branch.completed_nodes) >= REQUIRED
    assert len(set(branch.completed_nodes)) == len(branch.completed_nodes)
    assert bundle.get("codex_entry", CODEX, include_locked=False) is not None
    assert resolve_branch(LABEL, bundle) == BRANCH
    assert resolve_branch("闲居者", bundle) == BRANCH
    # The other four branches keep their own source kinds.
    kinds = {item.key: item.source_kind for item in definition.branches}
    assert kinds == {
        "merchant": "commission",
        "warden": "battle",
        "gardener": "harvest_or_dispatch",
        "wanderer": "battle",
        "sojourner": "idle_claims",
    }


def test_fifth_branch_readiness_choose_claim_and_replay() -> None:
    async def run() -> None:
        clock = Clock(datetime(2026, 11, 8, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock, adapters=("onebot.v11",))
            user = "story-sojourner"
            try:
                assert (await runtime.dispatch(_context(user, "create"), "开始修仙")).ok
                assert (await runtime.dispatch(_context(user, "seek"), "寻仙问道")).ok
                started = await runtime.dispatch(_context(user, "start"), "开始剧情")
                assert started.code == "STORY_STARTED", started

                # With no settled idle assignment the branch is below threshold.
                blocked = await runtime.dispatch(
                    _context(user, "blocked"), f"选择剧情 {LABEL}"
                )
                assert blocked.code == "STORY_CHOICE_NOT_READY", blocked

                # One real settled idle claim is still one short of the gate.
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    player_id = connection.execute(
                        "SELECT id FROM players WHERE platform_user_id=?", (user,)
                    ).fetchone()[0]
                    now = clock().isoformat()
                    connection.execute(
                        "INSERT INTO residences(residence_id, player_id, operation_id, residence_key, "
                        "status, starts_at, ends_at, rent_cost, created_at, updated_at) "
                        "VALUES ('sojourner-res', ?, 'sojourner-res-op', 'residence.town_room', "
                        "'active', ?, ?, 0, ?, ?)",
                        (player_id, now, (clock.value + timedelta(days=1)).isoformat(), now, now),
                    )
                await _claim_idle(runtime, clock, user, "first", "灵圃看护", hours=4)
                status = await runtime.dispatch(_context(user, "status-one"), "剧情线")
                row = next(
                    item for item in status.data["branches"] if item["key"] == BRANCH
                )
                assert row["eligible"] is False, row
                assert len(row["evidence_operation_ids"]) == 1, row
                still_blocked = await runtime.dispatch(
                    _context(user, "blocked-two"), f"选择剧情 {LABEL}"
                )
                assert still_blocked.code == "STORY_CHOICE_NOT_READY", still_blocked

                # A second settled idle claim meets the threshold.
                second = await _claim_idle(runtime, clock, user, "second", "镇中行旅", hours=2)
                ready = await runtime.dispatch(_context(user, "status-two"), "剧情线")
                row = next(item for item in ready.data["branches"] if item["key"] == BRANCH)
                assert row["eligible"] is True, row
                assert len(row["evidence_operation_ids"]) == REQUIRED, row

                chosen = await runtime.dispatch(_context(user, "choose"), f"选择剧情 {LABEL}")
                assert chosen.code == "STORY_ROUTE_LOCKED", chosen
                assert chosen.data["selected_route"] == BRANCH
                replay_choose = await runtime.dispatch(
                    _context(user, "choose"), f"选择剧情 {LABEL}"
                )
                assert replay_choose.data["idempotent_replay"] is True

                claimed = await runtime.dispatch(_context(user, "claim"), "领取剧情结局")
                assert claimed.code == "STORY_ENDING_CLAIMED", claimed
                assert claimed.data["idempotent_replay"] is False
                replay_claim = await runtime.dispatch(_context(user, "claim"), "领取剧情结局")
                assert replay_claim.code == "STORY_ENDING_CLAIMED"
                assert replay_claim.data["idempotent_replay"] is True

                with sqlite3.connect(runtime.settings.database_path) as connection:
                    flags = json.loads(
                        connection.execute(
                            "SELECT intro_json FROM players WHERE platform_user_id=?", (user,)
                        ).fetchone()[0]
                    )["flags"]
                    codex_count = connection.execute(
                        "SELECT COUNT(*) FROM codex_entries c JOIN players p ON p.id=c.player_id "
                        "WHERE p.platform_user_id=? AND c.entry_key=?",
                        (user, CODEX),
                    ).fetchone()[0]
                assert "flag.road.sojourner" in flags
                assert "appearance.home.sojourner" in flags
                assert codex_count == 1
            finally:
                await runtime.close()

    asyncio.run(run())
