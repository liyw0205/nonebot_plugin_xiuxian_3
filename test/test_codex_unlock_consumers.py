"""The remaining codex unlocks must have a real runtime consumer.

Of the eight shipped `codex_unlock` rows only two were read by code. This module
pins the four this phase gave a consumer: two gate a transport route (P2) or an
idle route (here), and the encyclopedia/display benefits surface in the codex
overview only once the milestone is claimed.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle
from nonebot_plugin_xiuxian_3.xiuxian.specials.idle_rules import idle_route_definitions

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

GATED_IDLE = (
    ("idle.beast_observation", "display.codex_creature_badge", "观兽"),
    ("idle.tower_watch", "hint.tower_route", "塔外守望"),
)
ENCRYPTED_BENEFITS = ("encyclopedia.paths_6", "display.domain_observatory")


def _context(user: str, name: str, operation_id: str = "") -> CommandContext:
    return CommandContext(
        adapter="web", user_id=user, request_id=name, operation_id=operation_id
    )


def _prepare(runtime, user: str) -> None:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE players SET stage='seeker', realm_key='qi_sensing', realm_layer=3, "
            "stamina=200, stamina_max=200, energy=200, energy_max=200, "
            "spirit_stones=500 WHERE platform_user_id=?",
            (user,),
        )


def _claim(runtime, user: str, unlock_key: str, milestone_key: str) -> None:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "INSERT INTO codex_milestone_claims"
            "(player_id, milestone_key, operation_id, snapshot_json, reward_json,"
            " unlocks_json, claimed_at)"
            " VALUES ((SELECT id FROM players WHERE platform_user_id=?), ?, ?, '{}',"
            " '{}', ?, ?)",
            (
                user,
                milestone_key,
                f"fixture-claim:{milestone_key}:{user}",
                json.dumps([unlock_key]),
                datetime.now(timezone.utc).isoformat(),
            ),
        )


def test_idle_routes_declare_a_real_codex_unlock() -> None:
    bundle = ContentBundle.load(DATA)
    definitions = idle_route_definitions(bundle)
    unlocks = {row["key"] for row in bundle.list("codex_unlock", include_locked=False)}
    for route_key, unlock_key, _command in GATED_IDLE:
        definition = definitions[route_key]
        assert definition.required_unlock == unlock_key, route_key
        assert unlock_key in unlocks, (route_key, unlock_key)
    # The pre-existing routes stay ungated.
    assert definitions["idle.town_errand"].required_unlock is None


def test_every_shipped_unlock_has_a_consumer() -> None:
    """No active codex_unlock may be promised without a runtime reader."""

    bundle = ContentBundle.load(DATA)
    unlocks = {row["key"] for row in bundle.list("codex_unlock", include_locked=False)}
    source = (ROOT / "nonebot_plugin_xiuxian_3" / "xiuxian").rglob("*.py")
    code = "\n".join(path.read_text(encoding="utf-8") for path in source)
    # Unlocks are consumed either by declaring them in content that a gate reads,
    # or by being printed as a claimed benefit in the codex overview.
    declared = set()
    for kind in ("livelihood",):
        for row in bundle.list(kind, include_locked=False):
            if isinstance(row.get("unlock_key"), str):
                declared.add(row["unlock_key"])
            requirements = row.get("requirements")
            if isinstance(requirements, dict) and isinstance(
                requirements.get("codex_unlock"), str
            ):
                declared.add(requirements["codex_unlock"])
    overview_benefits = set(ENCRYPTED_BENEFITS)
    covered = declared | overview_benefits
    assert unlocks <= covered, sorted(unlocks - covered)
    assert "unlock_label" in code


def test_idle_route_refuses_without_the_unlock_and_runs_after_claim() -> None:
    async def run() -> None:
        clock_box = [datetime(2026, 9, 30, 12, tzinfo=timezone.utc)]
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=lambda: clock_box[0])
            user = "idle-unlock"
            try:
                assert (await runtime.dispatch(_context(user, "create"), "开始修仙")).ok
                assert (await runtime.dispatch(_context(user, "seek"), "寻仙问道")).ok
                _prepare(runtime, user)

                blocked = await runtime.dispatch(
                    _context(user, "blocked", "idle-blocked"), "开始挂机 观兽"
                )
                assert not blocked.ok, blocked
                assert blocked.code == "IDLE_REQUIREMENT_MISSING", blocked

                _claim(runtime, user, "display.codex_creature_badge", "codex.xuantian.creature_3")
                started = await runtime.dispatch(
                    _context(user, "start", "idle-start"), "开始挂机 观兽"
                )
                assert started.ok, started
            finally:
                await runtime.close()

    asyncio.run(run())


def test_codex_overview_lists_claimed_benefits_only_after_the_claim() -> None:
    async def run() -> None:
        clock_box = [datetime(2026, 9, 30, 12, tzinfo=timezone.utc)]
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=lambda: clock_box[0])
            user = "codex-benefits"
            try:
                assert (await runtime.dispatch(_context(user, "create"), "开始修仙")).ok
                before = await runtime.dispatch(_context(user, "codex"), "图鉴")
                assert before.code == "CODEX_OVERVIEW", before
                assert before.data["unlocked_benefits"] == [], before.data

                _claim(runtime, user, "encyclopedia.paths_6", "codex.paths_6")
                _claim(
                    runtime,
                    user,
                    "display.domain_observatory",
                    "codex.domain.frontier_records_3",
                )
                after = await runtime.dispatch(_context(user, "codex"), "图鉴")
                assert after.code == "CODEX_OVERVIEW", after
                benefits = set(after.data["unlocked_benefits"])
                assert set(ENCRYPTED_BENEFITS) <= benefits, benefits
                assert "已解锁见闻" in after.message, after.message
            finally:
                await runtime.close()

    asyncio.run(run())
