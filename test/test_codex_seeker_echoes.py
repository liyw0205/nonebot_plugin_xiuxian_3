from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory

from combat_fixtures import BALANCED_QUALIFICATION

from mainline_fixtures import mark_mainline_snapshot_legacy
from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.exploration.rules import (
    battle_roll_bp,
    exploration_encounter_selection,
)


ADAPTERS = ("qq.official", "onebot.v11")


class MutableClock:
    def __init__(self, value: datetime):
        self.value = value

    def __call__(self) -> datetime:
        return self.value

    def advance(self, **kwargs: int) -> None:
        self.value += timedelta(**kwargs)


def _context(adapter: str, user: str, operation_id: str) -> CommandContext:
    return CommandContext(adapter=adapter, user_id=user, operation_id=f"{adapter}:{user}:{operation_id}")


def _expire_exploration(runtime, exploration_id: str) -> None:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE exploration_sessions SET ends_at=? WHERE exploration_id=?",
            ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(), exploration_id),
        )


def _prepare_player(runtime, adapter: str, user: str, *, location: str, realm: str, layer: int) -> None:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE players SET stage='cultivator', realm_key=?, realm_layer=?, location_key=?, "
            "stamina=100, stamina_max=100, energy=100, energy_max=100, max_hp=999, initiative=99, "
            "qualification_json=? WHERE platform=? AND platform_user_id=?",
            (realm, layer, location, json.dumps(BALANCED_QUALIFICATION), adapter, user),
        )


def test_codex_echoes_uses_weighted_frozen_encounter_and_real_codex_projection() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, adapters=ADAPTERS)
            try:
                for adapter in ADAPTERS:
                    user = f"codex-iron-{adapter}"
                    assert (
                        await runtime.adapters.dispatch(
                            adapter, _context(adapter, user, "create"), "开始修仙"
                        )
                    ).code == "PLAYER_CREATED"
                    _prepare_player(
                        runtime,
                        adapter,
                        user,
                        location="xuantian.outskirts",
                        realm="qi_sensing",
                        layer=3,
                    )
                    operation_suffix = next(
                        f"iron-{index}"
                        for index in range(10_000)
                        if exploration_encounter_selection(
                            "explore.trial_outskirts",
                            seed=f"{adapter}:{user}:iron-{index}",
                            realm_key="qi_sensing",
                            realm_layer=3,
                        )[0]
                        == "enemy.iron_boar"
                        and battle_roll_bp(f"{adapter}:{user}:iron-{index}:battle") < 2_000
                    )
                    started = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, user, operation_suffix),
                        "开始探索 近郊短历练",
                    )
                    assert started.code == "EXPLORATION_STARTED", started.message
                    exploration_id = str(started.data["exploration_id"])
                    with sqlite3.connect(runtime.settings.database_path) as connection:
                        snapshot = json.loads(
                            connection.execute(
                                "SELECT snapshot_json FROM exploration_sessions WHERE exploration_id=?",
                                (exploration_id,),
                            ).fetchone()[0]
                        )
                    assert snapshot["encounter_enemy_key"] == "enemy.iron_boar"
                    assert snapshot["encounter_candidates"] == [
                        {"enemy_key": "enemy.wood_rat", "weight": 70},
                        {"enemy_key": "enemy.iron_boar", "weight": 30},
                    ]
                    _expire_exploration(runtime, exploration_id)
                    settled = await runtime.adapters.dispatch(
                        adapter, _context(adapter, user, "settle"), "结算探索"
                    )
                    assert settled.code == "EXPLORATION_SETTLED", settled.message
                    assert settled.data["battle_outcome"] == "won"
                    with sqlite3.connect(runtime.settings.database_path) as connection:
                        assert connection.execute(
                            "SELECT enemy_key FROM battle_sessions WHERE battle_id=?",
                            (settled.data["battle_id"],),
                        ).fetchone()[0] == "enemy.iron_boar"
                        assert connection.execute(
                            "SELECT COUNT(*) FROM codex_entries WHERE player_id=(SELECT id FROM players WHERE platform=? AND platform_user_id=?) AND entry_key=?",
                            (adapter, user, "codex.creature.iron_boar"),
                        ).fetchone()[0] == 1
                    replay = await runtime.adapters.dispatch(
                        adapter, _context(adapter, user, "settle"), "结算探索"
                    )
                    assert replay.code == "EXPLORATION_SETTLED"
                    assert replay.data["idempotent_replay"] is True
            finally:
                await runtime.close()

    asyncio.run(run())


def test_codex_echoes_idle_stage_requires_full_claims_and_replays_on_both_adapters() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 11, 11, 12, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, adapters=ADAPTERS, clock=clock)
            try:
                for adapter in ADAPTERS:
                    user = f"codex-idle-{adapter}"
                    assert (
                        await runtime.adapters.dispatch(
                            adapter, _context(adapter, user, "create"), "开始修仙"
                        )
                    ).code == "PLAYER_CREATED"
                    assert (
                        await runtime.adapters.dispatch(
                            adapter, _context(adapter, user, "seek"), "寻仙问道"
                        )
                    ).ok
                    _prepare_player(
                        runtime,
                        adapter,
                        user,
                        location="cave.mist_grotto",
                        realm="qi_gathering",
                        layer=4,
                    )
                    # Earlier stages are deliberately completed through their
                    # legacy objective-free save format; this test focuses on
                    # the new full-claim consumer and its retry semantics.
                    for stage, label in (("codex_echoes.1", "近郊寻迹"), ("codex_echoes.2", "两页见闻")):
                        started = await runtime.adapters.dispatch(
                            adapter,
                            _context(adapter, user, f"{stage}:start"),
                            f"开始图鉴回响主线 {label}",
                        )
                        assert started.code == "MAINLINE_STARTED", started.message
                        mark_mainline_snapshot_legacy(runtime, adapter, user, stage)
                        claimed = await runtime.adapters.dispatch(
                            adapter,
                            _context(adapter, user, f"{stage}:claim"),
                            f"领取图鉴回响主线奖励 {label}",
                        )
                        assert claimed.code == "MAINLINE_REWARD_CLAIMED", claimed.message

                    # The milestone is an existing codex consumer; no codex row
                    # is injected here. The stage still has to observe real idle
                    # assignment settlement after this public unlock is present.
                    with sqlite3.connect(runtime.settings.database_path) as connection:
                        player_id = connection.execute(
                            "SELECT id FROM players WHERE platform=? AND platform_user_id=?",
                            (adapter, user),
                        ).fetchone()[0]
                        connection.execute(
                            "INSERT INTO codex_milestone_claims"
                            "(player_id, milestone_key, operation_id, snapshot_json, reward_json, unlocks_json, claimed_at) "
                            "VALUES (?, ?, ?, '{}', '{}', ?, ?)",
                            (
                                player_id,
                                "codex.xuantian.creature_3",
                                f"milestone:{adapter}:{user}",
                                json.dumps(
                                    ["display.codex_creature_badge", "hint.tower_route"],
                                    ensure_ascii=False,
                                ),
                                clock().isoformat(),
                            ),
                        )

                    started = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, user, "stage3:start"),
                        "开始图鉴回响主线 守望成册",
                    )
                    assert started.code == "MAINLINE_STARTED", started.message
                    early = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, user, "stage3:early"),
                        "领取图鉴回响主线奖励 守望成册",
                    )
                    assert early.code == "MAINLINE_OBJECTIVES_INCOMPLETE"

                    fallback_start = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, user, "beast:fallback:start"),
                        "开始挂机 观兽",
                    )
                    assert fallback_start.code == "IDLE_STARTED"
                    clock.advance(hours=26, seconds=1)
                    fallback = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, user, "beast:fallback:claim"),
                        "领取挂机",
                    )
                    assert fallback.code == "IDLE_CLAIMED"
                    assert fallback.data["fallback"] is True
                    still_running = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, user, "stage3:after-fallback"),
                        "领取图鉴回响主线奖励 守望成册",
                    )
                    assert still_running.code == "MAINLINE_OBJECTIVES_INCOMPLETE"

                    # The expired assignment consumed today's route quota;
                    # retry on the next UTC day with a fresh full window.
                    clock.advance(days=1)

                    full_beast = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, user, "beast:full:start"),
                        "开始挂机 观兽",
                    )
                    assert full_beast.code == "IDLE_STARTED"
                    clock.advance(hours=2)
                    claimed_beast = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, user, "beast:full:claim"),
                        "领取挂机",
                    )
                    assert claimed_beast.code == "IDLE_CLAIMED"
                    assert claimed_beast.data["fallback"] is False

                    full_tower = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, user, "tower:full:start"),
                        "开始挂机 塔外守望",
                    )
                    assert full_tower.code == "IDLE_STARTED"
                    clock.advance(hours=3)
                    claimed_tower = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, user, "tower:full:claim"),
                        "领取挂机",
                    )
                    assert claimed_tower.code == "IDLE_CLAIMED"
                    assert claimed_tower.data["fallback"] is False

                    done = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, user, "stage3:claim"),
                        "领取图鉴回响主线奖励 守望成册",
                    )
                    assert done.code == "MAINLINE_REWARD_CLAIMED", done.message
                    replay = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, user, "stage3:claim"),
                        "领取图鉴回响主线奖励 守望成册",
                    )
                    assert replay.code == "MAINLINE_REWARD_CLAIMED"
                    assert replay.data["idempotent_replay"] is True
            finally:
                await runtime.close()

    asyncio.run(run())
