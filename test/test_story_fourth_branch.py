"""Focused contract for the fourth xuantian-road story branch (游历 / wanderer).

The branch is data-driven: it reuses the existing battle source kind with a
distinct threshold (3 wins), a new ending/flag/appearance key pair and a new
active story codex entry. This test covers readiness (unlock), completion
(choose + claim), and idempotent replay without new commands or schema.
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
from nonebot_plugin_xiuxian_3.xiuxian.specials.story_rules import (
    resolve_branch,
    story_definition,
)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
BRANCH = "wanderer"
LABEL = "游历"
CODEX = "codex.story.xuantian.road.wanderer"
REQUIRED = 3


def _context(user: str, name: str, operation_id: str = "") -> CommandContext:
    return CommandContext(
        adapter="web", user_id=user, request_id=name, operation_id=operation_id
    )


def _seed_wins(database_path, user: str, count: int) -> list[str]:
    operation_ids = [f"wanderer-win-{user}-{index}" for index in range(count)]
    now = "2026-01-01T00:00:00+00:00"
    with sqlite3.connect(database_path) as connection:
        player_id = connection.execute(
            "SELECT id FROM players WHERE platform='web' AND platform_user_id=?",
            (user,),
        ).fetchone()[0]
        for index, operation_id in zip(range(count), operation_ids):
            connection.execute(
                "INSERT INTO battle_sessions(battle_id,player_id,start_operation_id,"
                "resolved_operation_id,battle_type,enemy_key,location_key,status,"
                "reward_status,starts_at,turn_deadline,result_json,created_at,updated_at) "
                "VALUES(?,?,?,?,'pve','enemy.story.test','xuantian.new_town','settled',"
                "'none',?,?,?,?,?)",
                (
                    f"wanderer-battle-{user}-{index}", player_id,
                    f"battle-start-{operation_id}", operation_id, now, now,
                    json.dumps({"outcome": "won"}), now, now,
                ),
            )
    return operation_ids


def test_fourth_story_branch_is_content_backed_and_resolves() -> None:
    bundle = ContentBundle.load(DATA)
    definition = story_definition(bundle)
    keys = [branch.key for branch in definition.branches]
    assert len(keys) == 4
    assert keys.count(BRANCH) == 1
    branch = next(item for item in definition.branches if item.key == BRANCH)
    assert branch.required_source_count == REQUIRED
    assert branch.source_kind == "battle"
    assert branch.ending_key == "ending.wanderer"
    assert branch.flag_key == "flag.road.wanderer"
    assert branch.appearance_key == "appearance.home.wanderer"
    assert branch.codex_entry_key == CODEX
    assert len(branch.completed_nodes) >= REQUIRED
    assert len(set(branch.completed_nodes)) == len(branch.completed_nodes)
    assert bundle.get("codex_entry", CODEX, include_locked=False) is not None
    assert resolve_branch(LABEL, bundle) == BRANCH
    assert resolve_branch("游历者", bundle) == BRANCH


def test_fourth_story_branch_unlock_completion_and_replay() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            user = "story-wanderer-flow"
            try:
                assert (await runtime.dispatch(_context(user, "create"), "开始修仙")).ok
                assert (await runtime.dispatch(_context(user, "seek"), "寻仙问道")).ok
                assert (
                    await runtime.dispatch(
                        _context(user, "start-before-seek-check"), "剧情线"
                    )
                ).data["status"] == "available"
                started = await runtime.dispatch(_context(user, "start"), "开始剧情")
                assert started.code == "STORY_STARTED", started

                # Unlock gate: with no battle evidence the branch cannot be chosen.
                blocked = await runtime.dispatch(
                    _context(user, "blocked"), f"选择剧情 {LABEL}"
                )
                assert blocked.code == "STORY_CHOICE_NOT_READY", blocked

                # Status hint lists all four routes (no stale hardcoded three).
                active = await runtime.dispatch(_context(user, "status"), "剧情线")
                hint = active.message
                assert "游历" in hint and "选择剧情" in hint

                wins = _seed_wins(runtime.settings.database_path, user, REQUIRED)
                chosen = await runtime.dispatch(
                    _context(user, "choose"), f"选择剧情 {LABEL}"
                )
                assert chosen.code == "STORY_ROUTE_LOCKED", chosen
                assert chosen.data["source_operation_ids"] == list(reversed(wins))
                replay_choose = await runtime.dispatch(
                    _context(user, "choose"), f"选择剧情 {LABEL}"
                )
                assert replay_choose.data["idempotent_replay"] is True

                claimed = await runtime.dispatch(_context(user, "claim"), "领取剧情结局")
                assert claimed.code == "STORY_ENDING_CLAIMED", claimed
                assert claimed.data["idempotent_replay"] is False
                replay_claim = await runtime.dispatch(
                    _context(user, "claim"), "领取剧情结局"
                )
                assert replay_claim.code == "STORY_ENDING_CLAIMED"
                assert replay_claim.data["idempotent_replay"] is True

                with sqlite3.connect(runtime.settings.database_path) as connection:
                    flags = json.loads(
                        connection.execute(
                            "SELECT intro_json FROM players WHERE platform='web' "
                            "AND platform_user_id=?",
                            (user,),
                        ).fetchone()[0]
                    )["flags"]
                    codex_count = connection.execute(
                        "SELECT COUNT(*) FROM codex_entries c JOIN players p ON p.id=c.player_id "
                        "WHERE p.platform='web' AND p.platform_user_id=? AND c.entry_key=?",
                        (user, CODEX),
                    ).fetchone()[0]
                assert "flag.road.wanderer" in flags
                assert "appearance.home.wanderer" in flags
                assert codex_count == 1
            finally:
                await runtime.close()

    asyncio.run(run())
