"""Focused contract for the seeker-tier idle routes and their codex award.

Two routes are added to `data/生活/生活.json`: a seeker residence route that
also awards a brand-new `codex.route.*` discovery, and a second seeker route
gated on street reputation with its own weighted pool. This file pins the
loader contract, the requirement gates, the real settlement (reward paid AND
the codex entry recorded inside the same claim), the fallback after the max
claim window, the per-route daily limit and the idempotent replay.
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
from nonebot_plugin_xiuxian_3.xiuxian.specials.idle_rules import (
    idle_route_definitions,
    reward_for,
)

DATA = Path(__file__).parents[1] / "data"

HERB = "idle.seeker_herb_tending"
HERB_LABEL = "灵田照看"
HERB_CODEX = "codex.route.seeker_herb_tending"
INQUIRY = "idle.seeker_town_inquiry"
INQUIRY_LABEL = "镇中问询"


class Clock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value

    def advance(self, **kwargs: int) -> None:
        self.value += timedelta(**kwargs)


def _context(adapter: str, user: str, operation_id: str) -> CommandContext:
    return CommandContext(adapter=adapter, user_id=user, operation_id=operation_id)


def _player_id(runtime, adapter: str, user: str) -> int:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        return connection.execute(
            "SELECT id FROM players WHERE platform=? AND platform_user_id=?", (adapter, user)
        ).fetchone()[0]


def _row(result, key: str):
    return next(item for item in result.data["routes"] if item["route_key"] == key)


def test_seeker_routes_load_with_their_gates_and_pools() -> None:
    bundle = ContentBundle.load(DATA)
    definitions = idle_route_definitions(bundle)
    assert HERB in definitions and INQUIRY in definitions

    herb = definitions[HERB]
    assert herb.required_stage == "seeker"
    assert herb.required_residence is True
    assert herb.duration_seconds == 14400
    assert (herb.stamina_cost, herb.energy_cost) == (0, 1)
    assert herb.daily_limit == 1

    inquiry = definitions[INQUIRY]
    assert inquiry.required_stage == "seeker"
    assert inquiry.required_residence is False
    assert dict(inquiry.required_local_reputation) == {"local.xuantian.new_town": 10}
    assert inquiry.duration_seconds == 10800
    assert (inquiry.stamina_cost, inquiry.energy_cost) == (1, 0)
    assert inquiry.daily_limit == 1

    # Every outcome of the herb pool really carries the new codex discovery,
    # including the guaranteed fallback outcome.
    for definition in (herb, inquiry):
        full_pool = reward_for(definition, "seeker:seed", fallback=False)
        fallback_pool = reward_for(definition, "seeker:seed", fallback=True)
        assert full_pool and fallback_pool
        assert len(fallback_pool) >= 1
    assert reward_for(herb, "seeker:seed", fallback=False)[HERB_CODEX] == 1
    assert reward_for(herb, "seeker:seed", fallback=True)[HERB_CODEX] == 1
    assert HERB_CODEX not in reward_for(inquiry, "seeker:seed", fallback=False)
    # The codex entry itself is active content with a real route category.
    entry = bundle.require("codex_entry", HERB_CODEX, include_locked=False)
    assert entry["category"] == "route"


def test_seeker_herb_route_requires_residence_and_pays_a_codex_discovery() -> None:
    async def run() -> None:
        clock = Clock(datetime(2026, 11, 8, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock, adapters=("onebot.v11",))
            adapter, user = "onebot.v11", "ob-seeker-herb"
            try:
                assert (await runtime.dispatch(_context(adapter, user, "create"), "开始修仙")).ok
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE players SET stage='seeker', stamina=50, stamina_max=50, energy=40 "
                        "WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    )

                # No residence yet: the route is blocked and reports why.
                blocked = await runtime.dispatch(
                    _context(adapter, user, "preview-blocked"), f"挂机预览 {HERB_LABEL}"
                )
                assert blocked.code == "IDLE_PREVIEW", blocked.message
                row = _row(blocked, HERB)
                assert row["ready"] is False
                assert "需要有效居所或地块" in row["missing"]
                refused = await runtime.dispatch(
                    _context(adapter, user, "start-blocked"), f"开始挂机 {HERB_LABEL}"
                )
                assert refused.code == "IDLE_REQUIREMENT_MISSING", refused

                player_id = _player_id(runtime, adapter, user)
                now = clock().isoformat()
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "INSERT INTO residences(residence_id, player_id, operation_id, residence_key, "
                        "status, starts_at, ends_at, rent_cost, created_at, updated_at) "
                        "VALUES ('seeker-herb-res', ?, 'seeker-herb-res-op', 'residence.herb_court', "
                        "'active', ?, ?, 0, ?, ?)",
                        (player_id, now, (clock.value + timedelta(days=1)).isoformat(), now, now),
                    )
                ready = await runtime.dispatch(
                    _context(adapter, user, "preview-ready"), f"挂机预览 {HERB_LABEL}"
                )
                assert _row(ready, HERB)["ready"] is True, _row(ready, HERB)["missing"]

                started = await runtime.dispatch(
                    _context(adapter, user, "herb-start"), f"开始挂机 {HERB_LABEL}"
                )
                assert started.code == "IDLE_STARTED", started.message
                clock.advance(hours=4)
                claimed = await runtime.dispatch(
                    _context(adapter, user, "herb-claim"), "领取挂机"
                )
                assert claimed.code == "IDLE_CLAIMED", claimed.message
                assert claimed.data["fallback"] is False
                assert claimed.data["reward"][HERB_CODEX] == 1
                assert claimed.data["reward"]["item.herb.blood_grass"] >= 2
                assert "灵田照看见闻" in claimed.message
                assert HERB_CODEX not in claimed.message

                with sqlite3.connect(runtime.settings.database_path) as connection:
                    discovery = connection.execute(
                        "SELECT category, first_seen_operation_id FROM codex_entries "
                        "WHERE player_id=? AND entry_key=?",
                        (player_id, HERB_CODEX),
                    ).fetchone()
                    inventory = json.loads(
                        connection.execute(
                            "SELECT inventory_json FROM players WHERE id=?", (player_id,)
                        ).fetchone()[0]
                        or "{}"
                    )
                assert discovery is not None
                assert discovery[0] == "route"
                assert discovery[1] == "herb-claim"
                assert inventory.get("item.herb.blood_grass", 0) >= 2

                # The claim operation replays the frozen payload and the
                # per-route daily limit refuses a second run the same day.
                replay = await runtime.dispatch(
                    _context(adapter, user, "herb-claim"), "领取挂机"
                )
                assert replay.code == "IDLE_CLAIMED", replay
                assert replay.data["reward"] == claimed.data["reward"]
                limited = await runtime.dispatch(
                    _context(adapter, user, "herb-again"), f"开始挂机 {HERB_LABEL}"
                )
                assert limited.code == "IDLE_DAILY_LIMIT", limited
            finally:
                await runtime.close()

    asyncio.run(run())


def test_seeker_town_inquiry_gates_on_reputation_and_falls_back_after_max_window() -> None:
    async def run() -> None:
        clock = Clock(datetime(2026, 11, 8, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock, adapters=("qq.official",))
            adapter, user = "qq.official", "qq-seeker-inquiry"
            try:
                assert (await runtime.dispatch(_context(adapter, user, "create"), "开始修仙")).ok
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE players SET stage='seeker', stamina=50, stamina_max=50, energy=40 "
                        "WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    )
                player_id = _player_id(runtime, adapter, user)

                blocked = await runtime.dispatch(
                    _context(adapter, user, "preview-blocked"), f"挂机预览 {INQUIRY_LABEL}"
                )
                row = _row(blocked, INQUIRY)
                assert row["ready"] is False
                assert "地方名望不足（需要 10）" in row["missing"]

                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "INSERT INTO player_reputations(player_id, local_json, service_reputation, "
                        "updated_at) VALUES (?, ?, 0, ?) "
                        "ON CONFLICT(player_id) DO UPDATE SET local_json=excluded.local_json",
                        (
                            player_id,
                            json.dumps({"local.xuantian.new_town": 10}, sort_keys=True),
                            clock().isoformat(),
                        ),
                    )
                ready = await runtime.dispatch(
                    _context(adapter, user, "preview-ready"), f"挂机预览 {INQUIRY_LABEL}"
                )
                assert _row(ready, INQUIRY)["ready"] is True, _row(ready, INQUIRY)["missing"]

                started = await runtime.dispatch(
                    _context(adapter, user, "inq-start"), f"开始挂机 {INQUIRY_LABEL}"
                )
                assert started.code == "IDLE_STARTED", started.message
                # Past the 24h grace window the frozen fallback reward applies.
                clock.advance(hours=27, seconds=1)
                claimed = await runtime.dispatch(
                    _context(adapter, user, "inq-claim"), "领取挂机"
                )
                assert claimed.code == "IDLE_CLAIMED", claimed.message
                assert claimed.data["fallback"] is True
                assert claimed.data["reward"] == {
                    "spirit_stones": 15,
                    "local.xuantian.new_town": 1,
                }, claimed.data["reward"]

                with sqlite3.connect(runtime.settings.database_path) as connection:
                    local_json = connection.execute(
                        "SELECT local_json FROM player_reputations WHERE player_id=?", (player_id,)
                    ).fetchone()[0]
                assert json.loads(local_json)["local.xuantian.new_town"] == 11
            finally:
                await runtime.close()

    asyncio.run(run())
