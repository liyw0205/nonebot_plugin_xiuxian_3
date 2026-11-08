"""Transport routes are gated by real codex milestone unlocks.

Two of the eight shipped `codex_unlock` rows had no runtime consumer. This module
pins the new transport gate: a route with `unlock_key` refuses until the matching
milestone is claimed, and then really runs through the existing engine.
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
from nonebot_plugin_xiuxian_3.xiuxian.livelihood.route_rules import route_definitions

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

HERB_ROUTE = "route.town_herb_vale"
HERB_UNLOCK = "hint.herb_route"
ABYSS_ROUTE = "route.cloud_to_abyss_gate"
ABYSS_UNLOCK = "encyclopedia.domain_tactics"
GATED = ((HERB_ROUTE, HERB_UNLOCK), (ABYSS_ROUTE, ABYSS_UNLOCK))


def _context(user: str, name: str, operation_id: str = "") -> CommandContext:
    return CommandContext(
        adapter="web", user_id=user, request_id=name, operation_id=operation_id
    )


def test_gated_routes_declare_a_real_codex_unlock() -> None:
    bundle = ContentBundle.load(DATA)
    definitions = route_definitions(bundle)
    unlocks = {row["key"] for row in bundle.list("codex_unlock", include_locked=False)}
    for route_key, unlock_key in GATED:
        definition = definitions[route_key]
        assert definition.unlock_key == unlock_key, route_key
        assert unlock_key in unlocks, (route_key, unlock_key)


def test_ungated_route_keeps_its_original_behaviour() -> None:
    bundle = ContentBundle.load(DATA)
    definition = route_definitions(bundle)["route.new_town_outskirts"]
    assert definition.unlock_key is None


def _prepare(runtime, user: str, *, location: str, stage: str = "mortal") -> None:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE players SET stage=?, realm_key='qi_sensing', realm_layer=1, "
            "location_key=?, stamina=200, stamina_max=200, "
            "inventory_json=? WHERE platform_user_id=?",
            (stage, location, json.dumps({"item.herb.spirit_leaf": 4}), user),
        )


def _claim_unlock(runtime, user: str, unlock_key: str, milestone_key: str) -> None:
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
                f"fixture-claim:{user}",
                json.dumps([unlock_key]),
                datetime.now(timezone.utc).isoformat(),
            ),
        )


def test_route_refuses_until_the_milestone_is_claimed_then_runs() -> None:
    async def run() -> None:
        clock_box = [datetime(2026, 9, 30, 12, tzinfo=timezone.utc)]
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=lambda: clock_box[0])
            user = "route-gate"
            try:
                assert (await runtime.dispatch(_context(user, "create"), "开始修仙")).ok
                _prepare(runtime, user, location="xuantian.new_town")

                # Without the unlock the start must refuse and touch nothing.
                blocked = await runtime.dispatch(
                    _context(user, "blocked", "route-blocked"),
                    "开始运输 百草运输 灵叶 1",
                )
                assert blocked.code == "ROUTE_UNLOCK_REQUIRED", blocked
                # The preview also reports the missing unlock.
                preview = await runtime.dispatch(
                    _context(user, "preview"), "运输预览 百草运输 灵叶 1"
                )
                assert preview.code == "ROUTE_PREVIEW", preview
                assert "图鉴见闻" in preview.data["missing"], preview.data["missing"]

                _claim_unlock(runtime, user, HERB_UNLOCK, "codex.xuantian.materials_5")
                started = await runtime.dispatch(
                    _context(user, "start", "route-start"),
                    "开始运输 百草运输 灵叶 1",
                )
                assert started.code == "ROUTE_STARTED", started
                clock_box[0] = clock_box[0] + timedelta(seconds=1800)
                settled = await runtime.dispatch(_context(user, "settle"), "结算运输")
                assert settled.code == "ROUTE_SETTLED", settled

                # Replaying the same start returns the frozen result, no second row.
                replay = await runtime.dispatch(
                    _context(user, "start", "route-start"),
                    "开始运输 百草运输 灵叶 1",
                )
                assert replay.data.get("idempotent_replay") is True, replay
            finally:
                await runtime.close()

    asyncio.run(run())
